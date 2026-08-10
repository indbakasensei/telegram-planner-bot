"""
Tests for v15.2 M3 -- Real Tool Adapters (core/ai/tool_adapters.py).

Covers the M3 acceptance scenarios (docs/engineering/V15_2_BAKA_BRAIN.md
§M3-TESTS) with Genshin-style acceptance fixtures (Xiao, Kinich, Xilonen,
Nefer, Lauma, Columbina). Those names are TEST data only -- nothing in
core/ai/tool_adapters.py knows any of them.

Highlights:
  * entity get/list/filter/update/update+topic/create/duplicate
  * task list/find/create/update/complete/delete + the reminder surface
    (reminders ARE task due-times -- a created task's due_date/due_time
    show up in list_tasks structured data)
  * habit/goal, workspace, conversational reference (M1 resolver reuse),
    and mixed-capability chaining through ONE registry
  * adversarial: unknown args (rejected on writes, dropped on reads),
    missing targets, no active workspace, bad field values, duplicate
    registration, execute-never-raises, risk classification, read-doesn't-
    mutate-active
  * integration: the adapters drive projection through the SAME alpha.13
    contract (/add and NL creation use) -- RecorderProj proves the seam is
    called with real card/update text, and a FakeClient+TelegramProjection
    run proves topics/messages are produced end-to-end offline, with NO
    second Telegram-topic mechanism.
"""
import pytest

import database as db
from core.ai.tool_adapters import build_tool_registry
from core.ai.tools import (
    RiskLevel,
    Tool,
    ToolRegistry,
    ToolRegistryError,
)
from core.workspace.adapters.projection import TelegramClient, TelegramProjection
from core.workspace.engine import EntityEngine

# Genshin acceptance fixtures (test data only).
XIAO, KINICH, XILONEN, NEFER, LAUMA, COLUMBINA = (
    "Xiao", "Kinich", "Xilonen", "Nefer", "Lauma", "Columbina")


class RecorderProj:
    """Duck-typed projection that records every call (mirrors the M1
    recorder in tests/test_entity_manager_projection.py)."""

    def __init__(self, fail_ensure=False, fail_update=False):
        self.ensured = []    # (entity_type, entity_id, title, initial_message)
        self.updates = []    # (entity_type, entity_id, title, text, initial)
        self._fail_ensure = fail_ensure
        self._fail_update = fail_update

    def ensure_entity_topic(self, user_id, workspace_id, entity_type,
                            entity_id, title, initial_message=None):
        if self._fail_ensure:
            raise RuntimeError("topic creation failed")
        self.ensured.append((entity_type, entity_id, title, initial_message))
        return 4242

    def post_entity_update(self, user_id, workspace_id, entity_type,
                           entity_id, entity_title, text,
                           initial_message=None):
        if self._fail_update:
            raise RuntimeError("topic update failed")
        self.updates.append(
            (entity_type, entity_id, entity_title, text, initial_message))
        return None


class FakeClient(TelegramClient):
    """Records calls; hands out deterministic topic/message ids (the same
    fake used by tests/test_workspace_groups.py)."""

    def __init__(self):
        self.topics = []
        self.messages = []
        self.photos = []

    def create_forum_topic(self, chat_id, name):
        self.topics.append((chat_id, name))
        return 100 + len(self.topics)

    def send_message(self, chat_id, topic_id, text, parse_mode=None):
        self.messages.append((chat_id, topic_id, text, parse_mode))
        return 1000 + len(self.messages)

    def send_photo(self, chat_id, topic_id, file_id, caption):
        self.photos.append((chat_id, topic_id, file_id, caption))
        return 2000 + len(self.photos)


def _game(uid, title="Genshin"):
    """A real game workspace + active binding (via the real DB paths)."""
    eng = EntityEngine()
    ws = eng.create_workspace(uid, title, template="game", seed_milestones=False)
    db.tg_set_active(uid, ws.id)
    return eng, ws


def _wire(uid, projection=None):
    """A per-user M3 registry on the temp database."""
    return build_tool_registry(uid, projection=projection)


