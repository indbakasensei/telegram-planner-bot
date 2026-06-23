"""
scheduler.py — Reminder checker, now with recurring task support.
Tests 14, 15, 16 coverage (daily/weekly/monthly recurrence).
"""
import sqlite3
from datetime import datetime
import pytz

DB_NAME = "planner.db"
IST = pytz.timezone("Asia/Kolkata")

def get_due_tasks():
    """Get all tasks due right now — one-time AND recurring."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    now = datetime.now(IST)
    current_date = now.strftime("%Y-%m-%d")
    current_time = now.strftime("%H:%M")
    current_weekday = now.weekday()  # Monday=0 ... Sunday=6
    current_day = now.day

    tasks = []

    # One-time tasks (no recurrence) — exact date+time match
    c.execute('''
        SELECT id, user_id, title, due_date, due_time
        FROM tasks
        WHERE due_date = ? AND due_time = ? AND done = 0
        AND (recurrence_type IS NULL OR recurrence_type = '')
    ''', (current_date, current_time))
    tasks.extend(c.fetchall())

    # Daily recurring — fires every day at due_time
    c.execute('''
        SELECT id, user_id, title, due_date, due_time
        FROM tasks
        WHERE due_time = ? AND done = 0 AND recurrence_type = 'daily'
    ''', (current_time,))
    tasks.extend(c.fetchall())

    # Weekly recurring — fires on matching weekday at due_time
    c.execute('''
        SELECT id, user_id, title, due_date, due_time
        FROM tasks
        WHERE due_time = ? AND done = 0 AND recurrence_type = 'weekly'
        AND recurrence_weekday = ?
    ''', (current_time, current_weekday))
    tasks.extend(c.fetchall())

    # Monthly recurring — fires on matching day-of-month at due_time
    c.execute('''
        SELECT id, user_id, title, due_date, due_time
        FROM tasks
        WHERE due_time = ? AND done = 0 AND recurrence_type = 'monthly'
        AND recurrence_day = ?
    ''', (current_time, current_day))
    tasks.extend(c.fetchall())

    conn.close()

    # De-duplicate by task id (in case a task matches more than one clause)
    seen = set()
    unique_tasks = []
    for t in tasks:
        if t[0] not in seen:
            seen.add(t[0])
            unique_tasks.append(t)

    return unique_tasks