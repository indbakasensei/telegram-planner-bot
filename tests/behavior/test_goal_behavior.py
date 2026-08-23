"""
Characterization tests for Goal behavior — freezes CURRENT behavior exactly.

Covers: create, progress update, deadline update, completion.
No improvements, no refactoring, no snapshots.
"""
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

import database as db
from core.offline.engine import OfflineEngine
from core.offline.request_context import RequestContext
from core.intent.intent_types import Intent
from core.storage import Storage

IST = ZoneInfo("Asia/Kolkata")
UID = 555000111


def ctx(text, intent=Intent.ADD_TASK, now=None):
    return RequestContext(user_id=UID, text=text, intent=intent, entities={}, now=now)


@pytest.fixture
def storage(temp_db):
    return Storage()


@pytest.fixture
def engine(storage):
    return OfflineEngine(storage)


# ── CREATE ──────────────────────────────────────────────────────────────────

def test_goal_create_basic(storage):
    """Creating a goal stores it with expected defaults."""
    gid = db.add_goal(UID, "Read 12 books")
    assert gid is not None

    row = storage.goals.get_by_id(gid, UID)
    assert row is not None
    assert row[1] == "Read 12 books"    # title
    assert row[4] == 0                  # progress
    assert row[5] == 0                  # done
    assert row[6] is not None           # created_at


def test_goal_create_with_deadline(storage):
    """Creating a goal with deadline stores it."""
    gid = db.add_goal(UID, "Finish project", deadline="2026-12-31")
    assert gid is not None

    row = storage.goals.get_by_id(gid, UID)
    assert row[3] == "2026-12-31"       # deadline


def test_goal_create_with_target(storage):
    """Creating a goal with target stores it."""
    # Note: database.add_goal doesn't take target, but the schema has it
    # We test the full schema via direct insert if needed
    gid = db.add_goal(UID, "Target goal")
    conn = sqlite3.connect(db.DB_NAME)
    conn.execute("UPDATE goals SET target=? WHERE id=?", (50, gid))
    conn.commit()
    conn.close()

    row = storage.goals.get_by_id(gid, UID)
    # The get_goals_full returns target
    goals = db.get_goals_full(UID)
    target_goal = [g for g in goals if g[0] == gid][0]
    assert target_goal[4] == 50  # target


# ── PROGRESS UPDATE ────────────────────────────────────────────────────────

def test_goal_progress_update_basic(storage):
    """Updating goal progress increments progress."""
    gid = db.add_goal(UID, "Progress goal")
    result = db.update_goal_progress(gid, UID, 25)
    assert result is not None
    new_progress, target, done = result
    assert new_progress == 25
    assert target == 100  # default target
    assert done is False


def test_goal_progress_update_multiple(storage):
    """Multiple progress updates accumulate."""
    gid = db.add_goal(UID, "Accumulate goal")
    db.update_goal_progress(gid, UID, 30)
    db.update_goal_progress(gid, UID, 40)
    result = db.update_goal_progress(gid, UID, 20)
    assert result is not None
    new_progress, target, done = result
    assert new_progress == 90
    assert done is False


def test_goal_progress_update_clamped_to_target(storage):
    """Progress is clamped to target (100 by default)."""
    gid = db.add_goal(UID, "Clamp goal")
    result = db.update_goal_progress(gid, UID, 150)
    assert result is not None
    new_progress, target, done = result
    assert new_progress == 100
    assert target == 100
    assert done is True


def test_goal_progress_update_with_custom_target(storage):
    """Progress clamped to custom target."""
    gid = db.add_goal(UID, "Custom target goal")
    conn = sqlite3.connect(db.DB_NAME)
    conn.execute("UPDATE goals SET target=? WHERE id=?", (50, gid))
    conn.commit()
    conn.close()

    result = db.update_goal_progress(gid, UID, 60)
    assert result is not None
    new_progress, target, done = result
    assert new_progress == 50
    assert target == 50
    assert done is True


def test_goal_progress_update_negative_delta(storage):
    """Negative delta decreases progress (floored at 0)."""
    gid = db.add_goal(UID, "Decrease goal")
    db.update_goal_progress(gid, UID, 50)
    result = db.update_goal_progress(gid, UID, -20)
    assert result is not None
    new_progress, target, done = result
    assert new_progress == 30
    assert done is False


def test_goal_progress_update_below_zero_clamped(storage):
    """Negative delta clamped at 0."""
    gid = db.add_goal(UID, "Floor goal")
    result = db.update_goal_progress(gid, UID, -50)
    assert result is not None
    new_progress, target, done = result
    assert new_progress == 0
    assert done is False


def test_goal_progress_update_auto_completes(storage):
    """Reaching target marks goal done."""
    gid = db.add_goal(UID, "Auto complete goal")
    result = db.update_goal_progress(gid, UID, 100)
    assert result is not None
    new_progress, target, done = result
    assert new_progress == 100
    assert done is True

    # Verify done column updated
    conn = sqlite3.connect(db.DB_NAME)
    row = conn.execute("SELECT done FROM goals WHERE id=?", (gid,)).fetchone()
    conn.close()
    assert row[0] == 1


def test_goal_progress_update_nonexistent(storage):
    """Updating nonexistent goal returns None."""
    result = db.update_goal_progress(99999, UID, 10)
    assert result is None


def test_goal_progress_update_wrong_user(storage):
    """Updating goal owned by another user returns None."""
    gid = db.add_goal(UID, "Owned goal")
    result = db.update_goal_progress(gid, UID + 1, 10)
    assert result is None


# ── DEADLINE UPDATE ────────────────────────────────────────────────────────

