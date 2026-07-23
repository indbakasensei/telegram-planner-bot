"""
Tests for v15.0-alpha.7 -- the AI Workspace Orchestrator
(core/workspace/orchestrator.py).

All offline: no live LLM/NIM. The orchestrator consumes an injected
`Interpreter`; these tests use the shipped deterministic
`RuleBasedInterpreter` and a `StubInterpreter` returning fixed Proposals to
exercise the resolver pipeline in isolation. Proves generic NL -> validated
Entity Engine op: workspace/entity resolution + clarification, the safety
gate (confirm irreversible), AI-proposes/engine-validates, graceful
degradation, and the full orchestrator -> engine -> timeline cascade.
"""
import pytest

import database as db
from core.workspace.engine import EntityEngine
from core.workspace.orchestrator import (
    Action,
    OrchestratorContext,
    Proposal,
    RuleBasedInterpreter,
    Status,
    WorkspaceOrchestrator,
)
from core.workspace.timeline import TimelineEngine


OTHER = 707070707


class StubInterpreter:
    """Returns a fixed Proposal regardless of the utterance."""
    def __init__(self, proposal):
        self._p = proposal
    def interpret(self, utterance, context):
        return self._p


def orch(interpreter=None):
    return WorkspaceOrchestrator(interpreter=interpreter)


# ── RuleBasedInterpreter (generic parsing) ────────────────────────────────

@pytest.mark.parametrize("text,action", [
    ("create workspace Robot", Action.CREATE_WORKSPACE),
    ("add milestone Design", Action.ADD_MILESTONE),
    ("complete milestone Design", Action.COMPLETE_MILESTONE),
    ("archive milestone Design", Action.ARCHIVE_MILESTONE),
    ("delete milestone Design", Action.DELETE_MILESTONE),
    ("note: remember the thing", Action.ADD_NOTE),
    ("archive workspace", Action.ARCHIVE_WORKSPACE),
    ("complete workspace", Action.COMPLETE_WORKSPACE),
    ("rename to NewName", Action.RENAME_WORKSPACE),
    ("blah blah nonsense", Action.UNKNOWN),
])
def test_rule_based_actions(text, action):
    p = RuleBasedInterpreter().interpret(text, OrchestratorContext(1))
    assert p.action == action


def test_rule_based_in_prefix_sets_workspace_ref():
    p = RuleBasedInterpreter().interpret("in Robot, add milestone Wiring",
                                         OrchestratorContext(1))
    assert p.action == Action.ADD_MILESTONE
    assert p.workspace_ref == "Robot"
    assert p.params["title"] == "Wiring"


# ── create ────────────────────────────────────────────────────────────────

def test_create_workspace_end_to_end(temp_db, uid):
    res = orch().handle(uid, "create workspace Robot")
    assert res.ok and res.status == Status.APPLIED
    assert res.workspace.title == "Robot"
    assert db.get_workspace_by_title(uid, "Robot") is not None


def test_create_without_title_asks(temp_db, uid):
    res = orch(StubInterpreter(Proposal(Action.CREATE_WORKSPACE))).handle(uid, "x")
    assert res.status == Status.NEEDS_CLARIFICATION


# ── workspace selection ───────────────────────────────────────────────────

def test_active_workspace_used_when_no_ref(temp_db, uid):
    eng = EntityEngine()
    ws = eng.create_workspace(uid, "Robot")
    o = WorkspaceOrchestrator(engine=eng)
    res = o.handle(uid, "add milestone Wiring", active_workspace_id=ws.id)
    assert res.ok
    assert [m.title for m in eng.list_milestones(uid, ws.id)] == ["Wiring"]


def test_named_workspace_resolved(temp_db, uid):
    eng = EntityEngine()
    eng.create_workspace(uid, "Robot")
    o = WorkspaceOrchestrator(engine=eng)
    res = o.handle(uid, "in Robot, add milestone Frame")
    assert res.ok and res.workspace.title == "Robot"


def test_unknown_workspace_asks_clarification(temp_db, uid):
    res = orch().handle(uid, "in Ghost, add milestone X")
    assert res.status == Status.NEEDS_CLARIFICATION
    assert "Ghost" in res.message


def test_ambiguous_workspace_lists_options(temp_db, uid):
    eng = EntityEngine()
    eng.create_workspace(uid, "Robot Alpha")
    eng.create_workspace(uid, "Robot Beta")
    o = WorkspaceOrchestrator(engine=eng)
    res = o.handle(uid, "in Robot, add milestone X")
    assert res.status == Status.NEEDS_CLARIFICATION
    assert set(res.options) == {"Robot Alpha", "Robot Beta"}


def test_no_workspace_context_asks(temp_db, uid):
    res = orch().handle(uid, "add milestone X")   # no ref, no active
    assert res.status == Status.NEEDS_CLARIFICATION


# ── entity (milestone) resolution ─────────────────────────────────────────

def test_complete_milestone_resolved_by_name(temp_db, uid):
    eng = EntityEngine()
    ws = eng.create_workspace(uid, "Robot")
    eng.add_milestone(uid, ws.id, "Design phase")
    o = WorkspaceOrchestrator(engine=eng)
    res = o.handle(uid, "complete milestone Design", active_workspace_id=ws.id)
    assert res.ok
    assert res.entity.status == "done"


