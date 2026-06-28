"""
usage_logger.py — v11.1

Single entry point that every AI call site uses to record itself.
Designed to be CALLED FROM ANYWHERE without breaking anything if the
analytics layer has an issue — every operation is wrapped in try/except.

Performance: log_ai_request() queues a write to a background thread and
returns immediately. The actual SQLite INSERT happens off the AI request path.
This guarantees ZERO latency impact on AI responses.
"""
import sqlite3
import logging
import time
import uuid
import threading
import queue
from datetime import datetime
import pytz

from .token_counter import estimate_cost, get_provider_for_model

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")
DB_NAME = "planner.db"

# Process-level session id — survives until restart, lets us group calls
_SESSION_ID = str(uuid.uuid4())[:12]
_WAL_INITIALIZED = False
_WAL_LOCK = threading.Lock()

# Background writer queue — keeps INSERTs off the AI request path
_WRITE_QUEUE = queue.Queue(maxsize=10000)
_WRITER_THREAD = None
_WRITER_LOCK = threading.Lock()
_SHUTDOWN = False


def get_session_id() -> str:
    return _SESSION_ID


def _ensure_wal_mode(db_path: str):
    """Enable WAL once per process — faster concurrent writes."""
    global _WAL_INITIALIZED
    if _WAL_INITIALIZED:
        return
    with _WAL_LOCK:
        if _WAL_INITIALIZED:
            return
        try:
            conn = sqlite3.connect(db_path)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.close()
            _WAL_INITIALIZED = True
        except Exception as e:
            logger.error(f"WAL init failed (non-fatal): {e}")