# ── entities: create / duplicate / get / list / filter ───────────────────
def test_entity_create_creates_milestone_and_activates(temp_db, uid):
    _, ws = _game(uid)
    reg = _wire(uid)
    r = reg.execute("create_entity", {"name": XIAO})
    assert r.ok and r.data["entity_id"] > 0
    assert r.data["title"] == XIAO and r.data["workspace_id"] == ws.id
    assert r.data["topic_created"] is False   # no projection wired
    # became the active entity (same contract /add uses)
    assert db.tg_get_active(uid)[2] == r.data["entity_id"]
    eng = EntityEngine()
    assert [m.title for m in eng.list_milestones(uid, ws.id)] == [XIAO]


def test_entity_duplicate_rejected(temp_db, uid):
    _game(uid)
    reg = _wire(uid)
    assert reg.execute("create_entity", {"name": XIAO}).ok
    dup = reg.execute("create_entity", {"name": XIAO})
    assert not dup.ok and dup.error_code == "invalid_args"
    assert "already exists" in dup.output
    # no second milestone was created
    eng = EntityEngine()
    assert len(eng.list_milestones(uid, eng.list_workspaces(uid)[0].id)) == 1


def test_entity_get_by_name_and_workspace_ref(temp_db, uid):
    _, ws = _game(uid)
    reg = _wire(uid)
    reg.execute("create_entity", {"name": XIAO})
    r = reg.execute("get_entity", {"entity": XIAO})
    assert r.ok and r.data["title"] == XIAO
    assert r.data["workspace_id"] == ws.id
    # by #id and via explicit workspace title too
    by_id = reg.execute("get_entity", {"entity": str(r.data["entity_id"])})
    assert by_id.ok and by_id.data["entity_id"] == r.data["entity_id"]
    by_ws = reg.execute("get_entity", {"entity": XIAO, "workspace": "Genshin"})
    assert by_ws.ok and by_ws.data["entity_id"] == r.data["entity_id"]


def test_entity_list_returns_all(temp_db, uid):
    _game(uid)
    reg = _wire(uid)
    for name in (XIAO, KINICH, XILONEN):
        reg.execute("create_entity", {"name": name})
    r = reg.execute("list_entities", {})
    assert r.ok
    titles = [e["title"] for e in r.data]
    assert titles == [XIAO, KINICH, XILONEN]


def test_entity_filter_by_status(temp_db, uid):
    _, ws = _game(uid)
    eng = EntityEngine()
    reg = _wire(uid)
    reg.execute("create_entity", {"name": XIAO})
    reg.execute("create_entity", {"name": KINICH})
    mid = eng.list_milestones(uid, ws.id)[0].id
    eng.complete_milestone(uid, mid)   # Xiao done
    r = reg.execute("list_entities", {"status": "done"})
    assert [e["title"] for e in r.data] == [XIAO]
    r2 = reg.execute("list_entities", {"status": "todo"})
    assert [e["title"] for e in r2.data] == [KINICH]


# ── entities: update / update+topic / reference / find ───────────────────
def test_entity_update_applies_fields(temp_db, uid):
    _game(uid)
    reg = _wire(uid)
    reg.execute("create_entity", {"name": XIAO})
    r = reg.execute("update_entity", {"entity": XIAO,
                                      "fields": {"level": 90, "element": "Anemo"}})
    assert r.ok
    assert r.data["applied"] == {"level": 90, "element": "Anemo"}
    eid = r.data["entity_id"]
    eng = EntityEngine()
    fields = eng.get_fields(uid, eid)
    assert fields["level"] == 90 and fields["element"] == "Anemo"


def test_entity_update_projects_to_topic_append_only(temp_db, uid):
    """Integration: a projection is NOT bypassed -- update_entity calls
    post_entity_update with a real change summary + the current card, exactly
    the alpha.13 path NL updates use."""
    proj = RecorderProj()
    _game(uid)
    reg = _wire(uid, projection=proj)
    reg.execute("create_entity", {"name": XIAO})
    r = reg.execute("update_entity", {"entity": XIAO,
                                      "fields": {"level": 90, "element": "Anemo"}})
    assert r.ok and r.data["topic_posted"] is True
    assert len(proj.updates) == 1
    etype, eid, etitle, text, initial = proj.updates[0]
    assert etype == "milestone" and eid == r.data["entity_id"]
    assert etitle == XIAO
    # render.py title-cases field names in both the update and the card
    assert "Level" in text and "90" in text      # real change summary
    assert XIAO in initial and "Status" in initial   # real current card
    # append-only: the create-time ensure is untouched; no extra topic calls
    assert len(proj.ensured) == 1


