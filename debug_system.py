"""
debug_system.py — BAKA Debug & Bug-Tracking System (v1.0)

This is the foundation layer the roadmap says to build FIRST.
It lets you report bugs from inside Telegram, auto-logs every crash,
traces the last AI interaction, and stores everything in bugs.db so
you (and the AI helping you) can see exactly what went wrong.

Commands this powers (wired up in main.py):
  /debug      — toggle debug mode on/off (shows intent + entities inline)
  /report     — report a bug: /report <description>
  /bugs       — list all open bug reports
  /resolve    — mark a bug resolved: /resolve <id>
  /trace      — show the last AI interaction for your user
  /selftest   — run automated test messages

Everything is stored in a separate bugs.db so it never interferes
with the main planner.db.
"""
import sqlite3
import traceback
import json
from datetime import datetime

BUGS_DB = "bugs.db"

# Per-user last interaction trace (in memory, for /trace)
_last_trace = {}
# Per-user debug mode flag
_debug_mode = {}


def init_bugs_db():
    conn = sqlite3.connect(BUGS_DB)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS bugs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        type TEXT,              -- 'user_report' or 'auto_exception'
        description TEXT,
        user_input TEXT,        -- what the user typed when bug happened
        ai_intent TEXT,         -- what intent was detected
        ai_raw TEXT,            -- raw AI / entity data
        traceback TEXT,         -- stack trace for auto exceptions
        status TEXT DEFAULT 'open',  -- 'open' or 'resolved'
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS interactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        user_input TEXT,
        intent TEXT,
        entities TEXT,
        response TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.commit()
    conn.close()


# ── Debug mode toggle ─────────────────────────────────
def toggle_debug(user_id: int) -> bool:
    _debug_mode[user_id] = not _debug_mode.get(user_id, False)
    return _debug_mode[user_id]

def is_debug_on(user_id: int) -> bool:
    return _debug_mode.get(user_id, False)


# ── Interaction tracing ───────────────────────────────
def log_interaction(user_id: int, user_input: str, intent: str,
                    entities: dict, response: str):
    """Called on every message — stores the last interaction for /trace."""
    _last_trace[user_id] = {
        "user_input": user_input,
        "intent": intent,
        "entities": entities,
        "response": response,
        "time": datetime.now().strftime("%H:%M:%S")
    }
    # Also persist to DB (keep last interactions)
    try:
        conn = sqlite3.connect(BUGS_DB)
        c = conn.cursor()
        c.execute('''INSERT INTO interactions
                     (user_id, user_input, intent, entities, response)
                     VALUES (?,?,?,?,?)''',
                  (user_id, user_input, intent,
                   json.dumps(entities, ensure_ascii=False), response[:500]))
        # Keep only the most recent 50 per user
        c.execute('''DELETE FROM interactions WHERE id NOT IN
                     (SELECT id FROM interactions WHERE user_id=?
                      ORDER BY id DESC LIMIT 50) AND user_id=?''',
                  (user_id, user_id))
        conn.commit()
        conn.close()
    except Exception:
        pass

def get_last_trace(user_id: int) -> dict:
    return _last_trace.get(user_id)


# ── Bug reporting ─────────────────────────────────────
def report_bug(user_id: int, description: str) -> int:
    """User-reported bug. Auto-attaches the last interaction context."""
    trace = _last_trace.get(user_id, {})
    conn = sqlite3.connect(BUGS_DB)
    c = conn.cursor()
    c.execute('''INSERT INTO bugs
                 (user_id, type, description, user_input, ai_intent, ai_raw)
                 VALUES (?,?,?,?,?,?)''',
              (user_id, "user_report", description,
               trace.get("user_input", ""),
               trace.get("intent", ""),
               json.dumps(trace.get("entities", {}), ensure_ascii=False)))
    bug_id = c.lastrowid
    conn.commit()
    conn.close()
    return bug_id

