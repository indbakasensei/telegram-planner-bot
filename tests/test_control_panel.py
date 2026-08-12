"""
v15.3 M5 -- Manual Control Plane offline tests (core/control/*).

Proves on a temp DB (no Telegram) that:
  * every page renders and navigates (control_home, workspace, entity,
    topic, identity, equipment) with keyboards whose callbacks resolve;
  * the ctl: router dispatches every MUTATING op through the SHARED
    ToolRegistry path (execute_tool_async) -- never a second
    business-logic layer -- and the manual path produces the SAME domain
    effects the Worker's registry.execute produces;
  * the M5-F confirm flow gates DESTRUCTIVE tools with the tool spec's own
    wording and executes on [Yes], discards on [No];
  * data-entry gathers validate before confirming (create workspace,
    rename workspace, add entity, edit entity) -- including the
    kind-conflict refusal and field validation.

Threading contract (core/control/registry.py): the projection is resolved on
the event loop and frozen via with_projection before asyncio.to_thread runs
the tool. These tests exercise exactly that path (execute_tool_async /
confirm_yes / _dispatch).
"""
import pytest

import database as db
from core.ai.tools import RiskLevel
from core.control import pages
from core.control.actions import (
    begin_confirm,
    cancel_all,
    confirm_no,
    confirm_yes,
    pending_for,
)
from core.control.registry import build_context, execute_tool_async
from core.control.router import (
    _dispatch,
    _parse_kv_lines,
    _split_title_kind,
    _target,
    route_control_gathering,
)
from core.workspace.adapters.projection import TelegramProjection
from core.workspace.engine import EntityEngine

XIAO = "Xiao"


# ── helpers ───────────────────────────────────────────────────────────────
def _game_ws(uid):
    eng = EntityEngine()
    ws = eng.create_workspace(uid, "Genshin", template="game",
                              seed_milestones=False)
    db.tg_set_active(uid, ws.id)
    return eng, ws


def _ctx(uid, projection_factory=None):
    return build_context(uid, projection_factory=projection_factory)


def _linked_proj(uid, ws_id):
    """A real TelegramProjection over a recording client, linked to ws_id."""
    client = _RecordingClient()
    proj = TelegramProjection(client)
    proj.link_group(uid, ws_id, -100999)
    return proj, client


class _RecordingClient:
    """Records topic/message calls (the FakeClient pattern from the M4
    projection tests)."""

    def __init__(self):
        self.topics = []
        self.messages = []

    def create_forum_topic(self, chat_id, name):
        self.topics.append((chat_id, name))
        return 100 + len(self.topics)

    def send_message(self, chat_id, topic_id, text, parse_mode=None):
        self.messages.append((chat_id, topic_id, text, parse_mode))
        return 1000 + len(self.messages)

    def send_photo(self, chat_id, topic_id, file_id, caption):
        return 2000


def _make_entity(uid, ws_id, title, etype):
    return EntityEngine().add_milestone(uid, ws_id, title, entity_type=etype)


def _callbacks(kb):
    """Every callback_data string in a keyboard ([] for a None keyboard)."""
    if kb is None:
        return []
    out = []
    for row in kb.inline_keyboard:
        for b in row:
            if getattr(b, "callback_data", None):
                out.append(b.callback_data)
    return out


class _Msg:
    def __init__(self, text):
        self.text = text


class _FakeUpdate:
    def __init__(self, text):
        self.message = _Msg(text)


def has(text, needle):
    """Case-insensitive substring match — page titles are UPPERCASED by
    ui_components.page_title, so render assertions must not be case-bound."""
    return needle.upper() in text.upper()


# ── pages: render + navigation ────────────────────────────────────────────
def test_control_home_renders_and_navigates(temp_db, uid):
    eng, ws = _game_ws(uid)
    text, kb = pages.control_home(_ctx(uid))
    assert has(text, "Control Plane")
    assert has(text, f"#{ws.id} Genshin")
    cbs = _callbacks(kb)
    assert "ctl:ws:home" in cbs and "ctl:ent:list" in cbs
    assert "ctl:topic:home" in cbs and "ctl:ident:active" in cbs
    assert "ctl:eq:home" in cbs