def test_entity_create_projects_topic_via_single_contract(temp_db, uid):
    """Integration: create_entity drives ensure_entity_topic (the SAME
    contract /add uses) with the real initial card -- never a second
    Telegram-topic mechanism."""
    proj = RecorderProj()
    _game(uid)
    reg = _wire(uid, projection=proj)
    r = reg.execute("create_entity", {"name": XIAO})
    assert r.ok and r.data["topic_id"] == 4242 and r.data["topic_created"]
    assert len(proj.ensured) == 1
    etype, eid, title, initial = proj.ensured[0]
    assert etype == "milestone" and title == XIAO
    assert XIAO in initial and "Status" in initial
    assert len(proj.updates) == 0


def test_entity_create_topic_failure_mirrors_add_contract(temp_db, uid):
    """Topic CREATION failure is reported (exactly /add's 'Couldn't create the
    topic') -- it is NOT a silent best-effort, because an infrastructure
    problem (not a forum, not admin) must reach the user. The milestone is
    already committed before the topic step (same as /add), so a retry hits
    the duplicate guard instead of double-creating."""
    proj = RecorderProj(fail_ensure=True)
    _, ws = _game(uid)
    reg = _wire(uid, projection=proj)
    r = reg.execute("create_entity", {"name": XIAO})
    assert not r.ok and r.error_code == "internal"   # mirrors /add's error
    eng = EntityEngine()
    assert [m.title for m in eng.list_milestones(uid, ws.id)] == [XIAO]
    retry = reg.execute("create_entity", {"name": XIAO})
    assert not retry.ok and retry.error_code == "invalid_args"   # no double-create


def test_entity_update_projection_failure_is_best_effort(temp_db, uid):
    """Topic UPDATE failure is swallowed: the DB update stands and the tool
    still succeeds, reporting topic_posted=False + a warning -- exactly the
    best-effort seam EntityManager._handle_update uses."""
    proj = RecorderProj(fail_update=True)
    _, ws = _game(uid)
    reg = _wire(uid, projection=proj)
    reg.execute("create_entity", {"name": XIAO})
    r = reg.execute("update_entity", {"entity": XIAO, "fields": {"level": 90}})
    assert r.ok and r.data["topic_posted"] is False
    assert any("failed" in w.lower() for w in r.data["warnings"])
    eng = EntityEngine()
    assert eng.get_fields(uid, r.data["entity_id"])["level"] == 90  # DB stands


def test_entity_conversational_reference_resolves(temp_db, uid):
    """M1 ReferenceResolver reuse: 'her' after creating Xilonen resolves to
    Xilonen (active entity), exactly as in NL chat."""
    _game(uid)
    reg = _wire(uid)
    reg.execute("create_entity", {"name": XILONEN})   # activates her
    r = reg.execute("update_entity", {"entity": "her", "fields": {"level": 80}})
    assert r.ok and r.data["title"] == XILONEN
    eng = EntityEngine()
    assert eng.get_fields(uid, r.data["entity_id"])["level"] == 80


def test_entity_find_by_keyword(temp_db, uid):
    _game(uid)
    reg = _wire(uid)
    reg.execute("create_entity", {"name": XIAO})
    reg.execute("create_entity", {"name": KINICH})
    reg.execute("update_entity", {"entity": XIAO, "fields": {"element": "Anemo"}})
    r = reg.execute("find_entity", {"query": "Anemo"})
    assert [e["title"] for e in r.data] == [XIAO]
    r2 = reg.execute("find_entity", {"query": "kinich"})
    assert [e["title"] for e in r2.data] == [KINICH]
    r3 = reg.execute("find_entity", {"query": "ghost"})
    assert r3.ok and r3.data == []


