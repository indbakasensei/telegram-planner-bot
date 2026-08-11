"""
tests/test_worker_render.py -- v15.2 M4 response-format restoration (items 12/13).

The product rule: "Worker decides WHAT happened. Existing BAKA formatter
decides HOW it is displayed." The first live matrices came back as raw LLM
prose ("Xiao is now level 80"). `core.ai.worker_render.render_run_reply`
walks the run's step trace and maps each ok ToolResult onto the same
Telegram-HTML presentation the legacy handlers use (entity card, task/goal/
habit/workspace lines), so a Worker reply is formatted, escaped, and emoji'd
exactly like a /use /add or dashboard reply.

These tests drive a real Worker (deterministic FakeModel + real tool
adapters + real DB) and assert on the RENDERED reply -- never on the model's
prose. Matrix H of the broad test matrix (item 16).
"""
import json

import database as db
from core.ai.tool_adapters import build_tool_registry
from core.ai.worker import Worker
from core.ai.worker_render import render_run_reply
from core.ai.worker_contract import (
    TerminationReason,
    WorkerRequest,
)
from core.workspace.engine import EntityEngine

# Same harness as test_worker.py / test_worker_orchestration.py.
def _final(reply):
    return json.dumps({"action": "final", "reply": reply})


def _tool(name, args=None):
    return json.dumps({"action": "tool", "tool": name, "arguments": args or {}})


def _req(uid, text):
    return WorkerRequest(user_id=uid, text=text,
                         registry=build_tool_registry(uid))


def _worker(model):
    return Worker(model_fn=model, timeout=30.0)


def _game(uid, title="Genshin"):
    eng = EntityEngine()
    ws = eng.create_workspace(uid, title, template="game", seed_milestones=False)
    db.tg_set_active(uid, ws.id)
    return eng, ws


def _run_and_render(uid, responses, text, eng):
    model = FakeModel(*responses)
    run = _worker(model).run(_req(uid, text))
    reply = render_run_reply(run, user_id=uid,
                             fetcher=lambda u, e: eng.get_milestone(u, e))
    return run, reply


class FakeModel:
    def __init__(self, *responses):
        self._responses = list(responses)

    def __call__(self, messages, timeout):
        return self._responses.pop(0)


# ── entity cards ─────────────────────────────────────────────────────────
def test_render_create_entity_full_card_via_fetcher(temp_db, uid):
    """create_entity renders the FULL card (stored fields re-fetched), not a
    bare one-line claim -- the format /add shows in chat."""
    eng, ws = _game(uid)
    run, reply = _run_and_render(
        uid, [_tool("create_entity", {"name": "Xiao"}), _final("ok")],
        "Create Xiao", eng)
    assert run.termination is TerminationReason.FINAL
    assert "<b>Xiao</b>" in reply
    assert "created" in reply
    # The card came from the stored milestone (fetcher), so status is there.
    assert "Status: Todo" in reply


def test_render_create_entity_escapes_html_in_title(temp_db, uid):
    """A hostile/odd title must be HTML-escaped, never break the reply."""
    eng, ws = _game(uid)
    run, reply = _run_and_render(
        uid, [_tool("create_entity", {"name": "<b>&\"evil\""}), _final("ok")],
        "Create <b>&\"evil\"", eng)
    assert "<b>&lt;b&gt;&amp;\"evil\"</b>" in reply   # escaped, not a live tag
    assert "&quot;" not in reply  # fmt.esc leaves quotes alone (safe in text)


def test_render_adopted_entity(temp_db, uid):
    """Adoption (untyped row + typed create) renders the one-entity-one-topic
    note, not a duplicate-entity claim."""
    eng, ws = _game(uid)
    eng.add_milestone(uid, ws.id, "Xiao")           # untyped legacy row
    run, reply = _run_and_render(
        uid, [_tool("create_entity", {"name": "Xiao",
                                      "entity_type": "character"}),
              _final("ok")],
        "Create Xiao as a character", eng)
    assert "now a character" in reply
    assert "one entity, one topic" in reply
    assert "adopted" not in reply.lower() or "id" in reply  # readable


