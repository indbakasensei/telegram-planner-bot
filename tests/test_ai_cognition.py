"""
Tests for v15.1.0-alpha.3 -- the Cognitive Engine (Phase 1).

Proves the design guarantees end to end against real Workspace data:
- the planner routes questions to the right grounded tool;
- answers are composed ONLY from tool facts (no hallucination);
- conversation context (active workspace) makes follow-ups resolve without
  renaming the workspace (PART 7);
- when nothing exists, the engine says so (PART 8);
- the LLM planner routes-only and falls back safely.
All offline: the AI is injected; no live LLM, no Telegram.
"""
import database as db
from core.ai.cognition import (
    CognitiveEngine, Plan, PlanStep, RuleBasedPlanner,
)
from core.ai.llm_planner import LLMPlanner
from core.ai.workspace_tools import build_workspace_registry
from core.workspace.engine import EntityEngine
from core.workspace.groups_app import WorkspaceGroups


def _seed(uid):
    """A Drone project with entities in various states + a Genshin game."""
    app = WorkspaceGroups()
    drone = app.create(uid, "project", "Drone")          # also makes it active
    eng = EntityEngine()
    for title, status in [("Motor", "done"), ("Frame", "in_progress"),
                          ("Flight controller", "blocked")]:
        m = eng.add_milestone(uid, drone.id, title)
        if status != "todo":
            eng.transition_milestone(uid, m.id, status)
    genshin = app.create(uid, "game", "Genshin")         # active is now Genshin
    return app, eng, drone, genshin


# ── Grounded tools ────────────────────────────────────────────────────────

def test_list_entities_by_blocked_status_is_grounded(temp_db, uid):
    _, eng, drone, _ = _seed(uid)
    reg = build_workspace_registry(eng, uid, active_ws_id=drone.id)
    out = reg.get("list_entities").run(status="blocked")
    assert "Flight controller" in out and "Motor" not in out


def test_overview_reports_real_progress(temp_db, uid):
    _, eng, drone, _ = _seed(uid)
    reg = build_workspace_registry(eng, uid, active_ws_id=drone.id)
    out = reg.get("workspace_overview").run()
    assert "Drone" in out and "%" in out and "blocked" in out


# ── Planner routing ───────────────────────────────────────────────────────

def test_rulebased_routes_blocked_question():
    p = RuleBasedPlanner()
    from core.ai.cognition import CognitiveContext
    plan = p.plan("which component is blocked?",
                  CognitiveContext(1, 5, ("Drone",)))
    assert plan.steps[0].tool == "list_entities"
    assert plan.steps[0].args.get("status") == "blocked"


def test_rulebased_extracts_named_workspace():
    p = RuleBasedPlanner()
    from core.ai.cognition import CognitiveContext
    plan = p.plan("how far along is Drone?",
                  CognitiveContext(1, None, ("Drone", "Genshin")))
    assert plan.steps[0].tool == "workspace_overview"
    assert plan.steps[0].args.get("workspace") == "Drone"


# ── Cognitive Engine: grounding + conversation context ────────────────────

def test_engine_answer_is_grounded_in_facts(temp_db, uid):
    _, _, drone, _ = _seed(uid)
    eng = CognitiveEngine()
    res = eng.handle(uid, "which component is blocked in Drone?")
    assert res.grounded
    assert "Flight controller" in res.answer


def test_conversation_context_infers_active_workspace(temp_db, uid):
    # PART 7: "open Drone" sets context; the follow-up needs no workspace name.
    _, _, drone, _ = _seed(uid)
    eng = CognitiveEngine()
    eng.handle(uid, "open Drone workspace")               # sets active = Drone
    assert db.tg_get_active(uid)[0] == drone.id
    res = eng.handle(uid, "which component is blocked?")   # no name given
    assert "Flight controller" in res.answer


def test_no_fabrication_when_data_absent(temp_db, uid):
    # PART 8: a workspace with no blocked entities → truthful "no", not invented.
    app = WorkspaceGroups()
    app.create(uid, "game", "Genshin")
    eng = CognitiveEngine()
    res = eng.handle(uid, "what is blocked?")
    assert "No blocked" in res.answer or eng.NO_INFO in res.answer
    assert "Flight controller" not in res.answer


def test_unknown_workspace_is_not_fabricated(temp_db, uid):
    # When a specific (unknown) workspace is referenced, the grounded tool
    # refuses rather than inventing -- the no-fabrication guarantee lives at
    # the tool level. (The LLM planner forwards the named ref here.)
    _seed(uid)
    planner = LLMPlanner(
        ai_call=lambda p: '{"tool":"workspace_overview","args":{"workspace":"Spaceship"}}')
    eng = CognitiveEngine(planner=planner)
    res = eng.handle(uid, "how far along is Spaceship?")
    assert "couldn't find" in res.answer.lower()
    assert "%" not in res.answer      # did NOT answer about some other workspace


# ── LLM planner: routes only, falls back safely ───────────────────────────

def test_llm_planner_uses_returned_tool(temp_db, uid):
    _seed(uid)
    from core.ai.cognition import CognitiveContext
    planner = LLMPlanner(ai_call=lambda p: '{"tool":"list_workspaces","args":{}}')
    plan = planner.plan("what am I working on?", CognitiveContext(uid, None, ()))
    assert plan.steps[0].tool == "list_workspaces"


def test_llm_planner_falls_back_on_ai_error(temp_db, uid):
    from core.ai.cognition import CognitiveContext
    def boom(prompt):
        raise RuntimeError("provider down")
    planner = LLMPlanner(ai_call=boom)
    plan = planner.plan("which component is blocked?",
                        CognitiveContext(uid, None, ("Drone",)))
    # fell back to the deterministic planner
    assert plan.steps[0].tool == "list_entities"


def test_llm_planner_rejects_unknown_tool_and_falls_back():
    from core.ai.cognition import CognitiveContext
    planner = LLMPlanner(ai_call=lambda p: '{"tool":"drop_database","args":{}}')
    plan = planner.plan("list my workspaces",
                        CognitiveContext(1, None, ()))
    assert plan.steps[0].tool in {"list_workspaces", "workspace_overview"}


def test_engine_with_llm_planner_still_grounded(temp_db, uid):
    _seed(uid)
    planner = LLMPlanner(ai_call=lambda p: '{"tool":"workspace_overview","args":{"workspace":"Drone"}}')
    eng = CognitiveEngine(planner=planner)
    res = eng.handle(uid, "give me the drone status")
    assert "Drone" in res.answer and "%" in res.answer