def test_entity_get_does_not_change_active(temp_db, uid):
    """A READ_ONLY get must not mutate the persisted active entity."""
    _game(uid)
    reg = _wire(uid)
    reg.execute("create_entity", {"name": XIAO})       # active = Xiao
    kinich = reg.execute("create_entity", {"name": KINICH})  # active = Kinich
    r = reg.execute("get_entity", {"entity": XIAO})
    assert r.ok
    # a read must not move the persisted active entity
    assert db.tg_get_active(uid)[2] == kinich.data["entity_id"]


# ── tasks: list / find / create / update / complete / delete + reminder ──
def test_task_create_and_list(temp_db, uid):
    reg = _wire(uid)
    r = reg.execute("create_task", {"title": "Farm Xiao ascension"})
    assert r.ok and r.data["task_id"] > 0
    lst = reg.execute("list_tasks", {})
    assert lst.ok
    assert [t["title"] for t in lst.data] == ["Farm Xiao ascension"]


def test_task_reminder_surface_carries_due_fields(temp_db, uid):
    """Reminders are task due-times (no separate reminder entity). A task
    created with due_date+due_time exposes them in list_tasks structured
    data."""
    reg = _wire(uid)
    r = reg.execute("create_task", {"title": "Kinich weekly boss",
                                    "due_date": "2026-08-11", "due_time": "18:30"})
    assert r.ok
    lst = reg.execute("list_tasks", {})
    task = lst.data[0]
    assert task["due_date"] == "2026-08-11" and task["due_time"] == "18:30"
    assert task["recurrence_type"] is None


def test_task_create_duplicate_rejected(temp_db, uid):
    reg = _wire(uid)
    reg.execute("create_task", {"title": "Farm artifacts",
                                "due_date": "2026-08-11"})
    dup = reg.execute("create_task", {"title": "Farm artifacts",
                                      "due_date": "2026-08-11"})
    assert not dup.ok and dup.error_code == "invalid_args"
    assert "already exists" in dup.output


def test_task_create_rejects_invalid_datetime(temp_db, uid):
    reg = _wire(uid)
    r = reg.execute("create_task", {"title": "Bad date", "due_date": "2026-13-99"})
    assert not r.ok and r.error_code == "invalid_args"
    assert "Invalid date" in r.output


def test_task_find_by_title(temp_db, uid):
    reg = _wire(uid)
    reg.execute("create_task", {"title": "Xilonen night-time farm"})
    r = reg.execute("find_task", {"query": "night"})
    assert [t["title"] for t in r.data] == ["Xilonen night-time farm"]
    r2 = reg.execute("find_task", {"query": "nothing-here"})
    assert r2.ok and r2.data == []


def test_task_update(temp_db, uid):
    reg = _wire(uid)
    tid = reg.execute("create_task", {"title": "Farm Nefer materials"}).data["task_id"]
    r = reg.execute("update_task", {"task_id": tid, "category": "Study",
                                    "priority": "high"})
    assert r.ok and r.data["updated"] == {"category": "Study", "priority": "high"}
    row = db.get_task_by_id(tid, uid)
    assert row[4] == "Study" and row[5] == "high"


def test_task_complete(temp_db, uid):
    reg = _wire(uid)
    tid = reg.execute("create_task", {"title": "Lauma talent book"}).data["task_id"]
    r = reg.execute("complete_task", {"task_id": tid})
    assert r.ok and r.data["done"] is True
    # done tasks drop out of the pending list
    assert reg.execute("list_tasks", {}).data == []


def test_task_delete(temp_db, uid):
    reg = _wire(uid)
    tid = reg.execute("create_task", {"title": "Columbina boss"}).data["task_id"]
    r = reg.execute("delete_task", {"task_id": tid})
    assert r.ok and r.data["deleted"] is True
    assert db.get_task_by_id(tid, uid) is None


# ── habits / goals ───────────────────────────────────────────────────────
def test_habit_create_list_complete(temp_db, uid):
    reg = _wire(uid)
    hid = reg.execute("create_habit", {"title": "Daily Xiao farm",
                                       "time": "07:00"}).data["habit_id"]
    lst = reg.execute("list_habits", {})
    assert lst.data[0]["title"] == "Daily Xiao farm"
    r = reg.execute("complete_habit", {"habit_id": hid})
    assert r.ok and r.data["streak"] == 1 and r.data["already_logged"] is False
    # completing the same id through complete_task takes the habit branch
    r2 = reg.execute("complete_task", {"task_id": hid})
    assert r2.ok and r2.data["habit"] is True and r2.data["already_logged"] is True


