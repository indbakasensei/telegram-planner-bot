"""
Characterization tests for Task behavior — freezes CURRENT behavior exactly.

Covers: create, edit, complete, delete, recurring confirmation, overdue completion.
No improvements, no refactoring, no snapshots.
"""
import sqlite3
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

import database as db
from core.actions import create_task, update_task, complete_task, delete_task
from core.intent.intent_types import Intent
from core.offline.engine import OfflineEngine
from core.offline.request_context import RequestContext
from core.storage import Storage

IST = ZoneInfo("Asia/Kolkata")
# Use a fixed date in the future relative to when tests run (2026-08-23 is current date)
# All test dates must be >= current date to pass validation
NOW = datetime(2026, 8, 24, 10, 0, tzinfo=IST)
UID = 555000111


def ctx(text, uid=UID, task_id=None, now=NOW):
    entities = {"task_id": task_id} if task_id is not None else {}
    return RequestContext(user_id=uid, text=text, intent=Intent.ADD_TASK, entities=entities, now=now)


def ctx_edit(text, uid=UID, task_id=None, now=NOW):
    entities = {"task_id": task_id} if task_id is not None else {}
    return RequestContext(user_id=uid, text=text, intent=Intent.EDIT_TASK, entities=entities, now=now)


def ctx_done(text, uid=UID, task_id=None, now=NOW):
    entities = {"task_id": task_id} if task_id is not None else {}
    return RequestContext(user_id=uid, text=text, intent=Intent.EDIT_TASK, entities=entities, now=now)


def ctx_delete(text, uid=UID, task_id=None):
    entities = {"task_id": task_id} if task_id is not None else {}
    return RequestContext(user_id=uid, text=text, intent=Intent.DELETE_TASK, entities=entities)


@pytest.fixture
def engine(temp_db):
    return OfflineEngine(Storage())


# ── CREATE ──────────────────────────────────────────────────────────────────

def _create_task_via_engine(engine, text, uid):
    """Helper to create a task using the two-phase confirmation flow."""
    # Phase 1: propose
    result = engine.execute(ctx(text, uid))
    assert result.success is True
    assert result.metadata.get("needs_confirmation") is True

    # Phase 2: confirm/commit
    pending_data = result.metadata["pending_data"]
    result = engine.execute_pending("offline_add_task", pending_data, uid)
    assert result.success is True
    return result


def test_task_create_basic(temp_db, uid, engine):
    """Creating a task stores it with expected defaults."""
    result = _create_task_via_engine(engine, "add task Buy milk", uid)
    assert "Saved!" in result.message

    tasks = Storage().tasks.get_all(uid)
    assert len(tasks) == 1
    row = tasks[0]
    assert row[1] == "Buy milk"          # title
    assert row[5] == "medium"            # priority
    assert row[6] is None                # recurrence_type (None = no recurrence)

    # Verify done/paused/is_habit via raw SQL (not in 7-column get_all)
    conn = sqlite3.connect(db.DB_NAME)
    r = conn.execute("SELECT done, paused, is_habit FROM tasks WHERE id=?", (row[0],)).fetchone()
    conn.close()
    assert r[0] == 0
    assert r[1] == 0
    assert r[2] == 0


def test_task_create_with_due_date(temp_db, uid, engine):
    """Creating a task with due date stores it."""
    _create_task_via_engine(engine, "add task Call mom 2026-08-25", uid)

    tasks = Storage().tasks.get_all(uid)
    row = tasks[0]
    assert row[2] == "2026-08-25"        # due_date
    assert row[6] is None                # recurrence_type


def test_task_create_with_due_time(temp_db, uid, engine):
    """Creating a task with due time stores it."""
    _create_task_via_engine(engine, "add task Call mom at 17:00", uid)

    tasks = Storage().tasks.get_all(uid)
    row = tasks[0]
    assert row[3] == "17:00"             # due_time
    assert row[6] is None                # recurrence_type


def test_task_create_with_category(temp_db, uid, engine):
    """Creating a task with category stores it."""
    _create_task_via_engine(engine, "add task Buy milk #shopping", uid)

    tasks = Storage().tasks.get_all(uid)
    row = tasks[0]
    # Current behavior: category is hardcoded to "General" in create_task.propose(),
    # title is kept verbatim including "#shopping"
    assert row[4] == "General"           # category (hardcoded in propose)
    assert row[1] == "Buy milk #shopping"  # title verbatim
    assert row[6] is None                # recurrence_type


