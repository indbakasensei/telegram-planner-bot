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
    # ── SECTION A: Basic Task Creation ──────────────────
    ("Study Physics today at 8 PM",          "TASK · date=today · time=20:00 · priority=medium"),
    ("Remind me to call mom today",           "TASK · date=today · time=null (asks for time)"),
    ("Tomorrow at 7 AM go for a run",         "TASK · date=tomorrow · time=07:00"),
    ("Submit at 3pm",                         "TASK · time=15:00 (PM converted)"),
    ("Meeting at noon",                       "TASK · time=12:00"),

    # ── SECTION B: Hindi & Hinglish ─────────────────────
    ("Kal subah 8 baje gym yaad dila dena",   "TASK · tomorrow · 08:00"),
    ("Aaj raat 10 baje assignment submit",    "TASK · today · 22:00"),
    ("Parso doctor appointment hai",           "TASK · day after tomorrow"),
    ("Shaam ko meeting hai",                   "TASK · today · 18:00 (NOT 15:00)"),
    ("Dopahar mein lunch",                     "TASK · today · 13:00 (lunch=13:00 since v3.0)"),
    ("Jaldi karo, urgent task hai",            "TASK · priority=high · time=now+30min"),

    # ── SECTION C: Date & Time Parsing ──────────────────
    ("Remind me in 2 hours",                  "TASK · time=now+2hrs (relative)"),
    ("Remind me in 1 min to test",            "TASK · time=now+1min (NOT 01:00 — known bug fixed)"),
    ("Meeting at 1400",                       "TASK · time=14:00 (military)"),
    ("3 baje meeting hai",                    "Ambiguous → asks AM or PM buttons"),
    ("Create task tomorrow at 25 PM",         "⚠️ Invalid time rejected"),
    ("Remind me yesterday",                   "⚠️ Past date warning"),
    ("Submit on 2026-12-25",                  "TASK (NOT MEMORY_SAVE — date+verb=task)"),

    # ── SECTION D: Deadline Detection ───────────────────
    ("Submit assignment by Friday 5pm",       "TASK + is_deadline=True → confirms '⏳ Deadline mode ON'"),
    ("Assignment due tomorrow 10am",          "TASK + is_deadline=True"),
    ("Deliver presentation by Wednesday",     "TASK + is_deadline=True"),
    ("Meeting at 5pm",                        "TASK + is_deadline=False (no deadline phrasing)"),

    # ── SECTION E: Recurring Tasks & Habits ─────────────
    ("Go to gym every day at 6 AM",           "HABIT · daily · time=06:00"),
    ("Har Monday gym jana hai",               "HABIT · weekly Mon (NOT GOAL — regression test)"),
    ("Yoga every Sunday at 8 AM",             "HABIT · weekly Sun · time=08:00"),
    ("Pay rent on the 1st of every month",    "HABIT · monthly · day=1"),
    ("Har roz exercise karna hai",            "HABIT · daily (Hindi)"),

    # ── SECTION F: Memory System ─────────────────────────
    ("Remember my exam is on June 20",        "MEMORY_SAVE · key=exam · value=June 20"),
    ("When is my exam?",                      "MEMORY_GET → retrieves stored value"),
    ("Remember my favorite color is blue",    "MEMORY_SAVE new entry"),
    ("Remember my favorite color is red",     "MEMORY_SAVE → UPDATES (no duplicate)"),

    # ── SECTION G: Goals ────────────────────────────────
    ("I want to read 12 books this year",     "GOAL intent → saved + Dashboard link shown"),
    ("I want to get fit by December",         "GOAL intent · deadline=December"),

    # ── SECTION H: View & Planning ──────────────────────
    ("What do I have today?",                 "VIEW · period=today (no task created)"),
    ("Show my tasks for this week",           "VIEW · period=week"),
    ("plan today",                            "PLAN → time-blocked schedule, asks Apply?"),
    ("plan my week",                          "PLAN → 7-day view with overload warnings"),

    # ── SECTION I: Multiple Tasks ────────────────────────
    ("Tomorrow buy groceries and call mom",   "MULTIPLE · 2 tasks detected and confirmed"),
    ("Gym at 7 and study at 9 tomorrow",      "MULTIPLE · 2 tasks · different times"),

    # ── SECTION J: AI Reasoning (v10.2+) ────────────────
    ("think what should I focus on today?",   "THINK → free AI reasoning with your profile context"),
    ("think am I taking on too much?",        "THINK → analysis of open + overdue tasks"),
    ("ask how can I improve my mornings?",    "THINK → personalized advice (uses habits/history)"),

    # ── SECTION K: Search & Tools (v10.0) ───────────────
    ("search physics",                        "SEARCH → finds matching tasks + memories + habits"),
    ("templates",                             "LIST → shows all saved templates"),
    ("export",                                "EXPORT → full plain-text data backup"),

    # ── SECTION L: AI Models & Analytics (v11.0+) ───────
    ("status",                                "STATUS → 3-test AI benchmark (Connectivity/JSON/Intent)"),
    ("status full",                           "STATUS → 6-test benchmark with grade A+-F"),
    ("models",                                "MODELS → 6 model statuses + real usage from analytics"),
    ("image a sunset over mountains",         "IMAGE → FLUX.1-schnell via NIM, ~10s"),
    ("video waves on a beach",                "VIDEO → FLUX frame + SVD animation via NIM, 1-3 min"),
    ("usage",                                 "USAGE → today + lifetime AI call stats"),
    ("performance",                           "PERF → p50/p95/p99 latency + fastest/slowest model"),
    ("errors",                                "ERRORS → error timeline + breakdown by model"),

    # ── SECTION M: Dashboard (v9.0) ─────────────────────
    ("dashboard",                             "DASHBOARD → home hub with all counts + inline buttons"),

    # ── SECTION N: Settings & Wellness ──────────────────
    ("settings",                              "SETTINGS → quiet hours, interval, wellness status"),
    ("wellness on",                           "WELLNESS → enabled (pings water/break/eyes nudges)"),
    ("insights",                              "INSIGHTS → learned patterns: tone, active hours, snoozes"),
    ("proactive",                             "PROACTIVE → control panel for all automatic features"),

    # ── SECTION O: Edge Cases ───────────────────────────
    ("I'm tired today",                       "CHAT intent (NOT a task — no stray task creation)"),
    ("How are you?",                          "CHAT intent → conversational reply"),
    ("Show plan for today",                   "VIEW intent (NOT task creation)"),
    ("Meeting this evening",                  "time=18:00 (NOT 15:00 — vague-time parser wins)"),
    ("What time is it?",                      "CHAT → shows current IST time"),

    # ── SECTION P: Project Management (v12.0) ──────────
    ("goal build drone by 2026-08-15",          "GOAL created → note the goal_id"),
    ("need <id> motor, propeller, battery",     "MATERIALS → 3 added, use your goal_id"),
    ("got motor",                                "MARK ACQUIRED → fuzzy match, shows progress"),
    ("started <id>",                             "WORKLOG → work started, project state=started"),
    ("worklog <id> frame is done",               "WORKLOG progress entry, kind=progress"),
    ("project <id>",                             "PROJECT CARD → materials list, worklog, progress bar"),
    ("projects",                                 "ALL PROJECTS with progress bars"),
    ("shopping",                                 "SHOPPING LIST → all pending materials grouped by project"),
    ("finished <id>",                            "MARK DONE → 🎉, work_state=finished"),
]