def _writer_loop(db_path: str):
    """Background thread that drains the write queue."""
    while not _SHUTDOWN:
        try:
            row = _WRITE_QUEUE.get(timeout=1.0)
        except queue.Empty:
            continue
        if row is None:  # sentinel to stop
            break
        try:
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            c.execute("""INSERT INTO ai_usage
                (timestamp, user_id, session_id, conversation_id, provider,
                 model_name, request_type, intent, prompt_tokens, completion_tokens,
                 total_tokens, estimated_cost, latency_ms, status, error_message,
                 fallback_used, response_length)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", row)
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"async log write failed: {e}")


def _ensure_writer():
    """Start the background writer thread on first use."""
    global _WRITER_THREAD
    if _WRITER_THREAD and _WRITER_THREAD.is_alive():
        return
    with _WRITER_LOCK:
        if _WRITER_THREAD and _WRITER_THREAD.is_alive():
            return
        _WRITER_THREAD = threading.Thread(
            target=_writer_loop, args=(DB_NAME,),
            daemon=True, name="analytics-writer"
        )
        _WRITER_THREAD.start()


def shutdown_writer():
    """Graceful shutdown — call on bot stop. Safe to skip (daemon thread)."""
    global _SHUTDOWN
    _SHUTDOWN = True
    try:
        _WRITE_QUEUE.put_nowait(None)
    except queue.Full:
        pass


def init_usage_table(db_path: str = DB_NAME):
    """
    Create ai_usage table + indexes. Idempotent — safe to call repeatedly.
    Called once by database.init_db() so existing migrations stay consistent.
    """
    try:
        _ensure_wal_mode(db_path)
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS ai_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            user_id INTEGER,
            session_id TEXT,
            conversation_id TEXT,
            provider TEXT,
            model_name TEXT,
            request_type TEXT,
            intent TEXT,
            prompt_tokens INTEGER DEFAULT 0,
            completion_tokens INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            estimated_cost REAL DEFAULT 0,
            latency_ms INTEGER DEFAULT 0,
            status TEXT,
            error_message TEXT,
            fallback_used INTEGER DEFAULT 0,
            response_length INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")
        # Indexes for the dashboard's most common queries
        c.execute("CREATE INDEX IF NOT EXISTS idx_usage_user ON ai_usage(user_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_usage_model ON ai_usage(model_name)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_usage_created ON ai_usage(created_at)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_usage_status ON ai_usage(status)")
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"init_usage_table failed: {e}")


def log_ai_request(
    model_name: str,
    latency_ms: int,
    status: str = "success",
    user_id: int = None,
    request_type: str = "UNKNOWN",
    intent: str = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    response_text: str = None,
    error_message: str = None,
    fallback_used: bool = False,
    conversation_id: str = None,
    db_path: str = DB_NAME,
) -> None:
    """
    Record a single AI request. NEVER raises — analytics must never break AI.

    v11.1: Async queued — returns immediately, write happens on background thread.
    Sub-microsecond impact on the AI response path.
    """
    try:
        _ensure_writer()
        total = (prompt_tokens or 0) + (completion_tokens or 0)
        cost = estimate_cost(model_name, prompt_tokens or 0, completion_tokens or 0)
        provider = get_provider_for_model(model_name)
        response_len = len(response_text) if response_text else 0
        timestamp = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
        row = (timestamp, user_id, _SESSION_ID, conversation_id, provider,
               model_name, request_type, intent, prompt_tokens or 0,
               completion_tokens or 0, total, cost, latency_ms or 0,
               status, error_message, 1 if fallback_used else 0, response_len)
        try:
            _WRITE_QUEUE.put_nowait(row)
        except queue.Full:
            logger.warning("analytics queue full — dropping a log entry")
    except Exception as e:
        # Logging must NEVER take down an AI call
        logger.error(f"log_ai_request failed (non-fatal): {e}")


def log_ai_request_sync(*args, **kwargs):
    """Synchronous version for testing — exact same behavior, blocks until written."""
    try:
        # Mimic log_ai_request but inline-write
        model_name = kwargs.get("model_name") or (args[0] if args else None)
        if not model_name:
            return
        total = (kwargs.get("prompt_tokens", 0) or 0) + (kwargs.get("completion_tokens", 0) or 0)
        cost = estimate_cost(model_name, kwargs.get("prompt_tokens", 0) or 0,
                              kwargs.get("completion_tokens", 0) or 0)
        provider = get_provider_for_model(model_name)
        response_text = kwargs.get("response_text")
        response_len = len(response_text) if response_text else 0
        timestamp = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("""INSERT INTO ai_usage
            (timestamp, user_id, session_id, conversation_id, provider,
             model_name, request_type, intent, prompt_tokens, completion_tokens,
             total_tokens, estimated_cost, latency_ms, status, error_message,
             fallback_used, response_length)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (timestamp, kwargs.get("user_id"), _SESSION_ID,
             kwargs.get("conversation_id"), provider, model_name,
             kwargs.get("request_type", "UNKNOWN"), kwargs.get("intent"),
             kwargs.get("prompt_tokens", 0) or 0, kwargs.get("completion_tokens", 0) or 0,
             total, cost, kwargs.get("latency_ms", 0) or 0,
             kwargs.get("status", "success"), kwargs.get("error_message"),
             1 if kwargs.get("fallback_used") else 0, response_len))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"log_ai_request_sync failed: {e}")


def log_image_request(
    model_name: str,
    latency_ms: int,
    status: str = "success",
    user_id: int = None,
    prompt_text: str = None,
    image_count: int = 1,
    error_message: str = None,
) -> None:
    """Specialized logger for image generation (no token counts, per-image cost)."""
    try:
        from .token_counter import MODEL_COSTS
        info = MODEL_COSTS.get(model_name, {})
        cost = (info.get("per_image", 0) or 0) * image_count
        provider = get_provider_for_model(model_name)
        timestamp = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("""INSERT INTO ai_usage
            (timestamp, user_id, session_id, provider, model_name, request_type,
             prompt_tokens, completion_tokens, total_tokens, estimated_cost,
             latency_ms, status, error_message, response_length)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (timestamp, user_id, _SESSION_ID, provider, model_name, "IMAGE_GENERATION",
             len(prompt_text) if prompt_text else 0, 0, 0, cost, latency_ms or 0,
             status, error_message, 1 if status == "success" else 0))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"log_image_request failed (non-fatal): {e}")