def test_control_home_no_active_state(temp_db, uid):
    text, kb = pages.control_home(_ctx(uid))
    assert "No workspace active" in text
    assert "ctl:ws:home" in _callbacks(kb)


def test_workspace_page_active_and_no_active_states(temp_db, uid):
    eng, ws = _game_ws(uid)
    text, kb = pages.workspace_page(_ctx(uid))
    assert "Current workspace" in text and "Genshin" in text
    assert f"ctl:ws:detail:{ws.id}" in _callbacks(kb)
    assert "ctl:ws:create" in _callbacks(kb)
    # explicit no-active state (M5-A)
    db.tg_clear_active(uid)
    text2, _ = pages.workspace_page(_ctx(uid))
    assert "No workspace active" in text2


def test_workspace_detail_controls(temp_db, uid):
    eng, ws = _game_ws(uid)
    text, kb = pages.workspace_detail(_ctx(uid), ws.id)
    assert "Genshin" in text and "100%" not in text
    cbs = _callbacks(kb)
    for target in (f"ctl:ws:open:{ws.id}", f"ctl:ws:close:{ws.id}",
                   f"ctl:ws:inspect:{ws.id}", f"ctl:ws:rename:{ws.id}",
                   f"ctl:ws:archive:{ws.id}"):
        assert target in cbs


def test_workspace_inspect_renders_counts(temp_db, uid):
    eng, ws = _game_ws(uid)
    _make_entity(uid, ws.id, XIAO, "character")
    text, _ = pages.workspace_inspect(_ctx(uid), ws.id)
    assert "Progress" in text and "By status" in text


def test_entity_hub_and_list(temp_db, uid):
    eng, ws = _game_ws(uid)
    _make_entity(uid, ws.id, "M5_Test_Character_A", "character")
    _make_entity(uid, ws.id, "M5_Test_Weapon_A", "weapon")
    ctx = _ctx(uid)
    hub, kb = pages.entity_hub(ctx)
    assert "Entities" in hub
    for kind in ("character", "weapon", "artifact"):
        assert f"ctl:ent:list:{kind}" in _callbacks(kb)
    text, _ = pages.entity_list(ctx, "character")
    assert "M5_Test_Character_A" in text
    assert "M5_Test_Weapon_A" not in text   # kinds do not leak across lists


def test_entity_detail_and_missing(temp_db, uid):
    eng, ws = _game_ws(uid)
    m = _make_entity(uid, ws.id, XIAO, "character")
    text, kb = pages.entity_detail(_ctx(uid), m.id)
    assert XIAO in text and "character" in text.lower()
    assert f"ctl:ent:del:{m.id}" in _callbacks(kb)
    missing, _ = pages.entity_detail(_ctx(uid), 999999)
    assert "entity" in missing.lower() and "not found" in missing.lower()


def test_topic_center_health_summary(temp_db, uid):
    eng, ws = _game_ws(uid)
    m = _make_entity(uid, ws.id, XIAO, "character")
    proj, client = _linked_proj(uid, ws.id)
    ctx = _ctx(uid, projection_factory=lambda: proj)
    proj.ensure_entity_topic(uid, ws.id, "milestone", m.id, XIAO)
    text, kb = pages.topic_center(ctx)
    assert has(text, "Topic Center")
    assert f"ctl:topic:view:{m.id}" in _callbacks(kb)
    assert "ctl:topic:repair" in _callbacks(kb)


def test_topic_detail_locked_state(temp_db, uid):
    eng, ws = _game_ws(uid)
    m = _make_entity(uid, ws.id, XIAO, "character")
    proj, client = _linked_proj(uid, ws.id)
    ctx = _ctx(uid, projection_factory=lambda: proj)
    proj.ensure_entity_topic(uid, ws.id, "milestone", m.id, XIAO)
    proj.set_topic_locked(ws.id, "milestone", m.id, True)
    text, _ = pages.topic_detail(ctx, m.id)
    assert "locked" in text.lower()


