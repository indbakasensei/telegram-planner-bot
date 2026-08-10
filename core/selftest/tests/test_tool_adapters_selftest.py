"""Self-tests: v15.2 M3 — AI Tool Adapters (category AI).

Live, offline probes confirming the M3 adapter surface (core/ai/tool_adapters.py)
is healthy in the running app: the full 24-tool registry builds with the M2
contract and honest risk classifications, and a deterministic entity+task
round-trip through ONE registry drives the alpha.13 projection (a fake client
proves the real card/update text is posted — the adapters never bypass the
projection). Both checks create data under SELFTEST_USER_ID and clean it up
in finally blocks, so they leave no residue and are safe to re-run.
"""
from core.selftest.models import SELFTEST_USER_ID, SelfTestFail
from core.selftest.registry import selftest

# The full M3 tool surface (24 names).
_EXPECTED_TOOLS = frozenset({
    # tasks
    "list_tasks", "find_task", "create_task", "update_task",
    "complete_task", "delete_task",
    # habits
    "create_habit", "list_habits", "complete_habit",
    # goals
    "create_goal", "list_goals", "update_goal_progress",
    # entities (projection + M1 reference reuse)
    "create_entity", "get_entity", "update_entity", "list_entities",
    "find_entity",
    # workspace
    "list_workspaces", "get_workspace", "open_workspace", "inspect_workspace",
    # memory / recall
    "get_memories", "search_memories", "recall",
})

# Names that MUST be classified as writing state (never READ_ONLY).
_WRITING_TOOLS = frozenset({
    "create_task", "update_task", "complete_task",
    "create_habit", "complete_habit",
    "create_goal", "update_goal_progress",
    "create_entity", "update_entity", "open_workspace",
})


@selftest(name="AI Tool Adapter Registry", category="AI")
def check_ai_tool_adapter_registry():
    """build_tool_registry registers the complete M3 surface under the M2
    contract with honest risk classifications: every write tool is MUTATING
    (open_workspace included — it persists active state), delete_task is
    DESTRUCTIVE, and nothing is misclassified as SYSTEM. No second registry,
    no second ToolResult."""
    from core.ai.tool_adapters import build_tool_registry
    from core.ai.tools import RiskLevel

    reg = build_tool_registry(SELFTEST_USER_ID)
    names = set(reg.names())
    missing = _EXPECTED_TOOLS - names
    extra = names - _EXPECTED_TOOLS
    if missing:
        raise SelfTestFail(f"adapter tools missing: {sorted(missing)}")
    if extra:
        raise SelfTestFail(f"unexpected tools: {sorted(extra)}")

    for name in _WRITING_TOOLS:
        spec = reg.get(name).spec
        if spec.risk is RiskLevel.READ_ONLY:
            raise SelfTestFail(f"{name} misclassified as READ_ONLY")
    if reg.get("delete_task").spec.risk is not RiskLevel.DESTRUCTIVE:
        raise SelfTestFail("delete_task not classified DESTRUCTIVE")
    if any(t.spec.risk is RiskLevel.SYSTEM for t in reg.all()):
        raise SelfTestFail("a tool is classified SYSTEM (no admin surface in M3)")
    return f"adapter registry ok · {len(names)} tools, risks honest"


@selftest(name="AI Tool Adapter Round-trip", category="AI")
def check_ai_tool_adapter_roundtrip():
    """A deterministic entity+task round-trip through ONE registry against the
    live database, with a fake Telegram client proving the adapter posts the
    real alpha.13 card + append-only update to the entity's topic (projection
    is NOT bypassed). Cleans up completely."""
    import database as db
    from core.ai.tool_adapters import build_tool_registry
    from core.workspace.adapters.projection import (
        TelegramClient, TelegramProjection,
    )
    from core.workspace.engine import EntityEngine

    class _Fake(TelegramClient):
        def __init__(self):
            self.topics = []     # names
            self.messages = []   # (topic_id, text, parse_mode)
        def create_forum_topic(self, chat_id, name):
            self.topics.append(name)
            return 900 + len(self.topics)
        def send_message(self, chat_id, topic_id, text, parse_mode=None):
            self.messages.append((topic_id, text, parse_mode))
            return 1
        def send_photo(self, chat_id, topic_id, file_id, caption):
            return 2

    eng = EntityEngine()
    ws = eng.create_workspace(SELFTEST_USER_ID, "[selftest] adapter",
                              template="game", seed_milestones=False)
    task_id = None
    try:
        db.tg_set_active(SELFTEST_USER_ID, ws.id)
        fake = _Fake()
        proj = TelegramProjection(fake)
        proj.link_group(SELFTEST_USER_ID, ws.id, -100777)
        reg = build_tool_registry(SELFTEST_USER_ID, engine=eng, projection=proj)

        e = reg.execute("create_entity", {"name": "[selftest] hero"})
        if not (e.ok and e.data.get("topic_created")):
            raise SelfTestFail(f"create_entity failed: {e}")
        if fake.topics != ["[selftest] hero"]:
            raise SelfTestFail(f"topic not created for entity: {fake.topics}")

        u = reg.execute("update_entity", {"entity": "[selftest] hero",
                                          "fields": {"level": 80, "element": "Pyro"}})
        if not (u.ok and u.data.get("topic_posted")
                and u.data["applied"].get("level") == 80):
            raise SelfTestFail(f"update_entity failed: {u}")
        # ONE topic only; the update is append-only to it (alpha.13).
        if len(fake.topics) != 1:
            raise SelfTestFail(f"update created a second topic: {fake.topics}")
        if not any("Level" in text for (_tid, text, _pm) in fake.messages):
            raise SelfTestFail("projection did not post the real card/update text")

        t = reg.execute("create_task", {"title": "[selftest] task",
                                        "due_date": "2026-08-11"})
        if not t.ok:
            raise SelfTestFail(f"create_task failed: {t}")
        task_id = t.data["task_id"]
        c = reg.execute("complete_task", {"task_id": task_id})
        if not (c.ok and c.data.get("done")):
            raise SelfTestFail(f"complete_task failed: {c}")

        lst = reg.execute("list_entities", {})
        if [x["title"] for x in lst.data] != ["[selftest] hero"]:
            raise SelfTestFail(f"list_entities wrong: {lst.data}")
        return (f"adapter round-trip ok · entity→topic + append-only update, "
                f"task done, list correct")
    finally:
        if task_id is not None:
            db.delete_task(task_id, SELFTEST_USER_ID)
        db.delete_workspace(ws.id, SELFTEST_USER_ID)
        db.tg_clear_active(SELFTEST_USER_ID)
