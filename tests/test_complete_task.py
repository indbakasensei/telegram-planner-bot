"""
Tests for core/actions/complete_task.py -- the v14.6 Offline Task
Completion (BAKA's fourth Offline write operation).

Includes Behavioral Equivalence tests (Legacy's mark_done()+log_completion()
sequence, called the way main.py's done_task() does, vs. Offline's
execute() -- comparing final database state including the learning-log
side effects) and all 8 failure scenarios this sprint's brief named:
already completed, task missing, invalid ID, database exception,
database locked, duplicate completion, concurrent completion, invalid
state (a habit -- Legacy's streak logic owns those, Offline must branch
away untouched).
"""
import sqlite3
import time
import tracemalloc
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

import database as db
from core.actions import complete_task
from core.intent.intent_types import Intent
from core.offline.engine import OfflineEngine
from core.offline.request_context import RequestContext
from core.storage import Storage

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 3, 4, 10, 30, tzinfo=IST)


def ctx(text, uid, task_id=None):
    entities = {"task_id": task_id} if task_id is not None else {}
    return RequestContext(user_id=uid, text=text, intent=Intent.EDIT_TASK,
                           entities=entities, now=NOW)


@pytest.fixture
def engine():
    return OfflineEngine(Storage())


# ── match_entry_command ───────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected_id", [
    ("done 5", 5),
    ("DONE 5", 5),
    ("complete task 3", 3),
    ("finish task 2", 2),
    ("mark done 7", 7),
    ("done 5 please", 5),
])
def test_match_entry_command_recognizes_all_legacy_prefixes(text, expected_id):
    assert complete_task.match_entry_command(text) == expected_id


@pytest.mark.parametrize("text", [
    "done",  # bare -- Legacy's pick-list UX, stays Legacy-only
    "mark task complete",  # no numeric id
    "check off task",  # not a Legacy prefix either
    "complete 5",  # "complete " alone isn't in Legacy's prefix group
    "delete 5",
    "random text",
])
def test_match_entry_command_rejects_unsupported_text(text):
    assert complete_task.match_entry_command(text) is None


# ── _compute_delay_minutes ────────────────────────────────────────────────

def test_delay_zero_when_no_due_time():
    assert complete_task._compute_delay_minutes(None, NOW) == 0


def test_delay_computed_when_late():
    # Due 09:00, completed 10:30 -> 90 minutes late.
    assert complete_task._compute_delay_minutes("09:00", NOW) == 90


def test_delay_clamped_to_zero_when_early():
    # Due 15:00, completed 10:30 -> early, clamps to 0 (Legacy's max(0, ...)).
    assert complete_task._compute_delay_minutes("15:00", NOW) == 0


def test_delay_zero_on_malformed_time():
    assert complete_task._compute_delay_minutes("garbage", NOW) == 0


# ── execute(): the happy path and its side effects ───────────────────────

def test_execute_marks_done(temp_db, uid):
    tid = Storage().tasks.add(uid, "Buy milk")
    result = complete_task.execute(tid, uid, Storage(), NOW)
    assert result.success is True
    assert "Done!" in result.message and "Buy milk" in result.message
    assert Storage().tasks.get_all(uid) == []
    done = Storage().tasks.get_all(uid, done=1)
    assert len(done) == 1 and done[0][0] == tid


def test_execute_writes_learning_logs(temp_db, uid):
    tid = Storage().tasks.add(uid, "Report", due_time="09:00")
    complete_task.execute(tid, uid, Storage(), NOW)
    conn = sqlite3.connect(temp_db)
    completions = conn.execute(
        "SELECT user_id, task_id, title, category, scheduled_time, delay_minutes "
        "FROM completions_log").fetchall()
    interactions = conn.execute(
        "SELECT user_id, action FROM interaction_log").fetchall()
    conn.close()
    assert completions == [(uid, tid, "Report", "General", "09:00", 90)]
    assert (uid, "task_done") in interactions


def test_execute_requires_now(temp_db, uid):
    tid = Storage().tasks.add(uid, "Task")
    result = complete_task.execute(tid, uid, Storage(), None)
    assert result.success is False
    assert "missing_now" in result.warnings
    # Not marked done -- the guard fires before mark_done().
    assert len(Storage().tasks.get_all(uid)) == 1


# ── Failure scenarios (all 8 from the brief) ─────────────────────────────

def test_failure_already_completed_matches_legacy(temp_db, uid):
    # Verified Legacy behavior: get_task_by_id() has no done-flag filter
    # and mark_done()'s UPDATE is idempotent, so re-completing an
    # already-done task succeeds silently in Legacy. Offline matches --
    # not "fixed" -- per behavioral equivalence.
    tid = Storage().tasks.add(uid, "Task")
    complete_task.execute(tid, uid, Storage(), NOW)
    again = complete_task.execute(tid, uid, Storage(), NOW)
    assert again.success is True
    assert len(Storage().tasks.get_all(uid, done=1)) == 1


def test_failure_task_missing(temp_db, uid):
    result = complete_task.execute(424242, uid, Storage(), NOW)
    assert result.success is False
    assert "task_not_found" in result.warnings


