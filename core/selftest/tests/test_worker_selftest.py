"""Self-tests: v15.2 M4 — AI Worker (category AI).

The GLM-5.2 Worker (core/ai/worker.py) is DORMANT behind feature_flags.WORKER
and the owner-only canary (main.py). These probes verify from the live app
that the dormant surface stays healthy and verifiable from /selftest:

  1. "AI Worker (dormant)" — the flag defaults OFF, the gate is owner-only,
     the tool surface the Worker builds on is the complete 30-tool M4
     registry (M3's 24 + update_goal_deadline + the 5-tool topic-lifecycle
     family), MAX_TOOL_CALLS is the hard cap, and there is NO separate
     "reminders" tool (reminders ARE task due-times).
  2. "AI Worker deterministic round-trip" — ONE run through a deterministic
     fake model (no network, no real GLM) proving the bounded loop compiles
     context, executes a MUTATING tool through the ToolRegistry, honours the
     final decision, and reports an honest handled result. Cleans up its task
     in a finally block.

Both are fully offline and leave no residue.
"""
import json

import database as db
from core.feature_flags import WORKER
from core.selftest.models import SELFTEST_USER_ID, SelfTestFail
from core.selftest.registry import selftest
from core.ai.worker_contract import MAX_TOOL_CALLS, WorkerRequest


class _FakeModel:
    """Deterministic model stub for the round-trip probe (no network)."""
    def __init__(self, responses):
        self._responses = list(responses)
    def __call__(self, messages, timeout):
        if not self._responses:
            raise AssertionError("model called more times than expected")
        return self._responses.pop(0)


@selftest(name="AI Worker (dormant)", category="AI")
def check_ai_worker_dormant():
    """The Worker is dormant-by-default and owner-gated, builds on the full
    M3 surface, and adds no separate reminder tool."""
    if not isinstance(WORKER, bool):
        raise SelfTestFail("feature_flags.WORKER is not a bool")
    if MAX_TOOL_CALLS != 6:
        raise SelfTestFail(f"MAX_TOOL_CALLS must be 6, got {MAX_TOOL_CALLS}")

    import main as main_mod
    src = main_mod.__file__ or ""
    # The owner-only canary gate must exist verbatim in handle_message.
    if "feature_flags.WORKER and is_admin(user_id)" not in open(src).read():
        raise SelfTestFail("owner-only gate 'feature_flags.WORKER and is_admin' "
                           "not found in main.py")

    reg = _registry()
    names = {t.spec.name for t in reg.all()}
    if len(names) != 30:
        raise SelfTestFail(f"expected 30 tools, got {len(names)}")
    if "reminders" in names or "list_reminders" in names:
        raise SelfTestFail("a separate 'reminders' tool exists (M4 forbids it; "
                           "reminders ARE task due-times)")
    # v15.2 M4 surface: the goal domain owns deadlines, and entity retrieval
    # is type-aware. Both must be present and shaped correctly, or the live
    # failures F6/F9 can silently regress.
    if "update_goal_deadline" not in names:
        raise SelfTestFail("update_goal_deadline tool missing (F6: goals own "
                           "their deadlines, never entity target_level)")
    ent_spec = reg.get("list_entities").spec
    if "entity_type" not in ent_spec.parameters["properties"]:
        raise SelfTestFail("list_entities lost its entity_type filter "
                           "(F9: 'show all characters' is a structured kind "
                           "filter, not a keyword hack)")
    # Topic lifecycle family (M4 items7/8/10) — one canonical topic per
    # (workspace_id, entity_id), delete is DESTRUCTIVE.
    for tname in ("get_entity_topic", "ensure_entity_topic",
                  "set_entity_topic_locked", "delete_entity_topic",
                  "list_entity_topics"):
        if tname not in names:
            raise SelfTestFail(f"{tname} tool missing (topic lifecycle, M4 "
                               "items7/8/10)")
    from core.ai.tools import RiskLevel
    if reg.get("delete_entity_topic").spec.risk is not RiskLevel.DESTRUCTIVE:
        raise SelfTestFail("delete_entity_topic not classified DESTRUCTIVE "
                           "(M4 item8: a topic delete is destructive + "
                           "confirmation-gated)")
    return (f"dormant/owner-only ok · WORKER={WORKER} · 30 tools · "
            f"MAX_TOOL_CALLS={MAX_TOOL_CALLS}")


@selftest(name="AI Worker Deterministic Round-trip", category="AI")
def check_ai_worker_roundtrip():
    """One bounded Worker run through a fake model, end-to-end offline: the
    loop builds context, executes a MUTATING tool via the ToolRegistry, and
    returns an honest final. Cleans up its task in a finally block."""
    from core.ai.tool_adapters import build_tool_registry
    from core.ai.worker import Worker

    reg = build_tool_registry(SELFTEST_USER_ID)
    model = _FakeModel([
        json.dumps({"action": "tool", "tool": "create_task",
                    "arguments": {"title": "[selftest] worker task",
                                  "due_date": "2026-08-11"}}),
        json.dumps({"action": "final", "reply": "Created the selftest task."}),
    ])
    task_id = None
    try:
        req = WorkerRequest(user_id=SELFTEST_USER_ID,
                            text="create a selftest task",
                            registry=reg)
        result = Worker(model_fn=model, timeout=30.0).run(req)
        if not result.handled:
            raise SelfTestFail(f"worker not handled: {result}")
        if result.termination.value != "final":
            raise SelfTestFail(f"termination not final: {result.termination}")
        if len(result.steps) != 1 or not result.steps[0].result.ok:
            raise SelfTestFail(f"create_task step not ok: {result.steps}")
        task_id = result.steps[0].result.data.get("task_id")
        if task_id is None:
            raise SelfTestFail("create_task returned no task_id")
        if db.get_task_by_id(task_id, SELFTEST_USER_ID) is None:
            raise SelfTestFail("task not actually committed to the database")
        return (f"round-trip ok · 1 tool step + final · task [{task_id}] "
                f"committed · model_calls=2")
    finally:
        if task_id is not None:
            try:
                db.delete_task(task_id, SELFTEST_USER_ID)
            except Exception:
                pass


def _registry():
    from core.ai.tool_adapters import build_tool_registry
    return build_tool_registry(SELFTEST_USER_ID)
