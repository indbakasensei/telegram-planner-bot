"""
Tests for core/actions/delete_task.py -- the v14.5 Offline Task Delete
(BAKA's first destructive Offline write operation).

Includes Behavioral Equivalence tests (Legacy's database.delete_task()
vs. Offline's propose()+commit(), compared by resulting database state)
and all 8 Failure Injection scenarios this sprint's brief named:
database locked, database exception, task missing, double confirmation,
cancel, invalid ID, timeout, concurrent delete.
"""
import sqlite3
import time
import tracemalloc

import pytest

import database as db
from core.actions import delete_task
from core.intent.intent_types import Intent
from core.offline.engine import OfflineEngine
from core.offline.request_context import RequestContext
from core.storage import Storage


def ctx(text, uid, task_id=None):
    entities = {"task_id": task_id} if task_id is not None else {}
    return RequestContext(user_id=uid, text=text, intent=Intent.DELETE_TASK, entities=entities)


@pytest.fixture
def engine():
    return OfflineEngine(Storage())


# ── format_preview ────────────────────────────────────────────────────────

def test_format_preview():
    task = (1, "Buy milk", "2027-01-05", "17:00", "General", "medium", None)
    preview = delete_task.format_preview(task)
    assert "Buy milk" in preview
    assert "2027-01-05" in preview


# ── propose(): Locate + Preview ──────────────────────────────────────────

def test_propose_task_found(temp_db, uid):
    tid = Storage().tasks.add(uid, "Buy milk")
    result = delete_task.propose(tid, uid, Storage())
    assert result.success is True
    assert result.metadata == {"needs_confirmation": True, "pending_data": {"task_id": tid}}
    # Never deletes.
    assert Storage().tasks.get_by_id(tid, uid) is not None


def test_propose_task_not_found(temp_db, uid):
    result = delete_task.propose(99999, uid, Storage())
    assert result.success is False
    assert "task_not_found" in result.warnings


# ── commit(): Confirm + Delete + Verify + Return ─────────────────────────

def test_commit_deletes_and_verifies(temp_db, uid):
    tid = Storage().tasks.add(uid, "Buy milk")
    result = delete_task.commit({"task_id": tid}, uid, Storage())
    assert result.success is True
    assert result.metadata["deleted_title"] == "Buy milk"
    assert Storage().tasks.get_by_id(tid, uid) is None


def test_commit_missing_task_id(uid):
    result = delete_task.commit({}, uid, Storage())
    assert result.success is False
    assert "missing_task_id" in result.warnings


# ── OfflineEngine dispatch ───────────────────────────────────────────────

def test_engine_execute_delete_task(temp_db, uid, engine):
    tid = Storage().tasks.add(uid, "Task")
    result = engine.execute(ctx("delete task " + str(tid), uid, task_id=tid))
    assert result.success is True
    assert result.metadata["needs_confirmation"] is True


def test_engine_execute_delete_task_missing_id(temp_db, uid, engine):
    result = engine.execute(ctx("delete this", uid))
    assert result.success is False
    assert "unsupported_action" in result.warnings


