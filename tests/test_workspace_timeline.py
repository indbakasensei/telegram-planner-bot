"""
Tests for v15.0-alpha.5 -- the Knowledge Timeline (append-only event
infrastructure): the database layer, Storage facade, TimelineRepository,
and the TimelineEngine subscriber wired to the Entity Engine's event hook.

All offline against the temp_db fixture. The headline test is
`test_engine_events_are_recorded_*`: performing Entity Engine mutations
with the Timeline attached persists correct, user-scoped rows -- proving
the event seam carries everything a subscriber needs (the reason alpha.5
upgraded the hook to a self-contained EntityEvent).
"""
import sqlite3

import pytest

import database as db
from core.storage import Storage
from core.workspace.engine import EntityEngine
from core.workspace.timeline import (
    TimelineEngine,
    TimelineEvent,
    TimelineRepository,
)


# ── Schema ────────────────────────────────────────────────────────────────

def test_timeline_table_and_columns(temp_db):
    assert "timeline_events" in db.REQUIRED_TABLES
    conn = sqlite3.connect(temp_db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(timeline_events)")}
    conn.close()
    assert {"user_id", "workspace_id", "entity_type", "entity_id",
            "event_type", "summary", "payload", "source", "created_at",
            "synced_at"} <= cols
    assert db.verify_schema_integrity(temp_db)["ok"]


# ── database layer ────────────────────────────────────────────────────────

def test_add_and_get_timeline(temp_db, uid):
    db.add_timeline_event(uid, "workspace.created", "Created workspace: A",
                          entity_type="workspace", entity_id=1, workspace_id=1,
                          payload={"title": "A"})
    db.add_timeline_event(uid, "milestone.added", "Added milestone: M",
                          entity_type="milestone", entity_id=2, workspace_id=1)
    rows = db.get_timeline(uid)
    assert len(rows) == 2
    assert rows[0][5] == "milestone.added"   # newest-first
    assert db.count_timeline(uid) == 2
    assert db.count_timeline(uid, workspace_id=1) == 2


def test_entity_timeline(temp_db, uid):
    db.add_timeline_event(uid, "milestone.added", "x", entity_type="milestone",
                          entity_id=7, workspace_id=1)
    db.add_timeline_event(uid, "milestone.status_changed", "y",
                          entity_type="milestone", entity_id=7, workspace_id=1)
    db.add_timeline_event(uid, "note.added", "z", entity_type="note",
                          entity_id=99, workspace_id=1)
    hist = db.get_entity_timeline("milestone", 7)
    assert len(hist) == 2
    assert {r[5] for r in hist} == {"milestone.added", "milestone.status_changed"}


def test_unsynced_and_mark_synced(temp_db, uid):
    e1 = db.add_timeline_event(uid, "workspace.created", "a", workspace_id=1)
    db.add_timeline_event(uid, "milestone.added", "b", workspace_id=1)
    assert len(db.get_unsynced_timeline(uid)) == 2
    db.mark_timeline_synced(e1)
    remaining = db.get_unsynced_timeline(uid)
    assert len(remaining) == 1
    assert remaining[0][5] == "milestone.added"


def test_reset_clears_timeline(temp_db, uid):
    db.add_timeline_event(uid, "workspace.created", "a", workspace_id=1)
    db.reset_everything(uid)
    assert db.count_timeline(uid) == 0


# ── Facade ────────────────────────────────────────────────────────────────

def test_facade_timeline_delegates(temp_db, uid):
    s = Storage()
    assert s.timeline is not None
    s.timeline.add(uid, "workspace.created", "a", workspace_id=1)
    assert s.timeline.list_for_user(uid) == db.get_timeline(uid)
    assert s.timeline.count(uid) == 1


# ── Repository ────────────────────────────────────────────────────────────

def test_repository_maps_rows_and_payload(temp_db, uid):
    repo = TimelineRepository()
    repo.add(uid, "workspace.created", "Created workspace: A",
             entity_type="workspace", entity_id=1, workspace_id=1,
             payload={"title": "A", "status": "active"})
    events = repo.for_user(uid)
    assert len(events) == 1
    ev = events[0]
    assert isinstance(ev, TimelineEvent)
    assert ev.event_type == "workspace.created"
    assert ev.payload == {"title": "A", "status": "active"}


# ── TimelineEngine.record (direct) ────────────────────────────────────────

def test_record_builds_summary_and_payload(temp_db, uid):
    from core.workspace.events import build_event
    from core.workspace.models import Workspace
    ws = Workspace(id=5, user_id=uid, template="book", title="Deep Work")
    ev = build_event("workspace.created", "workspace", ws, uid)
    te = TimelineEngine()
    te.record(ev)
    rec = te.timeline(uid)[0]
    assert rec.summary == "Created workspace: Deep Work"
    assert rec.payload["title"] == "Deep Work"
    assert rec.workspace_id == 5 and rec.entity_id == 5
    assert rec.user_id == uid


# ── Integration: Entity Engine + Timeline subscriber ──────────────────────

def test_engine_events_are_recorded(temp_db, uid):
    te = TimelineEngine()
    eng = EntityEngine(on_event=te.record)

    ws = eng.create_workspace(uid, "Robot", template="project")  # 1 + 5 seeded
    ms = eng.add_milestone(uid, ws.id, "Extra")
    eng.complete_milestone(uid, ms.id)

    events = te.timeline(uid, workspace_id=ws.id)
    types = [e.event_type for e in events]
    assert "workspace.created" in types
    assert types.count("milestone.added") == 6      # 5 seeded + 1
    assert "milestone.status_changed" in types
    # every row is scoped to the right user + workspace
    assert all(e.user_id == uid and e.workspace_id == ws.id for e in events)


def test_engine_milestone_event_carries_user_and_ids(temp_db, uid):
    # This is the crux: a Milestone model has no user_id, but the recorded
    # event must still be user-scoped (the engine stamps it via EntityEvent).
    te = TimelineEngine()
    eng = EntityEngine(on_event=te.record)
    ws = eng.create_workspace(uid, "W")           # generic: no seeded milestones
    ms = eng.add_milestone(uid, ws.id, "M")
    hist = te.entity_history("milestone", ms.id)
    assert len(hist) == 1
    assert hist[0].user_id == uid
    assert hist[0].workspace_id == ws.id
    assert hist[0].entity_id == ms.id
    assert hist[0].summary == "Added milestone: M"


def test_delete_event_records_pre_delete_snapshot(temp_db, uid):
    te = TimelineEngine()
    eng = EntityEngine(on_event=te.record)
    ws = eng.create_workspace(uid, "W")
    ms = eng.add_milestone(uid, ws.id, "Doomed")
    eng.delete_milestone(uid, ms.id)
    latest = te.timeline(uid)[0]
    assert latest.event_type == "milestone.deleted"
    assert latest.summary == "Deleted milestone: Doomed"


def test_seeded_milestones_marked_system_source(temp_db, uid):
    te = TimelineEngine()
    eng = EntityEngine(on_event=te.record)
    ws = eng.create_workspace(uid, "P", template="project")
    seeded = [e for e in te.timeline(uid) if e.event_type == "milestone.added"]
    assert seeded and all(e.source == "system" for e in seeded)


# ── flag-OFF neutrality: no subscriber => no rows ─────────────────────────

def test_default_engine_records_nothing(temp_db, uid):
    eng = EntityEngine()  # no on_event -> default no-op sink
    ws = eng.create_workspace(uid, "W", template="project")
    eng.add_milestone(uid, ws.id, "M")
    assert db.count_timeline(uid) == 0
