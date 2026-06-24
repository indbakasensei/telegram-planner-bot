import sqlite3
from datetime import datetime

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
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('DELETE FROM memories WHERE user_id=? AND key=?', (user_id, key))
    conn.commit()
    conn.close()

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