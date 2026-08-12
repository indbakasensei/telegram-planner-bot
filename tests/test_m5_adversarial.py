"""
v15.3 M5-H -- the 14-scenario adversarial matrix (plan section 7).

Fourteen adversarial scenario kinds applied across every M5 feature
(workspace control, entity CRUD per kind, topic lifecycle, identity
inspector, equipment, task/goal/habit foundation):

  happy / duplicate / missing / wrong_kind / wrong_workspace /
  already_locked / already_unlocked / missing_topic / repeated /
  cancel_confirm / invalid_input / stale_identity /
  cross_ws_isolation / permission_boundary

Fresh names ONLY (M5_Test_Character_A/B, M5_Test_Weapon_A,
M5_Test_Artifact_A) -- nothing here can collide with live or fixture data.

Failure policy (binding, plan section 7): a failing scenario is fixed in the
implementation (or the expectation re-derived from the SPEC) -- never
weakened or deleted.
"""
import asyncio

import pytest

import database as db
from core.ai.tool_adapters import build_tool_registry
from core.control import pages
from core.control.actions import begin_confirm, confirm_no, pending_for
from core.control.registry import build_context
from core.control.router import _topic_delete_dialog
from core.workspace.adapters.projection import TelegramProjection
from core.workspace.engine import EntityEngine

# fresh-only names
CHAR_A, CHAR_B = "M5_Test_Character_A", "M5_Test_Character_B"
WEAPON_A = "M5_Test_Weapon_A"
ARTIFACT_A = "M5_Test_Artifact_A"
ADOPT_A = "M5_Test_Adopt_A"   # deliberately kind-neutral (no kind word)
WS_A, WS_B = "M5_Test_Workspace_A", "M5_Test_Workspace_B"

_ENTITY_TYPE = "milestone"   # the binding constant every tool adapter uses


class _Client:
    def __init__(self):
        self.topics = []
        self.messages = []

    def create_forum_topic(self, chat_id, name):
        self.topics.append((chat_id, name))
        return 100 + len(self.topics)

    def send_message(self, chat_id, topic_id, text, parse_mode=None):
        self.messages.append((chat_id, topic_id, text, parse_mode))
        return 1000 + len(self.messages)

    def delete_forum_topic(self, chat_id, topic_id):
        self.topics = [(c, n) for c, n in self.topics if c != chat_id
                       or n != f"t{topic_id}"]
        return True


def _game(uid):
    eng = EntityEngine()
    ws = eng.create_workspace(uid, "Genshin", template="game",
                              seed_milestones=False)
    db.tg_set_active(uid, ws.id)
    return eng, ws


def _linked(uid, ws):
    client = _Client()
    proj = TelegramProjection(client)
    proj.link_group(uid, ws.id, -100999)
    return proj, client


def _make(uid, ws_id, title, etype):
    return EntityEngine().add_milestone(uid, ws_id, title, entity_type=etype)


def _ctx(uid, projection_factory=None):
    return build_context(uid, projection_factory=projection_factory)


def _reg(uid, projection=None):
    return build_tool_registry(uid, projection=projection)


def _run(coro):
    """Run an async control-plane helper to completion (fresh event loop --
    these are sync tests over the same temp-DB storage)."""
    return asyncio.run(coro)


# ══════════════════════════ WORKSPACE CONTROL (M5-A) ══════════════════════
def test_ws_happy_lifecycle(temp_db, uid):
    reg = _reg(uid)
    r = reg.execute("create_workspace", {"title": WS_A, "template": "game"})
    assert r.ok and r.data["active"] is True
    ws_id = r.data["workspace_id"]
    assert db.tg_get_active(uid)[0] == ws_id
    # rename
    assert reg.execute("rename_workspace",
                       {"workspace": ws_id, "title": "M5_Test_Workspace_Renamed"}).ok
    # open (switch) is a no-op on the already-active ws
    assert reg.execute("open_workspace", {"workspace": ws_id}).ok
    # close clears active, row survives
    assert reg.execute("close_workspace", {}).ok
    active = db.tg_get_active(uid)
    assert active is None or active[0] is None
    assert EntityEngine().get_workspace_or_none(uid, ws_id) is not None


