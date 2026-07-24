"""
Tests for v15.0-beta.4 -- the Asset Workspace template.

Third application of the beta.2 thesis, and the broadest: ONE reusable
template represents any owned physical asset (vehicle/computer/drone/robot/
...) purely through template metadata + generic Workspace entities, flowing
through the UNCHANGED Workspace OS (Entity Engine -> Orchestrator ->
Timeline -> Sync). Covers registration, coexistence with Game + Knowledge,
the metadata schema, validation, normalization (enum + string), the
validating create helper, generic AI interaction, timeline, sync, and AST
purity.
"""
import pytest

import database as db
from core.workspace import templates
from core.workspace.engine import EntityEngine
from core.workspace.errors import EntityValidationError
from core.workspace.orchestrator import Status, WorkspaceOrchestrator
from core.workspace.sync import SyncEngine
from core.workspace.adapters.telegram import TelegramAdapter
from core.workspace.templates import asset
from core.workspace.templates.asset import (
    ASSET_CONDITIONS,
    ASSET_KEY,
    ASSET_STATUSES,
    ASSET_TYPES,
    create_asset_workspace,
    default_metadata,
    normalize_asset_metadata,
    validate_asset_metadata,
)
from core.workspace.timeline import TimelineEngine


# ── Registration (the extension point) ────────────────────────────────────

def test_asset_template_registered():
    assert templates.exists(ASSET_KEY)
    tpl = templates.get(ASSET_KEY)
    assert tpl.key == "asset"
    assert tpl.icon == "📦"
    assert tpl.label == "Asset"
    assert "maintenance" in tpl.sections


def test_asset_template_metadata_fields():
    tpl = templates.get(ASSET_KEY)
    assert set(tpl.metadata_fields) == {
        "asset_type", "status", "condition", "manufacturer", "model",
        "serial_number", "purchase_date", "warranty_expiry", "location"}


def test_asset_coexists_with_game_and_knowledge():
    # Three independent drop-in templates registered side by side.
    for key in ("game", "knowledge", "asset"):
        assert templates.exists(key)
    keys = {templates.get(k).key for k in ("game", "knowledge", "asset")}
    assert keys == {"game", "knowledge", "asset"}


def test_one_template_covers_every_asset_kind():
    # The point of the milestone: no per-type template -- the kind is metadata.
    assert set(ASSET_TYPES) >= {
        "vehicle", "computer", "drone", "robot", "equipment", "tool"}
    # ...but there is exactly one registered asset template.
    asset_templates = [t for t in templates.all_templates() if t.key == "asset"]
    assert len(asset_templates) == 1


# ── Metadata schema + defaults ────────────────────────────────────────────

def test_default_metadata_fills_status_and_condition_not_type():
    meta = default_metadata()
    assert meta["status"] == "active"
    assert meta["condition"] == "good"
    assert "asset_type" not in meta        # required, no default


# ── Validation rules ──────────────────────────────────────────────────────

def test_asset_type_is_required():
    errs = validate_asset_metadata({"status": "active"})
    assert errs and "asset_type" in errs[0]


def test_valid_metadata_passes():
    assert validate_asset_metadata({
        "asset_type": "drone", "status": "active", "condition": "excellent",
        "manufacturer": "DJI", "model": "Mavic 3",
        "warranty_expiry": "2028-01-01"}) == []


def test_invalid_asset_type_rejected():
    errs = validate_asset_metadata({"asset_type": "spaceship"})
    assert errs and "asset_type" in errs[0]


def test_invalid_status_rejected():
    assert validate_asset_metadata({"asset_type": "tool", "status": "melted"})


def test_invalid_condition_rejected():
    assert validate_asset_metadata({"asset_type": "tool", "condition": "mint"})


def test_non_str_manufacturer_rejected():
    assert validate_asset_metadata({"asset_type": "tool", "manufacturer": 5})


def test_all_enum_values_are_valid():
    for t in ASSET_TYPES:
        assert validate_asset_metadata({"asset_type": t}) == []
    for s in ASSET_STATUSES:
        assert validate_asset_metadata({"asset_type": "tool", "status": s}) == []
    for c in ASSET_CONDITIONS:
        assert validate_asset_metadata({"asset_type": "tool", "condition": c}) == []


def test_dates_are_optional_free_form_strings():
    assert validate_asset_metadata({
        "asset_type": "vehicle", "purchase_date": "sometime in 2019",
        "warranty_expiry": ""}) == []


# ── Normalization (enums + strings) ───────────────────────────────────────

def test_normalize_lowercases_and_trims_enums():
    meta = normalize_asset_metadata(
        {"asset_type": " Vehicle ", "status": "ACTIVE", "condition": "Good"})
    assert meta["asset_type"] == "vehicle"
    assert meta["status"] == "active"
    assert meta["condition"] == "good"


def test_normalize_trims_string_fields():
    meta = normalize_asset_metadata(
        {"asset_type": "drone", "manufacturer": "  DJI  ", "location": " Garage "})
    assert meta["manufacturer"] == "DJI"
    assert meta["location"] == "Garage"


def test_normalize_fills_enum_defaults():
    meta = normalize_asset_metadata({"asset_type": "tool"})
    assert meta["status"] == "active"
    assert meta["condition"] == "good"


# ── Validating create helper (normalize-then-validate; OS unchanged) ──────

def test_create_asset_workspace_valid(temp_db, uid):
    eng = EntityEngine()
    ws = create_asset_workspace(eng, uid, "Tesla Model 3",
                                metadata={"asset_type": "vehicle", "manufacturer": "Tesla"})
    assert ws.template == "asset"
    assert ws.icon == "📦"
    assert ws.metadata["asset_type"] == "vehicle"
    assert ws.metadata["status"] == "active"       # default filled
    assert ws.metadata["condition"] == "good"      # default filled


