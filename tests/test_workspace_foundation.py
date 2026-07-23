"""
Tests for the v15.0-alpha.1 Workspace Foundation (docs/v15/).

Covers, all offline against the temp_db fixture (conftest.py):
  - schema: new tables, nullable FK columns, REQUIRED_TABLES, SCHEMA_VERSION;
  - database.py Workspace/Milestone/Note CRUD;
  - Storage-Facade delegation;
  - Repository tuple->model mapping;
  - Service: template seeding, progress rollup, flag-gated bootstrap;
  - Migration: projects -> workspaces, idempotent, no data loss;
  - Template registry;
  - the headline guarantee: with WORKSPACE OFF, init_db() creates ZERO
    workspace rows and existing behaviour is byte-identical.
"""
import sqlite3

import pytest

import database as db
from core import feature_flags
from core.storage import Storage
from core.workspace import templates
from core.workspace.models import Milestone, Note, Workspace
from core.workspace.repository import WorkspaceRepository
from core.workspace.service import WorkspaceService


# ── Schema ────────────────────────────────────────────────────────────────

WORKSPACE_TABLES = ["workspaces", "milestones", "notes", "attachments",
                    "tags", "entity_tags"]


def test_workspace_tables_created(temp_db):
    conn = sqlite3.connect(temp_db)
    existing = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    for t in WORKSPACE_TABLES:
        assert t in existing, f"{t} missing after init_db()"


def test_nullable_fk_columns_added(temp_db):
    conn = sqlite3.connect(temp_db)
    task_cols = {r[1] for r in conn.execute("PRAGMA table_info(tasks)")}
    goal_cols = {r[1] for r in conn.execute("PRAGMA table_info(goals)")}
    mem_cols = {r[1] for r in conn.execute("PRAGMA table_info(memories)")}
    conn.close()
    assert "workspace_id" in task_cols
    assert "milestone_id" in task_cols
    assert "workspace_id" in goal_cols
    assert "workspace_id" in mem_cols


def test_required_tables_and_schema_version(temp_db):
    for t in WORKSPACE_TABLES:
        assert t in db.REQUIRED_TABLES
    assert db.SCHEMA_VERSION >= 2
    report = db.verify_schema_integrity(temp_db)
    assert report["ok"], report


def test_init_db_is_idempotent(temp_db):
    # Running init_db() again must not raise or duplicate anything.
    db.init_db()
    db.init_db()
    report = db.verify_schema_integrity(temp_db)
    assert report["ok"], report


# ── Byte-identical guarantee (flag OFF) ───────────────────────────────────

def test_flag_off_creates_no_workspace_rows(temp_db, uid):
    # A normal v14 session (add a task) must leave workspaces empty.
    db.add_task(uid, "buy milk", "2026-07-24")
    conn = sqlite3.connect(temp_db)
    n = conn.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0]
    conn.close()
    assert n == 0


def test_flag_defaults_off():
    # The shipped default must be OFF.
    assert feature_flags._flag("WORKSPACE") is False


def test_existing_task_columns_default_null(temp_db, uid):
    tid = db.add_task(uid, "task", "2026-07-24")
    conn = sqlite3.connect(temp_db)
    ws = conn.execute("SELECT workspace_id, milestone_id FROM tasks WHERE id=?",
                      (tid,)).fetchone()
    conn.close()
    assert ws == (None, None)


# ── database.py CRUD ──────────────────────────────────────────────────────

def test_create_and_get_workspace(temp_db, uid):
    wid = db.create_workspace(uid, "My Book", template="book", icon="📖",
                              metadata={"author": "Cal Newport"})
    row = db.get_workspace(wid, uid)
    assert row[0] == wid
    assert row[2] == "book"
    assert row[3] == "My Book"
    assert row[4] == "active"


