"""
Tests for v15.0-alpha.4 -- Milestone management: archive + soft-delete
(core/workspace/engine.py archive_milestone/delete_milestone, the
lifecycle 'archived' state, and the database soft-delete column).

All offline against the temp_db fixture. Proves: archived/deleted
milestones drop out of default listings and the progress denominator; a
soft-deleted row is retained (never DROPped); ownership is enforced;
events fire through the existing hook; and flag-OFF startup is unaffected
(the columns ship empty).
"""
import sqlite3

import pytest

import database as db
from core.workspace import lifecycle
from core.workspace.engine import (
    EV_MILESTONE_ARCHIVED,
    EV_MILESTONE_DELETED,
    EntityEngine,
)
from core.workspace.errors import EntityNotFound, InvalidTransition
from core.workspace.models import MS_ARCHIVED, MS_DONE, MS_TODO


OTHER = 313131313


def make_engine():
    events = []
    eng = EntityEngine(on_event=lambda ev: events.append((ev.event_type, ev.entity_type)))
    return eng, events


def _ws_with_milestones(eng, uid, n=3):
    ws = eng.create_workspace(uid, "W")
    return ws, [eng.add_milestone(uid, ws.id, f"M{i}") for i in range(n)]


# ── Schema ────────────────────────────────────────────────────────────────

def test_milestone_soft_delete_columns_exist(temp_db):
    conn = sqlite3.connect(temp_db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(milestones)")}
    conn.close()
    assert "archived_at" in cols
    assert "deleted_at" in cols


# ── Lifecycle ─────────────────────────────────────────────────────────────

def test_lifecycle_allows_archive_and_restore():
    lc = lifecycle.MILESTONE_LIFECYCLE
    assert lc.can(MS_TODO, MS_ARCHIVED)
    assert lc.can(MS_DONE, MS_ARCHIVED)
    assert lc.can(MS_ARCHIVED, MS_TODO)          # restore
    assert not lc.can(MS_ARCHIVED, MS_DONE)      # can't jump archived->done


# ── Archive ───────────────────────────────────────────────────────────────

def test_archive_hides_from_default_list(temp_db, uid):
    eng, _ = make_engine()
    ws, ms = _ws_with_milestones(eng, uid, 3)
    eng.archive_milestone(uid, ms[0].id)
    visible = eng.list_milestones(uid, ws.id)
    assert ms[0].id not in {m.id for m in visible}
    assert len(visible) == 2
    # but reachable when explicitly including archived
    witharch = eng.list_milestones(uid, ws.id, include_archived=True)
    archived = next(m for m in witharch if m.id == ms[0].id)
    assert archived.status == MS_ARCHIVED
    assert archived.archived_at is not None


def test_archive_excluded_from_progress(temp_db, uid):
    eng, _ = make_engine()
    ws, ms = _ws_with_milestones(eng, uid, 4)
    eng.complete_milestone(uid, ms[0].id)         # 1/4 = 25%
    assert eng.workspace_progress(uid, ws.id) == 25
    eng.archive_milestone(uid, ms[1].id)          # denominator now 3
    assert eng.workspace_progress(uid, ws.id) == 33  # 1/3


def test_archive_is_noop_when_already_archived(temp_db, uid):
    eng, events = make_engine()
    ws, ms = _ws_with_milestones(eng, uid, 1)
    eng.archive_milestone(uid, ms[0].id)
    events.clear()
    again = eng.archive_milestone(uid, ms[0].id)
    assert again.status == MS_ARCHIVED
    assert events == []                           # no second event


def test_archive_emits_event(temp_db, uid):
    eng, events = make_engine()
    ws, ms = _ws_with_milestones(eng, uid, 1)
    events.clear()
    eng.archive_milestone(uid, ms[0].id)
    assert (EV_MILESTONE_ARCHIVED, "milestone") in events


def test_archive_ownership_enforced(temp_db, uid):
    eng, _ = make_engine()
    ws, ms = _ws_with_milestones(eng, uid, 1)
    with pytest.raises(EntityNotFound):
        eng.archive_milestone(OTHER, ms[0].id)


# ── Soft delete ───────────────────────────────────────────────────────────

def test_soft_delete_hides_but_keeps_row(temp_db, uid):
    eng, _ = make_engine()
    ws, ms = _ws_with_milestones(eng, uid, 2)
    eng.delete_milestone(uid, ms[0].id)
    # gone from every normal read...
    assert db.get_milestone(ms[0].id) is None
    assert ms[0].id not in {m.id for m in eng.list_milestones(uid, ws.id)}
    assert ms[0].id not in {m.id for m in
                            eng.list_milestones(uid, ws.id, include_archived=True)}
    # ...but the row is retained (soft delete, never DROP)
    conn = sqlite3.connect(temp_db)
    row = conn.execute(
        "SELECT deleted_at FROM milestones WHERE id=?", (ms[0].id,)).fetchone()
    conn.close()
    assert row is not None and row[0] is not None


def test_soft_delete_excluded_from_progress(temp_db, uid):
    eng, _ = make_engine()
    ws, ms = _ws_with_milestones(eng, uid, 4)
    eng.complete_milestone(uid, ms[0].id)
    eng.delete_milestone(uid, ms[1].id)           # denominator 3
    assert eng.workspace_progress(uid, ws.id) == 33  # 1/3


def test_double_delete_raises(temp_db, uid):
    eng, _ = make_engine()
    ws, ms = _ws_with_milestones(eng, uid, 1)
    eng.delete_milestone(uid, ms[0].id)
    with pytest.raises(EntityNotFound):
        eng.delete_milestone(uid, ms[0].id)


def test_delete_emits_event(temp_db, uid):
    eng, events = make_engine()
    ws, ms = _ws_with_milestones(eng, uid, 1)
    events.clear()
    eng.delete_milestone(uid, ms[0].id)
    assert (EV_MILESTONE_DELETED, "milestone") in events


def test_delete_ownership_enforced(temp_db, uid):
    eng, _ = make_engine()
    ws, ms = _ws_with_milestones(eng, uid, 1)
    with pytest.raises(EntityNotFound):
        eng.delete_milestone(OTHER, ms[0].id)


def test_cannot_transition_a_deleted_milestone(temp_db, uid):
    eng, _ = make_engine()
    ws, ms = _ws_with_milestones(eng, uid, 1)
    eng.delete_milestone(uid, ms[0].id)
    with pytest.raises(EntityNotFound):
        eng.transition_milestone(uid, ms[0].id, MS_DONE)


# ── flag-OFF neutrality ───────────────────────────────────────────────────

def test_columns_ship_empty_on_fresh_db(temp_db, uid):
    # A fresh milestone has no archive/delete stamps.
    eng, _ = make_engine()
    ws, ms = _ws_with_milestones(eng, uid, 1)
    m = eng.get_workspace(uid, ws.id)  # workspace ok
    row = db.get_milestone(ms[0].id)
    assert row[9] is None   # archived_at
    assert row[10] is None  # deleted_at