def test_ws_duplicate_title_is_not_a_false_refusal(temp_db, uid):
    reg = _reg(uid)
    a = reg.execute("create_workspace", {"title": WS_A, "template": "game"})
    b = reg.execute("create_workspace", {"title": WS_A, "template": "game"})
    # workspaces are NOT title-deduplicated -- a second same-title workspace
    # is legal and distinct (the duplicate guard lives at ENTITY level)
    assert a.ok and b.ok and a.data["workspace_id"] != b.data["workspace_id"]


def test_ws_missing_target_is_strict(temp_db, uid):
    reg = _reg(uid)
    for tool, args in (
        ("open_workspace", {"workspace": 999999}),
        ("rename_workspace", {"workspace": 999999, "title": "X"}),
        ("archive_workspace", {"workspace": 999999}),
    ):
        r = reg.execute(tool, args)
        assert not r.ok, tool
        assert "no workspace matches" in r.output, tool
    # nothing was silently touched
    assert EntityEngine().list_workspaces(uid) == []


def test_ws_wrong_kind_template_rejected(temp_db, uid):
    reg = _reg(uid)
    r = reg.execute("create_workspace", {"title": WS_A, "template": "spaceship"})
    assert not r.ok and "unknown workspace kind" in r.output


def test_ws_repeated_ops_are_noop(temp_db, uid):
    eng, ws = _game(uid)
    reg = _reg(uid)
    # close twice: both contained no-ops, the row never disappears
    assert reg.execute("close_workspace", {}).ok
    assert reg.execute("close_workspace", {}).ok
    assert eng.get_workspace_or_none(uid, ws.id) is not None
    # archive twice: second reports noop
    first = reg.execute("archive_workspace", {"workspace": ws.id})
    assert first.ok and first.data["noop"] is False
    second = reg.execute("archive_workspace", {"workspace": ws.id})
    assert second.ok and second.data["noop"] is True


def test_ws_cancel_confirmation_does_not_execute(temp_db, uid):
    eng, ws = _game(uid)
    ctx = _ctx(uid)
    begin_confirm(ctx, "archive_workspace", {"workspace": ws.id},
                  return_to="ctl:ws:home")
    assert pending_for(uid) is not None
    _run(confirm_no(ctx, lambda t: pages.control_home(ctx)))
    assert pending_for(uid) is None
    assert eng.get_workspace_or_none(uid, ws.id).status == "active"  # untouched


def test_ws_cross_ws_isolation(temp_db, uid):
    eng = EntityEngine()
    a = eng.create_workspace(uid, WS_A, template="game", seed_milestones=False)
    b = eng.create_workspace(uid, WS_B, template="game", seed_milestones=False)
    db.tg_set_active(uid, b.id)
    # closing the ACTIVE workspace must not touch A's binding; opening A
    # switches cleanly
    _make(uid, a.id, CHAR_A, "character")
    reg = _reg(uid)
    assert reg.execute("close_workspace", {}).ok
    assert eng.list_milestones(uid, a.id)  # A's entities untouched
    assert reg.execute("open_workspace", {"workspace": a.id}).ok
    assert db.tg_get_active(uid)[0] == a.id


# ══════════════════════ ENTITY CRUD PER KIND (M5-B) ══════════════════════
@pytest.mark.parametrize("kind,name", [
    ("character", CHAR_A), ("weapon", WEAPON_A), ("artifact", ARTIFACT_A),
])
def test_ent_happy_create_get_list_kind(temp_db, uid, kind, name):
    eng, ws = _game(uid)
    reg = _reg(uid)
    r = reg.execute("create_entity", {"name": name, "entity_type": kind})
    assert r.ok and r.data["entity_type"] == kind
    got = reg.execute("get_entity", {"entity": name})
    assert got.ok and got.data["entity_type"] == kind
    listed = reg.execute("list_entities", {"kind": kind})
    assert [d["title"] for d in listed.data] == [name]


