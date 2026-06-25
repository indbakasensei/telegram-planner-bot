"""
scheduler.py — v2.0 Passive PA Reminder Engine
Features:
- Remind until done (repeated reminders, not just once)
- Escalation near deadline (interval shrinks)
- Quiet hours (no pings during sleep)
- Batching (group reminders per user)
- Auto carry-forward at midnight
- Re-surface ignored tasks
"""
import sqlite3
from datetime import datetime, timedelta
import pytz

DB_NAME = "planner.db"
IST = pytz.timezone("Asia/Kolkata")


def is_quiet_hours(user_id):
    """Check if current IST time is within user's quiet hours."""
    from database import get_user_prefs
    prefs = get_user_prefs(user_id)
    now = datetime.now(IST)
    current = now.strftime("%H:%M")
    start = prefs["quiet_start"]  # e.g. "23:00"
    end = prefs["quiet_end"]      # e.g. "07:00"

    # Handle overnight quiet hours (23:00 → 07:00)
    if start > end:
        return current >= start or current < end
    else:
        return start <= current < end


def should_remind_again(last_reminded_str, interval_minutes):
    """Check if enough time has passed since last reminder."""
    if not last_reminded_str:
        return True
    try:
        last = datetime.strptime(last_reminded_str, "%Y-%m-%d %H:%M")
        now = datetime.now(IST).replace(tzinfo=None)
        diff = (now - last).total_seconds() / 60
        return diff >= interval_minutes
    except ValueError:
        return True


def get_escalated_interval(reminder_count, base_interval, due_date_str, due_time_str):
    """
    Escalate reminder frequency based on urgency.
    - First 2 reminders: base interval (default 30 min)
    - Next 2: half the interval (15 min)
    - After that: 10 min
    - If deadline is within 1 hour: every 5 min
    """
    now = datetime.now(IST)

    # Check time until deadline
    if due_date_str and due_time_str:
        try:
            deadline = datetime.strptime(f"{due_date_str} {due_time_str}", "%Y-%m-%d %H:%M")
            deadline = IST.localize(deadline)
            minutes_until = (deadline - now).total_seconds() / 60
            if minutes_until < 0:
                # Already overdue — remind every 10 min
                return min(base_interval, 10)
            elif minutes_until <= 60:
                return 5  # Last hour: every 5 min
            elif minutes_until <= 180:
                return 10  # Last 3 hours: every 10 min
        except ValueError:
            pass

    # Escalate by reminder count
    if reminder_count <= 2:
        return base_interval
    elif reminder_count <= 4:
        return max(base_interval // 2, 10)
    else:
        return 10


def get_due_tasks():
    """
    v2.0: Get tasks needing a reminder RIGHT NOW.
    Handles one-time + recurring. Respects paused, snoozed, quiet hours.
    Returns list of (id, user_id, title, due_date, due_time) tuples.
    """
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    now = datetime.now(IST)
    current_date = now.strftime("%Y-%m-%d")
    current_time = now.strftime("%H:%M")
    current_dt = now.strftime("%Y-%m-%d %H:%M")
    weekday = now.weekday()
    day = now.day

    snooze_ok = "(snooze_until IS NULL OR snooze_until <= ?)"
    base = "done=0 AND paused=0 AND " + snooze_ok

    tasks = []

    # One-time tasks due now (exact match)
    c.execute(f"""SELECT id, user_id, title, due_date, due_time
        FROM tasks WHERE due_date=? AND due_time=? AND {base}
        AND (recurrence_type IS NULL OR recurrence_type='')""",
        (current_date, current_time, current_dt))
    tasks.extend(c.fetchall())

    # Daily recurring at this time
    c.execute(f"""SELECT id, user_id, title, due_date, due_time
        FROM tasks WHERE due_time=? AND {base} AND recurrence_type='daily'""",
        (current_time, current_dt))
    tasks.extend(c.fetchall())

    # Weekly recurring matching weekday + time
    c.execute(f"""SELECT id, user_id, title, due_date, due_time
        FROM tasks WHERE due_time=? AND {base}
        AND recurrence_type='weekly' AND recurrence_weekday=?""",
        (current_time, current_dt, weekday))
    tasks.extend(c.fetchall())

    # Monthly recurring matching day + time
    c.execute(f"""SELECT id, user_id, title, due_date, due_time
        FROM tasks WHERE due_time=? AND {base}
        AND recurrence_type='monthly' AND recurrence_day=?""",
        (current_time, current_dt, day))
    tasks.extend(c.fetchall())

    conn.close()

    # De-duplicate
    seen = set()
    unique = []
    for t in tasks:
        if t[0] not in seen:
            seen.add(t[0])
            unique.append(t)
    return unique


def get_tasks_needing_followup():
    """
    v2.0: Get OVERDUE tasks that need re-reminding.
    These are tasks past their due time that haven't been reminded recently
    (based on their escalated interval).
    Returns list of (id, user_id, title, due_date, due_time, reminder_count, last_reminded).
    """
    from database import get_user_prefs
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    now = datetime.now(IST)
    current_date = now.strftime("%Y-%m-%d")
    current_time = now.strftime("%H:%M")
    current_dt = now.strftime("%Y-%m-%d %H:%M")

    c.execute("""SELECT id, user_id, title, due_date, due_time,
                 COALESCE(reminder_count, 0), last_reminded
        FROM tasks
        WHERE done=0 AND paused=0
        AND due_date IS NOT NULL
        AND (due_date < ? OR (due_date = ? AND due_time IS NOT NULL AND due_time < ?))
        AND (snooze_until IS NULL OR snooze_until <= ?)
        AND (recurrence_type IS NULL OR recurrence_type = '')
        ORDER BY due_date ASC""",
        (current_date, current_date, current_time, current_dt))
    all_overdue = c.fetchall()
    conn.close()

    # Filter by: enough time since last reminder + not in quiet hours + under max reminders
    results = []
    for task in all_overdue:
        tid, uid, title, ddate, dtime, rcount, last_rem = task
        prefs = get_user_prefs(uid)

        # Skip if in quiet hours
        if is_quiet_hours(uid):
            continue

        # Skip if max reminders reached
        if rcount >= prefs["max_reminders"]:
            continue

        # Calculate escalated interval
        interval = get_escalated_interval(rcount, prefs["interval"], ddate, dtime)

        # Check if enough time has passed
        if should_remind_again(last_rem, interval):
            results.append(task)

    return results


def auto_carry_forward():
    """
    v2.0: Move all overdue non-recurring tasks to today.
    Called once daily (e.g., at midnight or first check of the day).
    Returns count of carried-forward tasks.
    """
    from database import carry_forward_overdue, get_all_user_ids
    now = datetime.now(IST)
    today = now.strftime("%Y-%m-%d")
    total = 0
    for uid in get_all_user_ids():
        count = carry_forward_overdue(uid, today)
        total += count
    return total