def test_render_get_entity_shows_card(temp_db, uid):
    eng, ws = _game(uid)
    m = eng.add_milestone(uid, ws.id, "Xiao")
    eng.update_field(uid, m.id, "level", 80)
    run, reply = _run_and_render(
        uid, [_tool("get_entity", {"entity": "Xiao"}), _final("ok")],
        "Show Xiao", eng)
    assert "<b>Xiao</b>" in reply
    assert "Level: 80" in reply          # stored field surfaced
    assert "Status: Todo" in reply


def test_render_update_entity_old_to_new(temp_db, uid):
    eng, ws = _game(uid)
    m = eng.add_milestone(uid, ws.id, "Xiao")
    eng.update_field(uid, m.id, "level", 22)
    run, reply = _run_and_render(
        uid, [_tool("update_entity", {"entity": "Xiao",
                                      "fields": {"level": 90}}),
              _final("ok")],
        "Set Xiao to level 90", eng)
    assert "<b>Xiao</b> updated" in reply
    assert "Level: 22 → 90" in reply     # format_entity_update old→new


def test_render_list_entities_typed_grouped(temp_db, uid):
    eng, ws = _game(uid)
    reg = build_tool_registry(uid)
    reg.execute("create_entity", {"name": "Xiao", "entity_type": "character"})
    reg.execute("create_entity", {"name": "Furina", "entity_type": "character"})
    reg.execute("create_entity", {"name": "Golden Troupe",
                                  "entity_type": "artifact"})
    run, reply = _run_and_render(
        uid, [_tool("list_entities", {"kind": "character"}),
              _final("ok")],
        "Show all characters", eng)
    assert "Characters" in reply or "character" in reply
    assert "#" in reply
    # The artifact must NEVER appear in the character reply.
    assert "Golden Troupe" not in reply


def test_render_list_entities_all_kind_markers(temp_db, uid):
    eng, ws = _game(uid)
    reg = build_tool_registry(uid)
    reg.execute("create_entity", {"name": "Xiao", "entity_type": "character"})
    reg.execute("create_goal", {"title": "Read Book"})
    run, reply = _run_and_render(
        uid, [_tool("list_entities", {"kind": "all"}), _final("ok")],
        "Show everything", eng)
    assert "Character" in reply and "Goals" in reply
    assert "Xiao" in reply and "Read Book" in reply


def test_render_every_list_tool_accepts_the_3arg_dispatch(temp_db, uid):
    """Regression (matrix E exposed it): every *_list tool lives in the
    dispatch set that passes (data, user_id, fetcher) -- a 1-arg renderer
    would TypeError on a real Worker listing tasks/goals/habits/workspaces.
    This pins all of them to the 3-arg signature and renders formatted."""
    eng, ws = _game(uid)
    reg = build_tool_registry(uid)
    db.add_goal(uid, "Gym", None)
    db.add_task(uid, "Buy Milk")
    reg.execute("create_habit", {"title": "Meditate"})
    reg.execute("list_workspaces", {})
    run, reply = _run_and_render(
        uid,
        [_tool("list_tasks", {}),
         _tool("list_goals", {}),
         _tool("list_habits", {}),
         _tool("list_workspaces", {}),
         _final("ok")],
        "Show me my lists", eng)
    assert "Buy Milk" in reply
    assert "🎯" in reply and "Gym" in reply
    assert "Meditate" in reply and "streak" in reply
    assert "Genshin" in reply                      # the workspace list


# ── goals ────────────────────────────────────────────────────────────────
def test_render_create_goal_and_deadline(temp_db, uid):
    run, reply = _run_and_render(
        uid,
        [_tool("create_goal", {"title": "Read Book"}),
         _tool("update_goal_deadline", {"goal": "Read Book",
                                        "deadline": "2026-08-31"}),
         _final("ok")],
        "Add goal Read Book with deadline this month end",
        EntityEngine())
    assert "🎯" in reply
    assert "Read Book" in reply
    assert "📅 2026-08-31" in reply


def test_render_goal_progress_complete(temp_db, uid):
    db.add_goal(uid, "Gym", None)
    run, reply = _run_and_render(
        uid, [_tool("update_goal_progress", {"goal_id": 1, "delta": 20}),
              _final("ok")],
        "Add 20 to Gym", EntityEngine())
    assert "🎯" in reply and "20" in reply