@pytest.mark.parametrize("kind", ["character", "weapon", "artifact"])
def test_ent_duplicate_same_kind_rejected(temp_db, uid, kind):
    eng, ws = _game(uid)
    reg = _reg(uid)
    assert reg.execute("create_entity", {"name": CHAR_A, "entity_type": kind}).ok
    dup = reg.execute("create_entity", {"name": CHAR_A, "entity_type": kind})
    assert not dup.ok and "already exists" in dup.output
    assert len(eng.list_milestones(uid, ws.id)) == 1   # no second row


def test_ent_duplicate_cross_kind_adopts(temp_db, uid):
    """Same name, different kind → the existing UNTYPED row ADOPTS the kind
    (one entity, one topic) -- never a second duplicate. (A typed row's DB
    kind wins per M4 priority 1, so a same-name different-kind create on a
    typed row reads as an honest 'already exists' instead -- pinned in
    test_ent_duplicate_same_kind_rejected.)"""
    eng, ws = _game(uid)
    reg = _reg(uid)
    assert reg.execute("create_entity",
                       {"name": ADOPT_A, "entity_type": "entity"}).ok
    adopted = reg.execute("create_entity",
                          {"name": ADOPT_A, "entity_type": "weapon"})
    assert adopted.ok and adopted.data["adopted"] is True
    assert adopted.data["entity_type"] == "weapon"
    assert len(eng.list_milestones(uid, ws.id)) == 1   # one row, one topic


def test_ent_missing_targets_are_errors(temp_db, uid):
    eng, ws = _game(uid)
    reg = _reg(uid)
    for tool, args in (
        ("get_entity", {"entity": "No Such Entity"}),
        ("update_entity", {"entity": "No Such Entity", "fields": {"level": 1}}),
        ("delete_entity", {"entity": "No Such Entity"}),
    ):
        r = reg.execute(tool, args)
        assert not r.ok, tool
        assert "no entity matches" in r.output, tool


def test_ent_invalid_input_validation_error(temp_db, uid):
    eng, ws = _game(uid)
    reg = _reg(uid)
    reg.execute("create_entity", {"name": CHAR_A, "entity_type": "character"})
    # level is an int 1-100: a text value is a validation error
    r = reg.execute("update_entity",
                    {"entity": CHAR_A, "fields": {"level": "not_a_number"}})
    assert not r.ok and r.error_code == "invalid_args"
    # the bad value was never written
    ch = eng.list_milestones(uid, ws.id)[0]
    assert eng.get_fields(uid, ch.id).get("level") != "not_a_number"


def test_ent_repeated_delete_errors_cleanly(temp_db, uid):
    eng, ws = _game(uid)
    reg = _reg(uid)
    reg.execute("create_entity", {"name": CHAR_A, "entity_type": "character"})
    first = reg.execute("delete_entity", {"entity": CHAR_A})
    assert first.ok and first.data["deleted"] is True
    second = reg.execute("delete_entity", {"entity": CHAR_A})
    assert not second.ok and "no entity matches" in second.output


def test_ent_cancel_delete_keeps_entity(temp_db, uid):
    eng, ws = _game(uid)
    reg = _reg(uid)
    reg.execute("create_entity", {"name": CHAR_A, "entity_type": "character"})
    ctx = _ctx(uid)
    begin_confirm(ctx, "delete_entity", {"entity": CHAR_A},
                  return_to="ctl:ent:list:character")
    assert pending_for(uid) is not None
    _run(confirm_no(ctx, lambda t: pages.control_home(ctx)))
    assert pending_for(uid) is None
    assert len(eng.list_milestones(uid, ws.id)) == 1   # entity survives


def test_ent_wrong_kind_does_not_leak(temp_db, uid):
    eng, ws = _game(uid)
    reg = _reg(uid)
    reg.execute("create_entity", {"name": CHAR_A, "entity_type": "character"})
    # the character never appears in the weapon/artifact lists
    for kind in ("weapon", "artifact"):
        listed = reg.execute("list_entities", {"kind": kind})
        assert listed.data == [], kind
    # and equip refuses the wrong role (a weapon can't be a character)
    reg.execute("create_entity", {"name": WEAPON_A, "entity_type": "weapon"})
    wrong = reg.execute("equip_item", {"character": WEAPON_A, "item": WEAPON_A})
    assert not wrong.ok and "not an equippable character" in wrong.output