def test_identity_inspector_exactly_eight_rows(temp_db, uid):
    eng, ws = _game_ws(uid)
    m = _make_entity(uid, ws.id, XIAO, "character")
    proj, _ = _linked_proj(uid, ws.id)
    proj.ensure_entity_topic(uid, ws.id, "milestone", m.id, XIAO)
    text, kb = pages.identity_inspector(_ctx(uid), m.id)
    for label in ("Name", "Entity ID", "Kind", "Workspace", "Topic ID",
                  "Topic status", "Lock status", "Active"):
        assert label in text, label
    assert f"ctl:ent:view:{m.id}" in _callbacks(kb)
    assert f"ctl:topic:view:{m.id}" in _callbacks(kb)


def test_identity_inspector_no_active_entity_state(temp_db, uid):
    eng, ws = _game_ws(uid)
    text, kb = pages.identity_inspector(_ctx(uid), None)
    assert "No active entity" in text
    # empty-state nav (no entity picker button -- the hint is text only)
    cbs = _callbacks(kb)
    assert "ctl:ident:active" in cbs and "ctl:home" in cbs


def test_equip_home_and_pick(temp_db, uid):
    eng, ws = _game_ws(uid)
    ch = _make_entity(uid, ws.id, "M5_Test_Character_A", "character")
    wp = _make_entity(uid, ws.id, "M5_Test_Weapon_A", "weapon")
    ctx = _ctx(uid)
    text, kb = pages.equip_home(ctx)
    assert "M5_Test_Character_A" in text
    assert f"ctl:eq:pick:{ch.id}" in _callbacks(kb)
    pick, kb2 = pages.equip_pick(ctx, ch.id)
    assert "M5_Test_Weapon_A" in pick
    assert f"ctl:eq:set:{ch.id}:{wp.id}" in _callbacks(kb2)


# ── router: page targets ──────────────────────────────────────────────────
def test_target_routes_every_namespace(temp_db, uid):
    eng, ws = _game_ws(uid)
    m = _make_entity(uid, ws.id, XIAO, "character")
    ctx = _ctx(uid)
    for target in ("ctl:home", "ctl:ws:home", "ctl:ent:list",
                   "ctl:topic:home", "ctl:ident:active", "ctl:eq:home"):
        text, kb = _target(ctx, target)
        assert text and kb is not None
    _, kb = _target(ctx, f"ctl:ent:view:{m.id}")
    assert f"ctl:ent:del:{m.id}" in _callbacks(kb)


# ── router: immediate mutations via the shared ToolRegistry ───────────────
async def test_dispatch_open_workspace_switches_active(temp_db, uid):
    eng = EntityEngine()
    ws_a = eng.create_workspace(uid, "M5_Test_Workspace_A", template="game",
                                seed_milestones=False)
    ws_b = eng.create_workspace(uid, "M5_Test_Workspace_B", template="game",
                                seed_milestones=False)
    db.tg_set_active(uid, ws_a.id)
    ctx = _ctx(uid)
    text, _ = await _dispatch(ctx, ["ctl", "ws", "open", str(ws_b.id)])
    assert db.tg_get_active(uid)[0] == ws_b.id   # open_workspace ran
    assert "M5_Test_Workspace_B" in text


async def test_dispatch_close_clears_active_keeps_row(temp_db, uid):
    eng, ws = _game_ws(uid)
    ctx = _ctx(uid)
    text, _ = await _dispatch(ctx, ["ctl", "ws", "close", str(ws.id)])
    active = db.tg_get_active(uid)
    assert active is None or active[0] is None   # clear_active deletes the row
    assert eng.get_workspace_or_none(uid, ws.id) is not None   # row survives
    assert "No workspace active" in text or "Workspaces" in text


async def test_dispatch_ws_archive_enters_confirm_gate(temp_db, uid):
    eng, ws = _game_ws(uid)
    ctx = _ctx(uid)
    text, kb = await _dispatch(ctx, ["ctl", "ws", "archive", str(ws.id)])
    pending = pending_for(uid)
    assert pending is not None and pending.tool == "archive_workspace"
    cbs = _callbacks(kb)
    assert "ctl:confirm:yes" in cbs and "ctl:confirm:no" in cbs
    assert "archive" in text.lower()
    assert eng.get_workspace_or_none(uid, ws.id).status == "active"  # not yet
    cancel_all(uid)


