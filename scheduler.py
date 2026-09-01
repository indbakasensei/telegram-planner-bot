import os
"""
scheduler.py — v2.1 Fixed Reminder Engine

Bugs fixed:
- BUG 1: Snooze now re-fires (snooze_until checked as separate query)
- BUG 2: Missed reminders caught (due_time <= now + last_reminded guard)
- BUG 4: <= comparison for snooze_until instead of exact match
- BUG 5: last_reminded guard prevents every-minute spam
"""
import sqlite3
from datetime import datetime, timedelta
import pytz

DB_NAME = os.getenv("DB_NAME", "planner.db")
IST = pytz.timezone("Asia/Kolkata")

# How many minutes back we look for missed reminders (catches restarts/busy bot)
LOOKBACK_MINUTES = 5


def is_quiet_hours(user_id):
    from database import get_user_prefs
    prefs = get_user_prefs(user_id)
    now = datetime.now(IST)
    current = now.strftime("%H:%M")
    start = prefs["quiet_start"]
    end = prefs["quiet_end"]
    if start == end:
        return False  # quiet hours disabled
    if start > end:
        return current >= start or current < end
    return start <= current < end


def should_remind_again(last_reminded_str, interval_minutes):
    if not last_reminded_str:
        return True
    try:
        last = IST.localize(datetime.strptime(last_reminded_str, "%Y-%m-%d %H:%M"))
        diff = (datetime.now(IST) - last).total_seconds() / 60
        return diff >= interval_minutes
    except ValueError:
        return True