def test_unknown_milestone_asks_with_options(temp_db, uid):
    eng = EntityEngine()
    ws = eng.create_workspace(uid, "Robot")
    eng.add_milestone(uid, ws.id, "Design")
    o = WorkspaceOrchestrator(engine=eng)
    res = o.handle(uid, "complete milestone Nonexistent", active_workspace_id=ws.id)
    assert res.status == Status.NEEDS_CLARIFICATION
    assert res.options == ("Design",)


def test_ambiguous_milestone_asks(temp_db, uid):
    eng = EntityEngine()
    ws = eng.create_workspace(uid, "Robot")
    eng.add_milestone(uid, ws.id, "Design part one")
    eng.add_milestone(uid, ws.id, "Design part two")
    o = WorkspaceOrchestrator(engine=eng)
    res = o.handle(uid, "complete milestone Design", active_workspace_id=ws.id)
    assert res.status == Status.NEEDS_CLARIFICATION
    assert len(res.options) == 2


# ── safety gate (confirm irreversible) ────────────────────────────────────

def test_delete_milestone_requires_confirmation(temp_db, uid):
    eng = EntityEngine()
    ws = eng.create_workspace(uid, "Robot")
    eng.add_milestone(uid, ws.id, "Doomed")
    o = WorkspaceOrchestrator(engine=eng)
    res = o.handle(uid, "delete milestone Doomed", active_workspace_id=ws.id)
    assert res.status == Status.NEEDS_CONFIRMATION
    # nothing deleted yet
    assert [m.title for m in eng.list_milestones(uid, ws.id)] == ["Doomed"]
    # confirm applies it
    res2 = o.handle(uid, "delete milestone Doomed", active_workspace_id=ws.id,
                    confirm=True)
    assert res2.ok
    assert eng.list_milestones(uid, ws.id) == []


def test_archive_workspace_requires_confirmation(temp_db, uid):
    eng = EntityEngine()
    ws = eng.create_workspace(uid, "Robot")
    o = WorkspaceOrchestrator(engine=eng)
    assert o.handle(uid, "archive workspace",
                    active_workspace_id=ws.id).status == Status.NEEDS_CONFIRMATION
    res = o.handle(uid, "archive workspace", active_workspace_id=ws.id, confirm=True)
    assert res.ok and res.workspace.status == "archived"


def test_reversible_actions_apply_directly(temp_db, uid):
    eng = EntityEngine()
    ws = eng.create_workspace(uid, "Robot")
    o = WorkspaceOrchestrator(engine=eng)
    # add milestone + note apply with no confirmation
    assert o.handle(uid, "add milestone Frame", active_workspace_id=ws.id).ok
    assert o.handle(uid, "note: buy parts", active_workspace_id=ws.id).ok


# ── graceful degradation + AI-proposes/engine-validates ───────────────────

def test_unknown_utterance_asks_to_rephrase(temp_db, uid):
    res = orch().handle(uid, "asdf qwer zxcv")
    assert res.status == Status.NEEDS_CLARIFICATION
    assert "rephrase" in res.message.lower()


def test_low_confidence_proposal_clarifies(temp_db, uid):
    stub = StubInterpreter(Proposal(Action.ADD_MILESTONE, confidence=0.1))
    res = orch(stub).handle(uid, "whatever")
    assert res.status == Status.NEEDS_CLARIFICATION


def test_engine_validates_a_bad_proposal(temp_db, uid):
    # AI proposes adding a milestone with an empty title -> engine rejects,
    # orchestrator surfaces REJECTED (not a crash).
    eng = EntityEngine()
    ws = eng.create_workspace(uid, "Robot")
    stub = StubInterpreter(Proposal(Action.ADD_MILESTONE, params={"title": "  "}))
    o = WorkspaceOrchestrator(engine=eng, interpreter=stub)
    res = o.handle(uid, "x", active_workspace_id=ws.id)
    assert res.status == Status.REJECTED


def test_ownership_enforced_via_engine(temp_db, uid):
    eng = EntityEngine()
    ws = eng.create_workspace(uid, "Mine")
    o = WorkspaceOrchestrator(engine=eng)
    # OTHER user targets uid's workspace by id -> not found -> clarification
    res = o.handle(OTHER, "add milestone X", active_workspace_id=ws.id)
    assert res.status == Status.NEEDS_CLARIFICATION


# ── generic: no template-specific behaviour ───────────────────────────────

def test_orchestrator_is_template_agnostic(temp_db, uid):
    # Same utterances work identically whatever the workspace template is.
    eng = EntityEngine()
    for tmpl in ("generic", "project", "book", "game"):
        ws = eng.create_workspace(uid, f"WS-{tmpl}", template=tmpl,
                                  seed_milestones=False)
        o = WorkspaceOrchestrator(engine=eng)
        res = o.handle(uid, "add milestone Step", active_workspace_id=ws.id)
        assert res.ok, tmpl


# ── full cascade: orchestrator -> engine -> timeline ──────────────────────

def test_cascade_records_timeline(temp_db, uid):
    te = TimelineEngine()
    eng = EntityEngine(on_event=te.record)
    o = WorkspaceOrchestrator(engine=eng)
    o.handle(uid, "create workspace Robot")
    ws = db.get_workspace_by_title(uid, "Robot")
    o.handle(uid, "add milestone Frame", active_workspace_id=ws[0])
    types = [e.event_type for e in te.timeline(uid)]
    assert "workspace.created" in types
    assert "milestone.added" in types
