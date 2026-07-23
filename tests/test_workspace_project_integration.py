"""
Integration tests for v15.0-alpha.3 -- Project <-> Workspace integration
(core/workspace/project_adapter.py + the database/repo bridge).

The milestone's thesis: the Workspace layer can transparently replace the
v14 Project backend. These tests prove it three ways:
  1. flag OFF is byte-identical (adapter dormant, legacy functions
     unchanged);
  2. a project routed through the Workspace layer returns the SAME data as
     the legacy project functions on the same goal;
  3. migration is verifiable and lossless (round-trip equivalence).
All offline against the temp_db fixture.
"""
import pytest

import database as db
from core import feature_flags
from core.storage import Storage
from core.workspace.errors import EntityNotFound
from core.workspace.project_adapter import ProjectAdapter, use_workspace_projects


OTHER = 424242424


# ── Routing flag ──────────────────────────────────────────────────────────

def test_routing_flag_reflects_feature_flag(monkeypatch):
    monkeypatch.setattr(feature_flags, "WORKSPACE", False)
    assert use_workspace_projects() is False
    monkeypatch.setattr(feature_flags, "WORKSPACE", True)
    assert use_workspace_projects() is True


def test_adapter_enabled_property(temp_db, monkeypatch):
    a = ProjectAdapter()
    monkeypatch.setattr(feature_flags, "WORKSPACE", True)
    assert a.enabled is True


# ── flag OFF: legacy path untouched ───────────────────────────────────────

def test_flag_off_legacy_project_functions_unchanged(temp_db, uid):
    # A v14 project built the legacy way must be fully intact and create
    # no workspace rows (the adapter is never invoked).
    gid = db.add_goal(uid, "Legacy drone")
    db.add_materials(uid, gid, ["motor", "frame"])
    db.add_worklog(uid, gid, "started", kind="started")
    assert db.get_materials(uid, gid)
    assert db.get_project_overview(uid, gid)["title"] == "Legacy drone"
    # no workspace was created behind our back
    conn = db.sqlite3.connect(temp_db)
    assert conn.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0] == 0
    conn.close()


# ── flag ON: project via workspace == legacy project ──────────────────────

def test_create_project_makes_workspace_and_goal_no_milestones(temp_db, uid):
    a = ProjectAdapter()
    view = a.create_project(uid, "Filament Recycler", deadline="2026-09-01")
    assert view.workspace.template == "project"
    assert view.title == "Filament Recycler"
    assert view.deadline == "2026-09-01"
    # backing goal exists and is linked
    assert db.get_workspace_goal_id(uid, view.workspace.id) == view.goal_id
    assert db.get_goal_workspace_id(uid, view.goal_id) == view.workspace.id
    # NO milestones were seeded (explicit scope guardrail)
    assert db.get_milestones(view.workspace.id) == []


def test_materials_and_worklog_route_to_same_goal(temp_db, uid):
    a = ProjectAdapter()
    view = a.create_project(uid, "Robot")
    a.add_materials(uid, view.workspace.id, ["servo", "battery"])
    a.add_worklog(uid, view.workspace.id, "began CAD", kind="started")
    # Reading through the adapter == reading the legacy functions on the
    # resolved goal: transparent replacement.
    assert a.get_materials(uid, view.workspace.id) == db.get_materials(uid, view.goal_id)
    assert a.get_worklog(uid, view.workspace.id) == db.get_worklog(uid, view.goal_id)


def test_progress_matches_legacy_computation(temp_db, uid):
    a = ProjectAdapter()
    view = a.create_project(uid, "Bench")
    a.add_materials(uid, view.workspace.id, ["a", "b"])
    mats = a.get_materials(uid, view.workspace.id)
    db.mark_material_acquired(uid, mats[0][0], True)  # 1/2 acquired
    a.add_worklog(uid, view.workspace.id, "in progress", kind="progress")
    # Adapter progress is the v14 materials/worklog computation, not a
    # milestone rollup.
    assert a.progress(uid, view.workspace.id) == \
        db.compute_project_progress(uid, view.goal_id)[0]