def test_ent_cross_ws_isolation(temp_db, uid):
    eng = EntityEngine()
    a = eng.create_workspace(uid, WS_A, template="game", seed_milestones=False)
    b = eng.create_workspace(uid, WS_B, template="game", seed_milestones=False)
    _make(uid, a.id, CHAR_A, "character")
    db.tg_set_active(uid, b.id)
    reg = _reg(uid)
    # CHAR_A lives in A; with B active it must not resolve (never silently
    # reach across workspaces)
    r = reg.execute("get_entity", {"entity": CHAR_A})
    assert not r.ok and "no entity matches" in r.output
    r = reg.execute("delete_entity", {"entity": CHAR_A})
    assert not r.ok and "no entity matches" in r.output
    assert len(eng.list_milestones(uid, a.id)) == 1   # A untouched


# ════════════════════════ TOPIC LIFECYCLE (M5-C) ═════════════════════════
def test_topic_happy_lifecycle(temp_db, uid):
    eng, ws = _game(uid)
    proj, client = _linked(uid, ws)
    m = _make(uid, ws.id, CHAR_A, "character")
    reg = _reg(uid, projection=proj)
    ensured = reg.execute("ensure_entity_topic", {"entity": CHAR_A})
    assert ensured.ok and ensured.data["topic_id"] is not None
    assert db.tg_get_entity_topic(_ENTITY_TYPE, m.id) is not None
    # lock → unlocked → delete
    assert reg.execute("set_entity_topic_locked",
                       {"entity": CHAR_A, "locked": True}).ok
    assert db.tg_get_entity_topic_locked(ws.id, _ENTITY_TYPE, m.id) is True
    assert reg.execute("set_entity_topic_locked",
                       {"entity": CHAR_A, "locked": False}).ok
    deleted = reg.execute("delete_entity_topic", {"entity": CHAR_A})
    # success = ok + binding gone (reason only carries refusal/partial notes)
    assert deleted.ok and deleted.data["topic_id"] is not None
    assert db.tg_get_entity_topic(_ENTITY_TYPE, m.id) is None
    # entity row survives the topic delete (DELETE TOPIC ≠ DELETE ENTITY)
    assert len(eng.list_milestones(uid, ws.id)) == 1


def test_topic_already_locked_and_unlocked_are_noop(temp_db, uid):
    eng, ws = _game(uid)
    proj, _ = _linked(uid, ws)
    m = _make(uid, ws.id, CHAR_A, "character")
    proj.ensure_entity_topic(uid, ws.id, _ENTITY_TYPE, m.id, CHAR_A)
    reg = _reg(uid, projection=proj)
    # lock twice → the second is ok and stays locked
    assert reg.execute("set_entity_topic_locked",
                       {"entity": CHAR_A, "locked": True}).ok
    again = reg.execute("set_entity_topic_locked",
                        {"entity": CHAR_A, "locked": True})
    assert again.ok and db.tg_get_entity_topic_locked(
        ws.id, _ENTITY_TYPE, m.id) is True
    # unlock twice → the second is ok and stays unlocked
    assert reg.execute("set_entity_topic_locked",
                       {"entity": CHAR_A, "locked": False}).ok
    again2 = reg.execute("set_entity_topic_locked",
                         {"entity": CHAR_A, "locked": False})
    assert again2.ok and db.tg_get_entity_topic_locked(
        ws.id, _ENTITY_TYPE, m.id) is False


def test_topic_locked_refuses_ordinary_delete(temp_db, uid):
    eng, ws = _game(uid)
    proj, _ = _linked(uid, ws)
    m = _make(uid, ws.id, CHAR_A, "character")
    proj.ensure_entity_topic(uid, ws.id, _ENTITY_TYPE, m.id, CHAR_A)
    proj.set_topic_locked(ws.id, _ENTITY_TYPE, m.id, True)
    reg = _reg(uid, projection=proj)
    refused = reg.execute("delete_entity_topic", {"entity": CHAR_A})
    assert not refused.ok and "LOCKED" in refused.output
    # force deletes a locked topic (success = ok + binding gone)
    forced = reg.execute("delete_entity_topic",
                         {"entity": CHAR_A, "force": True})
    assert forced.ok and forced.data["topic_id"] is not None
    assert db.tg_get_entity_topic(_ENTITY_TYPE, m.id) is None


