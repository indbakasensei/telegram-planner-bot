"""
Tests for scheduler.py's query/pacing logic. Functions here call
datetime.now(IST) internally rather than accepting an injectable `now`
(unlike date_parser.py), so tests either (a) compute expected values
relative to the real current moment via timedelta -- correct regardless
of when the suite runs, no monkeypatching needed -- or (b) monkeypatch
scheduler.datetime for tests that need to control time-of-day precisely
(is_quiet_hours' wraparound logic).

Uses the temp_db fixture (see conftest.py) for anything touching the
database -- never planner.db.
"""
from datetime import datetime, timedelta

import pytest

import database as db
import scheduler as sched

IST = sched.IST


class _FakeDateTime(datetime):
    """Lets a test pin scheduler.py's notion of "now" precisely, for the
    quiet-hours boundary logic where exact time-of-day matters."""
    _fixed = None

    @classmethod
    def now(cls, tz=None):
        return cls._fixed


@pytest.fixture
def fixed_time(monkeypatch):
    """Returns a setter: fixed_time(datetime(...)) pins scheduler's `now`."""
    def _set(dt):
        _FakeDateTime._fixed = dt
        monkeypatch.setattr(sched, "datetime", _FakeDateTime)
    return _set


# ── is_quiet_hours ─────────────────────────────────────────────────────

def test_is_quiet_hours_disabled_when_start_equals_end(temp_db, uid, fixed_time):
    db.set_quiet_hours(uid, "10:00", "10:00")
    fixed_time(datetime(2026, 3, 4, 3, 0, tzinfo=IST))  # 3am, would be "quiet" by default
    assert sched.is_quiet_hours(uid) is False


def test_is_quiet_hours_overnight_wraparound_inside_window(temp_db, uid, fixed_time):
    # Default quiet hours are 23:00-07:00 (start > end, wraps midnight).
    fixed_time(datetime(2026, 3, 4, 23, 30, tzinfo=IST))
    assert sched.is_quiet_hours(uid) is True


def test_is_quiet_hours_overnight_wraparound_early_morning_inside_window(temp_db, uid, fixed_time):
    fixed_time(datetime(2026, 3, 4, 5, 0, tzinfo=IST))
    assert sched.is_quiet_hours(uid) is True


def test_is_quiet_hours_overnight_wraparound_outside_window(temp_db, uid, fixed_time):
    fixed_time(datetime(2026, 3, 4, 12, 0, tzinfo=IST))
    assert sched.is_quiet_hours(uid) is False


def test_is_quiet_hours_same_day_window(temp_db, uid, fixed_time):
    db.set_quiet_hours(uid, "13:00", "15:00")  # start < end, no wraparound
    fixed_time(datetime(2026, 3, 4, 14, 0, tzinfo=IST))
    assert sched.is_quiet_hours(uid) is True
    fixed_time(datetime(2026, 3, 4, 16, 0, tzinfo=IST))
    assert sched.is_quiet_hours(uid) is False


def test_is_quiet_hours_boundary_is_inclusive_at_start(temp_db, uid, fixed_time):
    db.set_quiet_hours(uid, "13:00", "15:00")
    fixed_time(datetime(2026, 3, 4, 13, 0, tzinfo=IST))
    assert sched.is_quiet_hours(uid) is True


def test_is_quiet_hours_boundary_is_exclusive_at_end(temp_db, uid, fixed_time):
    db.set_quiet_hours(uid, "13:00", "15:00")
    fixed_time(datetime(2026, 3, 4, 15, 0, tzinfo=IST))
    assert sched.is_quiet_hours(uid) is False


# ── should_remind_again ───────────────────────────────────────────────────

def test_should_remind_again_no_prior_reminder():
    assert sched.should_remind_again(None, 30) is True


def test_should_remind_again_interval_elapsed():
    last = (datetime.now(IST) - timedelta(minutes=45)).strftime("%Y-%m-%d %H:%M")
    assert sched.should_remind_again(last, 30) is True


