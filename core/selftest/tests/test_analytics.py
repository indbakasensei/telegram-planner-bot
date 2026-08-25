"""Self-tests: analytics health (category Analytics)."""
from core.selftest.models import SelfTestFail
from core.selftest.registry import selftest


@selftest(name="Analytics Overview", category="Analytics")
def check_analytics_overview():
    """Verify analytics package imports and key functions execute without raising.
    This validates the analytics package is functional against the temp database
    created by the runner's _setup_temp_db()."""
    try:
        import analytics
    except ImportError as e:
        raise SelfTestFail("analytics package import failed",
                           details=str(e))

    # Verify init_usage_table creates the table (idempotent)
    try:
        analytics.init_usage_table()
    except Exception as e:
        raise SelfTestFail("init_usage_table() raised",
                           details=str(e))

    # Verify dashboard query functions return expected dict structures
    user_id = 999999  # non-existent user, should return zero-count dicts
    try:
        today = analytics.get_today_overview(user_id)
        if not isinstance(today, dict) or "requests_today" not in today:
            raise SelfTestFail("get_today_overview returned unexpected format",
                               details=f"got: {type(today)}")
    except Exception as e:
        raise SelfTestFail("get_today_overview() raised",
                           details=str(e))

    try:
        lifetime = analytics.get_lifetime_overview(user_id)
        if not isinstance(lifetime, dict) or "lifetime_requests" not in lifetime:
            raise SelfTestFail("get_lifetime_overview returned unexpected format",
                               details=f"got: {type(lifetime)}")
    except Exception as e:
        raise SelfTestFail("get_lifetime_overview() raised",
                           details=str(e))

    try:
        stats = analytics.get_model_stats(user_id)
        if not isinstance(stats, list):
            raise SelfTestFail("get_model_stats returned unexpected format",
                               details=f"got: {type(stats)}")
    except Exception as e:
        raise SelfTestFail("get_model_stats() raised",
                           details=str(e))

    # Verify logging functions don't raise (they queue internally)
    try:
        analytics.log_ai_request(
            model_name="z-ai/glm-5.2",
            latency_ms=123,
            status="success",
            user_id=user_id,
            request_type="TEST",
            prompt_tokens=10,
            completion_tokens=20,
            response_text="ok",
        )
    except Exception as e:
        raise SelfTestFail("log_ai_request() raised",
                           details=str(e))

    try:
        analytics.log_image_request(
            model_name="black-forest-labs/flux.1-schnell",
            latency_ms=456,
            status="success",
            user_id=user_id,
            prompt_text="test image",
            image_count=1,
        )
    except Exception as e:
        raise SelfTestFail("log_image_request() raised",
                           details=str(e))

    return "analytics package imports and functions OK"


@selftest(name="Analytics Table Creation", category="Analytics")
def check_analytics_table_creation():
    """Verify ai_usage table exists and has expected columns after init_usage_table()."""
    import sqlite3
    import database as db

    conn = sqlite3.connect(db.DB_NAME)
    c = conn.cursor()

    # Check table exists
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='ai_usage'")
    if not c.fetchone():
        conn.close()
        raise SelfTestFail("ai_usage table not created")

    # Check key columns
    c.execute("PRAGMA table_info(ai_usage)")
    columns = {row[1] for row in c.fetchall()}
    required_columns = {
        "id", "timestamp", "user_id", "session_id", "conversation_id",
        "provider", "model_name", "request_type", "intent",
        "prompt_tokens", "completion_tokens", "total_tokens",
        "estimated_cost", "latency_ms", "status", "error_message",
        "fallback_used", "response_length", "created_at"
    }
    missing = required_columns - columns
    if missing:
        conn.close()
        raise SelfTestFail(f"ai_usage missing columns: {missing}")

    # Check indexes exist
    c.execute("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_usage_%'")
    indexes = {row[0] for row in c.fetchall()}
    required_indexes = {
        "idx_usage_user", "idx_usage_model", "idx_usage_created", "idx_usage_status"
    }
    missing_idx = required_indexes - indexes
    if missing_idx:
        conn.close()
        raise SelfTestFail(f"ai_usage missing indexes: {missing_idx}")

    conn.close()
    return "ai_usage table schema verified"