def test_topic_missing_topic_is_contained_error(temp_db, uid):
    eng, ws = _game(uid)
    proj, _ = _linked(uid, ws)
    _make(uid, ws.id, CHAR_A, "character")
    reg = _reg(uid, projection=proj)
    r = reg.execute("delete_entity_topic", {"entity": CHAR_A})
    assert not r.ok and "no Telegram topic" in r.output
    # repeated delete of the same missing topic is the same contained error
    again = reg.execute("delete_entity_topic", {"entity": CHAR_A})
    assert not again.ok and "no Telegram topic" in again.output


def test_topic_missing_entity_is_error(temp_db, uid):
    eng, ws = _game(uid)
    proj, _ = _linked(uid, ws)
    reg = _reg(uid, projection=proj)
    for tool, args in (
        ("ensure_entity_topic", {"entity": "No Such Entity"}),
        ("set_entity_topic_locked", {"entity": "No Such Entity", "locked": True}),
        ("delete_entity_topic", {"entity": "No Such Entity"}),
    ):
        r = reg.execute(tool, args)
        assert not r.ok, tool
        assert "no entity matches" in r.output, tool


def test_topic_cancel_force_delete_keeps_topic(temp_db, uid):
    eng, ws = _game(uid)
    proj, _ = _linked(uid, ws)
    m = _make(uid, ws.id, CHAR_A, "character")
    proj.ensure_entity_topic(uid, ws.id, _ENTITY_TYPE, m.id, CHAR_A)
    proj.set_topic_locked(ws.id, _ENTITY_TYPE, m.id, True)
    ctx = _ctx(uid, projection_factory=lambda: proj)
    # the locked-topic delete dialog offers Force delete, not a plain confirm
    text, _kb = _topic_delete_dialog(ctx, m, ws)
    assert "LOCKED" in text
    # user taps Force delete → confirm → Cancel: the topic stays locked
    begin_confirm(ctx, "delete_entity_topic",
                  {"entity": str(m.id), "workspace": ws.id, "force": True},
                  return_to=f"ctl:topic:view:{m.id}")
    assert pending_for(uid) is not None
    _run(confirm_no(ctx, lambda t: pages.control_home(ctx)))
    assert pending_for(uid) is None
    assert db.tg_get_entity_topic(_ENTITY_TYPE, m.id) is not None
    assert db.tg_get_entity_topic_locked(ws.id, _ENTITY_TYPE, m.id) is True
    assert len(eng.list_milestones(uid, ws.id)) == 1


def test_topic_cross_ws_isolation(temp_db, uid):
    eng = EntityEngine()
    a = eng.create_workspace(uid, WS_A, template="game", seed_milestones=False)
    b = eng.create_workspace(uid, WS_B, template="game", seed_milestones=False)
    _make(uid, a.id, CHAR_A, "character")
    proj, _ = _linked(uid, a)
    db.tg_set_active(uid, b.id)
    reg = _reg(uid, projection=proj)
    # the topic tool resolves the entity in the ACTIVE (B) workspace only --
    # A's entity is unreachable, so no stray topic is ever created in A
    r = reg.execute("ensure_entity_topic", {"entity": CHAR_A})
    assert not r.ok and "no entity matches" in r.output
    assert db.tg_get_entity_topic(
        _ENTITY_TYPE, eng.list_milestones(uid, a.id)[0].id) is None


# ═══════════════════════ IDENTITY INSPECTOR (M5-D) ════════════════════════
def test_identity_happy_full_rows(temp_db, uid):
    eng, ws = _game(uid)
    m = _make(uid, ws.id, CHAR_A, "character")
    proj, _ = _linked(uid, ws)
    proj.ensure_entity_topic(uid, ws.id, _ENTITY_TYPE, m.id, CHAR_A)
    text, kb = pages.identity_inspector(_ctx(uid), m.id)
    for label in ("Name", "Entity ID", "Kind", "Workspace", "Topic ID",
                  "Topic status", "Lock status", "Active"):
        assert label in text, label


