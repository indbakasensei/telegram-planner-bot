import json
import logging
import os
import shutil
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
IST = ZoneInfo("Asia/Kolkata")

DB_NAME = "planner.db"

# v13.2: bumped whenever init_db() adds a new migration step. Purely a
# diagnostic marker (read by verify_schema_integrity() at startup) --
# nothing branches on its value, so an out-of-date number here cannot
# change runtime behavior, only what the startup integrity report says.
SCHEMA_VERSION = 2

logger = logging.getLogger(__name__)

# Every table that a fresh v13.2+ database should end up with, and the
# indexes init_db() creates for it. Used by both init_db() (to create
# them) and verify_schema_integrity() (to confirm they exist) so the two
# can't silently drift apart.
REQUIRED_TABLES = [
    "tasks", "memories", "goals", "habit_log", "user_preferences",
    "completions_log", "snooze_log", "interaction_log", "task_templates",
    "missed_capabilities", "ai_observations", "project_materials",
    "project_worklog",
    # v15.0-alpha.1 Workspace Foundation. These ship in every database
    # (additive, idempotent schema -- MIGRATION.md §4.1) but stay EMPTY
    # and UNUSED while feature_flags.WORKSPACE is OFF, exactly as the v14
    # Offline-Engine tables/flags shipped ahead of their consumers. No
    # existing behaviour reads or writes them yet.
    "workspaces", "milestones", "notes", "attachments", "tags",
    "entity_tags",
    # v15.0-alpha.5: append-only Knowledge Timeline (docs/v15/KTD.md).
    "timeline_events",
    # v15.0-alpha.6: durable outbound sync outbox (docs/v15/TWID.md).
    "sync_outbox",
]

# (index_name, table, columns, why) -- documented per Sprint 3 task 2.
# Each entry lists the specific query pattern(s) that motivated it, found
# by reviewing every WHERE/ORDER BY/GROUP BY in this file and scheduler.py.
REQUIRED_INDEXES = [
    ("idx_tasks_user_done_paused", "tasks", "(user_id, done, paused)",
     "The single most common filter across this file: nearly every "
     "per-user active-task read (get_tasks, get_overdue_tasks, "
     "get_upcoming_deadlines, get_stale_tasks, count_tasks_at_time, "
     "get_high_priority_soon, get_data_stats, weekly report, dashboard "
     "groups, search_all) filters on user_id, then done, then often "
     "paused."),
    ("idx_tasks_due", "tasks", "(due_date, due_time)",
     "scheduler.py's get_due_tasks() Case 1 -- the highest-FREQUENCY "
     "query in the system (every 60s), and NOT scoped by user_id since "
     "it checks every user's due tasks in one pass."),
    ("idx_tasks_recurrence", "tasks", "(recurrence_type, done, paused)",
     "scheduler.py's get_due_tasks() Cases 2-4 (daily/weekly/monthly "
     "recurring tasks) -- also a global, non-user-scoped scan every 60s."),
    ("idx_memories_user_key", "memories", "(user_id, key)",
     "Every memory read/write path does an exact (user_id, key) lookup: "
     "save_memory()'s existence check before insert/update, get_memory(), "
     "delete_memory()."),
    ("idx_goals_user", "goals", "(user_id)",
     "Every goal listing/progress query (get_goals, get_goals_full, "
     "get_project_overview, get_active_projects) filters by user_id."),
    ("idx_completions_log_user_time", "completions_log", "(user_id, completed_at)",
     "get_completion_patterns() and get_typical_time_for_category() "
     "filter by user_id and a completed_at cutoff."),
    ("idx_snooze_log_user_time", "snooze_log", "(user_id, snoozed_at)",
     "get_snooze_patterns() filters by user_id and a snoozed_at cutoff."),
    ("idx_interaction_log_user_time", "interaction_log", "(user_id, timestamp)",
     "get_active_hours() filters by user_id and a timestamp cutoff."),
    ("idx_ai_observations_user_status", "ai_observations", "(user_id, status)",
     "get_pending_observations() filters by user_id and status='pending' "
     "on every /suggestions call and the daily observation_engine job."),
    ("idx_missed_capabilities_user", "missed_capabilities", "(user_id, created_at)",
     "get_missed_capabilities() filters by user_id, ordered by created_at, "
     "on every /misses call."),
]
# Deliberately NOT indexed, with reasoning (so a future pass doesn't
# re-litigate this without context):
#   - user_preferences.user_id: already the table's INTEGER PRIMARY KEY,
#     which SQLite indexes automatically (it IS the rowid) -- a separate
#     index would be pure duplication.
#   - tasks.snooze_until, tasks.parent_task_id: real but low-frequency
#     query patterns (snooze-expiry check, subtasks); adding an index
#     helps reads but costs write overhead on every task insert/update,
#     and both are already narrowed by the indexes above before SQLite
#     would need to touch these columns. Revisit if profiling ever shows
#     otherwise.
#   - habit_log: already has UNIQUE(habit_id, log_date), which SQLite
#     auto-indexes and which already covers every habit_log query's
#     leading filter.
#   - task_templates: already has UNIQUE(user_id, name), auto-indexed.
#   - project_materials, project_worklog: already indexed (idx_materials_*,
#     idx_worklog_*, added in v12.0) -- reviewed, still correct, untouched.


def get_connection(db_name: str = None) -> sqlite3.Connection:
    """Open a connection with this project's standard PRAGMAs applied.

    New infrastructure code (backup, integrity checks) uses this. Existing
    functions keep their own plain `sqlite3.connect(DB_NAME)` calls
    unchanged -- retrofitting all ~100 of them was judged out of scope for
    an infrastructure sprint whose brief is "do not change behaviour"; see
    CHANGELOG.md's v13.2 entry for the reasoning.
    """
    conn = sqlite3.connect(db_name or DB_NAME)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def backup_database(reason: str = "migration", keep: int = 5, db_name: str = None) -> str | None:
    """Back up the database file before a migration runs, using SQLite's
    own online-backup API (safe against a concurrently-open WAL file,
    unlike a raw file copy). Returns the backup path, or None if there
    was nothing to back up yet (fresh/empty database) or backup failed
    (logged, never raised -- a failed backup must not block startup).
    Keeps only the `keep` most recent backups per reason to avoid
    unbounded disk growth.
    """
    src_name = db_name or DB_NAME
    if not os.path.exists(src_name) or os.path.getsize(src_name) == 0:
        return None  # nothing to protect yet

    backup_dir = os.path.join(os.path.dirname(os.path.abspath(src_name)) or ".", "backups")
    try:
        os.makedirs(backup_dir, exist_ok=True)
        stamp = datetime.now(IST).strftime("%Y%m%d_%H%M%S")
        dest_path = os.path.join(backup_dir, f"{os.path.basename(src_name)}.{reason}.{stamp}.bak")

        src_conn = sqlite3.connect(src_name)
        dest_conn = sqlite3.connect(dest_path)
        with dest_conn:
            src_conn.backup(dest_conn)
        dest_conn.close()
        src_conn.close()

        # Prune old backups for this reason, keep the `keep` most recent
        prefix = f"{os.path.basename(src_name)}.{reason}."
        existing = sorted(
            f for f in os.listdir(backup_dir) if f.startswith(prefix)
        )
        for old in existing[:-keep] if keep > 0 else existing:
            try:
                os.remove(os.path.join(backup_dir, old))
            except OSError:
                pass

        logger.info(f"Database backed up to {dest_path} (reason={reason}).")
        return dest_path
    except Exception as e:
        logger.error(f"Database backup failed (reason={reason}): {e} — continuing without it.")
        return None


def verify_schema_integrity(db_name: str = None) -> dict:
    """Startup integrity check: confirms required tables and indexes
    exist, reports schema version, foreign-key enforcement setting, and
    journal mode. Never raises -- returns a report dict for the caller to
    log/act on; a missing piece is reported, not silently fixed here
    (fixing schema issues is init_db()'s job, this function only verifies
    and reports, per Sprint 3 task 5).
    """
    name = db_name or DB_NAME
    report = {
        "ok": True,
        "missing_tables": [],
        "missing_indexes": [],
        "schema_version": None,
        "foreign_keys": None,
        "journal_mode": None,
    }
    try:
        conn = get_connection(name)
        c = conn.cursor()

        c.execute("SELECT name FROM sqlite_master WHERE type='table'")
        existing_tables = {row[0] for row in c.fetchall()}
        report["missing_tables"] = [t for t in REQUIRED_TABLES if t not in existing_tables]

        c.execute("SELECT name FROM sqlite_master WHERE type='index'")
        existing_indexes = {row[0] for row in c.fetchall()}
        report["missing_indexes"] = [
            idx for idx, _, _, _ in REQUIRED_INDEXES if idx not in existing_indexes
        ]

        c.execute("PRAGMA user_version")
        report["schema_version"] = c.fetchone()[0]

        c.execute("PRAGMA foreign_keys")
        report["foreign_keys"] = bool(c.fetchone()[0])

        c.execute("PRAGMA journal_mode")
        report["journal_mode"] = c.fetchone()[0]

        conn.close()
        report["ok"] = not report["missing_tables"] and not report["missing_indexes"]
    except Exception as e:
        logger.error(f"verify_schema_integrity failed to run: {e}")
        report["ok"] = False
        report["error"] = str(e)
    return report


def _safe_add_column(c, table: str, col: str, definition: str) -> None:
    """Run one ALTER TABLE ... ADD COLUMN, distinguishing the expected
    "column already exists" case (silent -- this is what makes the
    additive-migration pattern idempotent) from anything else (disk full,
    corruption, permissions, a genuinely malformed DDL string), which is
    now logged loudly instead of silently swallowed. Sprint 3 task 3 --
    was previously a bare `except Exception: pass` that could not tell
    these apart.
    """
    try:
        c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {definition}")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e).lower():
            return  # expected: this column already exists, nothing to do
        logger.error(f"Migration failed: ALTER TABLE {table} ADD COLUMN {col} — {e}")
    except sqlite3.Error as e:
        logger.error(f"Unexpected database error adding {table}.{col}: {e}")


def init_db():
    # v13.2: back up before any migration touches the file. No-op on a
    # fresh/empty database (nothing to protect yet). A failed backup is
    # logged and does not block startup -- see backup_database().
    backup_database(reason="startup_migration")

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    # v13.2: WAL mode -- readers no longer block writers (or vice versa),
    # which matters once the scheduler and multiple handlers are hitting
    # the database concurrently. Persisted in the file itself, so this
    # only needs to run once per database file, but re-asserting it on
    # every init_db() call is harmless and cheap.
    c.execute("PRAGMA journal_mode=WAL")
    logger.info(f"Database journal mode: {c.execute('PRAGMA journal_mode').fetchone()[0]}")

    c.execute('''CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        due_date TEXT,
        due_time TEXT,
        category TEXT DEFAULT 'General',
        priority TEXT DEFAULT 'medium',
        done INTEGER DEFAULT 0,
        recurrence_type TEXT DEFAULT NULL,
        recurrence_weekday INTEGER DEFAULT NULL,
        recurrence_day INTEGER DEFAULT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')

    for col, definition in [
        ("priority", "TEXT DEFAULT 'medium'"),
        ("recurrence_type", "TEXT DEFAULT NULL"),
        ("recurrence_weekday", "INTEGER DEFAULT NULL"),
        ("recurrence_day", "INTEGER DEFAULT NULL"),
        ("paused", "INTEGER DEFAULT 0"),
        ("snooze_until", "TEXT DEFAULT NULL"),
        ("last_reminded", "TEXT DEFAULT NULL"),
        ("tags", "TEXT DEFAULT NULL"),
        ("reminder_count", "INTEGER DEFAULT 0"),
        ("parent_task_id", "INTEGER DEFAULT NULL"),
        ("is_habit", "INTEGER DEFAULT 0"),
        ("habit_start_date", "TEXT DEFAULT NULL"),
        ("current_streak", "INTEGER DEFAULT 0"),
        ("longest_streak", "INTEGER DEFAULT 0"),
        ("last_completed", "TEXT DEFAULT NULL"),
        ("followup_sent", "TEXT DEFAULT NULL"),
        ("followup_count", "INTEGER DEFAULT 0"),
        ("snooze_count", "INTEGER DEFAULT 0"),
        ("stale_flagged", "INTEGER DEFAULT 0"),
        ("is_deadline", "INTEGER DEFAULT 0"),
        ("buffer_sent", "TEXT DEFAULT ''"),
    ]:
        _safe_add_column(c, "tasks", col, definition)

    # NOTE: no UNIQUE constraint relied upon here — save_memory() below
    # does a manual check-then-insert/update instead of INSERT...ON CONFLICT,
    # so this works correctly whether the table was just created or already
    # existed from an earlier version of the bot (which lacked UNIQUE).
    c.execute('''CREATE TABLE IF NOT EXISTS memories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        key TEXT NOT NULL,
        value TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS habit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        habit_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        log_date TEXT NOT NULL,
        completed INTEGER DEFAULT 1,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(habit_id, log_date)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS goals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        deadline TEXT,
        progress INTEGER DEFAULT 0,
        done INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    # v9.0 hotfix: legacy goals tables may pre-date some columns.
    # CREATE TABLE IF NOT EXISTS skips when table exists, so explicitly migrate.
    for col, ddl in [
        ("deadline", "TEXT"),
        ("progress", "INTEGER DEFAULT 0"),
        ("done", "INTEGER DEFAULT 0"),
        ("created_at", "TEXT DEFAULT CURRENT_TIMESTAMP"),
        ("target", "INTEGER DEFAULT 100"),
    ]:
        _safe_add_column(c, "goals", col, ddl)

    conn.commit()
    # v8.0: ensure preference + learning table migrations run at startup
    try:
        _init_preferences(conn)
    except sqlite3.Error as e:
        logger.error(f"Preferences table migration failed: {e}")
    try:
        _init_learning_tables(conn)
    except sqlite3.Error as e:
        logger.error(f"Learning tables migration failed: {e}")
    try:
        _init_project_tables(conn)
    except sqlite3.Error as e:
        logger.error(f"Project tables migration failed: {e}")
    try:
        _init_templates(conn)
    except sqlite3.Error as e:
        logger.error(f"Templates table migration failed: {e}")
    try:
        _init_missed_capabilities(conn)
    except sqlite3.Error as e:
        logger.error(f"Missed-capabilities table migration failed: {e}")
    try:
        _init_observations(conn)
    except sqlite3.Error as e:
        logger.error(f"Observations table migration failed: {e}")
    # v15.0-alpha.1: Workspace Foundation schema. Additive and idempotent
    # (MIGRATION.md). Runs on every startup; creates empty tables + adds
    # nullable workspace_id/milestone_id columns to existing tables. No
    # data is migrated here and no existing behaviour changes -- the tables
    # stay dormant until feature_flags.WORKSPACE is enabled.
    try:
        _init_workspace_tables(conn)
    except sqlite3.Error as e:
        logger.error(f"Workspace tables migration failed: {e}")
    # v11.1: ai_usage analytics table. Deliberately left as a broad
    # try/except (not narrowed like the migration steps above) -- this is
    # an optional-dependency-availability guard for the known-incomplete
    # `analytics` package, not schema migration; see DEBUGGING.md's Known
    # Issues and ENGINEERING_AUDIT.md for that already-tracked, separate
    # fix. Out of scope for this infrastructure sprint.
    try:
        from analytics import init_usage_table
        init_usage_table(DB_NAME)
    except Exception:
        pass

    # v13.2: create every index reviewed in Sprint 3 task 2 (see
    # REQUIRED_INDEXES above for what each one serves). CREATE INDEX IF
    # NOT EXISTS is idempotent, same additive pattern as the table/column
    # migrations above.
    for idx_name, table, columns, _why in REQUIRED_INDEXES:
        try:
            c.execute(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table}{columns}")
        except sqlite3.Error as e:
            logger.error(f"Failed to create index {idx_name} on {table}: {e}")

    c.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
    conn.commit()
    conn.close()
    logger.info(f"Database initialized (schema_version={SCHEMA_VERSION}).")


# ── Tasks ──────────────────────────────────────────────
def add_task(user_id, title, due_date=None, due_time=None,
             category='General', priority='medium',
             recurrence_type=None, recurrence_weekday=None, recurrence_day=None):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''INSERT INTO tasks
        (user_id, title, due_date, due_time, category, priority,
         recurrence_type, recurrence_weekday, recurrence_day)
        VALUES (?,?,?,?,?,?,?,?,?)''',
        (user_id, title, due_date, due_time, category, priority,
         recurrence_type, recurrence_weekday, recurrence_day))
    task_id = c.lastrowid
    conn.commit()
    conn.close()
    return task_id

def get_tasks(user_id, done=0):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''SELECT id, title, due_date, due_time, category, priority,
                 recurrence_type
                 FROM tasks WHERE user_id=? AND done=?
                 ORDER BY due_date ASC, due_time ASC''', (user_id, done))
    tasks = c.fetchall()
    conn.close()
    return tasks