def test_task_create_with_priority(temp_db, uid, engine):
    """Creating a task with priority stores it."""
    _create_task_via_engine(engine, "add task Urgent thing !high", uid)

    tasks = Storage().tasks.get_all(uid)
    row = tasks[0]
    assert row[5] == "high"              # priority
    assert row[6] is None                # recurrence_type


def test_task_create_recurring_daily(temp_db, uid, engine):
    """Creating a daily recurring task stores recurrence_type."""
    _create_task_via_engine(engine, "add task Daily thing every day", uid)

    tasks = Storage().tasks.get_all(uid)
    row = tasks[0]
    assert row[6] == "daily"             # recurrence_type at index 6


def test_task_create_recurring_weekly(temp_db, uid, engine):
    """Creating a weekly recurring task stores recurrence_type and weekday."""
    _create_task_via_engine(engine, "add task Weekly thing every monday", uid)

    tasks = Storage().tasks.get_all(uid)
    row = tasks[0]
    assert row[6] == "weekly"            # recurrence_type at index 6
    # recurrence_weekday not in 7-column get_all; query directly
    conn = sqlite3.connect(db.DB_NAME)
    r = conn.execute("SELECT recurrence_weekday FROM tasks WHERE id=?", (row[0],)).fetchone()
    conn.close()
    assert r[0] == 0                     # Monday = 0


def test_task_create_recurring_monthly(temp_db, uid, engine):
    """Creating a monthly recurring task stores recurrence_type and day."""
    _create_task_via_engine(engine, "add task Monthly thing every 15th", uid)

    tasks = Storage().tasks.get_all(uid)
    row = tasks[0]
    assert row[6] == "monthly"           # recurrence_type at index 6
    # recurrence_day not in 7-column get_all; query directly
    conn = sqlite3.connect(db.DB_NAME)
    r = conn.execute("SELECT recurrence_day FROM tasks WHERE id=?", (row[0],)).fetchone()
    conn.close()
    # Current behavior: engine sets recurrence_day=1 for monthly (default).
    # The test text "every 15th" doesn't get parsed to day=15 due to
    # detect_recurrence matching "monthly" before the "every" pattern.
    # This test freezes the current behavior: recurrence_day defaults to 1.
    assert r[0] == 1                    # day defaults to 1


# ── EDIT ────────────────────────────────────────────────────────────────────

def test_task_edit_rename(temp_db, uid, engine):
    """Editing a task to rename it updates title (two-phase: start_editing + apply_change)."""
    tid = Storage().tasks.add(uid, "Old title")
    # Phase 1: start editing
    result = engine.execute(ctx_edit("edit task " + str(tid), uid, task_id=tid))
    assert result.success is True
    assert result.metadata.get("start_editing") is True
    # Phase 2: apply change
    result = engine.continue_editing("rename to New title", tid, uid, NOW)
    assert result.success is True

    row = Storage().tasks.get_by_id(tid, uid)
    assert row[1] == "New title"


def test_task_edit_priority(temp_db, uid, engine):
    """Editing a task to change priority updates it."""
    tid = Storage().tasks.add(uid, "Task")
    result = engine.execute(ctx_edit("edit task " + str(tid), uid, task_id=tid))
    assert result.success is True
    result = engine.continue_editing("set priority to high", tid, uid, NOW)
    assert result.success is True

    row = Storage().tasks.get_by_id(tid, uid)
    assert row[5] == "high"


def test_task_edit_category(temp_db, uid, engine):
    """Editing a task to change category updates it."""
    tid = Storage().tasks.add(uid, "Task")
    result = engine.execute(ctx_edit("edit task " + str(tid), uid, task_id=tid))
    assert result.success is True
    result = engine.continue_editing("change category to Work", tid, uid, NOW)
    assert result.success is True

    row = Storage().tasks.get_by_id(tid, uid)
    assert row[4] == "Work"


def test_task_edit_due_date(temp_db, uid, engine):
    """Editing a task to change due date updates it."""
    tid = Storage().tasks.add(uid, "Task")
    result = engine.execute(ctx_edit("edit task " + str(tid), uid, task_id=tid))
    assert result.success is True
    result = engine.continue_editing("move to tomorrow", tid, uid, NOW)
    assert result.success is True

    row = Storage().tasks.get_by_id(tid, uid)
    assert row[2] == "2026-08-25"


