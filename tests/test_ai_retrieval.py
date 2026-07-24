"""
Tests for v15.1.0-alpha.8 -- real retrieval (WorkspaceRetriever + recall).

The retriever gathers related context from everything stored across a user's
workspaces (entities, statuses, notes) and ranks by relevance; the Cognitive
Engine routes broad questions to it and grounds the answer in real data.
All offline: keyword scoring, no model, no network.
"""
import database as db
from core.ai.cognition import CognitiveEngine, RuleBasedPlanner, CognitiveContext
from core.ai.workspace_retriever import RecallTool, WorkspaceRetriever
from core.workspace.engine import EntityEngine
from core.workspace.groups_app import WorkspaceGroups


def _seed(uid):
    app = WorkspaceGroups()
    eng = EntityEngine()
    drone = app.create(uid, "project", "Drone")
    fc = eng.add_milestone(uid, drone.id, "Flight controller")
    eng.transition_milestone(uid, fc.id, "blocked")
    db.add_note(drone.id, "Replaced the motor bearing", milestone_id=None)
    gen = app.create(uid, "game", "Genshin")
    ht = eng.add_milestone(uid, gen.id, "Hu Tao")
    db.add_note(gen.id, "Hu Tao needs the Teardrop Crystal talent domain",
                milestone_id=ht.id)
    return app, eng, drone, gen


# ── Retriever ranking + grounding ─────────────────────────────────────────

def test_retriever_finds_across_entities_and_notes(temp_db, uid):
    _seed(uid)
    r = WorkspaceRetriever(uid)
    docs = r.retrieve("what do I know about Hu Tao?")
    texts = " || ".join(d.text for d in docs)
    assert "Hu Tao" in texts
    assert "Teardrop Crystal" in texts          # the related note was retrieved
    assert "motor bearing" not in texts         # unrelated content excluded


def test_retriever_ranks_by_relevance(temp_db, uid):
    _seed(uid)
    docs = WorkspaceRetriever(uid).retrieve("Hu Tao talent domain")
    assert docs and "Hu Tao" in docs[0].text or "Teardrop" in docs[0].text
    assert all(d.score > 0 for d in docs)


def test_retriever_empty_on_unknown_topic(temp_db, uid):
    _seed(uid)
    assert WorkspaceRetriever(uid).retrieve("quarterly tax return") == []


def test_retriever_ignores_pure_stopword_query(temp_db, uid):
    _seed(uid)
    assert WorkspaceRetriever(uid).retrieve("what is it about?") == []


# ── recall tool ───────────────────────────────────────────────────────────

def test_recall_tool_grounds_answer(temp_db, uid):
    _seed(uid)
    tool = RecallTool(WorkspaceRetriever(uid))
    out = tool.run(query="Hu Tao")
    assert "Hu Tao" in out and out.startswith("Here's what I found")


def test_recall_tool_says_nothing_found(temp_db, uid):
    _seed(uid)
    out = RecallTool(WorkspaceRetriever(uid)).run(query="cryptocurrency")
    assert "couldn't find" in out.lower()


# ── planner routing + end-to-end via the engine ───────────────────────────

def test_planner_routes_broad_question_to_recall():
    plan = RuleBasedPlanner().plan("what do I know about Hu Tao?",
                                   CognitiveContext(1, None, ("Drone", "Genshin")))
    assert plan.steps[0].tool == "recall"
    assert plan.steps[0].args.get("query")


def test_planner_fallback_is_recall_when_no_specific_match():
    plan = RuleBasedPlanner().plan("nahida artifacts and weapons",
                                   CognitiveContext(1, None, ()))
    assert plan.steps[0].tool == "recall"


def test_engine_answers_broad_question_from_retrieval(temp_db, uid):
    _seed(uid)
    res = CognitiveEngine().handle(uid, "tell me about Hu Tao")
    assert res.grounded
    assert "Hu Tao" in res.answer and "Teardrop Crystal" in res.answer


def test_engine_specific_question_still_uses_precise_tool(temp_db, uid):
    # retrieval must not swallow the precise-tool paths
    _seed(uid)
    res = CognitiveEngine().handle(uid, "which component is blocked in Drone?")
    assert "Flight controller" in res.answer