def test_identity_missing_entity_page(temp_db, uid):
    eng, ws = _game(uid)
    text, _ = pages.identity_inspector(_ctx(uid), 999999)
    assert "not found" in text.lower()


def test_identity_stale_after_delete(temp_db, uid):
    eng, ws = _game(uid)
    m = _make(uid, ws.id, CHAR_A, "character")
    reg = _reg(uid)
    reg.execute("delete_entity", {"entity": CHAR_A})
    # the inspector for a deleted entity reads as missing (never a ghost row)
    text, _ = pages.identity_inspector(_ctx(uid), m.id)
    assert "not found" in text.lower()


def test_identity_cross_ws_isolation(temp_db, uid):
    eng = EntityEngine()
    a = eng.create_workspace(uid, WS_A, template="game", seed_milestones=False)
    b = eng.create_workspace(uid, WS_B, template="game", seed_milestones=False)
    m = _make(uid, a.id, CHAR_A, "character")
    db.tg_set_active(uid, b.id)
    # the inspector only reads the ACTIVE workspace -- A's entity is absent
    text, _ = pages.identity_inspector(_ctx(uid), m.id)
    assert "not found" in text.lower()


# ════════════════════════ EQUIPMENT (M5-E) ════════════════════════════════
def test_equip_happy_equip_unequip(temp_db, uid):
    eng, ws = _game(uid)
    ch = _make(uid, ws.id, CHAR_A, "character")
    _make(uid, ws.id, WEAPON_A, "weapon")
    reg = _reg(uid)
    r = reg.execute("equip_item", {"character": CHAR_A, "item": WEAPON_A})
    assert r.ok and eng.get_fields(uid, ch.id).get("weapon") == WEAPON_A
    u = reg.execute("equip_item", {"character": CHAR_A})
    assert u.ok and eng.get_fields(uid, ch.id).get("weapon") in ("", None)


def test_equip_wrong_kind_refused(temp_db, uid):
    eng, ws = _game(uid)
    _make(uid, ws.id, CHAR_A, "character")
    _make(uid, ws.id, ARTIFACT_A, "artifact")
    _make(uid, ws.id, WEAPON_A, "weapon")
    reg = _reg(uid)
    # artifact item → refused (M5-E boundary, no second DB)
    artifact = reg.execute("equip_item",
                           {"character": CHAR_A, "item": ARTIFACT_A})
    assert not artifact.ok and "artifact" in artifact.output.lower()
    # equip onto a weapon → refused
    onto_weapon = reg.execute("equip_item",
                              {"character": WEAPON_A, "item": WEAPON_A})
    assert not onto_weapon.ok
    # nothing was written to the character
    ch = eng.list_milestones(uid, ws.id)[0]
    assert eng.get_fields(uid, ch.id).get("weapon") in (None, "")


def test_equip_missing_targets_are_errors(temp_db, uid):
    eng, ws = _game(uid)
    _make(uid, ws.id, CHAR_A, "character")
    reg = _reg(uid)
    missing_item = reg.execute("equip_item",
                               {"character": CHAR_A, "item": "No Weapon"})
    assert not missing_item.ok and "no entity matches" in missing_item.output
    missing_char = reg.execute("equip_item",
                               {"character": "No Character", "item": "x"})
    assert not missing_char.ok and "no entity matches" in missing_char.output


def test_equip_repeated_op_is_idempotent(temp_db, uid):
    eng, ws = _game(uid)
    _make(uid, ws.id, CHAR_A, "character")
    _make(uid, ws.id, WEAPON_A, "weapon")
    reg = _reg(uid)
    assert reg.execute("equip_item",
                       {"character": CHAR_A, "item": WEAPON_A}).ok
    again = reg.execute("equip_item", {"character": CHAR_A, "item": WEAPON_A})
    assert again.ok   # same value re-written, never an error or a second row
    ch = eng.list_milestones(uid, ws.id)[0]
    assert eng.get_fields(uid, ch.id).get("weapon") == WEAPON_A