def test_task_edit_due_time(temp_db, uid, engine):
    """Editing a task to change due time updates it."""
    tid = Storage().tasks.add(uid, "Task")
    result = engine.execute(ctx_edit("edit task " + str(tid), uid, task_id=tid))
    assert result.success is True
    result = engine.continue_editing("move to 15:00", tid, uid, NOW)
    assert result.success is True

    row = Storage().tasks.get_by_id(tid, uid)
    assert row[3] == "15:00"


def test_task_edit_clear_due_date(temp_db, uid, engine):
    """Editing a task to clear due date - current behavior: unrecognized_change.

    Current update_task.py doesn't recognize "remove due date" as a valid change pattern.
    This test freezes that behavior."""
    tid = Storage().tasks.add(uid, "Task", due_date="2026-08-25")
    result = engine.execute(ctx_edit("edit task " + str(tid), uid, task_id=tid))
    assert result.success is True
    result = engine.continue_editing("remove due date", tid, uid, NOW)
    # Current behavior: unrecognized_change (not implemented in update_task.py)
    assert result.success is False
    assert "unrecognized_change" in result.warnings


def test_task_edit_clear_due_time(temp_db, uid, engine):
    """Editing a task to clear due time - current behavior: unrecognized_change.

    Current update_task.py doesn't recognize "remove due time" as a valid change pattern.
    This test freezes that behavior."""
    tid = Storage().tasks.add(uid, "Task", due_time="17:00")
    result = engine.execute(ctx_edit("edit task " + str(tid), uid, task_id=tid))
    assert result.success is True
    result = engine.continue_editing("remove due time", tid, uid, NOW)
    # Current behavior: unrecognized_change (not implemented in update_task.py)
    assert result.success is False
    assert "unrecognized_change" in result.warnings


# ── COMPLETE ────────────────────────────────────────────────────────────────

def test_task_complete_basic(temp_db, uid, engine):
    """Completing a task marks it done and logs completion."""
    tid = Storage().tasks.add(uid, "Buy milk")
    result = engine.execute(ctx_done("done " + str(tid), uid, task_id=tid))
    assert result.success is True
    assert "Done!" in result.message

    # Task should be marked done
    active = Storage().tasks.get_all(uid)
    assert len(active) == 0

    done = Storage().tasks.get_all(uid, done=1)
    assert len(done) == 1
    assert done[0][0] == tid


def test_task_complete_with_delay(temp_db, uid, engine):
    """Completing an overdue task logs delay minutes."""
    # Task due 09:00, NOW is 10:00 -> 60 min late (not 90 as old comment said)
    tid = Storage().tasks.add(uid, "Overdue task", due_time="09:00")
    result = engine.execute(ctx_done("done " + str(tid), uid, task_id=tid))
    assert result.success is True

    # Check completions_log for delay
    conn = sqlite3.connect(db.DB_NAME)
    row = conn.execute(
        "SELECT delay_minutes FROM completions_log WHERE task_id=?", (tid,)
    ).fetchone()
    conn.close()
    assert row[0] == 60


def test_task_complete_already_done(temp_db, uid, engine):
    """Completing an already-completed task fails gracefully."""
    tid = Storage().tasks.add(uid, "Task")
    # Use mark_done instead of update (update doesn't accept dict)
    Storage().tasks.mark_done(tid, uid)
    result = engine.execute(ctx_done("done " + str(tid), uid, task_id=tid))
    # Current behavior: re-completing succeeds silently (idempotent mark_done)
    # complete_task.execute doesn't check if already done before marking
    assert result.success is True
    assert "Done!" in result.message


def test_task_complete_nonexistent(temp_db, uid, engine):
    """Completing a nonexistent task fails."""
    result = engine.execute(ctx_done("done 99999", uid, task_id=99999))
    assert result.success is False
    assert "task_not_found" in result.warnings


def test_task_complete_recurring_confirmation(temp_db, uid, engine):
    """Completing a recurring task - current behavior: no confirmation needed.

    Current complete_task.execute() doesn't have confirmation logic for recurring
    tasks; it marks them done directly. This test freezes that behavior."""
    tid = Storage().tasks.add(uid, "Daily thing", recurrence_type="daily")
    result = engine.execute(ctx_done("done " + str(tid), uid, task_id=tid))
    # Current behavior: completes directly, no confirmation
    assert result.success is True
    assert "Done!" in result.message
    assert result.metadata.get("task_id") == tid