def test_overview_matches_legacy_plus_workspace_id(temp_db, uid):
    a = ProjectAdapter()
    view = a.create_project(uid, "Overview")
    a.add_materials(uid, view.workspace.id, ["x"])
    ov = a.overview(uid, view.workspace.id)
    legacy = db.get_project_overview(uid, view.goal_id)
    assert ov["title"] == legacy["title"]
    assert ov["materials"] == legacy["materials"]
    assert ov["progress"] == legacy["progress"]
    assert ov["workspace_id"] == view.workspace.id


def test_list_projects_only_project_workspaces(temp_db, uid):
    a = ProjectAdapter()
    a.create_project(uid, "P1")
    a.create_project(uid, "P2")
    # a non-project workspace must not show up
    Storage().workspaces.create(uid, "Just an Inbox", template="generic")
    titles = {p.title for p in a.list_projects(uid)}
    assert titles == {"P1", "P2"}


def test_ownership_scoping(temp_db, uid):
    a = ProjectAdapter()
    view = a.create_project(uid, "Mine")
    assert a.get_project(OTHER, view.workspace.id) is None
    with pytest.raises(EntityNotFound):
        a.get_materials(OTHER, view.workspace.id)


def test_get_project_none_for_non_project_workspace(temp_db, uid):
    ws_id = Storage().workspaces.create(uid, "Generic", template="generic")
    assert ProjectAdapter().get_project(uid, ws_id) is None


# ── Migration verification (round-trip) ───────────────────────────────────

def test_migrate_then_read_through_workspace_equals_legacy(temp_db, uid):
    # Build a legacy project, migrate it, then read it through the adapter.
    gid = db.add_goal(uid, "Legacy Build")
    db.add_materials(uid, gid, ["motor", "wheel", "chassis"])
    db.add_worklog(uid, gid, "kickoff", kind="started")

    a = ProjectAdapter()
    created = a.migrate(uid)
    assert created == 1

    ws_id = db.get_goal_workspace_id(uid, gid)
    view = a.get_project(uid, ws_id)
    assert view is not None
    assert view.goal_id == gid                      # same backing goal
    assert a.get_materials(uid, ws_id) == db.get_materials(uid, gid)
    assert a.overview(uid, ws_id)["progress"] == \
        db.get_project_overview(uid, gid)["progress"]


def test_verify_migration_reports_ok_after_migrate(temp_db, uid):
    gid = db.add_goal(uid, "P")
    db.add_materials(uid, gid, ["x"])
    a = ProjectAdapter()
    # Before migration: one unmigrated project.
    report = a.verify_migration(uid)
    assert report["ok"] is False
    assert gid in report["unmigrated_projects"]
    # After: clean.
    a.migrate(uid)
    report = a.verify_migration(uid)
    assert report["ok"] is True
    assert report["unmigrated_projects"] == []
    assert report["orphan_workspaces"] == []
    assert report["projects_total"] == 1
    assert report["project_workspaces_total"] == 1


def test_verify_migration_is_idempotent(temp_db, uid):
    gid = db.add_goal(uid, "P")
    db.add_worklog(uid, gid, "note")
    a = ProjectAdapter()
    assert a.migrate(uid) == 1
    assert a.migrate(uid) == 0                       # nothing new
    assert a.verify_migration(uid)["ok"] is True


def test_migration_preserves_all_project_data(temp_db, uid):
    gid = db.add_goal(uid, "Keep everything")
    db.add_materials(uid, gid, ["m1", "m2"])
    db.add_worklog(uid, gid, "entry one")
    before_mats = db.get_materials(uid, gid)
    before_work = db.get_worklog(uid, gid)
    ProjectAdapter().migrate(uid)
    # Original rows referenced, never moved or dropped.
    assert db.get_materials(uid, gid) == before_mats
    assert db.get_worklog(uid, gid) == before_work
