"""
Tests for core/actions/lifecycle_task.py -- the v14.7 Task lifecycle
operations (pause/resume/snooze/stop-reminders/carry-forward/paused-view),
the final Task-domain migration stage.

Scheduler-state equivalence note: `paused` and `snooze_until` ARE the
scheduler's state (scheduler.py's get_due_tasks() filters on them), so
the raw-column comparisons below are the scheduler-state comparison this
sprint's brief requires -- there is no separate scheduler store to diff.
"""
import sqlite3
import time
import tracemalloc
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

import database as db
from core.actions import lifecycle_task
from core.intent.intent_types import Intent
from core.offline.engine import OfflineEngine
from core.offline.request_context import RequestContext
from core.storage import Storage

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 3, 4, 10, 30, tzinfo=IST)


def ctx(text, uid, intent=Intent.EDIT_TASK):
    return RequestContext(user_id=uid, text=text, intent=intent, entities={}, now=NOW)


def cols(db_path, task_id):
    """(paused, snooze_until, due_time, due_date) -- the scheduler-state
    columns get_task_by_id() doesn't return."""
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT paused, snooze_until, due_time, due_date FROM tasks WHERE id=?",
        (task_id,)).fetchone()
    conn.close()
    return row


@pytest.fixture
def engine():
    return OfflineEngine(Storage())


# ── match_entry ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,op,args", [
    ("pause 5", "pause", {"task_id": 5}),
    ("PAUSE 5", "pause", {"task_id": 5}),
    ("resume 3", "resume", {"task_id": 3}),
    ("snooze 5 45", "snooze", {"task_id": 5, "minutes": 45}),
    ("stopreminder 7", "stop_reminders", {"task_id": 7}),
    ("stop reminder 7", "stop_reminders", {"task_id": 7}),
    ("stop reminders for 7", "stop_reminders", {"task_id": 7}),
    ("carryforward", "carry_forward", {}),
    ("carry forward", "carry_forward", {}),
    ("move overdue to today", "carry_forward", {}),
])
def test_match_entry_recognizes_all_legacy_phrases(text, op, args):
    assert lifecycle_task.match_entry(text) == (op, args)


@pytest.mark.parametrize("text", [
    "pause",        # id-less -- Legacy's usage reply stays Legacy's
    "resume",
    "snooze 5",     # missing minutes -- Legacy's usage reply
    "stopreminder",
    "paused",       # QUERY_TASK view, not an EDIT_TASK entry
    "done 5",       # completion's, not lifecycle's
    "edit task 5",  # update's
    "random text",
])
def test_match_entry_rejects_non_lifecycle_text(text):
    assert lifecycle_task.match_entry(text) is None


# ── Pause / Resume ───────────────────────────────────────────────────────

def test_pause_sets_paused_flag(temp_db, uid, engine):
    tid = Storage().tasks.add(uid, "Task")
    result = engine.execute(ctx(f"pause {tid}", uid))
    assert result.success is True
    assert "Paused" in result.message
    assert cols(temp_db, tid)[0] == 1


def test_resume_clears_paused_flag(temp_db, uid, engine):
    tid = Storage().tasks.add(uid, "Task")
    engine.execute(ctx(f"pause {tid}", uid))
    result = engine.execute(ctx(f"resume {tid}", uid))
    assert result.success is True
    assert cols(temp_db, tid)[0] == 0


def test_failure_already_paused_is_idempotent(temp_db, uid, engine):
    # Legacy's pause_task() is an idempotent UPDATE with no already-paused
    # guard -- re-pausing succeeds silently. Matched, not "fixed".
    tid = Storage().tasks.add(uid, "Task")
    engine.execute(ctx(f"pause {tid}", uid))
    again = engine.execute(ctx(f"pause {tid}", uid))
    assert again.success is True
    assert cols(temp_db, tid)[0] == 1


def test_failure_already_resumed_is_idempotent(temp_db, uid, engine):
    tid = Storage().tasks.add(uid, "Task")
    result = engine.execute(ctx(f"resume {tid}", uid))  # never paused
    assert result.success is True
    assert cols(temp_db, tid)[0] == 0


def test_archive_restore_hide_unhide_do_not_exist():
    # Phase 0 verified these operations don't exist anywhere in Legacy
    # (zero grep matches in main.py) -- per the brief: documented, not
    # invented. This test pins that finding.
    for op in ("archive", "restore", "hide", "unhide", "unsnooze"):
        assert lifecycle_task.match_entry(f"{op} 5") is None
        assert not hasattr(lifecycle_task, op)


# ── Snooze ────────────────────────────────────────────────────────────────