def test_equip_cross_ws_isolation(temp_db, uid):
    eng = EntityEngine()
    a = eng.create_workspace(uid, WS_A, template="game", seed_milestones=False)
    b = eng.create_workspace(uid, WS_B, template="game", seed_milestones=False)
    ch = _make(uid, a.id, CHAR_A, "character")
    _make(uid, a.id, WEAPON_A, "weapon")
    db.tg_set_active(uid, b.id)
    reg = _reg(uid)
    r = reg.execute("equip_item", {"character": CHAR_A, "item": WEAPON_A})
    assert not r.ok and "no entity matches" in r.output
    assert eng.get_fields(uid, ch.id).get("weapon") in (None, "")


# ══════════════════ TASK / GOAL / HABIT FOUNDATION (M5-G) ═════════════════
def test_foundation_happy_task_goal_habit(temp_db, uid):
    reg = _reg(uid)
    t = reg.execute("create_task", {"title": "M5_Test_Task_A"})
    assert t.ok and t.data["task_id"] > 0
    g = reg.execute("create_goal", {"title": "M5_Test_Goal_A"})
    assert g.ok and g.data["goal_id"] > 0
    h = reg.execute("create_habit", {"title": "M5_Test_Habit_A"})
    assert h.ok and h.data["habit_id"] > 0
    # complete_task completes a task by id
    assert reg.execute("complete_task", {"task_id": t.data["task_id"]}).ok
    # complete_habit logs a habit by id (repeat is not an error)
    assert reg.execute("complete_habit", {"habit_id": h.data["habit_id"]}).ok


def test_foundation_duplicate_task_same_date_rejected(temp_db, uid):
    reg = _reg(uid)
    assert reg.execute("create_task", {"title": "M5_Test_Task_A",
                                       "due_date": "2026-08-12"}).ok
    dup = reg.execute("create_task", {"title": "M5_Test_Task_A",
                                      "due_date": "2026-08-12"})
    assert not dup.ok and "already exists" in dup.output


def test_foundation_missing_targets_are_errors(temp_db, uid):
    reg = _reg(uid)
    assert not reg.execute("complete_task", {"task_id": 999999}).ok
    assert not reg.execute("complete_habit", {"habit_id": 999999}).ok
    assert not reg.execute("update_goal_progress",
                           {"goal_id": 999999, "delta": 50}).ok


def test_foundation_invalid_input_rejected(temp_db, uid):
    reg = _reg(uid)
    bad_date = reg.execute("create_task", {"title": "X", "due_date": "2026-13-99"})
    assert not bad_date.ok and "Invalid date" in bad_date.output
    bad_deadline = reg.execute("update_goal_deadline",
                               {"goal": "Any", "deadline": "not-a-date"})
    assert not bad_deadline.ok and "invalid deadline" in bad_deadline.output


# ═══════════════════════════ PERMISSION BOUNDARY ══════════════════════════
def test_cross_user_isolation(temp_db, uid):
    """A second user can neither see nor mutate the first user's data --
    every engine/tool path is ownership-checked. `other` has their OWN active
    workspace, so even the most permissive resolver path resolves inside
    other's surface and still can't reach owner's entity."""
    owner, other = uid, uid + 1
    eng = EntityEngine()
    ws = eng.create_workspace(owner, WS_A, template="game",
                              seed_milestones=False)
    db.tg_set_active(owner, ws.id)
    _make(owner, ws.id, CHAR_A, "character")
    other_ws = eng.create_workspace(other, WS_B, template="game",
                                    seed_milestones=False)
    db.tg_set_active(other, other_ws.id)
    reg_other = _reg(other)
    # other's workspace surface does not include owner's workspace
    assert [w.id for w in eng.list_workspaces(other)] == [other_ws.id]
    assert eng.get_workspace_or_none(other, ws.id) is None
    # other cannot resolve owner's entity by name (own active workspace),
    # nor by the owner's workspace ref -- both refuse before touching owner
    r = reg_other.execute("get_entity", {"entity": CHAR_A})
    assert not r.ok and "no entity matches" in r.output
    r = reg_other.execute("get_entity",
                          {"entity": CHAR_A, "workspace": ws.id})
    assert not r.ok and "no entity matches" in r.output
    r = reg_other.execute("delete_entity",
                          {"entity": CHAR_A, "workspace": ws.id})
    assert not r.ok
    # owner's data is intact
    assert len(eng.list_milestones(owner, ws.id)) == 1