def test_task_complete_recurring_confirmed(temp_db, uid):
    """Completing a recurring task twice - current behavior: idempotent completion.

    Current complete_task.execute() doesn't create new recurring instances;
    it just marks the task done. Second call succeeds silently (idempotent).
    This test freezes that behavior."""
    tid = Storage().tasks.add(uid, "Daily thing", recurrence_type="daily")
    # First call: marks done
    result = complete_task.execute(tid, uid, Storage(), NOW)
    assert result.success is True
    assert "Done!" in result.message

    # Second call: idempotent (already done)
    result = complete_task.execute(tid, uid, Storage(), NOW)
    assert result.success is True
    assert "Done!" in result.message

    # Original task should be done (check via raw SQL, get_by_id only returns 7 cols)
    conn = sqlite3.connect(db.DB_NAME)
    r = conn.execute("SELECT done FROM tasks WHERE id=?", (tid,)).fetchone()
    conn.close()
    assert r[0] == 1

    # No new recurring instance is created (current behavior)
    active = Storage().tasks.get_all(uid)
    assert len(active) == 0


# ── DELETE ──────────────────────────────────────────────────────────────────

def test_task_delete_basic(temp_db, uid, engine):
    """Deleting a task removes it after confirmation (two-phase: propose + commit)."""
    tid = Storage().tasks.add(uid, "Buy milk")
    # Propose
    result = engine.execute(ctx_delete("delete task " + str(tid), uid, task_id=tid))
    assert result.success is True
    assert result.metadata.get("needs_confirmation") is True
    pending_data = result.metadata["pending_data"]

    # Confirm via execute_pending (not engine.execute - no matcher for bare "yes")
    result = engine.execute_pending("offline_delete_task", pending_data, uid)
    assert result.success is True
    assert "Deleted" in result.message

    assert Storage().tasks.get_by_id(tid, uid) is None


def test_task_delete_not_found(temp_db, uid, engine):
    """Deleting a nonexistent task fails."""
    result = engine.execute(ctx_delete("delete task 99999", uid, task_id=99999))
    assert result.success is False
    assert "task_not_found" in result.warnings


def test_task_delete_cancel(temp_db, uid, engine):
    """Cancelling a delete leaves task intact.

    Current behavior: cancel is handled by main.py's conversation state,
    not by the engine. The engine only has propose/commit. This test
    verifies the propose step works; the cancel path is not in OfflineEngine."""
    tid = Storage().tasks.add(uid, "Buy milk")
    # Propose
    result = engine.execute(ctx_delete("delete task " + str(tid), uid, task_id=tid))
    assert result.success is True
    assert result.metadata.get("needs_confirmation") is True

    # Cancel path: simply don't call execute_pending. Task remains.
    assert Storage().tasks.get_by_id(tid, uid) is not None


# ── OVERDUE COMPLETION ──────────────────────────────────────────────────────

def test_task_complete_overdue_today(temp_db, uid, engine):
    """Completing a task overdue from today logs delay (current behavior: time-only).

    Current _compute_delay_minutes only compares time-of-day, not full datetime.
    So a task due yesterday 17:00 completed today 10:00 shows 0 delay (10:00 < 17:00).
    This test freezes that behavior."""
    tid = Storage().tasks.add(uid, "Overdue today", due_date="2026-08-23", due_time="17:00")
    result = engine.execute(ctx_done("done " + str(tid), uid, task_id=tid))
    assert result.success is True

    conn = sqlite3.connect(db.DB_NAME)
    row = conn.execute(
        "SELECT delay_minutes FROM completions_log WHERE task_id=?", (tid,)
    ).fetchone()
    conn.close()
    # Current behavior: delay computed from time only (ignores due_date)
    # Due 17:00, NOW 10:00 -> 0 (time not yet passed today)
    assert row[0] == 0


def test_task_complete_not_overdue(temp_db, uid, engine):
    """Completing a task not yet due logs zero delay."""
    tid = Storage().tasks.add(uid, "Future task", due_date="2026-08-30", due_time="17:00")
    result = engine.execute(ctx_done("done " + str(tid), uid, task_id=tid))
    assert result.success is True

    conn = sqlite3.connect(db.DB_NAME)
    row = conn.execute(
        "SELECT delay_minutes FROM completions_log WHERE task_id=?", (tid,)
    ).fetchone()
    conn.close()
    assert row[0] == 0