# ── tasks / habits ───────────────────────────────────────────────────────
def test_render_create_task_with_date(temp_db, uid):
    run, reply = _run_and_render(
        uid, [_tool("create_task", {"title": "Buy Milk",
                                    "due_date": "2026-08-11",
                                    "due_time": "18:00"}),
              _final("ok")],
        "Add task Buy Milk due 2026-08-11 18:00", EntityEngine())
    assert "✅" in reply
    assert "<b>Buy Milk</b>" in reply
    assert "📅 2026-08-11 18:00" in reply


def test_render_complete_and_delete_task(temp_db, uid):
    tid = db.add_task(uid, "Doom")
    run, reply = _run_and_render(
        uid, [_tool("complete_task", {"task_id": tid}),
              _final("ok")],
        "Complete the task", EntityEngine())
    assert "done" in reply and "<b>Doom</b>" in reply
    # delete_task is DESTRUCTIVE: the mechanical confirmation gate fires
    # BEFORE any execution, so the reply is the honest confirmation text,
    # never a silent run.
    run2, reply2 = _run_and_render(
        uid, [_tool("delete_task", {"task_id": tid}), _final("ok")],
        "Delete the task", EntityEngine())
    assert run2.termination is TerminationReason.CONFIRMATION_NEEDED
    assert "Permanently delete" in reply2
    assert db.get_task_by_id(tid, uid) is not None   # nothing was deleted


def test_render_habit_actions(temp_db, uid):
    run, reply = _run_and_render(
        uid, [_tool("create_habit", {"title": "Meditate"}),
              _tool("complete_habit", {"habit_id": 1}),
              _final("ok")],
        "Add habit Meditate and log it today", EntityEngine())
    assert "🌱" in reply and "Meditate" in reply
    assert "logged" in reply


# ── workspaces ───────────────────────────────────────────────────────────
def test_render_open_workspace(temp_db, uid):
    eng = EntityEngine()
    eng.create_workspace(uid, "Drone", template="generic")
    run, reply = _run_and_render(
        uid, [_tool("open_workspace", {"workspace": "Drone"}), _final("ok")],
        "Use Drone", eng)
    assert "Active workspace" in reply
    assert "<b>Drone</b>" in reply


# ── honesty / fallback ───────────────────────────────────────────────────
def test_render_failed_step_is_honest_not_fabricated(temp_db, uid):
    """One ok + one failed op: the failure is rendered as a warning line,
    never swallowed into a blanket success."""
    eng, ws = _game(uid)
    run, reply = _run_and_render(
        uid,
        [_tool("create_entity", {"name": "Aether"}),
         _tool("update_entity", {"entity": "Zhongli",
                                 "fields": {"level": 9}}),
         _final("ok")],
        "Create Aether, set Zhongli to level 9", eng)
    assert "<b>Aether</b>" in reply
    assert "⚠️" in reply and "update_entity failed" in reply


def test_render_max_steps_budget_note(temp_db, uid):
    eng, ws = _game(uid)
    # 6 ok tool decisions fill the budget; the 7th (composition) call is
    # malformed -> MAX_STEPS. The renderer must still show the completed ops.
    run, reply = _run_and_render(
        uid,
        [_tool("create_entity", {"name": "Keqing"}),
         _tool("update_entity", {"entity": "Keqing", "fields": {"level": 90}})] * 3
        + ["not-json-garbage"],
        "Create Keqing level 90", eng)
    assert run.termination is TerminationReason.MAX_STEPS
    assert "only fit part of that" in reply
    assert "<b>Keqing</b>" in reply


def test_render_falls_back_when_nothing_renders(temp_db, uid):
    """Zero-step FINAL (pure chat): the model's text is escaped and returned
    as-is -- no empty reply, no invented structure."""
    run, reply = _run_and_render(uid, [_final("Sure, I'm here!")],
                                 "hello", EntityEngine())
    assert reply == "Sure, I'm here!"


def test_render_graceful_fallback_when_tool_unknown(temp_db, uid):
    """A termination with NO ok steps falls back to the graceful text."""
    run, reply = _run_and_render(
        uid, [_tool("not_a_real_tool", {})], "do something", EntityEngine())
    assert run.termination is TerminationReason.UNKNOWN_TOOL
    assert reply and "rephrase" in reply.lower()