def test_snooze_sets_snooze_until_and_logs(temp_db, uid, engine):
    tid = Storage().tasks.add(uid, "Task", due_time="09:00", category="Work")
    result = engine.execute(ctx(f"snooze {tid} 45", uid))
    assert result.success is True
    assert cols(temp_db, tid)[1] == "2026-03-04 11:15"  # NOW + 45m
    assert "11:15" in result.message
    conn = sqlite3.connect(temp_db)
    snoozes = conn.execute(
        "SELECT user_id, task_id, title, category, snooze_minutes FROM snooze_log").fetchall()
    interactions = conn.execute(
        "SELECT action FROM interaction_log WHERE action='task_snooze'").fetchall()
    conn.close()
    assert snoozes == [(uid, tid, "Task", "Work", 45)]
    assert len(interactions) == 1


def test_snooze_label_formats(temp_db, uid, engine):
    tid = Storage().tasks.add(uid, "Task")
    r1 = engine.execute(ctx(f"snooze {tid} 90", uid))
    assert "1h 30m" in r1.message  # mirrors Legacy's "Xh Ym" label
    r2 = engine.execute(ctx(f"snooze {tid} 30", uid))
    assert "30m" in r2.message


@pytest.mark.parametrize("minutes", [0, 1441, 99999])
def test_snooze_rejects_out_of_range_duration(temp_db, uid, engine, minutes):
    # Mirrors main.py:2631's 1-1440 bound. Checked before locate, like
    # Legacy (which validates before get_task_by_id) -- wait, Legacy
    # validates minutes BEFORE the task lookup (main.py:2630-2637 order:
    # parse, range-check, then locate). Same order here.
    tid = Storage().tasks.add(uid, "Task")
    result = engine.execute(ctx(f"snooze {tid} {minutes}", uid))
    assert result.success is False
    assert "invalid_duration" in result.warnings
    assert cols(temp_db, tid)[1] is None  # nothing written


def test_snooze_learning_log_failure_swallowed_like_legacy(temp_db, uid):
    class _RaisingLearning:
        def log_snooze(self, *a, **k):
            raise RuntimeError("boom")

        def log_interaction(self, *a, **k):
            raise RuntimeError("unreachable")

    storage = Storage()
    tid = storage.tasks.add(uid, "Task")
    storage.learning = _RaisingLearning()
    result = lifecycle_task.snooze(tid, 30, uid, storage, NOW)
    assert result.success is True  # matches Legacy's bare try/except: pass
    assert cols(temp_db, tid)[1] is not None


def test_snooze_requires_now(temp_db, uid):
    tid = Storage().tasks.add(uid, "Task")
    result = lifecycle_task.snooze(tid, 30, uid, Storage(), None)
    assert result.success is False
    assert "missing_now" in result.warnings


# ── Stop reminders ────────────────────────────────────────────────────────

def test_stop_reminders_clears_due_time_and_snooze(temp_db, uid, engine):
    tid = Storage().tasks.add(uid, "Task", due_time="09:00")
    engine.execute(ctx(f"snooze {tid} 30", uid))
    result = engine.execute(ctx(f"stopreminder {tid}", uid))
    assert result.success is True
    paused, snooze_until, due_time, _ = cols(temp_db, tid)
    assert due_time is None and snooze_until is None
    assert paused == 0  # stop_reminders does NOT pause -- verified Legacy scope


# ── Carry forward ─────────────────────────────────────────────────────────

def test_carry_forward_moves_overdue_to_today(temp_db, uid, engine):
    tid = Storage().tasks.add(uid, "Old", due_date="2020-01-01")
    result = engine.execute(ctx("carryforward", uid))
    assert result.success is True
    assert result.metadata["count"] == 1
    assert cols(temp_db, tid)[3] == "2026-03-04"  # NOW's date


def test_carry_forward_none_overdue(temp_db, uid, engine):
    result = engine.execute(ctx("carry forward", uid))
    assert result.success is True
    assert result.metadata["count"] == 0
    assert "No overdue tasks" in result.message


def test_carry_forward_skips_paused_and_recurring(temp_db, uid, engine):
    # The exclusions live in database.carry_forward_overdue()'s WHERE
    # clause -- shared by construction, verified through the facade here.
    paused_id = Storage().tasks.add(uid, "Paused", due_date="2020-01-01")
    Storage().tasks.pause(paused_id, uid)
    recurring_id = Storage().tasks.add(uid, "Daily", due_date="2020-01-01",
                                        recurrence_type="daily")
    result = engine.execute(ctx("carryforward", uid))
    assert result.metadata["count"] == 0
    assert cols(temp_db, paused_id)[3] == "2020-01-01"
    assert cols(temp_db, recurring_id)[3] == "2020-01-01"


# ── Paused view (QUERY_TASK path) ─────────────────────────────────────────