def test_goal_deadline_update_set(storage):
    """Setting a deadline stores it."""
    gid = db.add_goal(UID, "Deadline goal")
    result = db.update_goal_deadline(gid, UID, "2026-06-30")
    assert result == gid

    row = storage.goals.get_by_id(gid, UID)
    assert row[3] == "2026-06-30"


def test_goal_deadline_update_clear(storage):
    """Clearing a deadline (None) stores NULL."""
    gid = db.add_goal(UID, "Clear deadline", deadline="2026-06-30")
    result = db.update_goal_deadline(gid, UID, None)
    assert result == gid

    row = storage.goals.get_by_id(gid, UID)
    assert row[3] is None


def test_goal_deadline_update_nonexistent(storage):
    """Updating deadline on nonexistent goal returns None."""
    result = db.update_goal_deadline(99999, UID, "2026-06-30")
    assert result is None


def test_goal_deadline_update_wrong_user(storage):
    """Updating deadline on another user's goal returns None."""
    gid = db.add_goal(UID, "Other's goal")
    result = db.update_goal_deadline(gid, UID + 1, "2026-06-30")
    assert result is None


# ── COMPLETION ──────────────────────────────────────────────────────────────

def test_goal_completion_via_progress(storage):
    """Goal marked done when progress reaches target."""
    gid = db.add_goal(UID, "Complete via progress")
    db.update_goal_progress(gid, UID, 100)

    row = storage.goals.get_by_id(gid, UID)
    assert row[5] == 1  # done


def test_goal_get_goals_excludes_done(storage):
    """get_goals excludes completed goals by default."""
    g1 = db.add_goal(UID, "Active goal")
    g2 = db.add_goal(UID, "Completed goal")
    db.update_goal_progress(g2, UID, 100)  # completes it

    goals = db.get_goals(UID)
    titles = [g[1] for g in goals]
    assert "Active goal" in titles
    assert "Completed goal" not in titles


def test_goal_get_goals_full_includes_done(storage):
    """get_goals_full includes all goals regardless of done status."""
    g1 = db.add_goal(UID, "Active goal full")
    g2 = db.add_goal(UID, "Completed goal full")
    db.update_goal_progress(g2, UID, 100)

    goals = db.get_goals_full(UID)
    titles = [g[1] for g in goals]
    assert "Active goal full" in titles
    assert "Completed goal full" in titles


def test_goal_get_goals_full_progress_target(storage):
    """get_goals_full returns progress and target."""
    gid = db.add_goal(UID, "Full detail goal")
    db.update_goal_progress(gid, UID, 42)

    goals = db.get_goals_full(UID)
    goal = [g for g in goals if g[0] == gid][0]
    assert goal[3] == 42   # progress
    assert goal[4] == 100  # target


# ── BEHAVIORAL EQUIVALENCE ──────────────────────────────────────────────────

def test_goal_create_equivalence_direct_vs_storage(storage):
    """database.add_goal() vs Storage.goals.add() produce identical rows."""
    # Direct database call
    legacy_gid = db.add_goal(UID, "Equivalence goal", deadline="2026-12-31")

    # Storage facade
    storage_gid = storage.goals.add(UID, "Equivalence goal", deadline="2026-12-31")

    legacy_row = storage.goals.get_by_id(legacy_gid, UID)
    storage_row = storage.goals.get_by_id(storage_gid, UID)

    for i in range(1, len(legacy_row)):
        assert legacy_row[i] == storage_row[i], f"Field {i} differs: legacy={legacy_row[i]} storage={storage_row[i]}"


def test_goal_progress_equivalence_direct_vs_storage(storage):
    """database.update_goal_progress() vs Storage.goals.update_progress() equivalence."""
    legacy_gid = db.add_goal(UID, "Progress eq goal")
    db.update_goal_progress(legacy_gid, UID, 35)

    storage_gid = storage.goals.add(UID, "Progress eq goal")
    storage.goals.update_progress(storage_gid, UID, 35)

    legacy_row = storage.goals.get_by_id(legacy_gid, UID)
    storage_row = storage.goals.get_by_id(storage_gid, UID)

    for i in range(1, len(legacy_row)):
        assert legacy_row[i] == storage_row[i], f"Field {i} differs"


def test_goal_deadline_equivalence_direct_vs_storage(storage):
    """database.update_goal_deadline() vs Storage.goals.update_deadline() equivalence."""
    legacy_gid = db.add_goal(UID, "Deadline eq goal")
    db.update_goal_deadline(legacy_gid, UID, "2026-07-04")

    storage_gid = storage.goals.add(UID, "Deadline eq goal")
    storage.goals.update_deadline(storage_gid, UID, "2026-07-04")

    legacy_row = storage.goals.get_by_id(legacy_gid, UID)
    storage_row = storage.goals.get_by_id(storage_gid, UID)

    for i in range(1, len(legacy_row)):
        assert legacy_row[i] == storage_row[i], f"Field {i} differs"


def test_goal_list_equivalence_direct_vs_storage(storage):
    """database.get_goals() vs Storage.goals.list() return same data."""
    db.add_goal(UID, "Goal A")
    db.add_goal(UID, "Goal B")
    db.add_goal(UID, "Goal C")
    db.update_goal_progress(2, UID, 100)  # complete B

    legacy_goals = db.get_goals(UID)
    storage_goals = storage.goals.list(UID)

    assert len(legacy_goals) == len(storage_goals)
    for lg, sg in zip(legacy_goals, storage_goals):
        assert lg == sg


if __name__ == "__main__":
    pytest.main([__file__, "-v"])