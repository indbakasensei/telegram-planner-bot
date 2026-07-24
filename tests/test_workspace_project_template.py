"""
Tests for v15.0-beta.5 -- the Project Workspace template.

Fourth application of the beta.2 thesis, against an EXECUTION-focused
domain: a project driven to completion through a milestone pipeline,
represented purely through template metadata + generic Workspace entities,
flowing through the UNCHANGED Workspace OS. This module also OWNS the
"project" template (moved out of builtin.py), so these tests additionally
guard that the migration preserved the template's shape and that the
alpha.3 ProjectAdapter bridge still works.
"""
import pytest

from core import feature_flags
from core.workspace import templates
from core.workspace.engine import EntityEngine
from core.workspace.errors import EntityValidationError
from core.workspace.orchestrator import Status, WorkspaceOrchestrator
from core.workspace.project_adapter import ProjectAdapter
from core.workspace.sync import SyncEngine
from core.workspace.adapters.telegram import TelegramAdapter
from core.workspace.templates import project
from core.workspace.templates.project import (
    PROJECT_DEFAULT_MILESTONES,
    PROJECT_KEY,
    PROJECT_PRIORITIES,
    PROJECT_STATUSES,
    create_project_workspace,
    default_metadata,
    normalize_project_metadata,
    validate_project_metadata,
)
from core.workspace.timeline import TimelineEngine


# ── Registration + migration-preserved shape ──────────────────────────────

def test_project_template_registered():
    assert templates.exists(PROJECT_KEY)
    tpl = templates.get(PROJECT_KEY)
    assert tpl.key == "project"
    assert tpl.icon == "🛠"
    assert tpl.label == "Project"


def test_project_shape_preserved_after_move_from_builtin():
    # The move into project.py must not change the icon, sections, default
    # pipeline, or progress model that existing tests + ProjectAdapter rely on.
    tpl = templates.get(PROJECT_KEY)
    assert tpl.default_milestones == (
        "Research", "Design", "Prototype", "Testing", "Documentation")
    assert tpl.default_milestones == PROJECT_DEFAULT_MILESTONES
    assert set(tpl.sections) == {
        "goals", "milestones", "tasks", "materials", "worklog", "files"}
    assert tpl.progress_model == "milestones"


def test_project_metadata_fields():
    tpl = templates.get(PROJECT_KEY)
    assert set(tpl.metadata_fields) == {"status", "priority", "target_date"}


def test_project_coexists_with_other_drop_in_templates():
    for key in ("game", "knowledge", "asset", "project"):
        assert templates.exists(key)


def test_still_registered_as_builtin_present():
    # The foundation "builtins present" guarantee still holds post-migration.
    for key in ("generic", "project", "book", "course", "research", "game"):
        assert templates.exists(key)


# ── Metadata schema + defaults ────────────────────────────────────────────

def test_default_metadata_fills_status_and_priority():
    meta = default_metadata()
    assert meta["status"] == "planning"
    assert meta["priority"] == "medium"


# ── Validation rules ──────────────────────────────────────────────────────

def test_valid_metadata_passes():
    assert validate_project_metadata({
        "status": "active", "priority": "high", "target_date": "2026-12-01"}) == []


def test_invalid_status_rejected():
    errs = validate_project_metadata({"status": "sorta-going"})
    assert errs and "status" in errs[0]


def test_invalid_priority_rejected():
    assert validate_project_metadata({"priority": "urgent-ish"})


def test_non_str_target_date_rejected():
    assert validate_project_metadata({"target_date": 20261201})


def test_all_enum_values_are_valid():
    for s in PROJECT_STATUSES:
        assert validate_project_metadata({"status": s}) == []
    for p in PROJECT_PRIORITIES:
        assert validate_project_metadata({"priority": p}) == []


def test_target_date_is_optional_free_form():
    assert validate_project_metadata({"status": "active", "target_date": "next Q2"}) == []


# ── Normalization (enums + strings) ───────────────────────────────────────

def test_normalize_lowercases_and_trims_enums():
    meta = normalize_project_metadata({"status": " Active ", "priority": "HIGH"})
    assert meta["status"] == "active"
    assert meta["priority"] == "high"