def test_habit_complete_twice_is_not_an_error(temp_db, uid):
    reg = _wire(uid)
    hid = reg.execute("create_habit", {"title": "Xilonen daily"}).data["habit_id"]
    reg.execute("complete_habit", {"habit_id": hid})
    again = reg.execute("complete_habit", {"habit_id": hid})
    assert again.ok and again.data["already_logged"] is True


def test_goal_create_list_progress(temp_db, uid):
    reg = _wire(uid)
    gid = reg.execute("create_goal", {"title": "Reach AR 60",
                                      "deadline": "2026-12-31"}).data["goal_id"]
    lst = reg.execute("list_goals", {})
    assert lst.data[0]["progress"] == 0 and lst.data[0]["target"] == 100
    r = reg.execute("update_goal_progress", {"goal_id": gid, "delta": 50})
    assert r.data == {"goal_id": gid, "progress": 50, "target": 100,
                      "completed": False}
    r2 = reg.execute("update_goal_progress", {"goal_id": gid, "delta": 50})
    assert r2.data["completed"] is True


# ── workspace ────────────────────────────────────────────────────────────
def test_workspace_list_get_open(temp_db, uid):
    eng = EntityEngine()
    ws = eng.create_workspace(uid, "Genshin", template="game",
                              seed_milestones=False)
    db.tg_set_active(uid, ws.id)
    reg = _wire(uid)
    r = reg.execute("list_workspaces", {})
    assert [w["title"] for w in r.data] == ["Genshin"]
    g = reg.execute("get_workspace", {"workspace": "Genshin"})
    assert g.ok and g.data["workspace_id"] == ws.id
    o = reg.execute("open_workspace", {"workspace": "Genshin"})
    assert o.ok and o.data["active"] is True
    assert db.tg_get_active(uid)[0] == ws.id


def test_workspace_inspect(temp_db, uid):
    _, ws = _game(uid)
    eng = EntityEngine()
    m = eng.add_milestone(uid, ws.id, XIAO)
    eng.complete_milestone(uid, m.id)
    eng.add_note(uid, ws.id, "Xiao farming done", kind="progress")
    reg = _wire(uid)
    r = reg.execute("inspect_workspace", {"workspace": "Genshin"})
    assert r.ok and r.data["total_entities"] == 1
    assert r.data["entities"]["done"] == 1
    assert r.data["recent_notes"][0]["content"] == "Xiao farming done"


# ── memory / recall ──────────────────────────────────────────────────────
def test_memory_reads(temp_db, uid):
    db.save_memory(uid, "main_dps", XIAO)
    reg = _wire(uid)
    all_mem = reg.execute("get_memories", {})
    assert {m["key"]: m["value"] for m in all_mem.data} == {"main_dps": XIAO}
    found = reg.execute("search_memories", {"query": "xiao"})
    assert found.data[0]["key"] == "main_dps"
    miss = reg.execute("search_memories", {"query": "ghost"})
    assert miss.ok and miss.data == []


def test_recall_grounded_in_stored_data(temp_db, uid):
    _, ws = _game(uid)
    eng = EntityEngine()
    eng.add_milestone(uid, ws.id, XIAO)
    eng.add_note(uid, ws.id, "Xiao needs talent materials", kind="progress")
    reg = _wire(uid)
    r = reg.execute("recall", {"query": "materials"})
    assert r.ok and r.data
    assert any("talent materials" in d["text"] for d in r.data)
    miss = reg.execute("recall", {"query": "zygoth"})
    assert miss.ok and miss.data == []