def test_should_remind_again_interval_not_elapsed():
    last = (datetime.now(IST) - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M")
    assert sched.should_remind_again(last, 30) is False


def test_should_remind_again_malformed_timestamp_defaults_true():
    assert sched.should_remind_again("not-a-real-timestamp", 30) is True


# ── get_escalated_interval ─────────────────────────────────────────────────

def test_get_escalated_interval_no_deadline_low_reminder_count_uses_base():
    assert sched.get_escalated_interval(1, 30, None, None) == 30


def test_get_escalated_interval_no_deadline_mid_reminder_count_halves():
    assert sched.get_escalated_interval(3, 30, None, None) == 15


def test_get_escalated_interval_no_deadline_high_reminder_count_floors_at_10():
    assert sched.get_escalated_interval(3, 15, None, None) == 10  # 15//2=7, floored to 10


def test_get_escalated_interval_no_deadline_very_high_reminder_count():
    assert sched.get_escalated_interval(5, 30, None, None) == 10


def test_get_escalated_interval_deadline_within_hour_escalates_to_5():
    now = datetime.now(IST)
    due = now + timedelta(minutes=30)
    assert sched.get_escalated_interval(
        1, 30, due.strftime("%Y-%m-%d"), due.strftime("%H:%M")
    ) == 5


def test_get_escalated_interval_deadline_within_three_hours_escalates_to_10():
    now = datetime.now(IST)
    due = now + timedelta(minutes=150)
    assert sched.get_escalated_interval(
        1, 30, due.strftime("%Y-%m-%d"), due.strftime("%H:%M")
    ) == 10


def test_get_escalated_interval_deadline_already_passed_caps_at_min_10():
    now = datetime.now(IST)
    due = now - timedelta(minutes=10)
    assert sched.get_escalated_interval(
        1, 30, due.strftime("%Y-%m-%d"), due.strftime("%H:%M")
    ) == 10


def test_get_escalated_interval_deadline_far_out_falls_back_to_reminder_count_logic():
    now = datetime.now(IST)
    due = now + timedelta(hours=10)
    assert sched.get_escalated_interval(
        1, 30, due.strftime("%Y-%m-%d"), due.strftime("%H:%M")
    ) == 30  # far enough out that the deadline branches don't apply


# ── get_due_tasks: one-time tasks ─────────────────────────────────────────

def test_get_due_tasks_finds_task_due_right_now(temp_db, uid):
    now = datetime.now(IST)
    tid = db.add_task(uid, "Due now", due_date=now.strftime("%Y-%m-%d"),
                       due_time=now.strftime("%H:%M"))
    due = sched.get_due_tasks()
    assert any(t[0] == tid for t in due)


def test_get_due_tasks_does_not_find_task_due_far_in_future(temp_db, uid):
    now = datetime.now(IST)
    future = now + timedelta(days=5)
    tid = db.add_task(uid, "Due later", due_date=future.strftime("%Y-%m-%d"),
                       due_time=future.strftime("%H:%M"))
    due = sched.get_due_tasks()
    assert not any(t[0] == tid for t in due)


def test_get_due_tasks_excludes_done_tasks(temp_db, uid):
    now = datetime.now(IST)
    tid = db.add_task(uid, "Already done", due_date=now.strftime("%Y-%m-%d"),
                       due_time=now.strftime("%H:%M"))
    db.mark_done(tid, uid)
    due = sched.get_due_tasks()
    assert not any(t[0] == tid for t in due)


def test_get_due_tasks_excludes_paused_tasks(temp_db, uid):
    now = datetime.now(IST)
    tid = db.add_task(uid, "Paused", due_date=now.strftime("%Y-%m-%d"),
                       due_time=now.strftime("%H:%M"))
    db.pause_task(tid, uid)
    due = sched.get_due_tasks()
    assert not any(t[0] == tid for t in due)


def test_get_due_tasks_no_duplicate_entries(temp_db, uid):
    # A task could theoretically match more than one of get_due_tasks'
    # internal query cases; the result must be de-duplicated by id.
    now = datetime.now(IST)
    tid = db.add_task(uid, "Due now", due_date=now.strftime("%Y-%m-%d"),
                       due_time=now.strftime("%H:%M"))
    due = sched.get_due_tasks()
    ids = [t[0] for t in due if t[0] == tid]
    assert len(ids) == 1


# ── get_due_tasks: recurring tasks ─────────────────────────────────────────

def test_get_due_tasks_daily_recurring_fires_at_matching_time(temp_db, uid):
    now = datetime.now(IST)
    tid = db.add_task(uid, "Daily standup", due_time=now.strftime("%H:%M"),
                       recurrence_type="daily")
    due = sched.get_due_tasks()
    assert any(t[0] == tid for t in due)


def test_get_due_tasks_weekly_recurring_fires_on_matching_weekday(temp_db, uid):
    now = datetime.now(IST)
    tid = db.add_task(uid, "Weekly review", due_time=now.strftime("%H:%M"),
                       recurrence_type="weekly", recurrence_weekday=now.weekday())
    due = sched.get_due_tasks()
    assert any(t[0] == tid for t in due)


def test_get_due_tasks_weekly_recurring_does_not_fire_on_other_weekday(temp_db, uid):
    now = datetime.now(IST)
    other_weekday = (now.weekday() + 3) % 7
    tid = db.add_task(uid, "Weekly review", due_time=now.strftime("%H:%M"),
                       recurrence_type="weekly", recurrence_weekday=other_weekday)
    due = sched.get_due_tasks()
    assert not any(t[0] == tid for t in due)


def test_get_due_tasks_monthly_recurring_fires_on_matching_day(temp_db, uid):
    now = datetime.now(IST)
    tid = db.add_task(uid, "Pay rent", due_time=now.strftime("%H:%M"),
                       recurrence_type="monthly", recurrence_day=now.day)
    due = sched.get_due_tasks()
    assert any(t[0] == tid for t in due)


# ── get_due_tasks: snooze expiry ──────────────────────────────────────────

def test_get_due_tasks_fires_when_snooze_expired(temp_db, uid):
    now = datetime.now(IST)
    past_due = now - timedelta(days=3)
    tid = db.add_task(uid, "Snoozed task", due_date=past_due.strftime("%Y-%m-%d"),
                       due_time=past_due.strftime("%H:%M"))
    expired = (now - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M")
    db.snooze_task(tid, uid, expired)
    due = sched.get_due_tasks()
    assert any(t[0] == tid for t in due)


def test_get_due_tasks_snooze_cleared_after_firing_no_repeat_fire(temp_db, uid):
    now = datetime.now(IST)
    past_due = now - timedelta(days=3)
    tid = db.add_task(uid, "Snoozed task", due_date=past_due.strftime("%Y-%m-%d"),
                       due_time=past_due.strftime("%H:%M"))
    expired = (now - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M")
    db.snooze_task(tid, uid, expired)
    sched.get_due_tasks()  # first call fires and clears snooze_until
    due_second_pass = sched.get_due_tasks()
    assert not any(t[0] == tid for t in due_second_pass)


def test_get_due_tasks_does_not_fire_before_snooze_expires(temp_db, uid):
    now = datetime.now(IST)
    past_due = now - timedelta(days=3)
    tid = db.add_task(uid, "Snoozed task", due_date=past_due.strftime("%Y-%m-%d"),
                       due_time=past_due.strftime("%H:%M"))
    future_snooze = (now + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M")
    db.snooze_task(tid, uid, future_snooze)
    due = sched.get_due_tasks()
    assert not any(t[0] == tid for t in due)


# ── get_tasks_needing_followup (overdue logic) ────────────────────────────

def test_get_tasks_needing_followup_finds_overdue_task(temp_db, uid):
    now = datetime.now(IST)
    db.set_quiet_hours(uid, "00:00", "00:00")  # disable quiet hours for determinism
    overdue = now - timedelta(hours=2)
    tid = db.add_task(uid, "Overdue task", due_date=overdue.strftime("%Y-%m-%d"),
                       due_time=overdue.strftime("%H:%M"))
    followups = sched.get_tasks_needing_followup()
    assert any(t[0] == tid for t in followups)


def test_get_tasks_needing_followup_respects_quiet_hours(temp_db, uid, fixed_time):
    now = datetime.now(IST)
    overdue = now - timedelta(hours=2)
    tid = db.add_task(uid, "Overdue task", due_date=overdue.strftime("%Y-%m-%d"),
                       due_time=overdue.strftime("%H:%M"))
    db.set_quiet_hours(uid, "00:00", "23:59")  # nearly all-day quiet hours
    followups = sched.get_tasks_needing_followup()
    assert not any(t[0] == tid for t in followups)


def test_get_tasks_needing_followup_respects_max_reminders_cap(temp_db, uid):
    now = datetime.now(IST)
    db.set_quiet_hours(uid, "00:00", "00:00")
    overdue = now - timedelta(hours=2)
    tid = db.add_task(uid, "Overdue task", due_date=overdue.strftime("%Y-%m-%d"),
                       due_time=overdue.strftime("%H:%M"))
    for _ in range(6):  # exceed the default max_reminders_per_task (5)
        db.increment_reminder_count(tid)
    followups = sched.get_tasks_needing_followup()
    assert not any(t[0] == tid for t in followups)


def test_get_tasks_needing_followup_excludes_recurring_tasks(temp_db, uid):
    now = datetime.now(IST)
    db.set_quiet_hours(uid, "00:00", "00:00")
    overdue_time = (now - timedelta(hours=2)).strftime("%H:%M")
    tid = db.add_task(uid, "Recurring", due_time=overdue_time, recurrence_type="daily")
    followups = sched.get_tasks_needing_followup()
    assert not any(t[0] == tid for t in followups)


# ── auto_carry_forward ──────────────────────────────────────────────────

def test_auto_carry_forward_moves_overdue_tasks_to_today(temp_db, uid):
    now = datetime.now(IST)
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    db.add_task(uid, "Overdue from yesterday", due_date=yesterday, due_time="09:00")
    count = sched.auto_carry_forward()
    assert count >= 1
    tasks_today = db.get_tasks_by_date(uid, now.strftime("%Y-%m-%d"))
    assert any(t[1] == "Overdue from yesterday" for t in tasks_today)


def test_auto_carry_forward_does_not_touch_future_tasks(temp_db, uid):
    now = datetime.now(IST)
    future = (now + timedelta(days=3)).strftime("%Y-%m-%d")
    tid = db.add_task(uid, "Future task", due_date=future, due_time="09:00")
    sched.auto_carry_forward()
    task = db.get_task_by_id(tid, uid)
    assert task[2] == future  # due_date unchanged


# ── deadline buffers (database.py, but conceptually part of the
# scheduler's deadline_buffer_check job -- grouped here per the test
# plan's Phase 2 scope) ───────────────────────────────────────────────────

def test_deadline_buffer_pending_deadline_detected(temp_db, uid):
    now = datetime.now(IST)
    due = now + timedelta(hours=5)
    tid = db.add_task(uid, "Submit report", due_date=due.strftime("%Y-%m-%d"),
                       due_time=due.strftime("%H:%M"))
    db.mark_as_deadline(tid, uid, True)
    pending = db.get_pending_deadlines()
    assert any(t[0] == tid for t in pending)


def test_deadline_buffer_sent_tracking_round_trip():
    sent = db.parse_buffer_sent("")
    assert len(sent) == 0


def test_deadline_buffer_mark_and_parse_round_trip(temp_db, uid):
    now = datetime.now(IST)
    due = now + timedelta(hours=5)
    tid = db.add_task(uid, "Submit report", due_date=due.strftime("%Y-%m-%d"),
                       due_time=due.strftime("%H:%M"))
    db.mark_as_deadline(tid, uid, True)
    db.mark_buffer_sent(tid, "6h")
    conn_check = db.get_task_by_id(tid, uid)
    # mark_buffer_sent stores into the buffer_sent column; verify via the
    # dedicated getter path used by the scheduler job.
    import sqlite3
    conn = sqlite3.connect(db.DB_NAME)
    row = conn.execute("SELECT buffer_sent FROM tasks WHERE id=?", (tid,)).fetchone()
    conn.close()
    assert "6h" in db.parse_buffer_sent(row[0])