def test_get_workspaces_filters_by_status(temp_db, uid):
    a = db.create_workspace(uid, "A")
    db.create_workspace(uid, "B")
    db.archive_workspace(a, uid)
    active = db.get_workspaces(uid, status="active")
    assert {r[3] for r in active} == {"B"}
    every = db.get_workspaces(uid, status=None)
    assert {r[3] for r in every} == {"A", "B"}


def test_get_workspace_by_title_case_insensitive(temp_db, uid):
    db.create_workspace(uid, "Inbox")
    assert db.get_workspace_by_title(uid, "inbox") is not None
    assert db.get_workspace_by_title(uid, "nope") is None


def test_update_workspace_stamps_and_archives(temp_db, uid):
    wid = db.create_workspace(uid, "W")
    db.update_workspace(wid, uid, title="W2", status="archived")
    row = db.get_workspace(wid, uid)
    assert row[3] == "W2"
    assert row[4] == "archived"
    assert row[12] is not None  # archived_at stamped


def test_milestone_crud_and_counts(temp_db, uid):
    wid = db.create_workspace(uid, "Proj", template="project")
    m1 = db.add_milestone(wid, "Research")
    db.add_milestone(wid, "Design")
    assert len(db.get_milestones(wid)) == 2
    assert db.count_milestones(wid) == (2, 0)
    db.update_milestone(m1, status="done")
    assert db.count_milestones(wid) == (2, 1)
    assert db.get_milestone(m1)[8] is not None  # completed_at stamped


def test_note_crud(temp_db, uid):
    wid = db.create_workspace(uid, "W")
    db.add_note(wid, "first", kind="knowledge")
    db.add_note(wid, "second")
    assert len(db.get_notes(wid)) == 2
    assert len(db.get_notes(wid, kind="knowledge")) == 1


# ── Storage Facade ────────────────────────────────────────────────────────

def test_facade_exposes_workspace_domains(temp_db):
    s = Storage()
    assert s.workspaces is not None
    assert s.milestones is not None
    assert s.notes is not None


def test_facade_delegates_byte_for_byte(temp_db, uid):
    s = Storage()
    wid = s.workspaces.create(uid, "Facade WS", template="research")
    assert s.workspaces.get(wid, uid) == db.get_workspace(wid, uid)
    mid = s.milestones.add(wid, "M")
    assert s.milestones.get(mid) == db.get_milestone(mid)
    s.notes.add(wid, "n")
    assert s.notes.list_for(wid) == db.get_notes(wid)


# ── Repository ────────────────────────────────────────────────────────────

def test_repository_maps_rows_to_models(temp_db, uid):
    repo = WorkspaceRepository()
    ws = repo.create_workspace(uid, "R", template="book",
                               metadata={"total_chapters": 10})
    assert isinstance(ws, Workspace)
    assert ws.title == "R"
    assert ws.metadata["total_chapters"] == 10
    assert repo.get_workspace(ws.id, uid) == ws

    ms = repo.add_milestone(ws.id, "chapter")
    assert isinstance(ms, Milestone)
    assert repo.list_milestones(ws.id)[0].title == "chapter"

    note = repo.add_note(ws.id, "hello", kind="note")
    assert isinstance(note, Note)
    assert note.content == "hello"


def test_repository_missing_workspace_is_none(temp_db, uid):
    assert WorkspaceRepository().get_workspace(9999, uid) is None


# ── Service ───────────────────────────────────────────────────────────────

def test_service_seeds_template_milestones(temp_db, uid):
    svc = WorkspaceService()
    ws = svc.create_workspace(uid, "Robot", template="project")
    titles = [m.title for m in svc._repo.list_milestones(ws.id)]
    assert titles == list(templates.get("project").default_milestones)
    assert ws.icon == "🛠"


def test_service_unknown_template_falls_back_to_generic(temp_db, uid):
    svc = WorkspaceService()
    ws = svc.create_workspace(uid, "X", template="does-not-exist")
    assert ws.template == "generic"