def test_paused_view_lists_paused_tasks(temp_db, uid, engine):
    tid = Storage().tasks.add(uid, "Sleeping", due_date="2027-01-01")
    Storage().tasks.pause(tid, uid)
    result = engine.execute(ctx("paused", uid, intent=Intent.QUERY_TASK))
    assert result.success is True
    assert "Sleeping" in result.message
    assert result.metadata["count"] == 1


def test_paused_view_empty(temp_db, uid, engine):
    result = engine.execute(ctx("show paused", uid, intent=Intent.QUERY_TASK))
    assert result.success is True
    assert result.message == "No paused tasks."


# ── Shared failure scenarios ─────────────────────────────────────────────

@pytest.mark.parametrize("text", ["pause 424242", "resume 424242",
                                    "snooze 424242 30", "stopreminder 424242"])
def test_failure_missing_task(temp_db, uid, engine, text):
    result = engine.execute(ctx(text, uid))
    assert result.success is False
    assert "task_not_found" in result.warnings


@pytest.mark.parametrize("bad_id", [0, 999999999])
def test_failure_invalid_id(temp_db, uid, engine, bad_id):
    result = engine.execute(ctx(f"pause {bad_id}", uid))
    assert result.success is False
    assert "task_not_found" in result.warnings


class _FakeTaskStorageRaises:
    def __init__(self, exc):
        self._exc = exc

    def get_by_id(self, *a, **k):
        return (1, "Task", None, "09:00", "General", "medium", None)

    def pause(self, *a, **k):
        raise self._exc


class _FakeStorage:
    def __init__(self, tasks):
        self.tasks = tasks


def test_failure_database_exception(uid):
    engine = OfflineEngine(_FakeStorage(_FakeTaskStorageRaises(RuntimeError("boom"))))
    result = engine.execute(ctx("pause 1", uid))
    assert result.success is False
    assert any(w.startswith("action_exception:") for w in result.warnings)


def test_failure_database_locked(uid):
    engine = OfflineEngine(_FakeStorage(
        _FakeTaskStorageRaises(sqlite3.OperationalError("database is locked"))))
    result = engine.execute(ctx("pause 1", uid))
    assert result.success is False
    assert any(w.startswith("action_exception:") for w in result.warnings)


def test_failure_duplicate_request(temp_db, uid, engine):
    # Duplicate snooze overwrites snooze_until -- Legacy's UPDATE has no
    # already-snoozed guard; the second value wins. Matched.
    tid = Storage().tasks.add(uid, "Task")
    engine.execute(ctx(f"snooze {tid} 30", uid))
    engine.execute(ctx(f"snooze {tid} 60", uid))
    assert cols(temp_db, tid)[1] == "2026-03-04 11:30"  # NOW + 60m won


def test_failure_concurrent_request(temp_db, uid, engine):
    # Task deleted by another path between requests -- next lifecycle op
    # fails gracefully.
    tid = Storage().tasks.add(uid, "Task")
    engine.execute(ctx(f"pause {tid}", uid))
    Storage().tasks.delete(tid, uid)
    result = engine.execute(ctx(f"resume {tid}", uid))
    assert result.success is False
    assert "task_not_found" in result.warnings


def test_failure_invalid_conversation_state_wrong_intent(temp_db, uid, engine):
    # A lifecycle phrase arriving under an intent the engine doesn't
    # dispatch for (e.g. CHAT) is unsupported -- falls through to Legacy.
    result = engine.execute(ctx("pause 5", uid, intent=Intent.CHAT))
    assert result.success is False
    assert "unsupported_intent" in result.warnings


# ── Behavioral Equivalence: Legacy vs Offline, same final state ──────────

def test_equivalence_pause_resume(temp_db, uid):
    legacy_id = db.add_task(uid, "T", None, None, "General", "medium", None, None, None)
    offline_uid = uid + 1
    offline_id = Storage().tasks.add(offline_uid, "T")

    db.pause_task(legacy_id, uid)                      # Legacy (main.py:2307)
    lifecycle_task.pause(offline_id, offline_uid, Storage())
    assert cols(temp_db, legacy_id)[0] == cols(temp_db, offline_id)[0] == 1

    db.resume_task(legacy_id, uid)                     # Legacy (main.py:2326)
    lifecycle_task.resume(offline_id, offline_uid, Storage())
    assert cols(temp_db, legacy_id)[0] == cols(temp_db, offline_id)[0] == 0