@pytest.mark.parametrize("bad_id", [0, -1, 999999999])
def test_failure_invalid_id(temp_db, uid, bad_id):
    result = complete_task.execute(bad_id, uid, Storage(), NOW)
    assert result.success is False
    assert "task_not_found" in result.warnings


class _FakeTaskStorageMarkDoneRaises:
    def __init__(self, exc):
        self._exc = exc

    def get_by_id(self, *a, **k):
        return (1, "Task", None, "09:00", "General", "medium", None)

    def mark_done(self, *a, **k):
        raise self._exc


class _FakeHabitStorageNotHabit:
    def is_habit(self, *a, **k):
        return False


class _FakeStorage:
    def __init__(self, tasks):
        self.tasks = tasks
        self.habits = _FakeHabitStorageNotHabit()


def test_failure_database_exception_via_engine(uid):
    engine = OfflineEngine(_FakeStorage(_FakeTaskStorageMarkDoneRaises(RuntimeError("boom"))))
    result = engine.execute(ctx("done 1", uid, task_id=1))
    assert result.success is False
    assert any(w.startswith("action_exception:") for w in result.warnings)


def test_failure_database_locked_via_engine(uid):
    engine = OfflineEngine(_FakeStorage(
        _FakeTaskStorageMarkDoneRaises(sqlite3.OperationalError("database is locked"))))
    result = engine.execute(ctx("done 1", uid, task_id=1))
    assert result.success is False
    assert any(w.startswith("action_exception:") for w in result.warnings)


def test_failure_duplicate_completion(temp_db, uid):
    # Same mechanism as already-completed -- named separately per the
    # brief's list. Additionally verifies the learning log DOES get a
    # second row (Legacy re-logs too: done_task() has no already-done
    # guard around log_completion()).
    tid = Storage().tasks.add(uid, "Task", due_time="09:00")
    complete_task.execute(tid, uid, Storage(), NOW)
    complete_task.execute(tid, uid, Storage(), NOW)
    conn = sqlite3.connect(temp_db)
    count = conn.execute("SELECT COUNT(*) FROM completions_log").fetchone()[0]
    conn.close()
    assert count == 2  # matches Legacy's real re-log behavior, documented


def test_failure_concurrent_completion(temp_db, uid):
    # A second path deletes the task between locate and a later attempt --
    # the next execute() finds nothing and fails gracefully.
    tid = Storage().tasks.add(uid, "Task")
    complete_task.execute(tid, uid, Storage(), NOW)
    Storage().tasks.delete(tid, uid)
    result = complete_task.execute(tid, uid, Storage(), NOW)
    assert result.success is False
    assert "task_not_found" in result.warnings


def test_failure_invalid_state_habit_branches_away(temp_db, uid):
    # "Invalid state" for this action: the task is a habit -- Legacy's
    # streak logic (log_habit_completion(), NOT mark_done()) owns those.
    # Offline must return habit_not_supported so main.py falls through
    # to Legacy untouched, and must NOT have marked anything done.
    hid = Storage().habits.add(uid, "Meditate")
    result = complete_task.execute(hid, uid, Storage(), NOW)
    assert result.success is False
    assert "habit_not_supported" in result.warnings
    assert Storage().tasks.get_all(uid, done=1) == []


def test_learning_log_failure_is_swallowed_like_legacy(temp_db, uid):
    # Legacy wraps log_completion()/log_interaction() in a bare
    # try/except: pass -- a learning-log failure must not un-succeed the
    # completion. Offline replicates that exactly.
    class _RaisingLearning:
        def log_completion(self, *a, **k):
            raise RuntimeError("learning tables corrupted")

        def log_interaction(self, *a, **k):
            raise RuntimeError("unreachable")

    storage = Storage()
    tid = storage.tasks.add(uid, "Task")
    storage.learning = _RaisingLearning()
    result = complete_task.execute(tid, uid, storage, NOW)
    assert result.success is True
    assert len(Storage().tasks.get_all(uid, done=1)) == 1


# ── OfflineEngine dispatch ───────────────────────────────────────────────

def test_engine_dispatches_done_to_complete(temp_db, uid, engine):
    tid = Storage().tasks.add(uid, "Task")
    result = engine.execute(ctx(f"done {tid}", uid, task_id=tid))
    assert result.success is True
    assert result.metadata.get("completed_title") == "Task"


def test_engine_dispatch_complete_before_edit_no_crosstalk(temp_db, uid, engine):
    # "edit task N" must still reach update_task, not complete_task --
    # the two entry regexes are disjoint; this proves it.
    tid = Storage().tasks.add(uid, "Task")
    result = engine.execute(ctx(f"edit task {tid}", uid))
    assert result.success is True
    assert result.metadata.get("start_editing") is True
    assert Storage().tasks.get_all(uid, done=1) == []  # nothing completed