# ── mixed-capability chaining (one registry) ─────────────────────────────
def test_mixed_capability_chain(temp_db, uid):
    """Entities + tasks + workspace all through ONE registry in sequence."""
    eng = EntityEngine()
    eng.create_workspace(uid, "Genshin", template="game", seed_milestones=False)
    reg = _wire(uid)
    reg.execute("open_workspace", {"workspace": "Genshin"})
    e = reg.execute("create_entity", {"name": XIAO})
    u = reg.execute("update_entity", {"entity": XIAO,
                                      "fields": {"level": 90, "element": "Anemo"}})
    t = reg.execute("create_task", {"title": "Farm Xiao ascension",
                                    "due_date": "2026-08-11"})
    c = reg.execute("complete_task", {"task_id": t.data["task_id"]})
    lst = reg.execute("list_entities", {})
    tasks = reg.execute("list_tasks", {})
    assert all(r.ok for r in (e, u, t, c, lst, tasks))
    assert [x["title"] for x in lst.data] == [XIAO]
    assert tasks.data == []   # completed
    assert u.data["applied"]["level"] == 90


# ── adversarial ──────────────────────────────────────────────────────────
def test_mutating_tool_rejects_unknown_arg(temp_db, uid):
    reg = _wire(uid)
    r = reg.execute("create_task", {"title": "X", "bogus": 1})
    assert not r.ok and r.error_code == "invalid_args"
    assert "bogus" in r.output


def test_readonly_tool_drops_unknown_arg(temp_db, uid):
    reg = _wire(uid)
    r = reg.execute("list_tasks", {"done": 0, "bogus": 1})
    assert r.ok   # unknown arg silently dropped on a read


def test_required_args_enforced(temp_db, uid):
    reg = _wire(uid)
    assert reg.execute("delete_task", {}).error_code == "invalid_args"
    assert reg.execute("find_task", {"query": ""}).error_code == "invalid_args"
    assert reg.execute("update_goal_progress",
                       {"goal_id": 1}).error_code == "invalid_args"


def test_missing_targets_are_invalid_args(temp_db, uid):
    reg = _wire(uid)
    for name, args in (
        ("complete_task", {"task_id": 999999}),
        ("delete_task", {"task_id": 999999}),
        ("update_task", {"task_id": 999999, "title": "X"}),
        ("complete_habit", {"habit_id": 999999}),
        ("update_goal_progress", {"goal_id": 999999, "delta": 5}),
        ("get_workspace", {"workspace": "ghost"}),
        ("get_entity", {"entity": "ghost"}),
    ):
        r = reg.execute(name, args)
        assert not r.ok and r.error_code == "invalid_args", name


def test_update_task_requires_a_change(temp_db, uid):
    reg = _wire(uid)
    tid = reg.execute("create_task", {"title": "X"}).data["task_id"]
    r = reg.execute("update_task", {"task_id": tid})
    assert not r.ok and "no fields" in r.output


def test_update_entity_requires_nonempty_fields(temp_db, uid):
    _game(uid)
    reg = _wire(uid)
    reg.execute("create_entity", {"name": XIAO})
    r = reg.execute("update_entity", {"entity": XIAO, "fields": {}})
    assert not r.ok and r.error_code == "invalid_args"


def test_entity_create_without_active_workspace_rejected(temp_db, uid):
    reg = _wire(uid)   # nothing created, nothing active
    r = reg.execute("create_entity", {"name": XIAO})
    assert not r.ok and r.error_code == "invalid_args"
    assert "workspace" in r.output.lower()


def test_entity_unknown_field_allowed_forward_compat(temp_db, uid):
    _game(uid)
    reg = _wire(uid)
    reg.execute("create_entity", {"name": XIAO})
    r = reg.execute("update_entity", {"entity": XIAO,
                                      "fields": {"future_field": "v"}})
    assert r.ok and r.data["applied"] == {"future_field": "v"}
    eng = EntityEngine()
    assert eng.get_fields(uid, r.data["entity_id"])["future_field"] == "v"


def test_entity_invalid_field_value_rejected(temp_db, uid):
    _game(uid)
    reg = _wire(uid)
    reg.execute("create_entity", {"name": XIAO})
    r = reg.execute("update_entity", {"entity": XIAO, "fields": {"level": "abc"}})
    assert not r.ok and r.error_code == "invalid_args"
    assert "level" in r.output   # tells the caller WHICH field failed