def test_equivalence_snooze_including_learning_logs(temp_db, uid):
    legacy_id = db.add_task(uid, "T", None, "09:00", "Work", "medium", None, None, None)
    offline_uid = uid + 1
    offline_id = Storage().tasks.add(offline_uid, "T", due_time="09:00", category="Work")

    # Legacy sequence (main.py:2639-2646) verbatim.
    from datetime import timedelta
    snooze_until = (NOW + timedelta(minutes=45)).strftime("%Y-%m-%d %H:%M")
    db.snooze_task(legacy_id, uid, snooze_until)
    db.log_snooze(uid, legacy_id, "T", "Work", 45)
    db.log_interaction(uid, "task_snooze")

    lifecycle_task.snooze(offline_id, 45, offline_uid, Storage(), NOW)

    assert cols(temp_db, legacy_id)[1] == cols(temp_db, offline_id)[1]
    conn = sqlite3.connect(temp_db)
    rows = conn.execute("SELECT title, category, snooze_minutes FROM snooze_log").fetchall()
    conn.close()
    assert len(rows) == 2 and rows[0] == rows[1]


def test_equivalence_stop_reminders(temp_db, uid):
    legacy_id = db.add_task(uid, "T", "2027-01-01", "09:00", "General", "medium", None, None, None)
    offline_uid = uid + 1
    offline_id = Storage().tasks.add(offline_uid, "T", due_date="2027-01-01", due_time="09:00")
    db.stop_reminders(legacy_id, uid)                  # Legacy (main.py:2527)
    lifecycle_task.stop_reminders(offline_id, offline_uid, Storage())
    assert cols(temp_db, legacy_id)[1:3] == cols(temp_db, offline_id)[1:3] == (None, None)


def test_equivalence_carry_forward(temp_db, uid):
    legacy_id = db.add_task(uid, "T", "2020-01-01", None, "General", "medium", None, None, None)
    offline_uid = uid + 1
    offline_id = Storage().tasks.add(offline_uid, "T", due_date="2020-01-01")
    today = NOW.strftime("%Y-%m-%d")
    legacy_count = db.carry_forward_overdue(uid, today)     # Legacy (main.py:2366)
    offline_result = lifecycle_task.carry_forward(offline_uid, Storage(), NOW)
    assert legacy_count == offline_result.metadata["count"] == 1
    assert cols(temp_db, legacy_id)[3] == cols(temp_db, offline_id)[3] == today


def test_carry_forward_requires_now(temp_db, uid):
    result = lifecycle_task.carry_forward(uid, Storage(), None)
    assert result.success is False
    assert "missing_now" in result.warnings


def test_execute_entry_unknown_operation(temp_db, uid):
    # Defensive branch: unreachable via match_entry()'s own output, but
    # execute_entry() is independently callable.
    result = lifecycle_task.execute_entry("teleport", {}, ctx("x", uid), Storage())
    assert result.success is False
    assert "unknown_operation" in result.warnings


# ── Performance (measurement only: latency, memory, query count) ─────────

def test_performance_latency_and_query_count(temp_db, uid, monkeypatch):
    storage = Storage()
    n = 100
    legacy_ids = [db.add_task(uid, f"L{i}", None, None, "General", "medium",
                               None, None, None) for i in range(n)]
    offline_uid = uid + 1
    offline_ids = [storage.tasks.add(offline_uid, f"O{i}") for i in range(n)]

    # Query counting: every database.py function opens its own connection;
    # wrap connect so each connection counts its executed statements.
    counts = {"n": 0}
    real_connect = db.sqlite3.connect

    def counting_connect(*a, **k):
        conn = real_connect(*a, **k)
        conn.set_trace_callback(lambda stmt: counts.__setitem__("n", counts["n"] + 1))
        return conn

    monkeypatch.setattr(db.sqlite3, "connect", counting_connect)

    counts["n"] = 0
    start = time.perf_counter()
    for tid in legacy_ids:
        db.get_task_by_id(tid, uid)   # Legacy locate (main.py:2303)
        db.pause_task(tid, uid)        # Legacy pause  (main.py:2307)
    legacy_ms = (time.perf_counter() - start) * 1000 / n
    legacy_queries = counts["n"] / n

    counts["n"] = 0
    start = time.perf_counter()
    for tid in offline_ids:
        lifecycle_task.pause(tid, offline_uid, storage)
    offline_ms = (time.perf_counter() - start) * 1000 / n
    offline_queries = counts["n"] / n

    # Query count must be IDENTICAL -- the offline path is the same two
    # database.py calls through a thin facade, nothing more.
    assert legacy_queries == offline_queries
    # Latency: loose sanity bounds only, measurement not optimization.
    assert legacy_ms < 50 and offline_ms < 50


def test_performance_memory(temp_db, uid):
    storage = Storage()
    ids = [storage.tasks.add(uid, f"T{i}") for i in range(50)]
    tracemalloc.start()
    before = tracemalloc.take_snapshot()
    for tid in ids:
        lifecycle_task.pause(tid, uid, storage)
        lifecycle_task.resume(tid, uid, storage)
    after = tracemalloc.take_snapshot()
    tracemalloc.stop()
    growth = sum(s.size_diff for s in after.compare_to(before, "lineno"))
    assert growth < 5_000_000