def test_engine_execute_delete_task_exception_is_caught(uid, engine, monkeypatch):
    monkeypatch.setattr(
        "core.offline.engine.delete_task.propose",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    result = engine.execute(ctx("delete task 1", uid, task_id=1))
    assert result.success is False
    assert any(w.startswith("action_exception:") for w in result.warnings)


def test_engine_execute_pending_delete_dispatches_correctly(temp_db, uid, engine):
    tid = Storage().tasks.add(uid, "Task")
    result = engine.execute_pending("offline_delete_task", {"task_id": tid}, uid)
    assert result.success is True


def test_engine_execute_pending_delete_exception_is_caught(uid, engine, monkeypatch):
    monkeypatch.setattr(
        "core.offline.engine.delete_task.commit",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    result = engine.execute_pending("offline_delete_task", {"task_id": 1}, uid)
    assert result.success is False
    assert any(w.startswith("commit_exception:") for w in result.warnings)


# ── Idempotency ───────────────────────────────────────────────────────────

def test_idempotency_repeated_commit_does_not_double_delete(temp_db, uid):
    tid = Storage().tasks.add(uid, "Task")
    r1 = delete_task.commit({"task_id": tid}, uid, Storage())
    assert r1.success is True
    assert r1.metadata.get("already_deleted") is not True

    r2 = delete_task.commit({"task_id": tid}, uid, Storage())
    assert r2.success is True
    assert r2.metadata.get("already_deleted") is True
    assert "already deleted" in r2.message.lower()


# ── Failure Injection: 8 scenarios named in this sprint's brief ─────────

class _FakeTaskStorageDeleteRaises:
    def __init__(self, task, exc):
        self._task = task
        self._exc = exc
        self.delete_calls = 0

    def get_by_id(self, *a, **k):
        return self._task

    def delete(self, *a, **k):
        self.delete_calls += 1
        raise self._exc


class _FakeStorage:
    def __init__(self, task_storage):
        self.tasks = task_storage


_SAMPLE_TASK = (1, "Task", None, None, "General", "medium", None)


def test_failure_database_locked():
    fake_tasks = _FakeTaskStorageDeleteRaises(
        _SAMPLE_TASK, sqlite3.OperationalError("database is locked"),
    )
    with pytest.raises(sqlite3.OperationalError):
        delete_task.commit({"task_id": 1}, 1, _FakeStorage(fake_tasks))


def test_failure_database_locked_via_engine(uid):
    fake_tasks = _FakeTaskStorageDeleteRaises(
        _SAMPLE_TASK, sqlite3.OperationalError("database is locked"),
    )
    engine = OfflineEngine(_FakeStorage(fake_tasks))
    result = engine.execute_pending("offline_delete_task", {"task_id": 1}, uid)
    assert result.success is False
    assert any(w.startswith("commit_exception:") for w in result.warnings)


def test_failure_database_exception_via_engine(uid):
    fake_tasks = _FakeTaskStorageDeleteRaises(_SAMPLE_TASK, RuntimeError("simulated failure"))
    engine = OfflineEngine(_FakeStorage(fake_tasks))
    result = engine.execute_pending("offline_delete_task", {"task_id": 1}, uid)
    assert result.success is False
    assert any(w.startswith("commit_exception:") for w in result.warnings)


def test_failure_task_missing(temp_db, uid):
    result = delete_task.propose(424242, uid, Storage())
    assert result.success is False
    assert "task_not_found" in result.warnings


def test_failure_double_confirmation(temp_db, uid):
    # Same mechanism as idempotency above -- named separately per this
    # sprint's explicit Failure Tests list.
    tid = Storage().tasks.add(uid, "Task")
    delete_task.commit({"task_id": tid}, uid, Storage())
    second = delete_task.commit({"task_id": tid}, uid, Storage())
    assert second.success is True
    assert second.metadata.get("already_deleted") is True


def test_failure_cancel_means_commit_never_called(temp_db, uid):
    # "Cancel" has no action-level branch -- it's main.py's job to not
    # call execute_pending() at all on a negative reply (see the
    # confirming-state handler). At the action level, the guarantee this
    # test verifies is: propose() alone never writes, regardless of what
    # the user replies next.
    tid = Storage().tasks.add(uid, "Task")
    delete_task.propose(tid, uid, Storage())
    assert Storage().tasks.get_by_id(tid, uid) is not None


@pytest.mark.parametrize("bad_id", [0, -1, 999999999])
def test_failure_invalid_id(temp_db, uid, bad_id):
    result = delete_task.propose(bad_id, uid, Storage())
    assert result.success is False
    assert "task_not_found" in result.warnings


def test_failure_timeout():
    fake_tasks = _FakeTaskStorageDeleteRaises(_SAMPLE_TASK, TimeoutError("simulated timeout"))
    with pytest.raises(TimeoutError):
        delete_task.commit({"task_id": 1}, 1, _FakeStorage(fake_tasks))


def test_failure_concurrent_delete(temp_db, uid):
    # Simulated by deleting the task through an independent path (a
    # second Storage instance, standing in for a concurrent request)
    # between propose() and commit() -- commit() must handle this
    # gracefully via the same idempotency check, not crash or
    # double-report success incorrectly.
    tid = Storage().tasks.add(uid, "Task")
    propose_result = delete_task.propose(tid, uid, Storage())
    assert propose_result.success is True

    Storage().tasks.delete(tid, uid)  # "concurrent" deletion via another path

    commit_result = delete_task.commit(propose_result.metadata["pending_data"], uid, Storage())
    assert commit_result.success is True
    assert commit_result.metadata.get("already_deleted") is True


def test_failure_verify_step_catches_a_failed_delete(temp_db, uid):
    # If delete() silently no-ops (e.g. a WHERE clause that matched zero
    # rows for a reason other than "already gone" -- defensive coverage),
    # the verify step must not report success anyway.
    class _NoOpDeleteTaskStorage:
        def get_by_id(self, task_id, user_id):
            return _SAMPLE_TASK  # always "found", even after "deleting"

        def delete(self, task_id, user_id):
            pass  # simulates a delete that didn't actually remove the row

    result = delete_task.commit({"task_id": 1}, uid, _FakeStorage(_NoOpDeleteTaskStorage()))
    assert result.success is False
    assert "delete_not_verified" in result.warnings


# ── Behavioral Equivalence: Legacy vs Offline, compare resulting DB state ──

def test_equivalence_delete_removes_the_row_in_both_paths(temp_db, uid):
    # Legacy path: main.py's delete_task_cmd() (main.py:501) calls
    # delete_task() directly, immediately, no confirmation.
    legacy_id = db.add_task(uid, "Task", None, None, "General", "medium", None, None, None)
    db.delete_task(legacy_id, uid)
    assert db.get_task_by_id(legacy_id, uid) is None

    # Offline path: propose() + commit() (with a deliberate confirm step
    # main.py inserts between them, ADR-010) via the Storage Facade.
    offline_uid = uid + 1
    offline_id = Storage().tasks.add(offline_uid, "Task")
    propose_result = delete_task.propose(offline_id, offline_uid, Storage())
    delete_task.commit(propose_result.metadata["pending_data"], offline_uid, Storage())
    assert db.get_task_by_id(offline_id, offline_uid) is None


def test_equivalence_no_cascading_cleanup_in_either_path(temp_db, uid):
    # Verified finding: database.delete_task() is a plain single-table
    # DELETE, no cascading cleanup of other tables. Offline's commit()
    # calls the exact same function via the Storage Facade -- proves
    # identical scope, not just identical outcome for the tasks table.
    tid = Storage().tasks.add(uid, "Task")
    Storage().goals.add(uid, "Unrelated goal")
    delete_task.commit({"task_id": tid}, uid, Storage())
    # The unrelated goal must be untouched.
    assert len(Storage().goals.get_all(uid)) == 1


def test_equivalence_no_confirmation_in_legacy_but_offline_adds_it():
    # Documented, deliberate divergence (ADR-010): Legacy's real
    # delete_task_cmd() deletes with zero confirmation of any kind --
    # verified by reading main.py:483-504 directly. Offline Delete adds
    # a confirm step (propose() never writes; only commit() does,
    # reachable only after main.py's confirming-state "yes"). This test
    # documents the intentional gap rather than asserting equivalence
    # where none is claimed.
    pass  # see test_propose_task_found (never writes) and
          # test_commit_deletes_and_verifies (only commit writes) above.


# ── Performance (measurement only) ────────────────────────────────────────

def test_performance_benchmark_legacy_vs_offline_delete(temp_db, uid):
    storage = Storage()
    n = 100

    legacy_ids = [db.add_task(uid, f"Legacy {i}", None, None, "General", "medium", None, None, None)
                  for i in range(n)]
    start = time.perf_counter()
    for tid in legacy_ids:
        db.delete_task(tid, uid)
    legacy_ms = (time.perf_counter() - start) * 1000 / n

    offline_uid = uid + 1
    offline_ids = [storage.tasks.add(offline_uid, f"Offline {i}") for i in range(n)]
    start = time.perf_counter()
    for tid in offline_ids:
        delete_task.commit({"task_id": tid}, offline_uid, storage)
    offline_ms = (time.perf_counter() - start) * 1000 / n

    # Measurement only, no optimization -- loose sanity bound against a
    # real bug (e.g. an accidental N+1 query), not a performance target.
    assert legacy_ms < 50
    assert offline_ms < 50


def test_performance_memory_offline_delete(temp_db, uid):
    storage = Storage()
    ids = [storage.tasks.add(uid, f"Task {i}") for i in range(50)]
    tracemalloc.start()
    before = tracemalloc.take_snapshot()
    for tid in ids:
        delete_task.commit({"task_id": tid}, uid, storage)
    after = tracemalloc.take_snapshot()
    tracemalloc.stop()
    total_growth = sum(s.size_diff for s in after.compare_to(before, "lineno"))
    assert total_growth < 5_000_000