def get_tasks_by_date(user_id, date):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''SELECT id, title, due_date, due_time, category, priority
                 FROM tasks WHERE user_id=? AND due_date=? AND done=0
                 ORDER BY due_time ASC''', (user_id, date))
    tasks = c.fetchall()
    conn.close()
    return tasks

def get_tasks_by_week(user_id, start_date, end_date):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''SELECT id, title, due_date, due_time, category, priority
                 FROM tasks WHERE user_id=? AND due_date BETWEEN ? AND ? AND done=0
                 ORDER BY due_date ASC, due_time ASC''',
              (user_id, start_date, end_date))
    tasks = c.fetchall()
    conn.close()
    return tasks

def get_task_by_id(task_id, user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''SELECT id, title, due_date, due_time, category, priority,
                 recurrence_type
                 FROM tasks WHERE id=? AND user_id=?''', (task_id, user_id))
    task = c.fetchone()
    conn.close()
    return task

def search_tasks_by_title(user_id, keyword):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''SELECT id, title, due_date, due_time, category
                 FROM tasks WHERE user_id=? AND done=0 AND title LIKE ?
                 ORDER BY due_date ASC''', (user_id, f'%{keyword}%'))
    tasks = c.fetchall()
    conn.close()
    return tasks

def mark_done(task_id, user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('UPDATE tasks SET done=1 WHERE id=? AND user_id=?', (task_id, user_id))
    conn.commit()
    conn.close()

def delete_task(task_id, user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('DELETE FROM tasks WHERE id=? AND user_id=?', (task_id, user_id))
    conn.commit()
    conn.close()

def update_task(task_id, user_id, title=None, due_date=None,
                due_time=None, category=None, priority=None):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    fields = {"title": title, "due_date": due_date, "due_time": due_time,
              "category": category, "priority": priority}
    for field, value in fields.items():
        if value is not None:
            c.execute(f'UPDATE tasks SET {field}=? WHERE id=? AND user_id=?',
                      (value, task_id, user_id))
    conn.commit()
    conn.close()

def task_exists(user_id, title, due_date):
    if not title:
        return False
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''SELECT id FROM tasks
                 WHERE user_id=? AND title=? AND due_date=? AND done=0''',
              (user_id, title, due_date))
    exists = c.fetchone() is not None
    conn.close()
    return exists

def get_recurring_tasks():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''SELECT id, user_id, title, due_time, category,
                 recurrence_type, recurrence_weekday, recurrence_day
                 FROM tasks WHERE recurrence_type IS NOT NULL AND done=0''')
    tasks = c.fetchall()
    conn.close()
    return tasks

# ── Memory ─────────────────────────────────────────────
def _normalize_memory_key(key):
    """Canonical form for MATCHING two memory keys (v14.26 bug fix). The
    AI generates the same fact's key inconsistently — 'favorite color'
    vs 'favorite_color' — which used to create two separate rows instead
    of overwriting. Comparing the normalized form (lowercased, with
    underscores/hyphens/whitespace collapsed to a single space) makes
    those variants match. Only used for comparison; the stored key text
    is left as-is, so existing keys keep working."""
    if not key:
        return ""
    k = str(key).lower().strip().replace("_", " ").replace("-", " ")
    return " ".join(k.split())

def save_memory(user_id, key, value):
    """
    Manual check-then-insert/update instead of INSERT...ON CONFLICT.
    This avoids depending on a UNIQUE(user_id, key) constraint, which
    older databases (created before this constraint was added) won't have.
    SQLite raises 'ON CONFLICT clause does not match any PRIMARY KEY or
    UNIQUE constraint' in that case — this approach works regardless.

    v14.26: matches on the NORMALIZED key so separator variants of the
    same fact overwrite rather than duplicate, and any pre-existing
    duplicate rows (different key spellings) are collapsed on the next save.
    """
    if not key:
        return False
    canon = _normalize_memory_key(key)
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT id, key FROM memories WHERE user_id=?', (user_id,))
    matches = [rid for rid, k in c.fetchall() if _normalize_memory_key(k) == canon]
    if matches:
        # Update the first, delete any duplicates that normalize the same.
        c.execute('UPDATE memories SET value=? WHERE id=?', (value, matches[0]))
        for extra in matches[1:]:
            c.execute('DELETE FROM memories WHERE id=?', (extra,))
    else:
        c.execute('INSERT INTO memories (user_id, key, value) VALUES (?,?,?)',
                  (user_id, key.lower().strip(), value))
    conn.commit()
    conn.close()
    return True

def get_memory(user_id, key):
    # v14.26: match on the normalized key so a fact stored under a
    # slightly different spelling is still found.
    canon = _normalize_memory_key(key)
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT key, value FROM memories WHERE user_id=?', (user_id,))
    rows = c.fetchall()
    conn.close()
    for k, v in rows:
        if _normalize_memory_key(k) == canon:
            return v
    return None

def get_all_memories(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT key, value FROM memories WHERE user_id=? ORDER BY created_at DESC',
              (user_id,))
    memories = c.fetchall()
    conn.close()
    return memories

def search_memories(user_id, query):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''SELECT key, value FROM memories
                 WHERE user_id=? AND (key LIKE ? OR value LIKE ?)
                 ORDER BY created_at DESC''',
              (user_id, f'%{query}%', f'%{query}%'))
    memories = c.fetchall()
    conn.close()
    return memories


# Question words to strip when a whole question ("When is my exam?") is used
# as a memory query -- so it falls back to the real keyword ("exam").
_MEM_STOPWORDS = frozenset({
    "when", "what", "whats", "whens", "where", "who", "which", "why", "how",
    "is", "are", "am", "was", "were", "my", "the", "a", "an", "of", "for",
    "on", "in", "to", "me", "you", "do", "does", "did", "have", "has", "had",
    "tell", "show", "about", "please", "that", "this", "it", "i", "again",
})


def search_memories_smart(user_id, query):
    """Search memories by the full query, then fall back to significant
    keywords so a natural question ("When is my exam?") still finds the
    'exam' memory instead of matching nothing (DBG-0006). Returns a
    de-duplicated [(key, value)] list, or [] if nothing matches -- callers
    should NOT dump all memories on empty."""
    direct = search_memories(user_id, query)
    if direct:
        return direct
    import re as _re
    words = [w for w in _re.findall(r"[a-z0-9]+", (query or "").lower())
             if len(w) > 2 and w not in _MEM_STOPWORDS]
    seen, out = set(), []
    for w in words:
        for k, v in search_memories(user_id, w):
            if (k, v) not in seen:
                seen.add((k, v))
                out.append((k, v))
    return out

def delete_memory(user_id, key):
    # v14.26: delete every row whose key normalizes to the requested one
    # (handles separator variants and any leftover duplicates).
    if not key:
        return False
    canon = _normalize_memory_key(key)
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT id, key FROM memories WHERE user_id=?', (user_id,))
    ids = [rid for rid, k in c.fetchall() if _normalize_memory_key(k) == canon]
    for rid in ids:
        c.execute('DELETE FROM memories WHERE id=?', (rid,))
    conn.commit()
    conn.close()
    return bool(ids)

# ── Goals ──────────────────────────────────────────────
def add_goal(user_id, title, deadline=None):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('INSERT INTO goals (user_id, title, deadline) VALUES (?,?,?)',
              (user_id, title, deadline))
    goal_id = c.lastrowid
    conn.commit()
    conn.close()
    return goal_id

def get_goals(user_id):
    """Legacy goals query — defensive against missing 'done' column."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    try:
        c.execute("PRAGMA table_info(goals)")
        cols = {r[1] for r in c.fetchall()}
    except Exception:
        cols = set()
    where_done = " AND COALESCE(done,0)=0" if "done" in cols else ""
    progress_expr = "COALESCE(progress,0)" if "progress" in cols else "0"
    deadline_expr = "deadline" if "deadline" in cols else "NULL"
    try:
        c.execute(
            f"SELECT id, title, {deadline_expr}, {progress_expr} "
            f"FROM goals WHERE user_id=?{where_done}",
            (user_id,)
        )
        goals = c.fetchall()
    except Exception:
        goals = []
    conn.close()
    return goals

# ── v1.1: Snooze / Pause / Postpone ───────────────────
def snooze_task(task_id, user_id, snooze_until):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE tasks SET snooze_until=? WHERE id=? AND user_id=?",
              (snooze_until, task_id, user_id))
    conn.commit()
    conn.close()

def postpone_task(task_id, user_id, new_date):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE tasks SET due_date=?, snooze_until=NULL WHERE id=? AND user_id=?",
              (new_date, task_id, user_id))
    conn.commit()
    conn.close()

def pause_task(task_id, user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE tasks SET paused=1 WHERE id=? AND user_id=?", (task_id, user_id))
    conn.commit()
    conn.close()

def resume_task(task_id, user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE tasks SET paused=0 WHERE id=? AND user_id=?", (task_id, user_id))
    conn.commit()
    conn.close()

def mark_reminded(task_id, timestamp):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE tasks SET last_reminded=? WHERE id=?", (timestamp, task_id))
    conn.commit()
    conn.close()

def get_paused_tasks(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT id, title, due_date, due_time, category FROM tasks WHERE user_id=? AND paused=1 AND done=0", (user_id,))
    tasks = c.fetchall()
    conn.close()
    return tasks

# ── v1.2: Overdue / Deadline / Tags ───────────────────
def get_overdue_tasks(user_id, current_date, current_time):
    """Tasks where due_date < today, or due_date = today and due_time < now."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""SELECT id, title, due_date, due_time, category, priority
        FROM tasks WHERE user_id=? AND done=0 AND paused=0
        AND due_date IS NOT NULL
        AND (due_date < ? OR (due_date = ? AND due_time IS NOT NULL AND due_time < ?))
        ORDER BY due_date ASC, due_time ASC""",
        (user_id, current_date, current_date, current_time))
    tasks = c.fetchall()
    conn.close()
    return tasks

def get_upcoming_deadlines(user_id, current_date, days_ahead=2):
    """Tasks due within the next N days (for deadline warnings)."""
    from datetime import datetime, timedelta
    end = (datetime.strptime(current_date, "%Y-%m-%d") + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""SELECT id, title, due_date, due_time, category, priority
        FROM tasks WHERE user_id=? AND done=0 AND paused=0
        AND due_date IS NOT NULL AND due_date BETWEEN ? AND ?
        ORDER BY due_date ASC, due_time ASC""",
        (user_id, current_date, end))
    tasks = c.fetchall()
    conn.close()
    return tasks

def set_tags(task_id, user_id, tags_str):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE tasks SET tags=? WHERE id=? AND user_id=?",
              (tags_str, task_id, user_id))
    conn.commit()
    conn.close()

def get_tasks_by_tag(user_id, tag):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT id, title, due_date, due_time, category, priority, tags FROM tasks WHERE user_id=? AND done=0 AND tags LIKE ?",
              (user_id, f"%{tag}%"))
    tasks = c.fetchall()
    conn.close()
    return tasks

def carry_forward_overdue(user_id, current_date):
    """Move all overdue tasks to today (carry forward)."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""UPDATE tasks SET due_date=?
        WHERE user_id=? AND done=0 AND paused=0
        AND due_date IS NOT NULL AND due_date < ?
        AND (recurrence_type IS NULL OR recurrence_type='')""",
        (current_date, user_id, current_date))
    count = c.rowcount
    conn.commit()
    conn.close()
    return count

# ── v2.0: User Preferences + Reminder Tracking ────────
def _init_preferences(conn):
    """Create preferences table if missing. Called by init_db."""
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS user_preferences (
        user_id INTEGER PRIMARY KEY,
        quiet_start TEXT DEFAULT '23:00',
        quiet_end TEXT DEFAULT '07:00',
        reminder_interval INTEGER DEFAULT 30,
        max_reminders_per_task INTEGER DEFAULT 5,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    # v8.0: wellness reminder columns — migrate safely
    for col, ddl in [
        ("wellness_on", "INTEGER DEFAULT 0"),
        ("wellness_interval", "INTEGER DEFAULT 90"),
        ("wellness_types", "TEXT DEFAULT 'all'"),
        ("last_wellness", "TEXT DEFAULT NULL"),
    ]:
        _safe_add_column(c, "user_preferences", col, ddl)
    conn.commit()

def get_user_prefs(user_id):
    conn = sqlite3.connect(DB_NAME)
    _init_preferences(conn)
    c = conn.cursor()
    c.execute("SELECT quiet_start, quiet_end, reminder_interval, max_reminders_per_task FROM user_preferences WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {"quiet_start": row[0], "quiet_end": row[1], "interval": row[2], "max_reminders": row[3]}
    return {"quiet_start": "23:00", "quiet_end": "07:00", "interval": 30, "max_reminders": 5}

def set_quiet_hours(user_id, start, end):
    conn = sqlite3.connect(DB_NAME)
    _init_preferences(conn)
    c = conn.cursor()
    c.execute("SELECT user_id FROM user_preferences WHERE user_id=?", (user_id,))
    if c.fetchone():
        c.execute("UPDATE user_preferences SET quiet_start=?, quiet_end=? WHERE user_id=?", (start, end, user_id))
    else:
        c.execute("INSERT INTO user_preferences (user_id, quiet_start, quiet_end) VALUES (?,?,?)", (user_id, start, end))
    conn.commit()
    conn.close()

def set_reminder_interval(user_id, minutes):
    conn = sqlite3.connect(DB_NAME)
    _init_preferences(conn)
    c = conn.cursor()
    c.execute("SELECT user_id FROM user_preferences WHERE user_id=?", (user_id,))
    if c.fetchone():
        c.execute("UPDATE user_preferences SET reminder_interval=? WHERE user_id=?", (minutes, user_id))
    else:
        c.execute("INSERT INTO user_preferences (user_id, reminder_interval) VALUES (?,?)", (user_id, minutes))
    conn.commit()
    conn.close()

def increment_reminder_count(task_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE tasks SET reminder_count = COALESCE(reminder_count, 0) + 1 WHERE id=?", (task_id,))
    conn.commit()
    conn.close()

def get_reminder_count(task_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT COALESCE(reminder_count, 0) FROM tasks WHERE id=?", (task_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0

def get_tasks_needing_reminder(current_date, current_time, current_dt):
    """Get all undone, unpaused tasks that are past due and haven't been reminded recently."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""SELECT t.id, t.user_id, t.title, t.due_date, t.due_time,
                 COALESCE(t.reminder_count, 0) as rcount, t.last_reminded
        FROM tasks t
        WHERE t.done=0 AND t.paused=0
        AND t.due_date IS NOT NULL
        AND (t.due_date < ? OR (t.due_date = ? AND t.due_time IS NOT NULL AND t.due_time <= ?))
        AND (t.snooze_until IS NULL OR t.snooze_until <= ?)
        AND (t.recurrence_type IS NULL OR t.recurrence_type = '')
        ORDER BY t.due_date ASC, t.due_time ASC""",
        (current_date, current_date, current_time, current_dt))
    tasks = c.fetchall()
    conn.close()
    return tasks

def get_all_user_ids():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT DISTINCT user_id FROM tasks WHERE done=0")
    ids = [r[0] for r in c.fetchall()]
    conn.close()
    return ids

# ── v2.1: Stop reminders / clear reminder time ─────────
def stop_reminders(task_id, user_id):
    """Clear due_time so task stays but never pings again."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""UPDATE tasks SET due_time=NULL, snooze_until=NULL
                 WHERE id=? AND user_id=?""", (task_id, user_id))
    conn.commit()
    conn.close()

def clear_snooze(task_id):
    """Clear snooze_until after it fires, preventing re-fire every minute."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE tasks SET snooze_until=NULL WHERE id=?", (task_id,))
    conn.commit()
    conn.close()

# ── v4.0: Subtasks + Planning ─────────────────────────
def add_subtask(user_id, parent_id, title, due_date=None, due_time=None,
                category='General', priority='medium'):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""INSERT INTO tasks
        (user_id, title, due_date, due_time, category, priority, parent_task_id)
        VALUES (?,?,?,?,?,?,?)""",
        (user_id, title, due_date, due_time, category, priority, parent_id))
    sub_id = c.lastrowid
    conn.commit()
    conn.close()
    return sub_id

def get_subtasks(parent_id, user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""SELECT id, title, due_date, due_time, category, priority, done
        FROM tasks WHERE parent_task_id=? AND user_id=?
        ORDER BY due_date ASC, due_time ASC""",
        (parent_id, user_id))
    subs = c.fetchall()
    conn.close()
    return subs

def get_tasks_for_planning(user_id, start_date, end_date):
    """Get all incomplete non-recurring tasks in a date range, for planning."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""SELECT id, title, due_date, due_time, category, priority,
                 COALESCE(parent_task_id, 0)
        FROM tasks
        WHERE user_id=? AND done=0 AND paused=0
        AND due_date BETWEEN ? AND ?
        AND (recurrence_type IS NULL OR recurrence_type='')
        ORDER BY due_date ASC,
                 CASE priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 WHEN 'low' THEN 3 END,
                 due_time ASC""",
        (user_id, start_date, end_date))
    tasks = c.fetchall()
    conn.close()
    return tasks

def count_tasks_per_day(user_id, start_date, end_date):
    """Returns {date: count} for overload detection."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""SELECT due_date, COUNT(*) FROM tasks
        WHERE user_id=? AND done=0 AND paused=0
        AND due_date BETWEEN ? AND ?
        GROUP BY due_date""",
        (user_id, start_date, end_date))
    rows = dict(c.fetchall())
    conn.close()
    return rows

# ── v5.0: Habit Engine ────────────────────────────────
def add_habit(user_id, title, time=None, recurrence="daily",
              recurrence_weekday=None, category="Health", priority="medium"):
    """Create a habit (a recurring task with is_habit=1)."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    today = datetime.now(IST).strftime("%Y-%m-%d")
    c.execute("""INSERT INTO tasks
        (user_id, title, due_time, category, priority,
         recurrence_type, recurrence_weekday,
         is_habit, habit_start_date, current_streak, longest_streak)
        VALUES (?,?,?,?,?,?,?,1,?,0,0)""",
        (user_id, title, time, category, priority,
         recurrence, recurrence_weekday, today))
    hid = c.lastrowid
    conn.commit()
    conn.close()
    return hid

def is_habit(task_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT COALESCE(is_habit,0) FROM tasks WHERE id=?", (task_id,))
    row = c.fetchone()
    conn.close()
    return bool(row and row[0])

def log_habit_completion(habit_id, user_id, log_date=None):
    """Log that habit was done on a given date (default today). Updates streak."""
    if log_date is None:
        log_date = datetime.now(IST).strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    # Insert log entry (UNIQUE constraint prevents double-log per day)
    try:
        c.execute("INSERT INTO habit_log (habit_id, user_id, log_date, completed) VALUES (?,?,?,1)",
                  (habit_id, user_id, log_date))
    except sqlite3.IntegrityError:
        # Already logged today
        conn.close()
        return False, "already_logged"

    # Compute current streak
    c.execute("""SELECT log_date FROM habit_log
                 WHERE habit_id=? AND completed=1
                 ORDER BY log_date DESC""", (habit_id,))
    dates = [r[0] for r in c.fetchall()]
    streak = 0
    cursor_date = datetime.strptime(log_date, "%Y-%m-%d").date()
    for d_str in dates:
        d = datetime.strptime(d_str, "%Y-%m-%d").date()
        if d == cursor_date:
            streak += 1
            cursor_date = cursor_date - timedelta(days=1)
        else:
            break

    # Update task's current_streak, longest_streak, last_completed
    c.execute("SELECT longest_streak FROM tasks WHERE id=?", (habit_id,))
    row = c.fetchone()
    longest = max(streak, (row[0] if row else 0) or 0)
    c.execute("""UPDATE tasks SET current_streak=?, longest_streak=?, last_completed=?
                 WHERE id=?""", (streak, longest, log_date, habit_id))
    conn.commit()
    conn.close()
    return True, streak

def get_habit_log(habit_id, user_id, days=30):
    """Return last N days of habit log entries."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    cutoff = (datetime.now(IST) - timedelta(days=days)).strftime("%Y-%m-%d")
    c.execute("""SELECT log_date, completed FROM habit_log
                 WHERE habit_id=? AND user_id=? AND log_date >= ?
                 ORDER BY log_date DESC""", (habit_id, user_id, cutoff))
    rows = c.fetchall()
    conn.close()
    return rows

def get_habits(user_id):
    """All active habits for the user."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""SELECT id, title, due_time, recurrence_type, recurrence_weekday,
                 current_streak, longest_streak, last_completed, habit_start_date
                 FROM tasks
                 WHERE user_id=? AND COALESCE(is_habit,0)=1 AND done=0 AND paused=0
                 ORDER BY current_streak DESC""", (user_id,))
    habits = c.fetchall()
    conn.close()
    return habits

def get_missed_days(habit_id, user_id, days=30):
    """Days the habit should have been done but wasn't, in the last N days."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""SELECT habit_start_date, recurrence_type, recurrence_weekday
                 FROM tasks WHERE id=? AND user_id=?""", (habit_id, user_id))
    row = c.fetchone()
    if not row:
        conn.close()
        return []
    start_date_str, recurrence_type, recurrence_weekday = row
    start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date() if start_date_str else None
    if not start_date:
        conn.close()
        return []

    cutoff = max(start_date,
                 (datetime.now(IST) - timedelta(days=days)).date())

    # Days when this habit "should" have happened
    expected = []
    today = datetime.now(IST).date()
    cur = cutoff
    while cur <= today:
        if recurrence_type == "daily":
            expected.append(cur.strftime("%Y-%m-%d"))
        elif recurrence_type == "weekly" and cur.weekday() == (recurrence_weekday or 0):
            expected.append(cur.strftime("%Y-%m-%d"))
        cur = cur + timedelta(days=1)

    # Logged days
    c.execute("""SELECT log_date FROM habit_log
                 WHERE habit_id=? AND user_id=? AND completed=1""", (habit_id, user_id))
    logged = {r[0] for r in c.fetchall()}
    conn.close()
    missed = [d for d in expected if d not in logged]
    return missed

def reset_streak(habit_id):
    """Reset streak to 0 when user explicitly skips a day."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE tasks SET current_streak=0 WHERE id=?", (habit_id,))
    conn.commit()
    conn.close()

# ── v6.0: Preference Learning ─────────────────────────
def _init_learning_tables(conn):
    """Create the learning log tables if missing."""
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS completions_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        task_id INTEGER,
        title TEXT,
        category TEXT,
        scheduled_time TEXT,
        completed_at TEXT NOT NULL,
        delay_minutes INTEGER DEFAULT 0
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS snooze_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        task_id INTEGER,
        title TEXT,
        category TEXT,
        snooze_minutes INTEGER,
        snoozed_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS interaction_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        action TEXT,
        timestamp TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()


def log_completion(user_id, task_id, title, category, scheduled_time, completed_at, delay_minutes=0):
    conn = sqlite3.connect(DB_NAME)
    _init_learning_tables(conn)
    c = conn.cursor()
    c.execute("""INSERT INTO completions_log
        (user_id, task_id, title, category, scheduled_time, completed_at, delay_minutes)
        VALUES (?,?,?,?,?,?,?)""",
        (user_id, task_id, title, category, scheduled_time, completed_at, delay_minutes))
    conn.commit()
    conn.close()


def log_snooze(user_id, task_id, title, category, snooze_minutes):
    conn = sqlite3.connect(DB_NAME)
    _init_learning_tables(conn)
    c = conn.cursor()
    c.execute("""INSERT INTO snooze_log
        (user_id, task_id, title, category, snooze_minutes)
        VALUES (?,?,?,?,?)""",
        (user_id, task_id, title, category, snooze_minutes))
    conn.commit()
    conn.close()


def log_interaction(user_id, action):
    conn = sqlite3.connect(DB_NAME)
    _init_learning_tables(conn)
    c = conn.cursor()
    c.execute("INSERT INTO interaction_log (user_id, action) VALUES (?,?)",
              (user_id, action))
    conn.commit()
    conn.close()


def get_active_hours(user_id, days=30):
    """Return {hour: count} of when user is most active."""
    conn = sqlite3.connect(DB_NAME)
    _init_learning_tables(conn)
    c = conn.cursor()
    cutoff = (datetime.now(IST) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    c.execute("""SELECT substr(timestamp, 12, 2) AS hour, COUNT(*) as cnt
        FROM interaction_log WHERE user_id=? AND timestamp >= ?
        GROUP BY hour ORDER BY cnt DESC""", (user_id, cutoff))
    rows = c.fetchall()
    conn.close()
    return {int(h): n for h, n in rows if h}


def get_completion_patterns(user_id, days=30):
    """Return analysis of when user actually completes tasks."""
    conn = sqlite3.connect(DB_NAME)
    _init_learning_tables(conn)
    c = conn.cursor()
    cutoff = (datetime.now(IST) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    c.execute("""SELECT category, AVG(delay_minutes), COUNT(*), substr(completed_at, 12, 2) AS hour
        FROM completions_log WHERE user_id=? AND completed_at >= ?
        GROUP BY category, hour""", (user_id, cutoff))
    rows = c.fetchall()
    conn.close()
    return rows


def get_snooze_patterns(user_id, days=30):
    """Categories most likely to be snoozed + avg snooze minutes."""
    conn = sqlite3.connect(DB_NAME)
    _init_learning_tables(conn)
    c = conn.cursor()
    cutoff = (datetime.now(IST) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    c.execute("""SELECT category, COUNT(*) as snoozes, AVG(snooze_minutes) as avg_min
        FROM snooze_log WHERE user_id=? AND snoozed_at >= ?
        GROUP BY category ORDER BY snoozes DESC""", (user_id, cutoff))
    rows = c.fetchall()
    conn.close()
    return rows


def get_category_distribution(user_id, days=30):
    """Returns {category: task_count} over the last N days."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    cutoff = (datetime.now(IST) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    c.execute("""SELECT category, COUNT(*) FROM tasks
        WHERE user_id=? AND created_at >= ? GROUP BY category""",
        (user_id, cutoff))
    rows = c.fetchall()
    conn.close()
    return dict(rows)


def get_typical_time_for_category(user_id, category, days=30):
    """Returns most common HH:MM that user completes tasks of this category at."""
    conn = sqlite3.connect(DB_NAME)
    _init_learning_tables(conn)
    c = conn.cursor()
    cutoff = (datetime.now(IST) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    c.execute("""SELECT substr(completed_at, 12, 5) AS hm, COUNT(*) as cnt
        FROM completions_log WHERE user_id=? AND category=? AND completed_at >= ?
        GROUP BY hm ORDER BY cnt DESC LIMIT 1""", (user_id, category, cutoff))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

# ── v6.1: Admin / Reset functions ─────────────────────
def reset_all_tasks(user_id):
    """Delete all of a user's non-habit tasks and reset the autoincrement
    counter. Habits are excluded — /resettasks's own confirmation message
    promises "habits... are kept"; use reset_all_habits() for those."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM tasks WHERE user_id=? AND COALESCE(is_habit,0)=0", (user_id,))
    deleted = c.rowcount
    # Reset the autoincrement counter ONLY if the table is now empty
    c.execute("SELECT COUNT(*) FROM tasks")
    if c.fetchone()[0] == 0:
        try:
            c.execute("DELETE FROM sqlite_sequence WHERE name='tasks'")
        except Exception:
            pass
    conn.commit()
    conn.close()
    return deleted

def reset_all_memories(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM memories WHERE user_id=?", (user_id,))
    deleted = c.rowcount
    conn.commit()
    conn.close()
    return deleted

def reset_all_habits(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM tasks WHERE user_id=? AND COALESCE(is_habit,0)=1", (user_id,))
    deleted = c.rowcount
    c.execute("DELETE FROM habit_log WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()
    return deleted

def reset_learning_data(user_id):
    """Wipe preference-learning logs."""
    conn = sqlite3.connect(DB_NAME)
    _init_learning_tables(conn)
    c = conn.cursor()
    total = 0
    for table in ["completions_log", "snooze_log", "interaction_log"]:
        c.execute(f"DELETE FROM {table} WHERE user_id=?", (user_id,))
        total += c.rowcount
    conn.commit()
    conn.close()
    return total

def reset_everything(user_id):
    """Nuclear reset — wipe ALL of a user's data and reset every ID.

    Must cover every table that references tasks.id or goals.id, or a
    freshly created task/habit/goal can silently inherit an old, unrelated
    record's history once the autoincrement counter is reset and IDs are
    reused (see ENGINEERING_AUDIT.md finding E1). project_materials and
    project_worklog reference goal_id; since goals.id gets reset here too,
    those two tables are exactly as much at risk as habit_log was for
    tasks.id, and are cleaned for the same reason. task_templates,
    missed_capabilities, and ai_observations don't reference task/goal ids
    at all (no inheritance risk), but are included so "deletes EVERYTHING"
    is actually true.
    """
    conn = sqlite3.connect(DB_NAME)
    _init_learning_tables(conn)
    _init_project_tables(conn)
    _init_templates(conn)
    _init_missed_capabilities(conn)
    _init_observations(conn)
    _init_workspace_tables(conn)
    c = conn.cursor()
    counts = {}
    for table in ["tasks", "memories", "goals", "habit_log",
                  "completions_log", "snooze_log", "interaction_log",
                  "project_materials", "project_worklog",
                  "task_templates", "missed_capabilities", "ai_observations"]:
        try:
            c.execute(f"DELETE FROM {table} WHERE user_id=?", (user_id,))
            counts[table] = c.rowcount
        except Exception:
            counts[table] = 0
    # v15.0-alpha.1: Workspace Foundation tables. The child tables
    # (milestones/notes/attachments/entity_tags) are keyed by
    # workspace_id/tag_id, not user_id, so they're scoped through their
    # owning parent. Same anti-orphan reason as project_materials above:
    # once workspaces exist and IDs are reused after a reset, un-cleared
    # children would surface under a new workspace (finding E1).
    for table in ["milestones", "notes", "attachments"]:
        try:
            c.execute(f"DELETE FROM {table} WHERE workspace_id IN "
                      "(SELECT id FROM workspaces WHERE user_id=?)", (user_id,))
            counts[table] = c.rowcount
        except Exception:
            counts[table] = 0
    # timeline_events + sync_outbox are user_id-scoped (v15.0-alpha.5/6).
    for table in ["timeline_events", "sync_outbox"]:
        try:
            c.execute(f"DELETE FROM {table} WHERE user_id=?", (user_id,))
            counts[table] = c.rowcount
        except Exception:
            counts[table] = 0
    try:
        c.execute("DELETE FROM entity_tags WHERE tag_id IN "
                  "(SELECT id FROM tags WHERE user_id=?)", (user_id,))
        counts["entity_tags"] = c.rowcount
    except Exception:
        counts["entity_tags"] = 0
    for table in ["workspaces", "tags"]:
        try:
            c.execute(f"DELETE FROM {table} WHERE user_id=?", (user_id,))
            counts[table] = c.rowcount
        except Exception:
            counts[table] = 0
    # Reset ID counters for every table just wiped above, but only once
    # each parent table is globally empty (matches the existing tasks-table
    # guard) — avoids resetting a sequence that another user still has
    # live rows depending on, in this single-DB multi-user-scoped schema.
    for parent_table, seq_tables in (
        ("tasks", ["tasks", "habit_log"]),
        ("memories", ["memories"]),
        ("goals", ["goals", "project_materials", "project_worklog"]),
        ("task_templates", ["task_templates"]),
        ("missed_capabilities", ["missed_capabilities"]),
        ("ai_observations", ["ai_observations"]),
        ("workspaces", ["workspaces", "milestones", "notes", "attachments"]),
        ("tags", ["tags", "entity_tags"]),
        ("timeline_events", ["timeline_events"]),
        ("sync_outbox", ["sync_outbox"]),
    ):
        c.execute(f"SELECT COUNT(*) FROM {parent_table}")
        if c.fetchone()[0] == 0:
            for seq_table in seq_tables:
                try:
                    c.execute("DELETE FROM sqlite_sequence WHERE name=?", (seq_table,))
                except Exception:
                    pass
    conn.commit()
    conn.close()
    return counts

def get_data_stats(user_id):
    """Counts of all the user's data — for the admin panel."""
    conn = sqlite3.connect(DB_NAME)
    _init_learning_tables(conn)
    c = conn.cursor()
    stats = {}
    queries = {
        "active_tasks": "SELECT COUNT(*) FROM tasks WHERE user_id=? AND done=0",
        "done_tasks": "SELECT COUNT(*) FROM tasks WHERE user_id=? AND done=1",
        "habits": "SELECT COUNT(*) FROM tasks WHERE user_id=? AND COALESCE(is_habit,0)=1",
        "memories": "SELECT COUNT(*) FROM memories WHERE user_id=?",
        "goals": "SELECT COUNT(*) FROM goals WHERE user_id=?",
        "completions_logged": "SELECT COUNT(*) FROM completions_log WHERE user_id=?",
        "snoozes_logged": "SELECT COUNT(*) FROM snooze_log WHERE user_id=?",
    }
    for key, q in queries.items():
        try:
            c.execute(q, (user_id,))
            stats[key] = c.fetchone()[0]
        except Exception:
            stats[key] = 0
    # Highest task ID
    c.execute("SELECT MAX(id) FROM tasks")
    row = c.fetchone()
    stats["max_task_id"] = row[0] if row and row[0] else 0
    conn.close()
    return stats

# ── v7.0: Follow-up Intelligence ──────────────────────
def get_tasks_for_followup(user_id_filter=None):
    """
    Tasks whose due time passed 15+ min ago, not done, not paused,
    and we haven't sent a follow-up for THIS occurrence yet.
    Returns tuples for the 'did you finish?' check.
    """
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    now = datetime.now(IST)
    today = now.strftime("%Y-%m-%d")
    # Only follow up on tasks whose time passed 15+ minutes ago
    cutoff_hm = (now - timedelta(minutes=15)).strftime("%H:%M")
    c.execute("""SELECT id, user_id, title, due_date, due_time,
                 COALESCE(followup_count,0), followup_sent, category
        FROM tasks
        WHERE done=0 AND paused=0
        AND due_date IS NOT NULL AND due_time IS NOT NULL
        AND (recurrence_type IS NULL OR recurrence_type='')
        AND (due_date < ? OR (due_date = ? AND due_time <= ?))
        AND (followup_sent IS NULL OR substr(followup_sent,1,10) < ?)
        ORDER BY due_date, due_time""",
        (today, today, cutoff_hm, today))
    rows = c.fetchall()
    conn.close()
    return rows

def mark_followup_sent(task_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    now = datetime.now(IST).strftime("%Y-%m-%d %H:%M")
    c.execute("""UPDATE tasks SET followup_sent=?,
                 followup_count=COALESCE(followup_count,0)+1 WHERE id=?""",
              (now, task_id))
    conn.commit()
    conn.close()

def increment_snooze_count(task_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE tasks SET snooze_count=COALESCE(snooze_count,0)+1 WHERE id=?",
              (task_id,))
    conn.commit()
    conn.close()

def get_snooze_count(task_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT COALESCE(snooze_count,0) FROM tasks WHERE id=?", (task_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0

def get_stale_tasks(user_id, days_threshold=3):
    """Tasks incomplete and 3+ days past their due date."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    cutoff = (datetime.now(IST) - timedelta(days=days_threshold)).strftime("%Y-%m-%d")
    c.execute("""SELECT id, title, due_date, due_time, category, priority,
                 COALESCE(snooze_count,0), COALESCE(followup_count,0)
        FROM tasks
        WHERE user_id=? AND done=0 AND paused=0
        AND due_date IS NOT NULL AND due_date < ?
        AND (recurrence_type IS NULL OR recurrence_type='')
        ORDER BY due_date ASC""", (user_id, cutoff))
    rows = c.fetchall()
    conn.close()
    return rows

def get_unresolved_today(user_id):
    """Tasks scheduled for today that are still not done."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    today = datetime.now(IST).strftime("%Y-%m-%d")
    c.execute("""SELECT id, title, due_time, category, priority
        FROM tasks
        WHERE user_id=? AND done=0 AND paused=0 AND due_date=?
        ORDER BY due_time ASC""", (user_id, today))
    rows = c.fetchall()
    conn.close()
    return rows

def get_all_active_user_ids():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT DISTINCT user_id FROM tasks WHERE done=0")
    ids = [r[0] for r in c.fetchall()]
    conn.close()
    return ids

# ── v8.0: Wellness / Proactive settings ───────────────
def get_wellness_prefs(user_id):
    conn = sqlite3.connect(DB_NAME)
    _init_preferences(conn)
    c = conn.cursor()
    c.execute("""SELECT COALESCE(wellness_on,0), COALESCE(wellness_interval,90),
                 COALESCE(wellness_types,'all'), last_wellness
                 FROM user_preferences WHERE user_id=?""", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {"on": bool(row[0]), "interval": row[1],
                "types": row[2], "last": row[3]}
    return {"on": False, "interval": 90, "types": "all", "last": None}

def set_wellness(user_id, on=None, interval=None, types=None):
    conn = sqlite3.connect(DB_NAME)
    _init_preferences(conn)
    c = conn.cursor()
    c.execute("SELECT user_id FROM user_preferences WHERE user_id=?", (user_id,))
    if not c.fetchone():
        c.execute("INSERT INTO user_preferences (user_id) VALUES (?)", (user_id,))
    if on is not None:
        c.execute("UPDATE user_preferences SET wellness_on=? WHERE user_id=?",
                  (1 if on else 0, user_id))
    if interval is not None:
        c.execute("UPDATE user_preferences SET wellness_interval=? WHERE user_id=?",
                  (interval, user_id))
    if types is not None:
        c.execute("UPDATE user_preferences SET wellness_types=? WHERE user_id=?",
                  (types, user_id))
    conn.commit()
    conn.close()

def mark_wellness_sent(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    now = datetime.now(IST).strftime("%Y-%m-%d %H:%M")
    c.execute("UPDATE user_preferences SET last_wellness=? WHERE user_id=?",
              (now, user_id))
    conn.commit()
    conn.close()

def get_wellness_enabled_users():
    conn = sqlite3.connect(DB_NAME)
    _init_preferences(conn)
    c = conn.cursor()
    c.execute("SELECT user_id FROM user_preferences WHERE COALESCE(wellness_on,0)=1")
    ids = [r[0] for r in c.fetchall()]
    conn.close()
    return ids

def count_tasks_at_time(user_id, date, time):
    """How many tasks the user has at a specific date+time (slot crowding)."""
    if not date or not time:
        return 0
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""SELECT COUNT(*) FROM tasks
        WHERE user_id=? AND done=0 AND due_date=? AND due_time=?""",
        (user_id, date, time))
    n = c.fetchone()[0]
    conn.close()
    return n

def get_high_priority_soon(user_id, hours=3):
    """High-priority tasks due within the next N hours (for proactive nudge)."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    now = datetime.now(IST)
    today = now.strftime("%Y-%m-%d")
    soon = (now + timedelta(hours=hours)).strftime("%H:%M")
    current = now.strftime("%H:%M")
    c.execute("""SELECT id, title, due_time, COALESCE(followup_count,0)
        FROM tasks
        WHERE user_id=? AND done=0 AND paused=0
        AND priority='high' AND due_date=?
        AND due_time IS NOT NULL
        AND due_time > ? AND due_time <= ?
        AND (recurrence_type IS NULL OR recurrence_type='')""",
        (user_id, today, current, soon))
    rows = c.fetchall()
    conn.close()
    return rows

# ── v9.0: Goal progress helpers ───────────────────────
def get_goals_full(user_id):
    """
    Goals with target for progress bars.
    Defensive: tolerates legacy schemas missing 'done', 'target', or 'created_at'.
    """
    conn = sqlite3.connect(DB_NAME)
    _c = conn.cursor()
    # Discover which columns actually exist in this DB
    try:
        _c.execute("PRAGMA table_info(goals)")
        cols = {r[1] for r in _c.fetchall()}
    except Exception:
        cols = set()
    has_done = "done" in cols
    has_target = "target" in cols
    has_created = "created_at" in cols
    has_progress = "progress" in cols
    has_deadline = "deadline" in cols

    progress_expr = "COALESCE(progress,0)" if has_progress else "0"
    target_expr = "COALESCE(target,100)" if has_target else "100"
    deadline_expr = "deadline" if has_deadline else "NULL"
    where_done = " AND COALESCE(done,0)=0" if has_done else ""
    order_clause = " ORDER BY created_at DESC" if has_created else " ORDER BY id DESC"

    try:
        _c.execute(
            f"SELECT id, title, {deadline_expr}, {progress_expr}, {target_expr} "
            f"FROM goals WHERE user_id=?{where_done}{order_clause}",
            (user_id,)
        )
        rows = _c.fetchall()
    except Exception:
        rows = []
    conn.close()
    return rows

def update_goal_progress(goal_id, user_id, delta):
    """
    Adjust a goal's progress by delta, clamped to [0, target]. Auto-completes.
    Defensive: works even if 'done' or 'target' columns don't exist yet.
    """
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("PRAGMA table_info(goals)")
    cols = {r[1] for r in c.fetchall()}
    has_done = "done" in cols
    has_target = "target" in cols
    has_progress = "progress" in cols

    if not has_progress:
        # Can't track progress without the column — bail out gracefully
        conn.close()
        return None

    progress_expr = "COALESCE(progress,0)"
    target_expr = "COALESCE(target,100)" if has_target else "100"
    c.execute(f"SELECT {progress_expr}, {target_expr} FROM goals WHERE id=? AND user_id=?",
              (goal_id, user_id))
    row = c.fetchone()
    if not row:
        conn.close()
        return None
    progress, target = row
    new_progress = max(0, min(target, progress + delta))
    done = 1 if new_progress >= target else 0

    if has_done:
        c.execute("UPDATE goals SET progress=?, done=? WHERE id=? AND user_id=?",
                  (new_progress, done, goal_id, user_id))
    else:
        c.execute("UPDATE goals SET progress=? WHERE id=? AND user_id=?",
                  (new_progress, goal_id, user_id))
    conn.commit()
    conn.close()
    return new_progress, target, bool(done)

def update_goal_deadline(goal_id, user_id, deadline):
    """Set (or clear, with None) a goal's deadline. Returns the goal_id on
    success -- INCLUDING when the deadline is cleared to None, because None
    is a legitimate new value, never a failure signal. Returns None only
    when the goal does not belong to user_id or the schema lacks a deadline
    column. v15.2 M4: the goal domain owns deadlines -- a goal request must
    never mutate a workspace entity (DEBUGGING.md F6/F7)."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("PRAGMA table_info(goals)")
    has_deadline = "deadline" in {r[1] for r in c.fetchall()}
    if not has_deadline:
        conn.close()
        return None
    c.execute("UPDATE goals SET deadline=? WHERE id=? AND user_id=?",
              (deadline, goal_id, user_id))
    if c.rowcount == 0:
        conn.close()
        return None
    conn.commit()
    conn.close()
    return goal_id

def get_done_today_count(user_id):
    """How many tasks the user completed today (by last_completed date)."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    today = datetime.now(IST).strftime("%Y-%m-%d")
    # done tasks updated today OR habit logs today
    c.execute("""SELECT COUNT(*) FROM tasks
                 WHERE user_id=? AND done=1
                 AND substr(COALESCE(last_completed, created_at),1,10)=?""",
              (user_id, today))
    n = c.fetchone()[0]
    conn.close()
    return n

# ── v10.0: Search, Templates, Reports ─────────────────
def search_all(user_id, keyword):
    """Search tasks, memories, habits, goals by keyword. Returns categorized results."""
    kw = f"%{keyword.lower()}%"
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    results = {"tasks": [], "memories": [], "habits": [], "goals": []}
    # Tasks
    c.execute("""SELECT id, title, due_date, due_time, category, priority, done
        FROM tasks WHERE user_id=? AND COALESCE(is_habit,0)=0
        AND (LOWER(title) LIKE ? OR LOWER(category) LIKE ? OR LOWER(tags) LIKE ?)
        ORDER BY done ASC, due_date DESC LIMIT 10""",
        (user_id, kw, kw, kw))
    results["tasks"] = c.fetchall()
    # Habits
    c.execute("""SELECT id, title, due_time, recurrence_type, current_streak
        FROM tasks WHERE user_id=? AND COALESCE(is_habit,0)=1
        AND LOWER(title) LIKE ? LIMIT 5""",
        (user_id, kw))
    results["habits"] = c.fetchall()
    # Memories
    c.execute("""SELECT key, value FROM memories
        WHERE user_id=? AND (LOWER(key) LIKE ? OR LOWER(value) LIKE ?)
        LIMIT 5""",
        (user_id, kw, kw))
    results["memories"] = c.fetchall()
    # Goals
    try:
        c.execute("PRAGMA table_info(goals)")
        cols = {r[1] for r in c.fetchall()}
        done_filter = " AND COALESCE(done,0)=0" if "done" in cols else ""
        c.execute(f"""SELECT id, title FROM goals
            WHERE user_id=? AND LOWER(title) LIKE ?{done_filter} LIMIT 5""",
            (user_id, kw))
        results["goals"] = c.fetchall()
    except Exception:
        pass
    conn.close()
    return results


def _init_templates(conn):
    conn.cursor().execute("""CREATE TABLE IF NOT EXISTS task_templates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        title TEXT NOT NULL,
        category TEXT DEFAULT 'General',
        priority TEXT DEFAULT 'medium',
        recurrence_type TEXT,
        default_time TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, name)
    )""")
    conn.commit()


def save_template(user_id, name, title, category="General", priority="medium",
                  recurrence_type=None, default_time=None):
    conn = sqlite3.connect(DB_NAME)
    _init_templates(conn)
    c = conn.cursor()
    try:
        c.execute("""INSERT INTO task_templates
            (user_id, name, title, category, priority, recurrence_type, default_time)
            VALUES (?,?,?,?,?,?,?)""",
            (user_id, name.lower().strip(), title, category, priority, recurrence_type, default_time))
    except sqlite3.IntegrityError:
        c.execute("""UPDATE task_templates
            SET title=?, category=?, priority=?, recurrence_type=?, default_time=?
            WHERE user_id=? AND name=?""",
            (title, category, priority, recurrence_type, default_time, user_id, name.lower().strip()))
    conn.commit()
    conn.close()


def get_template(user_id, name):
    conn = sqlite3.connect(DB_NAME)
    _init_templates(conn)
    c = conn.cursor()
    c.execute("""SELECT name, title, category, priority, recurrence_type, default_time
        FROM task_templates WHERE user_id=? AND name=?""",
        (user_id, name.lower().strip()))
    row = c.fetchone()
    conn.close()
    return row


def get_all_templates(user_id):
    conn = sqlite3.connect(DB_NAME)
    _init_templates(conn)
    c = conn.cursor()
    c.execute("""SELECT name, title, category, priority, recurrence_type, default_time
        FROM task_templates WHERE user_id=? ORDER BY name""", (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows


def delete_template(user_id, name):
    conn = sqlite3.connect(DB_NAME)
    _init_templates(conn)
    c = conn.cursor()
    c.execute("DELETE FROM task_templates WHERE user_id=? AND name=?",
              (user_id, name.lower().strip()))
    deleted = c.rowcount
    conn.commit()
    conn.close()
    return deleted


def get_weekly_report_data(user_id):
    """Gather data for a weekly digest."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    now = datetime.now(IST)
    week_start = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    today = now.strftime("%Y-%m-%d")

    # Tasks completed this week
    c.execute("""SELECT COUNT(*) FROM tasks
        WHERE user_id=? AND done=1
        AND substr(COALESCE(last_completed, created_at),1,10) BETWEEN ? AND ?""",
        (user_id, week_start, today))
    done_this_week = c.fetchone()[0]

    # Tasks created this week
    c.execute("""SELECT COUNT(*) FROM tasks
        WHERE user_id=? AND substr(created_at,1,10) BETWEEN ? AND ?""",
        (user_id, week_start, today))
    created_this_week = c.fetchone()[0]

    # Currently pending
    c.execute("SELECT COUNT(*) FROM tasks WHERE user_id=? AND done=0 AND paused=0",
              (user_id,))
    pending = c.fetchone()[0]

    # Overdue
    c.execute("""SELECT COUNT(*) FROM tasks
        WHERE user_id=? AND done=0 AND paused=0 AND due_date < ?
        AND (recurrence_type IS NULL OR recurrence_type='')""",
        (user_id, today))
    overdue = c.fetchone()[0]

    # Habits: best streaks
    c.execute("""SELECT title, current_streak, longest_streak
        FROM tasks WHERE user_id=? AND COALESCE(is_habit,0)=1 AND done=0
        ORDER BY current_streak DESC LIMIT 3""", (user_id,))
    top_habits = c.fetchall()

    conn.close()
    return {
        "done_this_week": done_this_week,
        "created_this_week": created_this_week,
        "pending": pending,
        "overdue": overdue,
        "top_habits": top_habits,
        "completion_rate": round(done_this_week / max(created_this_week, 1) * 100),
    }


def export_user_data(user_id):
    """Export all user data as a plain-text summary for backup."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    lines = [f"=== BAKA Data Export ===", f"User ID: {user_id}", f"Date: {datetime.now(IST).strftime('%Y-%m-%d %H:%M')}", ""]

    # Tasks
    c.execute("SELECT id,title,due_date,due_time,category,priority,done FROM tasks WHERE user_id=? ORDER BY due_date", (user_id,))
    tasks = c.fetchall()
    lines.append(f"=== TASKS ({len(tasks)}) ===")
    for t in tasks:
        status = "✅" if t[6] else "⏳"
        lines.append(f"{status} [{t[0]}] {t[1]} | {t[2] or '-'} {t[3] or '-'} | {t[4]} | {t[5]}")
    lines.append("")

    # Memories
    c.execute("SELECT key, value FROM memories WHERE user_id=?", (user_id,))
    mems = c.fetchall()
    lines.append(f"=== MEMORIES ({len(mems)}) ===")
    for k, v in mems:
        lines.append(f"  {k}: {v}")
    lines.append("")

    # Goals
    try:
        c.execute("SELECT id, title, progress FROM goals WHERE user_id=?", (user_id,))
        goals = c.fetchall()
        lines.append(f"=== GOALS ({len(goals)}) ===")
        for g in goals:
            lines.append(f"  [{g[0]}] {g[1]} — {g[2]}%")
    except Exception:
        pass

    conn.close()
    return "\n".join(lines)

# ── v10.1: Pre-Deadline Buffer Reminders ──────────────
def mark_as_deadline(task_id, user_id, is_deadline=True):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE tasks SET is_deadline=? WHERE id=? AND user_id=?",
              (1 if is_deadline else 0, task_id, user_id))
    conn.commit()
    conn.close()

def get_pending_deadlines():
    """All future deadline tasks (not done/paused) for buffer reminder checks."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    now = datetime.now(IST)
    today = now.strftime("%Y-%m-%d")
    current_time = now.strftime("%H:%M")
    c.execute("""SELECT id, user_id, title, due_date, due_time, priority,
                 COALESCE(buffer_sent,''), category
        FROM tasks
        WHERE done=0 AND paused=0
        AND COALESCE(is_deadline,0)=1
        AND due_date IS NOT NULL AND due_time IS NOT NULL
        AND (due_date > ? OR (due_date = ? AND due_time > ?))
        AND (recurrence_type IS NULL OR recurrence_type='')""",
        (today, today, current_time))
    rows = c.fetchall()
    conn.close()
    return rows

def mark_buffer_sent(task_id, buffer_label):
    """Record which buffer reminder has already been sent (e.g. '7d', '3d', '1d', '6h', '1h')."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT COALESCE(buffer_sent,'') FROM tasks WHERE id=?", (task_id,))
    row = c.fetchone()
    current = row[0] if row else ""
    sent = set(current.split(",")) if current else set()
    sent.discard("")
    sent.add(buffer_label)
    new_value = ",".join(sorted(sent))
    c.execute("UPDATE tasks SET buffer_sent=? WHERE id=?", (new_value, task_id))
    conn.commit()
    conn.close()

def parse_buffer_sent(buffer_sent_str):
    """Convert the comma-separated buffer_sent string to a set."""
    if not buffer_sent_str:
        return set()
    return set(s for s in buffer_sent_str.split(",") if s)

# ── v11.0 prep: Missed Capabilities Log ───────────────
def _init_missed_capabilities(conn):
    conn.cursor().execute("""CREATE TABLE IF NOT EXISTS missed_capabilities (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        user_input TEXT NOT NULL,
        ai_intent TEXT,
        ai_response TEXT,
        miss_type TEXT,
        confidence REAL,
        notes TEXT,
        reviewed INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()


def log_missed_capability(user_id, user_input, ai_intent=None, ai_response=None,
                           miss_type="low_confidence", confidence=None, notes=None):
    """
    Record an interaction where the AI didn't handle something well.
    miss_type: 'low_confidence' | 'chat_no_action' | 'fallback' | 'user_repeated' | 'thumbs_down'
    Reviewing these later tells us what features to build.
    """
    conn = sqlite3.connect(DB_NAME)
    _init_missed_capabilities(conn)
    c = conn.cursor()
    c.execute("""INSERT INTO missed_capabilities
        (user_id, user_input, ai_intent, ai_response, miss_type, confidence, notes)
        VALUES (?,?,?,?,?,?,?)""",
        (user_id, user_input, ai_intent, ai_response, miss_type, confidence, notes))
    conn.commit()
    conn.close()


def get_missed_capabilities(user_id, limit=50, only_unreviewed=True):
    conn = sqlite3.connect(DB_NAME)
    _init_missed_capabilities(conn)
    c = conn.cursor()
    where = "WHERE user_id=?"
    params = [user_id]
    if only_unreviewed:
        where += " AND reviewed=0"
    c.execute(f"""SELECT id, user_input, ai_intent, ai_response, miss_type,
                  confidence, notes, created_at
                  FROM missed_capabilities {where}
                  ORDER BY created_at DESC LIMIT ?""", params + [limit])
    rows = c.fetchall()
    conn.close()
    return rows


def mark_missed_reviewed(miss_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE missed_capabilities SET reviewed=1 WHERE id=?", (miss_id,))
    conn.commit()
    conn.close()


# ── v11.0 prep: AI Context Helper ─────────────────────
def get_user_context_for_ai(user_id, history_limit=5):
    """
    Build a rich context bundle the AI sees in every important call.
    This is the foundation of true autonomous behavior — the AI now reasons
    WITH your data, not in a vacuum.
    """
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    now = datetime.now(IST)
    today = now.strftime("%Y-%m-%d")

    # Recent completions
    c.execute("""SELECT title, category, last_completed FROM tasks
        WHERE user_id=? AND done=1
        ORDER BY COALESCE(last_completed, created_at) DESC LIMIT 5""", (user_id,))
    recent_done = c.fetchall()

    # Open commitments by category
    c.execute("""SELECT category, COUNT(*) FROM tasks
        WHERE user_id=? AND done=0 AND paused=0
        GROUP BY category""", (user_id,))
    open_by_cat = dict(c.fetchall())

    # Overdue count
    c.execute("""SELECT COUNT(*) FROM tasks
        WHERE user_id=? AND done=0 AND paused=0 AND due_date < ?
        AND (recurrence_type IS NULL OR recurrence_type='')""", (user_id, today))
    overdue_n = c.fetchone()[0]

    # Active habits
    c.execute("""SELECT title, COALESCE(current_streak,0) FROM tasks
        WHERE user_id=? AND COALESCE(is_habit,0)=1 AND done=0
        ORDER BY current_streak DESC LIMIT 5""", (user_id,))
    habits = c.fetchall()

    conn.close()
    return {
        "today_date": today,
        "current_time": now.strftime("%H:%M"),
        "weekday": now.strftime("%A"),
        "recent_completions": recent_done,
        "open_tasks_by_category": open_by_cat,
        "overdue_count": overdue_n,
        "active_habits": habits,
    }

# ── v11.0: AI Observations / Daily Suggestions ────────
def _init_observations(conn):
    conn.cursor().execute("""CREATE TABLE IF NOT EXISTS ai_observations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        observation TEXT NOT NULL,
        suggestion TEXT,
        action_type TEXT,
        action_payload TEXT,
        status TEXT DEFAULT 'pending',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        responded_at TEXT
    )""")
    conn.commit()


def add_observation(user_id, observation, suggestion=None, action_type=None, action_payload=None):
    """Store an AI-generated observation/suggestion for user review."""
    conn = sqlite3.connect(DB_NAME)
    _init_observations(conn)
    c = conn.cursor()
    c.execute("""INSERT INTO ai_observations
        (user_id, observation, suggestion, action_type, action_payload)
        VALUES (?,?,?,?,?)""",
        (user_id, observation, suggestion, action_type, action_payload))
    obs_id = c.lastrowid
    conn.commit()
    conn.close()
    return obs_id


def get_pending_observations(user_id, limit=10):
    conn = sqlite3.connect(DB_NAME)
    _init_observations(conn)
    c = conn.cursor()
    c.execute("""SELECT id, observation, suggestion, action_type, action_payload, created_at
        FROM ai_observations WHERE user_id=? AND status='pending'
        ORDER BY created_at DESC LIMIT ?""", (user_id, limit))
    rows = c.fetchall()
    conn.close()
    return rows


def respond_to_observation(obs_id, status):
    """Mark an observation as approved / rejected / dismissed."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    now = datetime.now(IST).strftime("%Y-%m-%d %H:%M")
    c.execute("UPDATE ai_observations SET status=?, responded_at=? WHERE id=?",
              (status, now, obs_id))
    conn.commit()
    conn.close()


def get_observation(obs_id, user_id):
    conn = sqlite3.connect(DB_NAME)
    _init_observations(conn)
    c = conn.cursor()
    c.execute("""SELECT id, observation, suggestion, action_type, action_payload, status
        FROM ai_observations WHERE id=? AND user_id=?""", (obs_id, user_id))
    row = c.fetchone()
    conn.close()
    return row

# ══════════════════════════════════════════════════════════════
# v12.0 — Project Management (materials + work log)
# ══════════════════════════════════════════════════════════════
# A "project" is just a goal with attached materials and worklog.
# Both tables are linked to goals.id so deleting a goal cascades cleanly.

def _init_project_tables(conn):
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS project_materials (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        goal_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        quantity INTEGER DEFAULT 1,
        acquired INTEGER DEFAULT 0,
        cost REAL,
        notes TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        acquired_at TEXT
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_materials_goal ON project_materials(goal_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_materials_user ON project_materials(user_id)")
    c.execute("""CREATE TABLE IF NOT EXISTS project_worklog (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        goal_id INTEGER NOT NULL,
        entry TEXT NOT NULL,
        kind TEXT DEFAULT 'note',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_worklog_goal ON project_worklog(goal_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_worklog_user ON project_worklog(user_id)")
    conn.commit()


# ── Materials ──────────────────────────────────────────
def add_materials(user_id, goal_id, names, quantity=1):
    """
    Add one or more materials to a project. `names` can be a list or
    a comma-separated string. Ignores duplicates (case-insensitive within a goal).
    Returns list of (id, name) actually added.
    """
    if isinstance(names, str):
        names = [n.strip() for n in names.split(",") if n.strip()]
    conn = sqlite3.connect(DB_NAME)
    _init_project_tables(conn)
    c = conn.cursor()
    added = []
    c.execute("SELECT LOWER(name) FROM project_materials WHERE user_id=? AND goal_id=?",
              (user_id, goal_id))
    existing = {r[0] for r in c.fetchall()}
    for name in names:
        if len(name) > 100 or name.lower() in existing:
            continue
        c.execute("""INSERT INTO project_materials (user_id, goal_id, name, quantity)
                     VALUES (?,?,?,?)""", (user_id, goal_id, name, quantity))
        added.append((c.lastrowid, name))
        existing.add(name.lower())
    conn.commit()
    conn.close()
    return added


def get_materials(user_id, goal_id):
    conn = sqlite3.connect(DB_NAME)
    _init_project_tables(conn)
    c = conn.cursor()
    c.execute("""SELECT id, name, quantity, acquired, cost, notes, created_at, acquired_at
                 FROM project_materials WHERE user_id=? AND goal_id=?
                 ORDER BY acquired, id""", (user_id, goal_id))
    rows = c.fetchall()
    conn.close()
    return rows


def mark_material_acquired(user_id, material_id, acquired=True):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M")
    c.execute("""UPDATE project_materials
                 SET acquired=?, acquired_at=?
                 WHERE id=? AND user_id=?""",
              (1 if acquired else 0, now_str if acquired else None,
               material_id, user_id))
    updated = c.rowcount
    conn.commit()
    conn.close()
    return updated


def delete_material(user_id, material_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM project_materials WHERE id=? AND user_id=?",
              (material_id, user_id))
    deleted = c.rowcount
    conn.commit()
    conn.close()
    return deleted


def find_material_by_name(user_id, keyword, goal_id=None):
    """
    Fuzzy-find a NOT-yet-acquired material by keyword.
    If goal_id is None, searches across all active projects (goals with materials).
    Returns list of (id, name, goal_id, goal_title). Empty if nothing found.
    """
    conn = sqlite3.connect(DB_NAME)
    _init_project_tables(conn)
    c = conn.cursor()
    kw = f"%{keyword.lower()}%"
    if goal_id:
        c.execute("""SELECT m.id, m.name, m.goal_id, g.title
                     FROM project_materials m JOIN goals g ON m.goal_id=g.id
                     WHERE m.user_id=? AND m.goal_id=? AND m.acquired=0
                       AND LOWER(m.name) LIKE ?""",
                  (user_id, goal_id, kw))
    else:
        c.execute("""SELECT m.id, m.name, m.goal_id, g.title
                     FROM project_materials m JOIN goals g ON m.goal_id=g.id
                     WHERE m.user_id=? AND m.acquired=0 AND LOWER(m.name) LIKE ?
                     ORDER BY m.created_at DESC LIMIT 5""",
                  (user_id, kw))
    rows = c.fetchall()
    conn.close()
    return rows


# ── Work log ───────────────────────────────────────────
def add_worklog(user_id, goal_id, entry, kind="note"):
    """kind: started | progress | blocker | note | finished"""
    conn = sqlite3.connect(DB_NAME)
    _init_project_tables(conn)
    c = conn.cursor()
    c.execute("""INSERT INTO project_worklog (user_id, goal_id, entry, kind)
                 VALUES (?,?,?,?)""", (user_id, goal_id, entry, kind))
    wid = c.lastrowid
    conn.commit()
    conn.close()
    return wid


def get_worklog(user_id, goal_id, limit=20):
    conn = sqlite3.connect(DB_NAME)
    _init_project_tables(conn)
    c = conn.cursor()
    c.execute("""SELECT id, entry, kind, created_at
                 FROM project_worklog WHERE user_id=? AND goal_id=?
                 ORDER BY id DESC LIMIT ?""",
              (user_id, goal_id, limit))
    rows = c.fetchall()
    conn.close()
    return rows


def get_last_worklog_days(user_id, goal_id):
    """Days since the most recent worklog entry, or None if never logged."""
    conn = sqlite3.connect(DB_NAME)
    _init_project_tables(conn)
    c = conn.cursor()
    c.execute("""SELECT MAX(created_at) FROM project_worklog
                 WHERE user_id=? AND goal_id=?""", (user_id, goal_id))
    row = c.fetchone()
    conn.close()
    if not row or not row[0]:
        return None
    try:
        last = datetime.strptime(row[0][:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=IST)
        return (datetime.now(IST) - last).days
    except Exception:
        return None


# ── Project overview ───────────────────────────────────
def compute_project_progress(user_id, goal_id):
    """
    50% weight: materials acquired ratio
    50% weight: work completion (finished=100%, progress=50%, started=25%, none=0%)
    Returns (progress_int_0_100, materials_ratio, work_state).
    """
    mats = get_materials(user_id, goal_id)
    if mats:
        acquired = sum(1 for m in mats if m[3])
        mat_pct = acquired / len(mats)
    else:
        mat_pct = 0

    work = get_worklog(user_id, goal_id, limit=100)
    kinds = {w[2] for w in work}
    if "finished" in kinds:
        work_pct, state = 1.0, "finished"
    elif "progress" in kinds:
        work_pct, state = 0.5, "in progress"
    elif "started" in kinds:
        work_pct, state = 0.25, "started"
    else:
        work_pct, state = 0.0, "not started"

    # If no materials, weight is 100% work; if no work log yet, weight is 100% materials
    if mats and work:
        progress = round(50 * mat_pct + 50 * work_pct)
    elif mats:
        progress = round(100 * mat_pct)
    elif work:
        progress = round(100 * work_pct)
    else:
        progress = 0
    return progress, mat_pct, state


def get_project_overview(user_id, goal_id):
    """Full project card data — used by /project command."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    try:
        c.execute("PRAGMA table_info(goals)")
        cols = [r[1] for r in c.fetchall()]
        has_done = "done" in cols
        done_col = ", done" if has_done else ""
        c.execute(f"SELECT id, title, deadline{done_col} FROM goals WHERE id=? AND user_id=?",
                  (goal_id, user_id))
        row = c.fetchone()
    except Exception:
        row = None
    conn.close()
    if not row:
        return None
    goal_id_v = row[0]
    title = row[1]
    deadline = row[2]
    done = row[3] if len(row) > 3 else 0
    mats = get_materials(user_id, goal_id_v)
    work = get_worklog(user_id, goal_id_v)
    progress, mat_pct, state = compute_project_progress(user_id, goal_id_v)
    return {
        "id": goal_id_v,
        "title": title,
        "deadline": deadline,
        "done": bool(done),
        "materials": mats,
        "worklog": work,
        "progress": progress,
        "materials_acquired": sum(1 for m in mats if m[3]),
        "materials_total": len(mats),
        "work_state": state,
    }


def get_active_projects(user_id):
    """Goals that have materials OR worklog entries attached."""
    conn = sqlite3.connect(DB_NAME)
    _init_project_tables(conn)
    c = conn.cursor()
    c.execute("PRAGMA table_info(goals)")
    cols = [r[1] for r in c.fetchall()]
    done_filter = " AND COALESCE(g.done,0)=0" if "done" in cols else ""
    c.execute(f"""SELECT DISTINCT g.id, g.title, g.deadline
                  FROM goals g
                  WHERE g.user_id=?{done_filter}
                    AND (g.id IN (SELECT goal_id FROM project_materials WHERE user_id=?)
                      OR g.id IN (SELECT goal_id FROM project_worklog WHERE user_id=?))
                  ORDER BY g.deadline""",
              (user_id, user_id, user_id))
    rows = c.fetchall()
    conn.close()
    return rows


def get_all_pending_materials(user_id):
    """Auto-shopping list across all projects."""
    conn = sqlite3.connect(DB_NAME)
    _init_project_tables(conn)
    c = conn.cursor()
    c.execute("""SELECT m.name, m.quantity, g.title, g.id
                 FROM project_materials m JOIN goals g ON m.goal_id=g.id
                 WHERE m.user_id=? AND m.acquired=0
                 ORDER BY g.deadline, m.name""", (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows


# ══════════════════════════════════════════════════════════════════════
# v15.0-alpha.1 -- Workspace Foundation (docs/v15/WED.md, MIGRATION.md)
#
# Data layer for the Workspace OS. These tables + functions ship in every
# database but stay empty and unused until feature_flags.WORKSPACE is
# enabled -- the Storage Facade / Repository / Service on top of them are
# the only callers, and no v14 handler touches them. Additive-and-
# idempotent throughout: creating an existing workspace-schema is a no-op,
# the migration helpers can run repeatedly without duplicating rows, and
# flag-OFF startup leaves these tables empty so behaviour is byte-
# identical to v14.26.
#
# Column orders below are FROZEN: the Repository maps tuples to models by
# position, so every getter must SELECT in this exact order.
# ══════════════════════════════════════════════════════════════════════

WORKSPACE_COLS = ("id, user_id, template, title, status, icon, metadata, "
                  "ai_summary, telegram_topic_id, sort_order, created_at, "
                  "updated_at, archived_at")
MILESTONE_COLS = ("id, workspace_id, goal_id, title, status, progress, "
                  "sort_order, created_at, completed_at, archived_at, "
                  "deleted_at, fields, entity_type")
NOTE_COLS = "id, workspace_id, milestone_id, kind, content, source, created_at"
TIMELINE_COLS = ("id, user_id, workspace_id, entity_type, entity_id, "
                 "event_type, summary, payload, source, created_at, synced_at")
SYNC_COLS = ("id, user_id, workspace_id, timeline_event_id, adapter, "
             "target_id, payload, status, attempts, last_error, created_at, "
             "sent_at, ref")


def _init_workspace_tables(conn):
    """Create the Workspace Foundation tables and add the nullable FK
    columns that link existing tasks/goals/memories to a workspace.

    Idempotent (CREATE TABLE IF NOT EXISTS + _safe_add_column). Every new
    FK column is nullable with no default, so existing rows remain valid
    and flag-OFF operation is unchanged (NULL workspace_id == 'Inbox',
    interpreted lazily at read time -- MIGRATION.md §4)."""
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS workspaces (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        template TEXT NOT NULL DEFAULT 'generic',
        title TEXT NOT NULL,
        status TEXT DEFAULT 'active',
        icon TEXT,
        metadata TEXT,
        ai_summary TEXT,
        telegram_topic_id INTEGER,
        sort_order INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        archived_at TEXT
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_workspaces_user "
              "ON workspaces(user_id, status)")

    c.execute("""CREATE TABLE IF NOT EXISTS milestones (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id INTEGER NOT NULL,
        goal_id INTEGER,
        title TEXT NOT NULL,
        status TEXT DEFAULT 'todo',
        progress INTEGER DEFAULT 0,
        sort_order INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        completed_at TEXT,
        entity_type TEXT DEFAULT 'entity'
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_milestones_workspace "
              "ON milestones(workspace_id)")

    c.execute("""CREATE TABLE IF NOT EXISTS notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id INTEGER NOT NULL,
        milestone_id INTEGER,
        kind TEXT DEFAULT 'note',
        content TEXT NOT NULL,
        source TEXT DEFAULT 'user',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_notes_workspace "
              "ON notes(workspace_id)")

    c.execute("""CREATE TABLE IF NOT EXISTS attachments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id INTEGER NOT NULL,
        note_id INTEGER,
        telegram_file_id TEXT,
        file_type TEXT,
        file_name TEXT,
        caption TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_attachments_workspace "
              "ON attachments(workspace_id)")

    # ── Telegram-adapter-owned bindings (v15.1) ──────────────────────────
    # These map Workspace entities to Telegram groups/topics WITHOUT putting
    # any Telegram id on the core workspace/milestone rows -- the Workspace OS
    # stays Telegram-agnostic; only the adapter reads these.
    c.execute("""CREATE TABLE IF NOT EXISTS tg_workspace_bindings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        workspace_id INTEGER NOT NULL UNIQUE,
        chat_id INTEGER NOT NULL,
        general_topic_id INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_tgbind_user "
              "ON tg_workspace_bindings(user_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_tgbind_chat "
              "ON tg_workspace_bindings(chat_id)")

    # One Telegram forum topic per workspace entity (entity_type+entity_id).
    # v15.2 M4 canonical binding: the SAME workspace+entity must never have
    # two topics, regardless of how each row was created (legacy /add,
    # Worker, backfill, a failed run). The unique index on
    # (workspace_id, entity_id) enforces one binding per workspace entity;
    # topic_locked is a durable protect bit (item 8).
    c.execute("""CREATE TABLE IF NOT EXISTS tg_entity_topics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        workspace_id INTEGER NOT NULL,
        entity_type TEXT NOT NULL,
        entity_id INTEGER NOT NULL,
        topic_id INTEGER NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(entity_type, entity_id)
    )""")
    _safe_add_column(c, "tg_entity_topics", "topic_locked", "INTEGER DEFAULT 0")
    c.execute("CREATE INDEX IF NOT EXISTS idx_tgtopic_ws "
              "ON tg_entity_topics(workspace_id)")
    try:
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS "
                  "idx_tgtopic_ws_entity "
                  "ON tg_entity_topics(workspace_id, entity_id)")
    except sqlite3.OperationalError:
        # A legacy DB that already holds duplicate (workspace_id, entity_id)
        # bindings cannot get the unique index without a repair first. Keep
        # the old unique(entity_type, entity_id) guard and let /topicrepair
        # reconcile -- never crash the bot on startup.
        logger.warning(
            "duplicate (workspace_id, entity_id) topic bindings detected; "
            "canonical unique index skipped — run /topicrepair")

    # The user's active workspace + entity (where the next photo/note lands).
    c.execute("""CREATE TABLE IF NOT EXISTS tg_active_context (
        user_id INTEGER PRIMARY KEY,
        workspace_id INTEGER,
        entity_type TEXT,
        entity_id INTEGER,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS tags (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        name TEXT NOT NULL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS entity_tags (
        tag_id INTEGER NOT NULL,
        entity_type TEXT NOT NULL,
        entity_id INTEGER NOT NULL
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_entity_tags "
              "ON entity_tags(entity_type, entity_id)")

    # v15.0-alpha.5: append-only Knowledge Timeline (docs/v15/KTD.md). One
    # immutable row per meaningful mutation. Only synced_at is ever updated
    # (by the future Telegram Sync); nothing here is edited or deleted in
    # normal operation.
    c.execute("""CREATE TABLE IF NOT EXISTS timeline_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        workspace_id INTEGER,
        entity_type TEXT,
        entity_id INTEGER,
        event_type TEXT NOT NULL,
        summary TEXT NOT NULL,
        payload TEXT,
        source TEXT DEFAULT 'user',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        synced_at TEXT
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_timeline_user "
              "ON timeline_events(user_id, workspace_id, id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_timeline_entity "
              "ON timeline_events(entity_type, entity_id)")

    # v15.0-alpha.6: durable outbound sync outbox (docs/v15/TWID.md). One
    # row per (timeline event, adapter); a worker drains 'pending' rows and
    # marks them 'sent' (with the delivered ref) or 'failed' after retries.
    # Decouples correctness (SQLite) from delivery (Telegram/etc.).
    c.execute("""CREATE TABLE IF NOT EXISTS sync_outbox (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        workspace_id INTEGER,
        timeline_event_id INTEGER,
        adapter TEXT NOT NULL,
        target_id INTEGER,
        payload TEXT,
        status TEXT DEFAULT 'pending',
        attempts INTEGER DEFAULT 0,
        last_error TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        sent_at TEXT,
        ref TEXT
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_sync_outbox_pending "
              "ON sync_outbox(user_id, status, id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_sync_outbox_event "
              "ON sync_outbox(timeline_event_id, adapter)")

    # Nullable FK columns on existing tables (NULL == Inbox / unassigned).
    _safe_add_column(c, "tasks", "workspace_id", "INTEGER")
    _safe_add_column(c, "tasks", "milestone_id", "INTEGER")
    _safe_add_column(c, "goals", "workspace_id", "INTEGER")
    _safe_add_column(c, "memories", "workspace_id", "INTEGER")

    # v15.0-alpha.4: milestone archive (status='archived' + stamp) and
    # soft delete (deleted_at set, row kept). Additive/idempotent.
    _safe_add_column(c, "milestones", "archived_at", "TEXT")
    _safe_add_column(c, "milestones", "deleted_at", "TEXT")

    # v15.1.0-alpha.9: structured per-entity fields (JSON TEXT, same
    # pattern as workspaces.metadata). NULL = no structured fields.
    _safe_add_column(c, "milestones", "fields", "TEXT")

    # v15.2 M4: per-entity KIND (character/artifact/weapon/item/entity) so
    # typed identity is (workspace_id, entity_type, id), duplicate detection
    # is type-aware, and "show all <kind>" filters structurally (M4 F8/F9).
    # Additive/idempotent; existing rows read as 'entity'.
    _safe_add_column(c, "milestones", "entity_type",
                     "TEXT DEFAULT 'entity'")

    conn.commit()


def _now_ist_str():
    """Timestamp string in IST (never a bare datetime.now() -- CLAUDE.md)."""
    return datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")


# ── Workspaces ─────────────────────────────────────────
def create_workspace(user_id, title, template="generic", icon=None,
                     metadata=None, sort_order=0):
    """Insert a workspace and return its id. `metadata` may be a dict
    (stored as JSON) or None."""
    conn = sqlite3.connect(DB_NAME)
    _init_workspace_tables(conn)
    c = conn.cursor()
    meta_json = json.dumps(metadata) if isinstance(metadata, dict) else metadata
    c.execute("""INSERT INTO workspaces
        (user_id, template, title, icon, metadata, sort_order)
        VALUES (?,?,?,?,?,?)""",
        (user_id, template, title, icon, meta_json, sort_order))
    ws_id = c.lastrowid
    conn.commit()
    conn.close()
    return ws_id


def get_workspace(workspace_id, user_id):
    conn = sqlite3.connect(DB_NAME)
    _init_workspace_tables(conn)
    c = conn.cursor()
    c.execute(f"SELECT {WORKSPACE_COLS} FROM workspaces WHERE id=? AND user_id=?",
              (workspace_id, user_id))
    row = c.fetchone()
    conn.close()
    return row


def get_workspaces(user_id, status="active"):
    """List a user's workspaces, newest sort_order first. `status=None`
    returns every status (active + archived + done)."""
    conn = sqlite3.connect(DB_NAME)
    _init_workspace_tables(conn)
    c = conn.cursor()
    if status is None:
        c.execute(f"SELECT {WORKSPACE_COLS} FROM workspaces WHERE user_id=? "
                  "ORDER BY sort_order ASC, id ASC", (user_id,))
    else:
        c.execute(f"SELECT {WORKSPACE_COLS} FROM workspaces "
                  "WHERE user_id=? AND status=? "
                  "ORDER BY sort_order ASC, id ASC", (user_id, status))
    rows = c.fetchall()
    conn.close()
    return rows


def get_workspace_by_title(user_id, title):
    """Exact (case-insensitive) title match -- used by migration idempotency
    and later by the AI Orchestrator's workspace selection."""
    conn = sqlite3.connect(DB_NAME)
    _init_workspace_tables(conn)
    c = conn.cursor()
    c.execute(f"SELECT {WORKSPACE_COLS} FROM workspaces "
              "WHERE user_id=? AND LOWER(title)=LOWER(?) "
              "ORDER BY id ASC LIMIT 1", (user_id, title))
    row = c.fetchone()
    conn.close()
    return row


def update_workspace(workspace_id, user_id, title=None, status=None,
                     icon=None, metadata=None, ai_summary=None,
                     telegram_topic_id=None, sort_order=None):
    """Update the given fields (only non-None ones). Always stamps
    updated_at. Setting status='archived' also stamps archived_at."""
    fields = {
        "title": title, "status": status, "icon": icon,
        "ai_summary": ai_summary, "telegram_topic_id": telegram_topic_id,
        "sort_order": sort_order,
    }
    if metadata is not None:
        fields["metadata"] = json.dumps(metadata) if isinstance(metadata, dict) else metadata
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    for field, value in fields.items():
        if value is not None:
            c.execute(f"UPDATE workspaces SET {field}=? WHERE id=? AND user_id=?",
                      (value, workspace_id, user_id))
    c.execute("UPDATE workspaces SET updated_at=? WHERE id=? AND user_id=?",
              (_now_ist_str(), workspace_id, user_id))
    if status == "archived":
        c.execute("UPDATE workspaces SET archived_at=? WHERE id=? AND user_id=?",
                  (_now_ist_str(), workspace_id, user_id))
    conn.commit()
    conn.close()


def archive_workspace(workspace_id, user_id):
    """Convenience wrapper: soft-archive (never deletes rows)."""
    update_workspace(workspace_id, user_id, status="archived")


def delete_workspace(workspace_id, user_id):
    """Hard-delete a workspace and its milestones + notes, scoped to the
    owner. Ownership-checked: removes nothing if the workspace isn't the
    user's. Returns True iff a workspace row was removed. Unlike
    archive_workspace (soft), this removes rows -- used by the Self-Test
    round-trip so it leaves no residue, and available for genuine hard
    deletes. (v15.0-rc.2)"""
    conn = sqlite3.connect(DB_NAME)
    _init_workspace_tables(conn)
    c = conn.cursor()
    c.execute("SELECT id FROM workspaces WHERE id=? AND user_id=?",
              (workspace_id, user_id))
    if c.fetchone() is None:
        conn.close()
        return False
    c.execute("DELETE FROM attachments WHERE workspace_id=?", (workspace_id,))
    c.execute("DELETE FROM notes WHERE workspace_id=?", (workspace_id,))
    c.execute("DELETE FROM milestones WHERE workspace_id=?", (workspace_id,))
    c.execute("DELETE FROM tg_entity_topics WHERE workspace_id=?", (workspace_id,))
    c.execute("DELETE FROM tg_workspace_bindings WHERE workspace_id=?", (workspace_id,))
    c.execute("DELETE FROM workspaces WHERE id=? AND user_id=?",
              (workspace_id, user_id))
    conn.commit()
    conn.close()
    return True


# ── Telegram-adapter-owned bindings (v15.1) ───────────────────────────────
# Pure storage for the Telegram projection adapter. The Workspace OS never
# reads these -- topic/chat ids live here, not on core entities.

def tg_link_workspace(user_id, workspace_id, chat_id, general_topic_id=None):
    """Bind a workspace to a Telegram group chat (idempotent by workspace)."""
    conn = sqlite3.connect(DB_NAME)
    _init_workspace_tables(conn)
    c = conn.cursor()
    c.execute("""INSERT INTO tg_workspace_bindings
                 (user_id, workspace_id, chat_id, general_topic_id)
                 VALUES (?,?,?,?)
                 ON CONFLICT(workspace_id) DO UPDATE SET
                   chat_id=excluded.chat_id,
                   general_topic_id=COALESCE(excluded.general_topic_id,
                                             tg_workspace_bindings.general_topic_id),
                   updated_at=?""",
              (user_id, workspace_id, chat_id, general_topic_id, _now_ist_str()))
    conn.commit()
    conn.close()


def tg_get_binding(workspace_id):
    """(chat_id, general_topic_id) for a workspace, or None if unbound."""
    conn = sqlite3.connect(DB_NAME)
    _init_workspace_tables(conn)
    c = conn.cursor()
    c.execute("SELECT chat_id, general_topic_id FROM tg_workspace_bindings "
              "WHERE workspace_id=?", (workspace_id,))
    row = c.fetchone()
    conn.close()
    return row


def tg_get_workspace_for_chat(chat_id):
    """The workspace_id bound to a chat, or None (used by /linkhere replies)."""
    conn = sqlite3.connect(DB_NAME)
    _init_workspace_tables(conn)
    c = conn.cursor()
    c.execute("SELECT workspace_id FROM tg_workspace_bindings WHERE chat_id=?",
              (chat_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None


def tg_set_general_topic(workspace_id, topic_id):
    conn = sqlite3.connect(DB_NAME)
    _init_workspace_tables(conn)
    c = conn.cursor()
    c.execute("UPDATE tg_workspace_bindings SET general_topic_id=?, updated_at=? "
              "WHERE workspace_id=?", (topic_id, _now_ist_str(), workspace_id))
    conn.commit()
    conn.close()


def tg_unlink_workspace(workspace_id):
    conn = sqlite3.connect(DB_NAME)
    _init_workspace_tables(conn)
    c = conn.cursor()
    c.execute("DELETE FROM tg_workspace_bindings WHERE workspace_id=?", (workspace_id,))
    c.execute("DELETE FROM tg_entity_topics WHERE workspace_id=?", (workspace_id,))
    conn.commit()
    conn.close()


def tg_set_entity_topic(user_id, workspace_id, entity_type, entity_id, topic_id):
    """Record the Telegram topic created for an entity (idempotent).
    v15.2 M4 canonical binding: there is NEVER more than one binding for a
    (workspace_id, entity_id), no matter what entity_type string a caller
    uses. Implemented as delete-any-other-canonical-row + upsert on the
    always-present UNIQUE(entity_type, entity_id), so it works even on a
    legacy DB where the canonical unique index could not be built."""
    conn = sqlite3.connect(DB_NAME)
    _init_workspace_tables(conn)
    c = conn.cursor()
    c.execute("DELETE FROM tg_entity_topics "
              "WHERE workspace_id=? AND entity_id=? "
              "AND NOT (entity_type=? AND entity_id=?)",
              (workspace_id, entity_id, entity_type, entity_id))
    c.execute("""INSERT INTO tg_entity_topics
                 (user_id, workspace_id, entity_type, entity_id, topic_id)
                 VALUES (?,?,?,?,?)
                 ON CONFLICT(entity_type, entity_id) DO UPDATE SET
                   topic_id=excluded.topic_id""",
              (user_id, workspace_id, entity_type, entity_id, topic_id))
    conn.commit()
    conn.close()


def tg_get_workspace_entity_topic(workspace_id, entity_type, entity_id):
    """The topic_id for a workspace entity, keyed canonically by
    (workspace_id, entity_id). Falls back to the legacy (entity_type,
    entity_id) key so pre-canonical rows still resolve."""
    conn = sqlite3.connect(DB_NAME)
    _init_workspace_tables(conn)
    c = conn.cursor()
    c.execute("SELECT topic_id FROM tg_entity_topics "
              "WHERE workspace_id=? AND entity_id=? LIMIT 1",
              (workspace_id, entity_id))
    row = c.fetchone()
    if row is None:
        c.execute("SELECT topic_id FROM tg_entity_topics "
                  "WHERE entity_type=? AND entity_id=? LIMIT 1",
                  (entity_type, entity_id))
        row = c.fetchone()
    conn.close()
    return row[0] if row else None


def tg_delete_entity_topic(workspace_id, entity_type, entity_id):
    """Remove the canonical topic binding for a workspace entity. Does NOT
    touch the underlying entity or its Telegram topic -- the binding row is
    just deleted so ensure_entity_topic can re-create it. v15.2 M4."""
    conn = sqlite3.connect(DB_NAME)
    _init_workspace_tables(conn)
    c = conn.cursor()
    c.execute("DELETE FROM tg_entity_topics WHERE workspace_id=? AND entity_id=?",
              (workspace_id, entity_id))
    if c.rowcount == 0:
        c.execute("DELETE FROM tg_entity_topics "
                  "WHERE entity_type=? AND entity_id=?",
                  (entity_type, entity_id))
    conn.commit()
    conn.close()


def tg_set_entity_topic_locked(workspace_id, entity_type, entity_id, locked: bool):
    """Durably lock/unlock a topic binding (v15.2 M4 item 8). A locked topic
    is refused for ordinary delete operations."""
    conn = sqlite3.connect(DB_NAME)
    _init_workspace_tables(conn)
    c = conn.cursor()
    c.execute("UPDATE tg_entity_topics SET topic_locked=? "
              "WHERE workspace_id=? AND entity_id=?",
              (1 if locked else 0, workspace_id, entity_id))
    if c.rowcount == 0:
        c.execute("UPDATE tg_entity_topics SET topic_locked=? "
                  "WHERE entity_type=? AND entity_id=?",
                  (1 if locked else 0, entity_type, entity_id))
    conn.commit()
    conn.close()


def tg_get_entity_topic_locked(workspace_id, entity_type, entity_id) -> bool:
    """Whether a topic binding is locked (v15.2 M4 item 8). False when there
    is no binding at all (nothing locked)."""
    conn = sqlite3.connect(DB_NAME)
    _init_workspace_tables(conn)
    c = conn.cursor()
    c.execute("SELECT topic_locked FROM tg_entity_topics "
              "WHERE workspace_id=? AND entity_id=? LIMIT 1",
              (workspace_id, entity_id))
    row = c.fetchone()
    if row is None:
        c.execute("SELECT topic_locked FROM tg_entity_topics "
                  "WHERE entity_type=? AND entity_id=? LIMIT 1",
                  (entity_type, entity_id))
        row = c.fetchone()
    conn.close()
    return bool(row[0]) if row else False


def tg_get_entity_topic(entity_type, entity_id):
    """The topic_id for an entity, or None if no topic has been created."""
    conn = sqlite3.connect(DB_NAME)
    _init_workspace_tables(conn)
    c = conn.cursor()
    c.execute("SELECT topic_id FROM tg_entity_topics "
              "WHERE entity_type=? AND entity_id=?", (entity_type, entity_id))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None


def tg_get_entity_topics(workspace_id):
    """All (entity_type, entity_id, topic_id) rows for a workspace."""
    conn = sqlite3.connect(DB_NAME)
    _init_workspace_tables(conn)
    c = conn.cursor()
    c.execute("SELECT entity_type, entity_id, topic_id FROM tg_entity_topics "
              "WHERE workspace_id=? ORDER BY id ASC", (workspace_id,))
    rows = c.fetchall()
    conn.close()
    return rows


def tg_set_active(user_id, workspace_id, entity_type=None, entity_id=None):
    """Set the user's active workspace (+ optional active entity)."""
    conn = sqlite3.connect(DB_NAME)
    _init_workspace_tables(conn)
    c = conn.cursor()
    c.execute("""INSERT INTO tg_active_context
                 (user_id, workspace_id, entity_type, entity_id, updated_at)
                 VALUES (?,?,?,?,?)
                 ON CONFLICT(user_id) DO UPDATE SET
                   workspace_id=excluded.workspace_id,
                   entity_type=excluded.entity_type,
                   entity_id=excluded.entity_id,
                   updated_at=excluded.updated_at""",
              (user_id, workspace_id, entity_type, entity_id, _now_ist_str()))
    conn.commit()
    conn.close()


def tg_get_active(user_id):
    """(workspace_id, entity_type, entity_id) for the user, or None."""
    conn = sqlite3.connect(DB_NAME)
    _init_workspace_tables(conn)
    c = conn.cursor()
    c.execute("SELECT workspace_id, entity_type, entity_id FROM tg_active_context "
              "WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row


def tg_clear_active(user_id):
    conn = sqlite3.connect(DB_NAME)
    _init_workspace_tables(conn)
    c = conn.cursor()
    c.execute("DELETE FROM tg_active_context WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()


# ── Milestones ─────────────────────────────────────────
def add_milestone(workspace_id, title, goal_id=None, sort_order=0, fields=None,
                  entity_type="entity"):
    """Insert a milestone and return its id. `fields` is an optional dict of
    template-specific structured per-entity fields, stored as JSON.
    `entity_type` is the entity's kind (default 'entity' -- see v15.2 M4)."""
    conn = sqlite3.connect(DB_NAME)
    _init_workspace_tables(conn)
    c = conn.cursor()
    fields_raw = json.dumps(fields) if fields else None
    c.execute("""INSERT INTO milestones
                 (workspace_id, goal_id, title, sort_order, fields, entity_type)
                 VALUES (?,?,?,?,?,?)""",
              (workspace_id, goal_id, title, sort_order, fields_raw,
               entity_type or "entity"))
    ms_id = c.lastrowid
    conn.commit()
    conn.close()
    return ms_id


def get_milestone(milestone_id):
    """A single milestone by id, excluding soft-deleted rows (a deleted
    milestone reads as gone -- v15.0-alpha.4)."""
    conn = sqlite3.connect(DB_NAME)
    _init_workspace_tables(conn)
    c = conn.cursor()
    c.execute(f"SELECT {MILESTONE_COLS} FROM milestones "
              "WHERE id=? AND deleted_at IS NULL", (milestone_id,))
    row = c.fetchone()
    conn.close()
    return row


def get_milestones(workspace_id, include_archived=False):
    """A workspace's milestones. Excludes soft-deleted rows always, and
    archived ones unless include_archived (v15.0-alpha.4)."""
    conn = sqlite3.connect(DB_NAME)
    _init_workspace_tables(conn)
    c = conn.cursor()
    archived_filter = "" if include_archived else " AND status!='archived'"
    c.execute(f"SELECT {MILESTONE_COLS} FROM milestones "
              f"WHERE workspace_id=? AND deleted_at IS NULL{archived_filter} "
              "ORDER BY sort_order ASC, id ASC", (workspace_id,))
    rows = c.fetchall()
    conn.close()
    return rows


def update_milestone(milestone_id, status=None, progress=None, title=None):
    """Update a milestone's status/progress/title. Setting status='done'
    stamps completed_at; status='archived' stamps archived_at."""
    fields = {"status": status, "progress": progress, "title": title}
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    for field, value in fields.items():
        if value is not None:
            c.execute(f"UPDATE milestones SET {field}=? WHERE id=?",
                      (value, milestone_id))
    if status == "done":
        c.execute("UPDATE milestones SET completed_at=? WHERE id=?",
                  (_now_ist_str(), milestone_id))
    elif status == "archived":
        c.execute("UPDATE milestones SET archived_at=? WHERE id=?",
                  (_now_ist_str(), milestone_id))
    conn.commit()
    conn.close()


def update_milestone_entity_type(milestone_id, entity_type):
    """Adopt an entity kind on an existing milestone (v15.2 M4 canonical
    binding). Used when a create collides by name with an existing row of a
    different kind -- the row is reused (one entity, one topic) and its kind
    upgraded rather than a second duplicate row being inserted."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE milestones SET entity_type=? WHERE id=?",
              (entity_type or "entity", milestone_id))
    conn.commit()
    conn.close()


def soft_delete_milestone(milestone_id):
    """Mark a milestone deleted without removing the row (stamps
    deleted_at). It then reads as gone from get_milestone/get_milestones
    but the record is retained for recovery/audit -- v15.0-alpha.4. No-op
    on an already-deleted row."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE milestones SET deleted_at=? WHERE id=? AND deleted_at IS NULL",
              (_now_ist_str(), milestone_id))
    conn.commit()
    conn.close()


def set_milestone_fields(milestone_id, fields):
    """Store a dict of structured per-entity fields on a milestone as JSON.
    None or empty dict clears the column. v15.1.0-alpha.9."""
    conn = sqlite3.connect(DB_NAME)
    _init_workspace_tables(conn)
    c = conn.cursor()
    raw = json.dumps(fields) if fields else None
    c.execute("UPDATE milestones SET fields=? WHERE id=?", (raw, milestone_id))
    conn.commit()
    conn.close()


def get_milestone_fields(milestone_id):
    """Return the stored per-entity fields dict for a milestone, or {}
    if the milestone doesn't exist, was deleted, or has no fields set."""
    conn = sqlite3.connect(DB_NAME)
    _init_workspace_tables(conn)
    c = conn.cursor()
    c.execute("SELECT fields FROM milestones WHERE id=? AND deleted_at IS NULL",
              (milestone_id,))
    row = c.fetchone()
    conn.close()
    if row is None or row[0] is None:
        return {}
    try:
        parsed = json.loads(row[0])
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, TypeError):
        return {}


def count_milestones(workspace_id):
    """Return (total, done) milestone counts -- the raw input for the
    Service's workspace progress rollup. Excludes soft-deleted and
    archived milestones: they are no longer part of the plan, so they
    don't count toward the denominator (v15.0-alpha.4)."""
    conn = sqlite3.connect(DB_NAME)
    _init_workspace_tables(conn)
    c = conn.cursor()
    c.execute("SELECT COUNT(*), COALESCE(SUM(status='done'),0) "
              "FROM milestones WHERE workspace_id=? "
              "AND deleted_at IS NULL AND status!='archived'", (workspace_id,))
    total, done = c.fetchone()
    conn.close()
    return total, done


# ── Notes ──────────────────────────────────────────────
def add_note(workspace_id, content, kind="note", milestone_id=None,
             source="user"):
    conn = sqlite3.connect(DB_NAME)
    _init_workspace_tables(conn)
    c = conn.cursor()
    c.execute("""INSERT INTO notes
        (workspace_id, milestone_id, kind, content, source)
        VALUES (?,?,?,?,?)""",
        (workspace_id, milestone_id, kind, content, source))
    note_id = c.lastrowid
    conn.commit()
    conn.close()
    return note_id


def add_attachment(workspace_id, note_id, telegram_file_id, file_type="photo",
                   file_name=None, caption=None):
    """Persist a file attachment (e.g. a Telegram photo file_id) against a
    note. Keeps the raw file_id so the image can be re-posted or re-fetched
    later without re-uploading (v15.1)."""
    conn = sqlite3.connect(DB_NAME)
    _init_workspace_tables(conn)
    c = conn.cursor()
    c.execute("""INSERT INTO attachments
        (workspace_id, note_id, telegram_file_id, file_type, file_name, caption)
        VALUES (?,?,?,?,?,?)""",
        (workspace_id, note_id, telegram_file_id, file_type, file_name, caption))
    att_id = c.lastrowid
    conn.commit()
    conn.close()
    return att_id


def get_attachments(workspace_id, note_id=None):
    conn = sqlite3.connect(DB_NAME)
    _init_workspace_tables(conn)
    c = conn.cursor()
    if note_id is None:
        c.execute("SELECT id, note_id, telegram_file_id, file_type, caption "
                  "FROM attachments WHERE workspace_id=? ORDER BY id ASC",
                  (workspace_id,))
    else:
        c.execute("SELECT id, note_id, telegram_file_id, file_type, caption "
                  "FROM attachments WHERE note_id=? ORDER BY id ASC", (note_id,))
    rows = c.fetchall()
    conn.close()
    return rows


def get_notes(workspace_id, kind=None):
    conn = sqlite3.connect(DB_NAME)
    _init_workspace_tables(conn)
    c = conn.cursor()
    if kind is None:
        c.execute(f"SELECT {NOTE_COLS} FROM notes WHERE workspace_id=? "
                  "ORDER BY id ASC", (workspace_id,))
    else:
        c.execute(f"SELECT {NOTE_COLS} FROM notes WHERE workspace_id=? AND kind=? "
                  "ORDER BY id ASC", (workspace_id, kind))
    rows = c.fetchall()
    conn.close()
    return rows


# ── Migration helpers (MIGRATION.md) ───────────────────
def ensure_default_workspace(user_id, title="Inbox", template="generic"):
    """Return the id of the user's default workspace, creating it once if
    absent. Idempotent -- a second call returns the same id, never a
    duplicate (matched by title). MIGRATION.md §2."""
    existing = get_workspace_by_title(user_id, title)
    if existing:
        return existing[0]
    return create_workspace(user_id, title=title, template=template,
                            icon="📥" if title == "Inbox" else None)


def migrate_projects_to_workspaces(user_id):
    """Convert each of the user's project-goals (a goal that has materials
    or worklog -- get_active_projects()'s definition) into a workspace of
    template 'project', and backfill workspace_id on the goal and its
    tasks. Idempotent: a goal already linked to a workspace is skipped, so
    re-running migrates only new projects. No row is moved or deleted --
    the goal/material/worklog tables are referenced, not rewritten
    (MIGRATION.md §3). Returns the number of workspaces created."""
    conn = sqlite3.connect(DB_NAME)
    _init_workspace_tables(conn)
    c = conn.cursor()
    # Project-goals: goals with materials or worklog and not yet linked.
    c.execute("""SELECT DISTINCT g.id, g.title FROM goals g
                 WHERE g.user_id=?
                   AND (g.workspace_id IS NULL)
                   AND (g.id IN (SELECT goal_id FROM project_materials WHERE user_id=?)
                     OR g.id IN (SELECT goal_id FROM project_worklog WHERE user_id=?))""",
              (user_id, user_id, user_id))
    project_goals = c.fetchall()
    created = 0
    for goal_id, goal_title in project_goals:
        c.execute("""INSERT INTO workspaces (user_id, template, title, icon)
                     VALUES (?, 'project', ?, '🛠')""",
                  (user_id, goal_title or "Project"))
        ws_id = c.lastrowid
        c.execute("UPDATE goals SET workspace_id=? WHERE id=? AND user_id=?",
                  (ws_id, goal_id, user_id))
        created += 1
    # v14 has no task->goal foreign key, so a project's tasks can't be
    # identified here; they remain in Inbox (workspace_id NULL) until a
    # later phase (or the AI Orchestrator) associates them. No data lost.
    conn.commit()
    conn.close()
    return created


# ── Project<->Workspace bridge (v15.0-alpha.3) ─────────
# A v14 "project" is a goal with materials/worklog. v15 routes projects
# through the Workspace layer by treating the project's goal as the backing
# record and a template='project' workspace as its container, linked via
# goals.workspace_id. These helpers are the bridge; the project's
# materials/worklog/progress functions above are reused verbatim (no data
# moved -- MIGRATION.md §3). All additive and uncalled while WORKSPACE is
# OFF, so the legacy /projects path stays byte-identical.
def get_workspace_goal_id(user_id, workspace_id):
    """The goal id backing a project workspace (reverse of the link), or
    None."""
    conn = sqlite3.connect(DB_NAME)
    _init_workspace_tables(conn)
    c = conn.cursor()
    c.execute("SELECT id FROM goals WHERE workspace_id=? AND user_id=? "
              "ORDER BY id ASC LIMIT 1", (workspace_id, user_id))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None


def get_goal_workspace_id(user_id, goal_id):
    """The workspace id a goal is linked to, or None."""
    conn = sqlite3.connect(DB_NAME)
    _init_workspace_tables(conn)
    c = conn.cursor()
    c.execute("SELECT workspace_id FROM goals WHERE id=? AND user_id=?",
              (goal_id, user_id))
    row = c.fetchone()
    conn.close()
    return row[0] if row and row[0] is not None else None


def set_goal_workspace(user_id, goal_id, workspace_id):
    """Link a goal to a workspace (idempotent -- re-setting the same link is
    a no-op)."""
    conn = sqlite3.connect(DB_NAME)
    _init_workspace_tables(conn)
    c = conn.cursor()
    c.execute("UPDATE goals SET workspace_id=? WHERE id=? AND user_id=?",
              (workspace_id, goal_id, user_id))
    conn.commit()
    conn.close()


def verify_project_migration(user_id):
    """Integrity report for the project->workspace migration: how many
    project-goals still lack a workspace link, and how many
    template='project' workspaces have no backing goal (orphans). `ok` is
    True when both are zero. Never raises -- returns a report dict."""
    report = {"ok": True, "unmigrated_projects": [], "orphan_workspaces": [],
              "projects_total": 0, "project_workspaces_total": 0}
    try:
        conn = sqlite3.connect(DB_NAME)
        _init_workspace_tables(conn)
        c = conn.cursor()
        # Project-goals (have materials or worklog) not yet linked.
        c.execute("""SELECT g.id FROM goals g WHERE g.user_id=?
                     AND g.workspace_id IS NULL
                     AND (g.id IN (SELECT goal_id FROM project_materials WHERE user_id=?)
                       OR g.id IN (SELECT goal_id FROM project_worklog WHERE user_id=?))""",
                  (user_id, user_id, user_id))
        report["unmigrated_projects"] = [r[0] for r in c.fetchall()]
        # Count all project-goals for context.
        c.execute("""SELECT COUNT(DISTINCT g.id) FROM goals g WHERE g.user_id=?
                     AND (g.id IN (SELECT goal_id FROM project_materials WHERE user_id=?)
                       OR g.id IN (SELECT goal_id FROM project_worklog WHERE user_id=?))""",
                  (user_id, user_id, user_id))
        report["projects_total"] = c.fetchone()[0]
        # Project workspaces with no backing goal.
        c.execute("""SELECT w.id FROM workspaces w
                     WHERE w.user_id=? AND w.template='project'
                     AND w.id NOT IN (SELECT workspace_id FROM goals
                                      WHERE user_id=? AND workspace_id IS NOT NULL)""",
                  (user_id, user_id))
        report["orphan_workspaces"] = [r[0] for r in c.fetchall()]
        c.execute("SELECT COUNT(*) FROM workspaces WHERE user_id=? AND template='project'",
                  (user_id,))
        report["project_workspaces_total"] = c.fetchone()[0]
        conn.close()
        report["ok"] = (not report["unmigrated_projects"]
                        and not report["orphan_workspaces"])
    except Exception as e:
        logger.error(f"verify_project_migration failed: {e}")
        report["ok"] = False
        report["error"] = str(e)
    return report


# ── Knowledge Timeline (v15.0-alpha.5, docs/v15/KTD.md) ─
# Append-only event log. add_timeline_event INSERTs; the getters read; only
# mark_timeline_synced updates (a single synced_at stamp, for the future
# Telegram Sync). Nothing edits summary/payload or deletes rows in normal
# operation -- immutability is what makes the timeline a trustworthy record.
def add_timeline_event(user_id, event_type, summary, entity_type=None,
                       entity_id=None, workspace_id=None, payload=None,
                       source="user"):
    """Append one immutable event; returns its id. `payload` may be a dict
    (stored as JSON) or a string/None."""
    payload_json = json.dumps(payload) if isinstance(payload, dict) else payload
    conn = sqlite3.connect(DB_NAME)
    _init_workspace_tables(conn)
    c = conn.cursor()
    c.execute("""INSERT INTO timeline_events
        (user_id, workspace_id, entity_type, entity_id, event_type,
         summary, payload, source)
        VALUES (?,?,?,?,?,?,?,?)""",
        (user_id, workspace_id, entity_type, entity_id, event_type,
         summary, payload_json, source))
    event_id = c.lastrowid
    conn.commit()
    conn.close()
    return event_id


def get_timeline(user_id, workspace_id=None, limit=50):
    """A user's timeline newest-first, optionally scoped to one workspace."""
    conn = sqlite3.connect(DB_NAME)
    _init_workspace_tables(conn)
    c = conn.cursor()
    if workspace_id is None:
        c.execute(f"SELECT {TIMELINE_COLS} FROM timeline_events "
                  "WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit))
    else:
        c.execute(f"SELECT {TIMELINE_COLS} FROM timeline_events "
                  "WHERE user_id=? AND workspace_id=? ORDER BY id DESC LIMIT ?",
                  (user_id, workspace_id, limit))
    rows = c.fetchall()
    conn.close()
    return rows


def get_entity_timeline(entity_type, entity_id, limit=50):
    """One entity's history, newest-first."""
    conn = sqlite3.connect(DB_NAME)
    _init_workspace_tables(conn)
    c = conn.cursor()
    c.execute(f"SELECT {TIMELINE_COLS} FROM timeline_events "
              "WHERE entity_type=? AND entity_id=? ORDER BY id DESC LIMIT ?",
              (entity_type, entity_id, limit))
    rows = c.fetchall()
    conn.close()
    return rows


def count_timeline(user_id, workspace_id=None):
    conn = sqlite3.connect(DB_NAME)
    _init_workspace_tables(conn)
    c = conn.cursor()
    if workspace_id is None:
        c.execute("SELECT COUNT(*) FROM timeline_events WHERE user_id=?",
                  (user_id,))
    else:
        c.execute("SELECT COUNT(*) FROM timeline_events "
                  "WHERE user_id=? AND workspace_id=?", (user_id, workspace_id))
    n = c.fetchone()[0]
    conn.close()
    return n


def mark_timeline_synced(event_id, synced_at=None):
    """Stamp synced_at on one event (the only mutation the timeline allows).
    Used by the future Telegram Sync (alpha.6); harmless here."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE timeline_events SET synced_at=? WHERE id=?",
              (synced_at or _now_ist_str(), event_id))
    conn.commit()
    conn.close()


def get_unsynced_timeline(user_id, limit=100):
    """Events not yet marked synced_at, oldest-first -- the drain order the
    outbox worker uses (TWID)."""
    conn = sqlite3.connect(DB_NAME)
    _init_workspace_tables(conn)
    c = conn.cursor()
    c.execute(f"SELECT {TIMELINE_COLS} FROM timeline_events "
              "WHERE user_id=? AND synced_at IS NULL ORDER BY id ASC LIMIT ?",
              (user_id, limit))
    rows = c.fetchall()
    conn.close()
    return rows


# ── Sync outbox (v15.0-alpha.6, docs/v15/TWID.md) ──────
# Durable outbound-sync queue. enqueue_sync inserts a pending row;
# get_pending_sync drains oldest-first; a row ends 'sent' (mark_sync_sent,
# with the delivered ref) or 'failed' (mark_sync_failed, after retries).
# One row per (timeline_event_id, adapter) -- sync_outbox_exists gives the
# engine idempotency so re-enqueuing never double-posts.
def enqueue_sync(user_id, adapter, payload, timeline_event_id=None,
                 workspace_id=None, target_id=None):
    conn = sqlite3.connect(DB_NAME)
    _init_workspace_tables(conn)
    c = conn.cursor()
    c.execute("""INSERT INTO sync_outbox
        (user_id, workspace_id, timeline_event_id, adapter, target_id, payload)
        VALUES (?,?,?,?,?,?)""",
        (user_id, workspace_id, timeline_event_id, adapter, target_id, payload))
    outbox_id = c.lastrowid
    conn.commit()
    conn.close()
    return outbox_id


def sync_outbox_exists(timeline_event_id, adapter):
    """Whether an outbox row already exists for this (event, adapter) --
    the engine's idempotency guard. Always False when timeline_event_id is
    None (ad-hoc rows are never deduped)."""
    if timeline_event_id is None:
        return False
    conn = sqlite3.connect(DB_NAME)
    _init_workspace_tables(conn)
    c = conn.cursor()
    c.execute("SELECT 1 FROM sync_outbox "
              "WHERE timeline_event_id=? AND adapter=? LIMIT 1",
              (timeline_event_id, adapter))
    exists = c.fetchone() is not None
    conn.close()
    return exists


def get_pending_sync(user_id, limit=100):
    """Pending outbox rows, oldest-first (the drain order)."""
    conn = sqlite3.connect(DB_NAME)
    _init_workspace_tables(conn)
    c = conn.cursor()
    c.execute(f"SELECT {SYNC_COLS} FROM sync_outbox "
              "WHERE user_id=? AND status='pending' ORDER BY id ASC LIMIT ?",
              (user_id, limit))
    rows = c.fetchall()
    conn.close()
    return rows


def get_sync_row(outbox_id):
    conn = sqlite3.connect(DB_NAME)
    _init_workspace_tables(conn)
    c = conn.cursor()
    c.execute(f"SELECT {SYNC_COLS} FROM sync_outbox WHERE id=?", (outbox_id,))
    row = c.fetchone()
    conn.close()
    return row


def mark_sync_sent(outbox_id, ref=None):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""UPDATE sync_outbox
                 SET status='sent', sent_at=?, ref=?,
                     attempts=attempts+1, last_error=NULL
                 WHERE id=?""", (_now_ist_str(), ref, outbox_id))
    conn.commit()
    conn.close()


def mark_sync_retry(outbox_id, error):
    """A recoverable failure: bump attempts + record the error, keep the
    row 'pending' so the next drain retries it."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""UPDATE sync_outbox
                 SET attempts=attempts+1, last_error=?
                 WHERE id=?""", (str(error)[:500], outbox_id))
    conn.commit()
    conn.close()


def mark_sync_failed(outbox_id, error):
    """A terminal failure (retries exhausted): mark 'failed' and stop."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""UPDATE sync_outbox
                 SET status='failed', attempts=attempts+1, last_error=?
                 WHERE id=?""", (str(error)[:500], outbox_id))
    conn.commit()
    conn.close()


def sync_remaining_for_event(timeline_event_id):
    """Count of not-yet-sent outbox rows for a timeline event -- lets the
    engine mark the event synced only once every adapter delivered."""
    if timeline_event_id is None:
        return 0
    conn = sqlite3.connect(DB_NAME)
    _init_workspace_tables(conn)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM sync_outbox "
              "WHERE timeline_event_id=? AND status!='sent'",
              (timeline_event_id,))
    n = c.fetchone()[0]
    conn.close()
    return n


def count_sync(user_id, status=None):
    conn = sqlite3.connect(DB_NAME)
    _init_workspace_tables(conn)
    c = conn.cursor()
    if status is None:
        c.execute("SELECT COUNT(*) FROM sync_outbox WHERE user_id=?", (user_id,))
    else:
        c.execute("SELECT COUNT(*) FROM sync_outbox WHERE user_id=? AND status=?",
                  (user_id, status))
    n = c.fetchone()[0]
    conn.close()
    return n