def get_escalated_interval(reminder_count, base_interval, due_date_str, due_time_str):
    now = datetime.now(IST)
    if due_date_str and due_time_str:
        try:
            deadline_naive = datetime.strptime(
                f"{due_date_str} {due_time_str}", "%Y-%m-%d %H:%M"
            )
            deadline = IST.localize(deadline_naive)
            minutes_until = (deadline - now).total_seconds() / 60
            if minutes_until < 0:
                return min(base_interval, 10)
            elif minutes_until <= 60:
                return 5
            elif minutes_until <= 180:
                return 10
        except ValueError:
            pass
    if reminder_count <= 2:
        return base_interval
    elif reminder_count <= 4:
        return max(base_interval // 2, 10)
    return 10


def get_due_tasks():
    """
    v2.1: Fixed reminder query.

    Three cases that should fire a reminder:
    1. Task whose due_time is within the last LOOKBACK_MINUTES (catches missed minutes)
       AND hasn't been reminded yet today
    2. Recurring tasks matching current weekday/day + time window
    3. Snoozed tasks whose snooze_until has now expired (THE BUG FIX)
    """
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    now = datetime.now(IST)
    current_date = now.strftime("%Y-%m-%d")
    current_dt = now.strftime("%Y-%m-%d %H:%M")
    # Lookback window — catch reminders we missed
    lookback_dt = (now - timedelta(minutes=LOOKBACK_MINUTES)).strftime("%Y-%m-%d %H:%M")
    weekday = now.weekday()
    day = now.day

    tasks = []

    # ── Case 1: One-time tasks due within lookback window ──
    # Guard: last_reminded is NULL or last_reminded < lookback window
    # (prevents re-firing every minute)
    c.execute("""SELECT id, user_id, title, due_date, due_time
        FROM tasks
        WHERE due_date=? AND due_time BETWEEN ? AND ?
        AND done=0 AND paused=0
        AND (recurrence_type IS NULL OR recurrence_type='')
        AND (snooze_until IS NULL OR snooze_until <= ?)
        AND (last_reminded IS NULL
             OR substr(last_reminded,1,10) < ?)""",
        (current_date,
         lookback_dt[-5:],   # HH:MM of lookback
         current_dt[-5:],    # HH:MM of now
         current_dt,
         current_date))      # only remind once per day for one-time tasks
    tasks.extend(c.fetchall())

    # ── Case 2: Daily recurring ──
    current_time_hhmm = now.strftime("%H:%M")
    lookback_time_hhmm = (now - timedelta(minutes=LOOKBACK_MINUTES)).strftime("%H:%M")
    c.execute("""SELECT id, user_id, title, due_date, due_time
        FROM tasks
        WHERE due_time BETWEEN ? AND ?
        AND done=0 AND paused=0
        AND recurrence_type='daily'
        AND (snooze_until IS NULL OR snooze_until <= ?)
        AND (last_reminded IS NULL
             OR substr(last_reminded,1,16) < ?)""",
        (lookback_time_hhmm, current_time_hhmm, current_dt,
         (now - timedelta(hours=20)).strftime("%Y-%m-%d %H:%M")))
    tasks.extend(c.fetchall())

    # ── Case 3: Weekly recurring ──
    c.execute("""SELECT id, user_id, title, due_date, due_time
        FROM tasks
        WHERE due_time BETWEEN ? AND ?
        AND done=0 AND paused=0
        AND recurrence_type='weekly' AND recurrence_weekday=?
        AND (snooze_until IS NULL OR snooze_until <= ?)
        AND (last_reminded IS NULL
             OR substr(last_reminded,1,16) < ?)""",
        (lookback_time_hhmm, current_time_hhmm, weekday, current_dt,
         (now - timedelta(hours=20)).strftime("%Y-%m-%d %H:%M")))
    tasks.extend(c.fetchall())

    # ── Case 4: Monthly recurring ──
    c.execute("""SELECT id, user_id, title, due_date, due_time
        FROM tasks
        WHERE due_time BETWEEN ? AND ?
        AND done=0 AND paused=0
        AND recurrence_type='monthly' AND recurrence_day=?
        AND (snooze_until IS NULL OR snooze_until <= ?)
        AND (last_reminded IS NULL
             OR substr(last_reminded,1,16) < ?)""",
        (lookback_time_hhmm, current_time_hhmm, day, current_dt,
         (now - timedelta(hours=20)).strftime("%Y-%m-%d %H:%M")))
    tasks.extend(c.fetchall())

    # ── Case 5 (BUG 1 + 19 FIX): Snoozed tasks whose snooze expired ──
    # When snooze_until <= now, fire the reminder regardless of last_reminded.
    # The "fire once" guard is handled by clearing snooze_until after firing
    # (see UPDATE below). The previous version's last_reminded guard was wrong
    # because last_reminded gets set on the original reminder, which can be AFTER
    # snooze_until was set (user snoozes immediately after being reminded).
    c.execute("""SELECT id, user_id, title, due_date, due_time
        FROM tasks
        WHERE done=0 AND paused=0
        AND snooze_until IS NOT NULL
        AND snooze_until <= ?""",
        (current_dt,))
    snooze_tasks = c.fetchall()
    # After firing, clear snooze_until so it doesn't re-fire every minute
    for t in snooze_tasks:
        c.execute("UPDATE tasks SET snooze_until=NULL WHERE id=?", (t[0],))
    if snooze_tasks:
        conn.commit()
    tasks.extend(snooze_tasks)

    conn.close()

    # De-duplicate by task id
    seen = set()
    unique = []
    for t in tasks:
        if t[0] not in seen:
            seen.add(t[0])
            unique.append(t)
    return unique


def get_tasks_needing_followup():
    """Overdue tasks that need re-reminding (unchanged from v2.0)."""
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

    results = []
    for task in all_overdue:
        tid, uid, title, ddate, dtime, rcount, last_rem = task
        if is_quiet_hours(uid):
            continue
        prefs = get_user_prefs(uid)
        if rcount >= prefs["max_reminders"]:
            continue
        interval = get_escalated_interval(rcount, prefs["interval"], ddate, dtime)
        if should_remind_again(last_rem, interval):
            results.append(task)
    return results


def auto_carry_forward():
    from database import carry_forward_overdue, get_all_user_ids
    now = datetime.now(IST)
    today = now.strftime("%Y-%m-%d")
    total = 0
    for uid in get_all_user_ids():
        count = carry_forward_overdue(uid, today)
        total += count
    return total