def test_registry_rejects_duplicate_names(temp_db, uid):
    reg = ToolRegistry()
    reg.register(_wire(uid).get("list_tasks"))
    with pytest.raises(ToolRegistryError):
        reg.register(_wire(uid).get("list_tasks"))


def test_registry_execute_never_raises(temp_db, uid):
    reg = _wire(uid)
    for name, args in (("no_such_tool", {}), ("create_task", "nope"),
                       ("create_task", {"title": 5}),
                       ("delete_task", {"task_id": True}),
                       ("update_entity", {"entity": "x", "fields": 3})):
        result = reg.execute(name, args)
        assert isinstance(result, object) and result is not None
        assert hasattr(result, "ok")


def test_risk_classification(temp_db, uid):
    expected = {
        "list_tasks": RiskLevel.READ_ONLY, "find_task": RiskLevel.READ_ONLY,
        "create_task": RiskLevel.MUTATING, "update_task": RiskLevel.MUTATING,
        "complete_task": RiskLevel.MUTATING, "delete_task": RiskLevel.DESTRUCTIVE,
        "create_habit": RiskLevel.MUTATING, "list_habits": RiskLevel.READ_ONLY,
        "complete_habit": RiskLevel.MUTATING,
        "create_goal": RiskLevel.MUTATING, "list_goals": RiskLevel.READ_ONLY,
        "update_goal_progress": RiskLevel.MUTATING,
        "create_entity": RiskLevel.MUTATING, "get_entity": RiskLevel.READ_ONLY,
        "update_entity": RiskLevel.MUTATING, "list_entities": RiskLevel.READ_ONLY,
        "find_entity": RiskLevel.READ_ONLY,
        "list_workspaces": RiskLevel.READ_ONLY, "get_workspace": RiskLevel.READ_ONLY,
        "open_workspace": RiskLevel.MUTATING,   # honest: changes active state
        "inspect_workspace": RiskLevel.READ_ONLY,
        "get_memories": RiskLevel.READ_ONLY, "search_memories": RiskLevel.READ_ONLY,
        "recall": RiskLevel.READ_ONLY,
    }
    reg = _wire(uid)
    assert set(reg.names()) == set(expected)
    for name, risk in expected.items():
        assert reg.get(name).spec.risk is risk, name
    # nothing is classified SYSTEM in M3 (no admin/system surface yet)
    assert all(t.spec.risk is not RiskLevel.SYSTEM for t in reg.all())


def test_delete_task_carries_confirmation_message(temp_db, uid):
    reg = _wire(uid)
    spec = reg.get("delete_task").spec
    assert spec.confirmation_message and "cannot be undone" in spec.confirmation_message


# ── integration: projection not bypassed (real TelegramProjection) ───────
def test_end_to_end_projection_with_real_client(temp_db, uid):
    """The full chain offline: FakeClient + TelegramProjection. create_entity
    makes ONE topic + initial card; update_entity appends ONE message to that
    same topic. Proves the adapter uses the alpha.13 single mechanism."""
    client = FakeClient()
    proj = TelegramProjection(client)
    eng = EntityEngine()
    ws = eng.create_workspace(uid, "Genshin", template="game", seed_milestones=False)
    db.tg_set_active(uid, ws.id)
    proj.link_group(uid, ws.id, -100999)   # real binding path
    reg = build_tool_registry(uid, projection=proj)

    r = reg.execute("create_entity", {"name": XIAO})
    assert r.ok and r.data["topic_created"] is True
    eid = r.data["entity_id"]
    assert len(client.topics) == 1 and client.topics[0] == (-100999, XIAO)
    # the initial card was posted to the new topic
    assert len(client.messages) == 1
    assert client.messages[0][0] == -100999 and client.messages[0][1] == 101
    assert XIAO in client.messages[0][2]
    # binding row records the topic (adapter-owned, same as /add)
    assert db.tg_get_entity_topic("milestone", eid) == 101

    u = reg.execute("update_entity", {"entity": XIAO, "fields": {"level": 90}})
    assert u.ok and u.data["topic_posted"] is True
    # NO second topic created; the update is append-only to the existing one
    assert len(client.topics) == 1
    assert len(client.messages) == 2
    assert client.messages[1][1] == 101
    assert "Level" in client.messages[1][2]
