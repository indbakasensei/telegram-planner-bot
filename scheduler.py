"""
scheduler.py — Reminder checker with recurring + snooze + pause support (v1.1).
"""
import sqlite3
from datetime import datetime
import pytz

DB_NAME = "planner.db"
IST = pytz.timezone("Asia/Kolkata")

def get_due_tasks():
    """Tasks due now — respects paused flag and snooze_until."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    now = datetime.now(IST)
    current_date = now.strftime("%Y-%m-%d")
    current_time = now.strftime("%H:%M")
    current_dt = now.strftime("%Y-%m-%d %H:%M")
    weekday = now.weekday()
    day = now.day

    tasks = []

    # Helper: snooze gate — task is eligible only if no active snooze
    snooze_ok = "(snooze_until IS NULL OR snooze_until <= ?)"

    # One-time tasks
    c.execute(f'''SELECT id, user_id, title, due_date, due_time
        FROM tasks
        WHERE due_date=? AND due_time=? AND done=0 AND paused=0
        AND (recurrence_type IS NULL OR recurrence_type='')
        AND {snooze_ok}''', (current_date, current_time, current_dt))
    tasks.extend(c.fetchall())

    # Daily
    c.execute(f'''SELECT id, user_id, title, due_date, due_time
        FROM tasks WHERE due_time=? AND done=0 AND paused=0
        AND recurrence_type='daily' AND {snooze_ok}''',
        (current_time, current_dt))
    tasks.extend(c.fetchall())

    # Weekly
    c.execute(f'''SELECT id, user_id, title, due_date, due_time
        FROM tasks WHERE due_time=? AND done=0 AND paused=0
        AND recurrence_type='weekly' AND recurrence_weekday=? AND {snooze_ok}''',
        (current_time, weekday, current_dt))
    tasks.extend(c.fetchall())

    # Monthly
    c.execute(f'''SELECT id, user_id, title, due_date, due_time
        FROM tasks WHERE due_time=? AND done=0 AND paused=0
        AND recurrence_type='monthly' AND recurrence_day=? AND {snooze_ok}''',
        (current_time, day, current_dt))
    tasks.extend(c.fetchall())

    # Snoozed tasks whose snooze time has now arrived (any time match)
    c.execute('''SELECT id, user_id, title, due_date, due_time
        FROM tasks WHERE done=0 AND paused=0
        AND snooze_until IS NOT NULL AND snooze_until<=?
        AND substr(snooze_until,1,16)=?''', (current_dt, current_dt))
    tasks.extend(c.fetchall())

    conn.close()

    seen = set()
    unique = []
    for t in tasks:
        if t[0] not in seen:
            seen.add(t[0])
            unique.append(t)
    return unique