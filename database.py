import sqlite3
from datetime import datetime, timedelta
import pytz
IST = pytz.timezone("Asia/Kolkata")

DB_NAME = "planner.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

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
    ]:
        try:
            c.execute(f'ALTER TABLE tasks ADD COLUMN {col} {definition}')
        except Exception:
            pass

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

    conn.commit()
    # v8.0: ensure preference + learning table migrations run at startup
    try:
        _init_preferences(conn)
    except Exception:
        pass
    try:
        _init_learning_tables(conn)
    except Exception:
        pass
    conn.commit()
    conn.close()


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
def save_memory(user_id, key, value):
    """
    Manual check-then-insert/update instead of INSERT...ON CONFLICT.
    This avoids depending on a UNIQUE(user_id, key) constraint, which
    older databases (created before this constraint was added) won't have.
    SQLite raises 'ON CONFLICT clause does not match any PRIMARY KEY or
    UNIQUE constraint' in that case — this approach works regardless.
    """
    if not key:
        return False
    key_clean = key.lower().strip()
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT id FROM memories WHERE user_id=? AND key=?', (user_id, key_clean))
    existing = c.fetchone()
    if existing:
        c.execute('UPDATE memories SET value=? WHERE id=?', (value, existing[0]))
    else:
        c.execute('INSERT INTO memories (user_id, key, value) VALUES (?,?,?)',
                  (user_id, key_clean, value))
    conn.commit()
    conn.close()
    return True

def get_memory(user_id, key):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT value FROM memories WHERE user_id=? AND key=?',
              (user_id, key.lower().strip()))
    result = c.fetchone()
    conn.close()
    return result[0] if result else None

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

def delete_memory(user_id, key):
    # Bug 19: keys stored lowercased+stripped — match the same way
    if not key:
        return False
    key_clean = key.lower().strip()
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('DELETE FROM memories WHERE user_id=? AND key=?', (user_id, key_clean))
    deleted = c.rowcount > 0
    conn.commit()
    conn.close()
    return deleted

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
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT id, title, deadline, progress FROM goals WHERE user_id=? AND done=0',
              (user_id,))
    goals = c.fetchall()
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
        try:
            c.execute(f"ALTER TABLE user_preferences ADD COLUMN {col} {ddl}")
        except Exception:
            pass
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
    today = datetime.now().strftime("%Y-%m-%d")
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
        log_date = datetime.now().strftime("%Y-%m-%d")
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
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
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
                 (datetime.now() - timedelta(days=days)).date())

    # Days when this habit "should" have happened
    expected = []
    today = datetime.now().date()
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
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
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
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
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
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
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
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
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
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    c.execute("""SELECT substr(completed_at, 12, 5) AS hm, COUNT(*) as cnt
        FROM completions_log WHERE user_id=? AND category=? AND completed_at >= ?
        GROUP BY hm ORDER BY cnt DESC LIMIT 1""", (user_id, category, cutoff))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

# ── v6.1: Admin / Reset functions ─────────────────────
def reset_all_tasks(user_id):
    """Delete all of a user's tasks and reset the autoincrement counter."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM tasks WHERE user_id=?", (user_id,))
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
    """Nuclear reset — wipe ALL of a user's data and reset task IDs."""
    conn = sqlite3.connect(DB_NAME)
    _init_learning_tables(conn)
    c = conn.cursor()
    counts = {}
    for table in ["tasks", "memories", "goals", "habit_log",
                  "completions_log", "snooze_log", "interaction_log"]:
        try:
            c.execute(f"DELETE FROM {table} WHERE user_id=?", (user_id,))
            counts[table] = c.rowcount
        except Exception:
            counts[table] = 0
    # Reset task ID counter if tasks table is globally empty
    c.execute("SELECT COUNT(*) FROM tasks")
    if c.fetchone()[0] == 0:
        for seq_table in ["tasks", "memories", "goals", "habit_log"]:
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