def test_service_progress_milestones(temp_db, uid):
    svc = WorkspaceService()
    ws = svc.create_workspace(uid, "P", template="project")  # 5 milestones
    assert svc.workspace_progress(uid, ws.id) == 0
    ms = svc._repo.list_milestones(ws.id)
    svc.complete_milestone(uid, ms[0].id)
    svc.complete_milestone(uid, ms[1].id)
    assert svc.workspace_progress(uid, ws.id) == 40  # 2/5


def test_service_progress_chapters(temp_db, uid):
    svc = WorkspaceService()
    ws = svc.create_workspace(uid, "Book", template="book", seed_milestones=False,
                              metadata={"total_chapters": 8, "current_chapter": 6})
    assert svc.workspace_progress(uid, ws.id) == 75


def test_service_progress_manual(temp_db, uid):
    svc = WorkspaceService()
    ws = svc.create_workspace(uid, "R", template="research",
                              metadata={"progress": 42})
    assert svc.workspace_progress(uid, ws.id) == 42


def test_service_ensure_inbox_idempotent(temp_db, uid):
    svc = WorkspaceService()
    a = svc.ensure_inbox(uid)
    b = svc.ensure_inbox(uid)
    assert a.id == b.id
    assert a.title == "Inbox"
    assert len(db.get_workspaces(uid, status=None)) == 1


def test_bootstrap_noop_when_flag_off(temp_db, uid):
    svc = WorkspaceService()
    assert feature_flags.WORKSPACE is False
    result = svc.bootstrap(uid)
    assert result["skipped"] is True
    assert db.get_workspaces(uid, status=None) == []


def test_bootstrap_runs_when_flag_on(temp_db, uid, monkeypatch):
    monkeypatch.setattr(feature_flags, "WORKSPACE", True)
    svc = WorkspaceService()
    result = svc.bootstrap(uid)
    assert result["skipped"] is False
    assert db.get_workspace_by_title(uid, "Inbox") is not None


# ── Migration ─────────────────────────────────────────────────────────────

def test_migrate_projects_creates_workspace_and_links_goal(temp_db, uid):
    gid = db.add_goal(uid, "Build a drone")
    db.add_materials(uid, gid, ["motor", "frame"])  # makes it a project-goal
    created = db.migrate_projects_to_workspaces(uid)
    assert created == 1
    ws = db.get_workspace_by_title(uid, "Build a drone")
    assert ws is not None
    assert ws[2] == "project"
    # goal is now linked
    conn = sqlite3.connect(temp_db)
    linked = conn.execute("SELECT workspace_id FROM goals WHERE id=?",
                          (gid,)).fetchone()[0]
    conn.close()
    assert linked == ws[0]


def test_migrate_projects_is_idempotent(temp_db, uid):
    gid = db.add_goal(uid, "P")
    db.add_worklog(uid, gid, "started")
    assert db.migrate_projects_to_workspaces(uid) == 1
    assert db.migrate_projects_to_workspaces(uid) == 0  # nothing new
    assert len(db.get_workspaces(uid, status=None)) == 1


def test_migrate_ignores_plain_goals(temp_db, uid):
    db.add_goal(uid, "just a goal, no materials or worklog")
    assert db.migrate_projects_to_workspaces(uid) == 0


def test_migration_preserves_goal_and_material_rows(temp_db, uid):
    gid = db.add_goal(uid, "Keep me")
    db.add_materials(uid, gid, ["x"])
    db.migrate_projects_to_workspaces(uid)
    # Original rows untouched (referenced, not moved).
    assert db.get_goals(uid)  # goal still there
    assert db.get_materials(uid, gid)  # materials still there


# ── Template registry ─────────────────────────────────────────────────────

def test_template_registry_builtins_present():
    for key in ("generic", "project", "book", "course", "research", "game"):
        assert templates.exists(key), key


def test_template_get_unknown_falls_back():
    assert templates.get("nonsense").key == "generic"


def test_template_all_and_keys_consistent():
    assert set(templates.keys()) == {t.key for t in templates.all_templates()}