def test_create_accepts_mixed_case_enums(temp_db, uid):
    # normalize-then-validate: human-entered 'Drone' / ' Stored ' are accepted.
    eng = EntityEngine()
    ws = create_asset_workspace(eng, uid, "Mavic",
                                metadata={"asset_type": "Drone", "status": " Stored "})
    assert ws.metadata["asset_type"] == "drone"
    assert ws.metadata["status"] == "stored"


def test_create_rejects_missing_asset_type(temp_db, uid):
    eng = EntityEngine()
    with pytest.raises(EntityValidationError):
        create_asset_workspace(eng, uid, "Mystery box", metadata={"status": "active"})


def test_create_rejects_unknown_asset_type(temp_db, uid):
    eng = EntityEngine()
    with pytest.raises(EntityValidationError):
        create_asset_workspace(eng, uid, "UFO", metadata={"asset_type": "spaceship"})


def test_create_asset_workspace_no_milestones_by_default(temp_db, uid):
    eng = EntityEngine()
    ws = create_asset_workspace(eng, uid, "Drill", metadata={"asset_type": "tool"})
    assert db.get_milestones(ws.id) == []


# ── The OS is unchanged: assets flow through the generic engine ───────────

def test_maintenance_are_generic_milestones(temp_db, uid):
    # maintenance/repairs/upgrades map onto milestones -- the generic entity.
    eng = EntityEngine()
    ws = create_asset_workspace(eng, uid, "Civic", metadata={"asset_type": "vehicle"})
    eng.add_milestone(uid, ws.id, "Oil change")
    eng.complete_milestone(uid, [m.id for m in eng.list_milestones(uid, ws.id)][0])
    assert eng.list_milestones(uid, ws.id)[0].status == "done"


def test_asset_progress_is_maintenance_completion(temp_db, uid):
    # progress = share of maintenance milestones done, via the generic
    # PROGRESS_MILESTONES rollup -- no asset-specific progress code.
    eng = EntityEngine()
    ws = create_asset_workspace(eng, uid, "Printer", metadata={"asset_type": "appliance"})
    eng.add_milestone(uid, ws.id, "Replace drum")
    eng.add_milestone(uid, ws.id, "Clean rollers")
    assert eng.workspace_progress(uid, ws.id) == 0
    eng.complete_milestone(uid, eng.list_milestones(uid, ws.id)[0].id)
    assert eng.workspace_progress(uid, ws.id) == 50


# ── AI interaction: the generic Orchestrator drives an asset workspace ────

def test_orchestrator_adds_maintenance_milestone_to_asset(temp_db, uid):
    # "My car needs an oil change" -> a maintenance milestone, handled by the
    # generic orchestrator with NO asset-specific logic.
    eng = EntityEngine()
    ws = create_asset_workspace(eng, uid, "My Car", metadata={"asset_type": "vehicle"})
    orch = WorkspaceOrchestrator(engine=eng)   # default RuleBasedInterpreter
    res = orch.handle(uid, "add milestone: Oil change", active_workspace_id=ws.id)
    assert res.status == Status.APPLIED
    assert [m.title for m in eng.list_milestones(uid, ws.id)] == ["Oil change"]


def test_orchestrator_adds_service_note_to_asset(temp_db, uid):
    # "I replaced the battery" -> a service-record note, generic path.
    eng = EntityEngine()
    ws = create_asset_workspace(eng, uid, "My Car", metadata={"asset_type": "vehicle"})
    orch = WorkspaceOrchestrator(engine=eng)
    res = orch.handle(uid, "note: Replaced the battery", active_workspace_id=ws.id)
    assert res.status == Status.APPLIED
    assert eng.list_notes(uid, ws.id)


def test_orchestrator_creates_asset_via_generic_create(temp_db, uid):
    # "I bought a new drone" -> create workspace, through the generic
    # create path (template defaults to generic; the point is no asset code
    # lives in the orchestrator).
    eng = EntityEngine()
    orch = WorkspaceOrchestrator(engine=eng)
    res = orch.handle(uid, "create workspace: New Drone")
    assert res.status == Status.APPLIED
    assert res.workspace.title == "New Drone"


# ── End-to-end: create -> Timeline -> Sync, like any other workspace ──────

def test_asset_flows_through_engine_timeline_sync(temp_db, uid):
    te = TimelineEngine()
    eng = EntityEngine(on_event=te.record)
    ws = create_asset_workspace(eng, uid, "Forklift",
                                metadata={"asset_type": "equipment"})
    events = [e.event_type for e in te.timeline(uid, workspace_id=ws.id)]
    assert "workspace.created" in events

    calls = []
    sync = SyncEngine(adapters=[TelegramAdapter(
        lambda u, t, tid: calls.append(t) or 1)])
    report = sync.sync(uid)
    assert report["sent"] >= 1 and calls


# ── Pattern check: asset added without touching OS registry internals ─────

def test_asset_module_only_uses_public_registry_api():
    # asset.py registers itself and imports ONLY the public extension
    # surface (the registry + the OS error type) -- checked against actual
    # imports, not docstring prose.
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(asset))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
    for forbidden in ("database", "core.workspace.engine",
                      "core.workspace.orchestrator", "core.workspace.sync",
                      "core.workspace.timeline", "core.workspace.repository"):
        assert forbidden not in imported, \
            f"asset template should not import {forbidden}"
    assert "core.workspace.templates.registry" in imported
