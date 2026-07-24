"""
Tests for v15.0-beta.2 -- the Game Workspace template (reference
implementation).

The thesis under test: a full new Workspace type is added purely through
the existing extension points, and it flows through the UNCHANGED Workspace
OS (Entity Engine -> Timeline -> Sync) exactly like any other workspace.
Covers template registration, the metadata schema, validation rules, the
validating create helper, and the end-to-end pipeline.
"""
import pytest

import database as db
from core.workspace import templates
from core.workspace.engine import EntityEngine
from core.workspace.errors import EntityValidationError
from core.workspace.sync import SyncEngine
from core.workspace.adapters.telegram import TelegramAdapter
from core.workspace.templates import game
from core.workspace.templates.game import (
    GAME_KEY,
    GAME_STATUSES,
    create_game_workspace,
    default_metadata,
    normalize_game_metadata,
    validate_game_metadata,
)
from core.workspace.timeline import TimelineEngine


# ── Registration (the extension point) ────────────────────────────────────

def test_game_template_registered():
    assert templates.exists(GAME_KEY)
    tpl = templates.get(GAME_KEY)
    assert tpl.key == "game"
    assert tpl.icon == "🎮"
    assert tpl.label == "Game"
    assert "objectives" in tpl.sections


def test_game_template_metadata_fields():
    tpl = templates.get(GAME_KEY)
    assert set(tpl.metadata_fields) == {"platform", "status", "hours_played", "progress"}


# ── Metadata schema + defaults ────────────────────────────────────────────

def test_default_metadata_has_status_backlog():
    meta = default_metadata()
    assert meta["status"] == "backlog"
    assert meta["hours_played"] == 0
    assert meta["progress"] == 0


# ── Validation rules ──────────────────────────────────────────────────────

def test_valid_metadata_passes():
    assert validate_game_metadata(
        {"platform": "PC", "status": "playing", "hours_played": 12, "progress": 40}) == []


def test_invalid_status_rejected():
    errs = validate_game_metadata({"status": "finished-ish"})
    assert errs and "status" in errs[0]


def test_negative_hours_rejected():
    assert validate_game_metadata({"hours_played": -3})


def test_progress_out_of_range_rejected():
    assert validate_game_metadata({"progress": 150})
    assert validate_game_metadata({"progress": -1})


def test_non_int_field_rejected():
    assert validate_game_metadata({"hours_played": "lots"})


def test_bool_is_not_int():
    assert validate_game_metadata({"hours_played": True})


def test_all_statuses_are_valid():
    for s in GAME_STATUSES:
        assert validate_game_metadata({"status": s}) == []


def test_normalize_fills_defaults_and_coerces():
    meta = normalize_game_metadata({"platform": "Switch", "hours_played": "9"})
    assert meta["status"] == "backlog"        # default filled
    assert meta["hours_played"] == 9          # coerced to int
    assert meta["platform"] == "Switch"


# ── Validating create helper (template-local, OS unchanged) ───────────────

def test_create_game_workspace_valid(temp_db, uid):
    eng = EntityEngine()
    ws = create_game_workspace(eng, uid, "Hollow Knight",
                               metadata={"platform": "PC", "status": "playing"})
    assert ws.template == "game"
    assert ws.icon == "🎮"
    assert ws.metadata["status"] == "playing"
    assert ws.metadata["progress"] == 0       # default filled


def test_create_game_workspace_rejects_bad_metadata(temp_db, uid):
    eng = EntityEngine()
    with pytest.raises(EntityValidationError):
        create_game_workspace(eng, uid, "Bad", metadata={"progress": 999})


def test_create_game_workspace_no_milestones_by_default(temp_db, uid):
    eng = EntityEngine()
    ws = create_game_workspace(eng, uid, "Celeste")
    assert db.get_milestones(ws.id) == []


# ── The OS is unchanged: game flows through the generic engine ────────────

def test_game_progress_uses_manual_model(temp_db, uid):
    # completion% lives in metadata['progress']; the engine's PROGRESS_MANUAL
    # model reads it -- no game-specific code in the engine.
    eng = EntityEngine()
    ws = create_game_workspace(eng, uid, "Celeste", metadata={"progress": 65})
    assert eng.workspace_progress(uid, ws.id) == 65


def test_game_objectives_are_generic_milestones(temp_db, uid):
    # "objectives" map onto milestones -- the generic entity, unchanged.
    eng = EntityEngine()
    ws = create_game_workspace(eng, uid, "Elden Ring")
    eng.add_milestone(uid, ws.id, "Beat Margit")
    eng.complete_milestone(uid, [m.id for m in eng.list_milestones(uid, ws.id)][0])
    assert eng.list_milestones(uid, ws.id)[0].status == "done"


def test_game_flows_through_engine_timeline_sync(temp_db, uid):
    # End-to-end: a game workspace is created + synced exactly like any
    # other workspace, proving zero special-casing in the OS.
    te = TimelineEngine()
    eng = EntityEngine(on_event=te.record)
    ws = create_game_workspace(eng, uid, "Zelda", metadata={"status": "playing"})
    events = [e.event_type for e in te.timeline(uid, workspace_id=ws.id)]
    assert "workspace.created" in events

    calls = []
    sync = SyncEngine(adapters=[TelegramAdapter(
        lambda u, t, tid: calls.append(t) or 1)])
    report = sync.sync(uid)
    assert report["sent"] >= 1 and calls


# ── Pattern check: game added without touching OS registry internals ──────

def test_game_module_only_uses_public_registry_api():
    # game.py registers itself and imports ONLY the public extension
    # surface (the registry + the OS error type) -- the same tools any
    # future template gets. Checked against actual imports (the module's
    # own top-level import statements), not docstring prose.
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(game))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
    # It must not import the OS internals -- only templates.registry + errors.
    for forbidden in ("database", "core.workspace.engine",
                      "core.workspace.orchestrator", "core.workspace.sync",
                      "core.workspace.timeline", "core.workspace.repository"):
        assert forbidden not in imported, \
            f"game template should not import {forbidden}"
    assert "core.workspace.templates.registry" in imported