def log_exception(user_id: int, user_input: str, exc: Exception):
    """Auto-called when any handler crashes."""
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    trace = _last_trace.get(user_id, {})
    conn = sqlite3.connect(BUGS_DB)
    c = conn.cursor()
    c.execute('''INSERT INTO bugs
                 (user_id, type, description, user_input, ai_intent, ai_raw, traceback)
                 VALUES (?,?,?,?,?,?,?)''',
              (user_id, "auto_exception", str(exc)[:200], user_input,
               trace.get("intent", ""),
               json.dumps(trace.get("entities", {}), ensure_ascii=False), tb))
    bug_id = c.lastrowid
    conn.commit()
    conn.close()
    return bug_id

def get_open_bugs(user_id: int = None) -> list:
    conn = sqlite3.connect(BUGS_DB)
    c = conn.cursor()
    if user_id:
        c.execute('''SELECT id, type, description, user_input, created_at
                     FROM bugs WHERE status='open' AND user_id=?
                     ORDER BY id DESC''', (user_id,))
    else:
        c.execute('''SELECT id, type, description, user_input, created_at
                     FROM bugs WHERE status='open' ORDER BY id DESC''')
    bugs = c.fetchall()
    conn.close()
    return bugs

def get_bug_detail(bug_id: int) -> tuple:
    conn = sqlite3.connect(BUGS_DB)
    c = conn.cursor()
    c.execute('''SELECT id, type, description, user_input, ai_intent,
                 ai_raw, traceback, status, created_at
                 FROM bugs WHERE id=?''', (bug_id,))
    bug = c.fetchone()
    conn.close()
    return bug

def resolve_bug(bug_id: int) -> bool:
    conn = sqlite3.connect(BUGS_DB)
    c = conn.cursor()
    c.execute("UPDATE bugs SET status='resolved' WHERE id=?", (bug_id,))
    changed = c.rowcount > 0
    conn.commit()
    conn.close()
    return changed

def export_all_bugs() -> str:
    """Returns a text report of all open bugs — paste this to your AI helper."""
    bugs = get_open_bugs()
    if not bugs:
        return "No open bugs! 🎉"
    lines = ["=== BAKA BUG REPORT ===", f"Generated: {datetime.now()}", ""]
    for bug in bugs:
        detail = get_bug_detail(bug[0])
        lines.append(f"--- Bug #{detail[0]} [{detail[1]}] ---")
        lines.append(f"Description: {detail[2]}")
        lines.append(f"User typed: {detail[3]}")
        lines.append(f"Intent detected: {detail[4]}")
        lines.append(f"Entities: {detail[5]}")
        if detail[6]:
            lines.append(f"Traceback:\n{detail[6]}")
        lines.append("")
    return "\n".join(lines)


# ── Self-test message bank ────────────────────────────
# Each tuple: (test message, what to verify)
SELFTEST_MESSAGES = [
    ("Study Physics today at 8 PM", "TASK intent, date=today, time=20:00"),
    ("Remind me to call mom today", "TASK intent, date=today, time empty"),
    ("Kal subah 8 baje gym", "TASK intent, date=tomorrow, time=08:00"),
    ("Parso doctor appointment hai", "TASK intent, date=day after tomorrow"),
    ("Remind me in 2 hours", "TASK intent, time=now+2hrs"),
    ("3 baje meeting hai", "Ambiguous — should ask AM or PM"),
    ("Create task at 25 PM", "Invalid time — should reject"),
    ("Remind me yesterday", "Past date — should warn"),
    ("Go to gym every day at 6 AM", "Recurring daily, time=06:00"),
    ("What do I have today?", "VIEW intent, period=today"),
    ("Show my tasks for this month", "VIEW intent, period=month"),
    ("Remember my exam is on June 20", "MEMORY_SAVE intent"),
    ("When is my exam?", "MEMORY_GET intent"),
    ("Tomorrow buy groceries and call mom", "MULTIPLE intent, 2 tasks"),
    ("How do I focus better?", "CHAT or ADVICE intent"),
]