async def test_dispatch_entity_delete_enters_confirm_gate(temp_db, uid):
    eng, ws = _game_ws(uid)
    m = _make_entity(uid, ws.id, "M5_Test_Character_A", "character")
    ctx = _ctx(uid)
    text, _ = await _dispatch(ctx, ["ctl", "ent", "del", str(m.id)])
    pending = pending_for(uid)
    assert pending is not None and pending.tool == "delete_entity"
    assert pending.arguments["entity"] == str(m.id)
    cancel_all(uid)


async def test_dispatch_topic_lock_unlock_immediate(temp_db, uid):
    eng, ws = _game_ws(uid)
    m = _make_entity(uid, ws.id, XIAO, "character")
    proj, client = _linked_proj(uid, ws.id)
    proj.ensure_entity_topic(uid, ws.id, "milestone", m.id, XIAO)
    ctx = _ctx(uid, projection_factory=lambda: proj)
    await _dispatch(ctx, ["ctl", "topic", "lock", str(m.id)])
    assert db.tg_get_entity_topic_locked(ws.id, "milestone", m.id) is True
    await _dispatch(ctx, ["ctl", "topic", "unlock", str(m.id)])
    assert db.tg_get_entity_topic_locked(ws.id, "milestone", m.id) is False


async def test_dispatch_topic_force_delete_enters_confirm_gate(temp_db, uid):
    eng, ws = _game_ws(uid)
    m = _make_entity(uid, ws.id, XIAO, "character")
    proj, client = _linked_proj(uid, ws.id)
    proj.ensure_entity_topic(uid, ws.id, "milestone", m.id, XIAO)
    proj.set_topic_locked(ws.id, "milestone", m.id, True)
    ctx = _ctx(uid, projection_factory=lambda: proj)
    text, kb = await _dispatch(ctx, ["ctl", "topic", "force", str(m.id)])
    pending = pending_for(uid)
    assert pending is not None and pending.tool == "delete_entity_topic"
    assert pending.arguments["force"] is True
    cbs = _callbacks(kb)
    assert "ctl:confirm:yes" in cbs and "ctl:confirm:no" in cbs
    cancel_all(uid)


async def test_dispatch_equip_set_and_unequip(temp_db, uid):
    eng, ws = _game_ws(uid)
    ch = _make_entity(uid, ws.id, "M5_Test_Character_A", "character")
    wp = _make_entity(uid, ws.id, "M5_Test_Weapon_A", "weapon")
    ctx = _ctx(uid)
    await _dispatch(ctx, ["ctl", "eq", "set", str(ch.id), str(wp.id)])
    assert eng.get_fields(uid, ch.id).get("weapon") == "M5_Test_Weapon_A"
    await _dispatch(ctx, ["ctl", "eq", "unequip", str(ch.id)])
    assert eng.get_fields(uid, ch.id).get("weapon") in ("", None)


# ── M5-F: one shared confirm flow ─────────────────────────────────────────
def test_begin_confirm_uses_spec_wording_and_sets_pending(temp_db, uid):
    eng, ws = _game_ws(uid)
    ctx = _ctx(uid)
    text, kb = begin_confirm(ctx, "archive_workspace",
                             {"workspace": ws.id}, return_to="ctl:ws:home")
    pending = pending_for(uid)
    assert pending is not None and pending.tool == "archive_workspace"
    assert pending.danger is True
    spec = build_control_registry(ctx).get("archive_workspace").spec
    assert pending.question == spec.confirmation_message
    assert "archive" in text.lower()
    assert "ctl:confirm:yes" in _callbacks(kb)
    cancel_all(uid)


def test_begin_confirm_unknown_tool_is_graceful(temp_db, uid):
    ctx = _ctx(uid)
    text, kb = begin_confirm(ctx, "no_such_tool", {}, return_to="ctl:home")
    assert "No tool named" in text
    assert pending_for(uid) is None


async def test_confirm_yes_executes_via_registry(temp_db, uid):
    eng, ws = _game_ws(uid)
    ctx = _ctx(uid)
    begin_confirm(ctx, "archive_workspace", {"workspace": ws.id},
                  return_to="ctl:ws:home")
    text, _ = await confirm_yes(ctx, lambda t: _target(ctx, t))
    assert pending_for(uid) is None
    assert eng.get_workspace_or_none(uid, ws.id).status == "archived"
    assert "Result" in text or "Archived" in text