def test_engine_unknown_intent_with_done_phrase_still_dispatches(temp_db, uid, engine):
    tid = Storage().tasks.add(uid, "Task")
    result = engine.execute(RequestContext(
        user_id=uid, text=f"mark done {tid}", intent=Intent.UNKNOWN,
        entities={}, now=NOW,
    ))
    assert result.success is True


# ── Behavioral Equivalence: Legacy vs Offline, compare final DB state ───

def _legacy_complete(task_id, uid_, now):
    """Replicates main.py's done_task() non-habit branch verbatim
    (mark_done + log_completion + log_interaction, main.py:459-476)."""
    task = db.get_task_by_id(task_id, uid_)
    db.mark_done(task_id, uid_)
    scheduled = task[3] or "00:00"
    delay = 0
    if task[3]:
        try:
            sh, sm = map(int, task[3].split(":"))
            scheduled_dt = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
            delay = max(0, int((now - scheduled_dt).total_seconds() / 60))
        except (ValueError, AttributeError):
            pass
    db.log_completion(uid_, task_id, task[1], task[4] or "General",
                       scheduled, now.strftime("%Y-%m-%d %H:%M:%S"), delay)
    db.log_interaction(uid_, "task_done")


def test_equivalence_final_database_state_matches(temp_db, uid):
    legacy_uid, offline_uid = uid, uid + 1
    legacy_id = db.add_task(legacy_uid, "Report", None, "09:00", "Work", "high",
                             None, None, None)
    offline_id = Storage().tasks.add(offline_uid, "Report", due_time="09:00",
                                      category="Work", priority="high")

    _legacy_complete(legacy_id, legacy_uid, NOW)
    complete_task.execute(offline_id, offline_uid, Storage(), NOW)

    legacy_row = db.get_task_by_id(legacy_id, legacy_uid)
    offline_row = db.get_task_by_id(offline_id, offline_uid)
    # Same columns, same values (ids/user_ids necessarily differ).
    assert legacy_row[1:] == offline_row[1:]
    # Done flag set identically.
    assert len(db.get_tasks(legacy_uid, done=1)) == 1
    assert len(db.get_tasks(offline_uid, done=1)) == 1

    # Learning-log rows identical field-for-field (bar user/task ids).
    conn = sqlite3.connect(temp_db)
    rows = conn.execute(
        "SELECT user_id, title, category, scheduled_time, completed_at, delay_minutes "
        "FROM completions_log ORDER BY user_id").fetchall()
    conn.close()
    assert len(rows) == 2
    assert rows[0][1:] == rows[1][1:]


def test_equivalence_recurring_task_completion(temp_db, uid):
    # mark_done() has no recurrence special-casing (plain UPDATE done=1,
    # verified by reading it) and both paths call the same function --
    # a completed recurring task ends up done=1 identically.
    legacy_id = db.add_task(uid, "Standup", None, "10:00", "Work", "medium",
                             "daily", None, None)
    offline_uid = uid + 1
    offline_id = Storage().tasks.add(offline_uid, "Standup", due_time="10:00",
                                      category="Work", recurrence_type="daily")
    _legacy_complete(legacy_id, uid, NOW)
    complete_task.execute(offline_id, offline_uid, Storage(), NOW)
    assert db.get_tasks(uid, done=1)[0][6] == "daily"
    assert db.get_tasks(offline_uid, done=1)[0][6] == "daily"


def test_equivalence_no_undo_in_either_path():
    # Reversibility Review (this sprint's explicit section): verified by
    # grep that Legacy has no undone/uncomplete/undo command anywhere in
    # main.py. Offline adds none either -- documented, not invented.
    assert not hasattr(complete_task, "undo")
    assert not hasattr(complete_task, "uncomplete")


# ── Performance (measurement only) ────────────────────────────────────────

def test_performance_benchmark_legacy_vs_offline_complete(temp_db, uid):
    storage = Storage()
    n = 100
    legacy_ids = [db.add_task(uid, f"L{i}", None, "09:00", "General", "medium",
                               None, None, None) for i in range(n)]
    start = time.perf_counter()
    for tid in legacy_ids:
        _legacy_complete(tid, uid, NOW)
    legacy_ms = (time.perf_counter() - start) * 1000 / n

    offline_uid = uid + 1
    offline_ids = [storage.tasks.add(offline_uid, f"O{i}", due_time="09:00")
                   for i in range(n)]
    start = time.perf_counter()
    for tid in offline_ids:
        complete_task.execute(tid, offline_uid, storage, NOW)
    offline_ms = (time.perf_counter() - start) * 1000 / n

    # Loose sanity bounds only -- measurement, not optimization.
    assert legacy_ms < 50
    assert offline_ms < 50


def test_performance_memory_offline_complete(temp_db, uid):
    storage = Storage()
    ids = [storage.tasks.add(uid, f"Task {i}") for i in range(50)]
    tracemalloc.start()
    before = tracemalloc.take_snapshot()
    for tid in ids:
        complete_task.execute(tid, uid, storage, NOW)
    after = tracemalloc.take_snapshot()
    tracemalloc.stop()
    total_growth = sum(s.size_diff for s in after.compare_to(before, "lineno"))
    assert total_growth < 5_000_000
