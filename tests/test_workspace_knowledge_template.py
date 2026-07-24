"""
Tests for v15.0-beta.3 -- the Knowledge Workspace template.

Second application of the beta.2 thesis: a full new Workspace type (this
time an educational/knowledge domain) is added purely through the existing
extension points, and flows through the UNCHANGED Workspace OS (Entity
Engine -> Timeline -> Sync) exactly like any other workspace. Covers
template registration, the metadata schema, validation rules, the
validating create helper, and the end-to-end pipeline.
"""
import pytest

import database as db
from core.workspace import templates
from core.workspace.engine import EntityEngine
from core.workspace.errors import EntityValidationError
from core.workspace.sync import SyncEngine
from core.workspace.adapters.telegram import TelegramAdapter
from core.workspace.templates import knowledge
from core.workspace.templates.knowledge import (
    KNOWLEDGE_KEY,
    KNOWLEDGE_STATUSES,
    create_knowledge_workspace,
    default_metadata,
    normalize_knowledge_metadata,
    validate_knowledge_metadata,
)
from core.workspace.timeline import TimelineEngine


# ── Registration (the extension point) ────────────────────────────────────

def test_knowledge_template_registered():
    assert templates.exists(KNOWLEDGE_KEY)
    tpl = templates.get(KNOWLEDGE_KEY)
    assert tpl.key == "knowledge"
    assert tpl.icon == "🧠"
    assert tpl.label == "Knowledge"
    assert "concepts" in tpl.sections


def test_knowledge_template_metadata_fields():
    tpl = templates.get(KNOWLEDGE_KEY)
    assert set(tpl.metadata_fields) == {
        "domain", "source", "status", "items_reviewed", "progress"}


def test_knowledge_registered_alongside_game_without_collision():
    # Both drop-in templates coexist; adding one did not disturb the other.
    assert templates.exists("game")
    assert templates.exists("knowledge")
    assert templates.get("knowledge").key != templates.get("game").key


# ── Metadata schema + defaults ────────────────────────────────────────────

def test_default_metadata_has_status_exploring():
    meta = default_metadata()
    assert meta["status"] == "exploring"
    assert meta["items_reviewed"] == 0
    assert meta["progress"] == 0


# ── Validation rules ──────────────────────────────────────────────────────

def test_valid_metadata_passes():
    assert validate_knowledge_metadata(
        {"domain": "Distributed Systems", "source": "book",
         "status": "learning", "items_reviewed": 12, "progress": 40}) == []


def test_invalid_status_rejected():
    errs = validate_knowledge_metadata({"status": "kinda-known"})
    assert errs and "status" in errs[0]


def test_negative_items_reviewed_rejected():
    assert validate_knowledge_metadata({"items_reviewed": -3})


def test_progress_out_of_range_rejected():
    assert validate_knowledge_metadata({"progress": 150})
    assert validate_knowledge_metadata({"progress": -1})


def test_non_int_field_rejected():
    assert validate_knowledge_metadata({"items_reviewed": "many"})


def test_bool_is_not_int():
    assert validate_knowledge_metadata({"items_reviewed": True})


def test_non_str_domain_rejected():
    assert validate_knowledge_metadata({"domain": 42})


def test_all_statuses_are_valid():
    for s in KNOWLEDGE_STATUSES:
        assert validate_knowledge_metadata({"status": s}) == []


def test_normalize_fills_defaults_and_coerces():
    meta = normalize_knowledge_metadata({"domain": "Algebra", "items_reviewed": "9"})
    assert meta["status"] == "exploring"      # default filled
    assert meta["items_reviewed"] == 9        # coerced to int
    assert meta["domain"] == "Algebra"


# ── Validating create helper (template-local, OS unchanged) ───────────────

def test_create_knowledge_workspace_valid(temp_db, uid):
    eng = EntityEngine()
    ws = create_knowledge_workspace(eng, uid, "Category Theory",
                                    metadata={"domain": "Math", "status": "learning"})
    assert ws.template == "knowledge"
    assert ws.icon == "🧠"
    assert ws.metadata["status"] == "learning"
    assert ws.metadata["progress"] == 0       # default filled


def test_create_knowledge_workspace_rejects_bad_metadata(temp_db, uid):
    eng = EntityEngine()
    with pytest.raises(EntityValidationError):
        create_knowledge_workspace(eng, uid, "Bad", metadata={"progress": 999})


def test_create_knowledge_workspace_no_milestones_by_default(temp_db, uid):
    eng = EntityEngine()
    ws = create_knowledge_workspace(eng, uid, "Rust Ownership")
    assert db.get_milestones(ws.id) == []


# ── The OS is unchanged: knowledge flows through the generic engine ───────

def test_knowledge_mastery_uses_manual_model(temp_db, uid):
    # mastery% lives in metadata['progress']; the engine's PROGRESS_MANUAL
    # model reads it -- no knowledge-specific code in the engine.
    eng = EntityEngine()
    ws = create_knowledge_workspace(eng, uid, "Optics", metadata={"progress": 65})
    assert eng.workspace_progress(uid, ws.id) == 65


def test_knowledge_concepts_are_generic_milestones(temp_db, uid):
    # "concepts" map onto milestones -- the generic entity, unchanged.
    eng = EntityEngine()
    ws = create_knowledge_workspace(eng, uid, "Linear Algebra")
    eng.add_milestone(uid, ws.id, "Understand eigenvectors")
    eng.complete_milestone(uid, [m.id for m in eng.list_milestones(uid, ws.id)][0])
    assert eng.list_milestones(uid, ws.id)[0].status == "done"


def test_knowledge_flows_through_engine_timeline_sync(temp_db, uid):
    # End-to-end: a knowledge workspace is created + synced exactly like any
    # other workspace, proving zero special-casing in the OS.
    te = TimelineEngine()
    eng = EntityEngine(on_event=te.record)
    ws = create_knowledge_workspace(eng, uid, "Thermodynamics",
                                    metadata={"status": "learning"})
    events = [e.event_type for e in te.timeline(uid, workspace_id=ws.id)]
    assert "workspace.created" in events

    calls = []
    sync = SyncEngine(adapters=[TelegramAdapter(
        lambda u, t, tid: calls.append(t) or 1)])
    report = sync.sync(uid)
    assert report["sent"] >= 1 and calls


# ── Pattern check: knowledge added without touching OS registry internals ──

def test_knowledge_module_only_uses_public_registry_api():
    # knowledge.py registers itself and imports ONLY the public extension
    # surface (the registry + the OS error type) -- the same tools any
    # future template gets. Checked against actual imports, not docstring
    # prose.
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(knowledge))
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
            f"knowledge template should not import {forbidden}"
    assert "core.workspace.templates.registry" in imported