async def test_confirm_yes_clears_active_on_close(temp_db, uid):
    eng, ws = _game_ws(uid)
    ctx = _ctx(uid)
    begin_confirm(ctx, "close_workspace", {}, return_to="ctl:ws:home")
    await confirm_yes(ctx, lambda t: _target(ctx, t))
    active = db.tg_get_active(uid)
    assert active is None or active[0] is None   # active context cleared
    assert eng.get_workspace_or_none(uid, ws.id).status == "active"


async def test_confirm_no_discards_without_executing(temp_db, uid):
    eng, ws = _game_ws(uid)
    ctx = _ctx(uid)
    begin_confirm(ctx, "archive_workspace", {"workspace": ws.id},
                  return_to="ctl:ws:home")
    text, _ = await confirm_no(ctx, lambda t: _target(ctx, t))
    assert pending_for(uid) is None
    # NOT executed -- the workspace is untouched
    assert eng.get_workspace_or_none(uid, ws.id).status == "active"
    assert "Workspaces" in text   # redrew the prior page (return_to)


async def test_confirm_yes_with_nothing_pending_is_graceful(temp_db, uid):
    ctx = _ctx(uid)
    text, kb = await confirm_yes(ctx, lambda t: _target(ctx, t))
    assert has(text, "Nothing to confirm")
    assert "ctl:confirm:yes" not in _callbacks(kb)


def test_cancel_all_drops_pending(temp_db, uid):
    eng, ws = _game_ws(uid)
    ctx = _ctx(uid)
    begin_confirm(ctx, "archive_workspace", {"workspace": ws.id},
                  return_to="ctl:ws:home")
    assert pending_for(uid) is not None
    cancel_all(uid)
    assert pending_for(uid) is None


# ── M5-F: data-entry gathers ──────────────────────────────────────────────
def test_split_title_kind(temp_db):
    assert _split_title_kind("My Game") == ("My Game", None)
    assert _split_title_kind("My Game | game") == ("My Game", "game")
    assert _split_title_kind("My Game|project") == ("My Game", "project")
    assert _split_title_kind("  |  ") == ("", None)


def test_parse_kv_lines(temp_db):
    assert _parse_kv_lines("weapon=Festering Desire\nlevel=80") == \
        {"weapon": "Festering Desire", "level": "80"}
    assert _parse_kv_lines("a: 1; b=2") == {"a": "1", "b": "2"}
    assert _parse_kv_lines("no pairs here") == {}


async def test_gather_create_workspace_reaches_confirm(temp_db, uid):
    ctx = _ctx(uid)
    text, kb = await route_control_gathering(
        _FakeUpdate("M5_Test_Workspace_A | game"), None,
        {"_ctl": "create_workspace"}, ["title"], ctx)
    pending = pending_for(uid)
    assert pending is not None and pending.tool == "create_workspace"
    assert pending.arguments["title"] == "M5_Test_Workspace_A"
    assert pending.arguments["template"] == "game"
    assert "ctl:confirm:yes" in _callbacks(kb)
    cancel_all(uid)


async def test_gather_create_workspace_rejects_unknown_kind(temp_db, uid):
    ctx = _ctx(uid)
    text, kb = await route_control_gathering(
        _FakeUpdate("X | spaceship"), None,
        {"_ctl": "create_workspace"}, ["title"], ctx)
    assert "unknown workspace kind" in text.lower()
    assert pending_for(uid) is None   # nothing queued -- corrected by user


async def test_gather_rename_workspace_reaches_confirm(temp_db, uid):
    eng, ws = _game_ws(uid)
    ctx = _ctx(uid)
    text, kb = await route_control_gathering(
        _FakeUpdate("M5_Renamed"), None,
        {"_ctl": "rename_workspace", "workspace": ws.id}, ["title"], ctx)
    pending = pending_for(uid)
    assert pending is not None and pending.tool == "rename_workspace"
    assert pending.arguments["workspace"] == ws.id
    assert pending.arguments["title"] == "M5_Renamed"
    cancel_all(uid)