# ── BEHAVIORAL EQUIVALENCE ──────────────────────────────────────────────────

def test_create_task_equivalence_legacy_vs_offline(temp_db, uid):
    """Legacy database.add_task() vs Offline create_task - current behavior differs.

    Current behavior differences:
    - Title: offline keeps verbatim "Equivalence task 2026-08-25 !high"; legacy gets cleaned "Equivalence task"
    - Priority: offline doesn't parse "!high" (uses keywords like "urgent"); legacy gets explicit "high"
    This test freezes current behavior - only compares fields that match (due_date, category, recurrence)."""
    storage = Storage()

    # Legacy path
    legacy_tid = db.add_task(uid, "Equivalence task", due_date="2026-08-25", priority="high")

    # Offline path (two-phase: propose + commit)
    propose_result = create_task.propose(ctx("add task Equivalence task 2026-08-25 !high", uid), storage)
    assert propose_result.success is True
    assert propose_result.metadata.get("needs_confirmation") is True
    offline_result = create_task.commit(propose_result.metadata["pending_data"], uid, storage)
    assert offline_result.success is True
    offline_tid = offline_result.metadata["task_id"]

    legacy_row = storage.tasks.get_by_id(legacy_tid, uid)
    offline_row = storage.tasks.get_by_id(offline_tid, uid)

    # Compare fields that match: due_date (2), category (4), recurrence_type (6)
    # Offline title (1) is verbatim; priority (5) doesn't parse "!high"
    assert legacy_row[2] == offline_row[2], f"due_date differs: legacy={legacy_row[2]} offline={offline_row[2]}"
    assert legacy_row[4] == offline_row[4], f"category differs: legacy={legacy_row[4]} offline={offline_row[4]}"
    assert legacy_row[6] == offline_row[6], f"recurrence_type differs: legacy={legacy_row[6]} offline={offline_row[6]}"


def test_complete_task_equivalence_legacy_vs_offline(temp_db, uid):
    """Legacy mark_done+log_completion vs Offline complete_task produce identical state."""
    storage = Storage()

    # Use the same delay computation as offline (60 min: NOW=10:00, due=09:00)
    expected_delay = 60

    # Legacy path
    legacy_tid = db.add_task(uid, "Complete me", due_time="09:00")
    # Get the task to fetch title and category for log_completion
    legacy_task = db.get_task_by_id(legacy_tid, uid)
    db.mark_done(legacy_tid, uid)
    db.log_completion(
        uid, legacy_tid, legacy_task[1], legacy_task[4] or "General",
        legacy_task[3] or "00:00", NOW.strftime("%Y-%m-%d %H:%M:%S"),
        delay_minutes=expected_delay
    )

    # Offline path
    offline_tid = storage.tasks.add(uid, "Complete me", due_time="09:00")
    result = complete_task.execute(offline_tid, uid, storage, NOW)
    assert result.success is True

    legacy_row = storage.tasks.get_by_id(legacy_tid, uid)
    offline_row = storage.tasks.get_by_id(offline_tid, uid)

    # Compare task fields
    for i in range(1, len(legacy_row)):
        assert legacy_row[i] == offline_row[i], f"Task field {i} differs"

    # Compare completions_log
    conn = sqlite3.connect(db.DB_NAME)
    legacy_log = conn.execute(
        "SELECT * FROM completions_log WHERE task_id=?", (legacy_tid,)
    ).fetchone()
    offline_log = conn.execute(
        "SELECT * FROM completions_log WHERE task_id=?", (offline_tid,)
    ).fetchone()
    conn.close()

    assert legacy_log is not None and offline_log is not None
    # task_id (index 2) differs between legacy and offline paths; compare from index 3
    for i in range(3, len(legacy_log)):
        assert legacy_log[i] == offline_log[i], f"Log field {i} differs"


def test_delete_task_equivalence_legacy_vs_offline(temp_db, uid):
    """Legacy database.delete_task() vs Offline delete_task produce identical state."""
    storage = Storage()

    # Legacy path
    legacy_tid = db.add_task(uid, "Delete me")
    db.delete_task(legacy_tid, uid)

    # Offline path
    offline_tid = storage.tasks.add(uid, "Delete me")
    delete_task.commit({"task_id": offline_tid}, uid, storage)

    assert storage.tasks.get_by_id(legacy_tid, uid) is None
    assert storage.tasks.get_by_id(offline_tid, uid) is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])