def test_normalize_trims_target_date_and_fills_defaults():
    meta = normalize_project_metadata({"target_date": "  2027-01-01  "})
    assert meta["target_date"] == "2027-01-01"
    assert meta["status"] == "planning"      # default filled
    assert meta["priority"] == "medium"


# ── Validating create helper (normalize-then-validate; OS unchanged) ──────

def test_create_project_seeds_default_pipeline(temp_db, uid):
    # Execution focus: milestones are seeded by default.
    eng = EntityEngine()
    ws = create_project_workspace(eng, uid, "Rover")
    assert ws.template == "project"
    assert ws.icon == "🛠"
    titles = [m.title for m in eng.list_milestones(uid, ws.id)]
    assert titles == list(PROJECT_DEFAULT_MILESTONES)


def test_create_project_without_seeding(temp_db, uid):
    eng = EntityEngine()
    ws = create_project_workspace(eng, uid, "Empty", seed_milestones=False)
    assert eng.list_milestones(uid, ws.id) == []


def test_create_accepts_mixed_case_enums(temp_db, uid):
    eng = EntityEngine()
    ws = create_project_workspace(eng, uid, "Launch",
                                  metadata={"status": "Active", "priority": " High "},
                                  seed_milestones=False)
    assert ws.metadata["status"] == "active"
    assert ws.metadata["priority"] == "high"


def test_create_rejects_bad_status(temp_db, uid):
    eng = EntityEngine()
    with pytest.raises(EntityValidationError):
        create_project_workspace(eng, uid, "Bad", metadata={"status": "whenever"})


# ── The OS is unchanged: execution progress = milestone rollup ────────────

def test_project_progress_is_milestone_completion(temp_db, uid):
    eng = EntityEngine()
    ws = create_project_workspace(eng, uid, "Pipeline")   # 5 seeded milestones
    assert eng.workspace_progress(uid, ws.id) == 0
    ms = eng.list_milestones(uid, ws.id)
    eng.complete_milestone(uid, ms[0].id)
    eng.complete_milestone(uid, ms[1].id)
    assert eng.workspace_progress(uid, ws.id) == 40      # 2 of 5


# ── AI interaction: the generic Orchestrator drives a project workspace ───

def test_orchestrator_adds_milestone_to_project(temp_db, uid):
    eng = EntityEngine()
    ws = create_project_workspace(eng, uid, "App", seed_milestones=False)
    orch = WorkspaceOrchestrator(engine=eng)
    res = orch.handle(uid, "add milestone: Ship v1", active_workspace_id=ws.id)
    assert res.status == Status.APPLIED
    assert [m.title for m in eng.list_milestones(uid, ws.id)] == ["Ship v1"]


# ── The alpha.3 ProjectAdapter bridge still works post-migration ──────────

def test_project_adapter_still_creates_project_workspaces(temp_db, uid, monkeypatch):
    # The v14 Project<->Workspace bridge creates template='project'
    # workspaces; moving the template into project.py must not break it.
    monkeypatch.setattr(feature_flags, "WORKSPACE", True)
    adapter = ProjectAdapter()
    view = adapter.create_project(uid, "Bridge Project", deadline="2026-10-01")
    assert view.workspace.template == "project"
    assert adapter.get_project(uid, view.workspace.id) is not None


# ── End-to-end: create -> Timeline -> Sync, like any other workspace ──────

def test_project_flows_through_engine_timeline_sync(temp_db, uid):
    te = TimelineEngine()
    eng = EntityEngine(on_event=te.record)
    ws = create_project_workspace(eng, uid, "Beta Launch", seed_milestones=False)
    events = [e.event_type for e in te.timeline(uid, workspace_id=ws.id)]
    assert "workspace.created" in events

    calls = []
    sync = SyncEngine(adapters=[TelegramAdapter(
        lambda u, t, tid: calls.append(t) or 1)])
    report = sync.sync(uid)
    assert report["sent"] >= 1 and calls


# ── Pattern check: project added without touching OS registry internals ───

def test_project_module_only_uses_public_registry_api():
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(project))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
    for forbidden in ("database", "core.workspace.engine",
                      "core.workspace.orchestrator", "core.workspace.sync",
                      "core.workspace.timeline", "core.workspace.repository",
                      "core.workspace.project_adapter"):
        assert forbidden not in imported, \
            f"project template should not import {forbidden}"
    assert "core.workspace.templates.registry" in imported