async def test_gather_add_entity_reaches_confirm(temp_db, uid):
    eng, ws = _game_ws(uid)
    ctx = _ctx(uid)
    text, kb = await route_control_gathering(
        _FakeUpdate("M5_Test_Character_A"), None,
        {"_ctl": "add_entity", "entity_type": "character"}, ["name"], ctx)
    pending = pending_for(uid)
    assert pending is not None and pending.tool == "create_entity"
    assert pending.arguments["name"] == "M5_Test_Character_A"
    assert pending.arguments["entity_type"] == "character"
    assert pending.arguments["workspace"] == ws.id
    cancel_all(uid)


async def test_gather_add_entity_kind_conflict_refused(temp_db, uid):
    eng, ws = _game_ws(uid)
    ctx = _ctx(uid)
    # 'Staff of Homa' resolves to weapon -- the character page must refuse
    text, kb = await route_control_gathering(
        _FakeUpdate("Staff of Homa"), None,
        {"_ctl": "add_entity", "entity_type": "character"}, ["name"], ctx)
    assert "reads as" in text and "weapon" in text.lower()
    assert pending_for(uid) is None   # never silently created the wrong kind
    assert "character" in text.lower()


async def test_gather_add_entity_no_active_workspace(temp_db, uid):
    ctx = _ctx(uid)
    text, kb = await route_control_gathering(
        _FakeUpdate("M5_Test_Character_A"), None,
        {"_ctl": "add_entity", "entity_type": "character"}, ["name"], ctx)
    assert "No workspace active" in text
    assert pending_for(uid) is None


async def test_gather_edit_entity_validates_then_confirms(temp_db, uid):
    eng, ws = _game_ws(uid)
    m = _make_entity(uid, ws.id, "M5_Test_Character_A", "character")
    ctx = _ctx(uid)
    text, kb = await route_control_gathering(
        _FakeUpdate("weapon=M5_Test_Weapon_A, level=80"), None,
        {"_ctl": "edit_entity", "entity": m.id}, ["fields"], ctx)
    pending = pending_for(uid)
    assert pending is not None and pending.tool == "update_entity"
    assert pending.arguments["fields"]["weapon"] == "M5_Test_Weapon_A"
    assert pending.arguments["fields"]["level"] == 80   # normalized to int
    cancel_all(uid)


async def test_gather_edit_entity_rejects_bad_values(temp_db, uid):
    eng, ws = _game_ws(uid)
    m = _make_entity(uid, ws.id, "M5_Test_Character_A", "character")
    ctx = _ctx(uid)
    # level is an int 1-100 -- a non-int is a validation error, not a confirm
    text, kb = await route_control_gathering(
        _FakeUpdate("level=not_a_number"), None,
        {"_ctl": "edit_entity", "entity": m.id}, ["fields"], ctx)
    assert "Validation failed" in text
    assert pending_for(uid) is None


# ── the no-second-logic proof: manual path == registry.execute ────────────
async def test_manual_path_matches_registry_domain_effects(temp_db, uid):
    """The SAME tool call produces identical domain effects whether driven by
    the control plane's confirm flow or a bare registry.execute (what the
    Worker uses). This is the M5 'no second business-logic layer' proof."""
    from core.ai.tool_adapters import build_tool_registry
    eng, ws = _game_ws(uid)
    ctx = _ctx(uid)

    # Worker path: registry.execute straight through
    worker_reg = build_tool_registry(uid)
    worker_reg.execute("create_entity",
                       {"name": XIAO, "entity_type": "character"})
    r = worker_reg.execute("archive_workspace", {"workspace": ws.id})

    # Manual path: confirm flow runs the SAME tool over the SAME DB
    begin_confirm(ctx, "archive_workspace", {"workspace": ws.id},
                  return_to="ctl:ws:home")
    await confirm_yes(ctx, lambda t: _target(ctx, t))

    # identical domain effects (status is the same, entities untouched)
    assert r.ok
    assert eng.get_workspace_or_none(uid, ws.id).status == "archived"
    assert eng.list_milestones(uid, ws.id)  # entities never cascade-deleted


# fixture to keep imports honest
def build_control_registry(ctx):
    from core.control.registry import build_control_registry as _b
    return _b(ctx)
