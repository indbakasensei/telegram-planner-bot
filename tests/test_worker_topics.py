"""
tests/test_worker_topics.py -- v15.2 M4 matrix E: topic lifecycle
(items 7/8/10) + self-heal repair (item 9).

Covers the TopicProjection tool surface through a REAL registry + a real
TelegramProjection over a recording FakeClient on a temp DB:
  * item 10 -- ensure/get/delete/list entity topic, generic projection tools
  * item 7  -- DELETE ENTITY ≠ DELETE TOPIC: delete_entity_topic removes only
    the topic + binding, never the DB entity; and the Worker's mechanical
    confirmation gate fires BEFORE a destructive delete ever executes
  * item 8  -- durable topic lock refuses ordinary deletion; force=true
    (explicit) overrides; lock survives a fresh registry/projection
  * item 9  -- repair_topics collapses logical duplicates (one title → one
    topic), adopts a concrete kind onto the canonical row, reports
    created/existing/duplicates/errors, and a re-run creates nothing

Matrix H cross-check: render_run_reply formats topic steps (ensure/get/lock/
list) into HTML instead of raw prose.
"""
import json

import database as db
from core.ai.tool_adapters import build_tool_registry
from core.ai.worker import Worker
from core.ai.worker_contract import TerminationReason, WorkerRequest
from core.ai.worker_render import render_run_reply
from core.workspace.adapters.projection import TelegramClient, TelegramProjection
from core.workspace.engine import EntityEngine
from core.workspace.groups_app import WorkspaceGroups

CHAT = -1009000


class FakeClient(TelegramClient):
    """Records topic/message/deletion calls; deterministic ids."""

    def __init__(self):
        self.topics = []       # (chat_id, name)
        self.messages = []     # (chat_id, topic_id, text, parse_mode)
        self.deleted = []      # (chat_id, topic_id)
        self._next_topic = 500

    def create_forum_topic(self, chat_id, name):
        self.topics.append((chat_id, name))
        topic_id = self._next_topic
        self._next_topic += 1
        return topic_id

    def send_message(self, chat_id, topic_id, text, parse_mode=None):
        self.messages.append((chat_id, topic_id, text, parse_mode))
        return 1

    def send_photo(self, chat_id, topic_id, file_id, caption):
        return 2

    def delete_forum_topic(self, chat_id, topic_id):
        self.deleted.append((chat_id, topic_id))
        return True


def _linked_game(uid, title="Genshin", fake=None):
    """A real game workspace, active, and linked to a fake group."""
    eng = EntityEngine()
    ws = eng.create_workspace(uid, title, template="game", seed_milestones=False)
    db.tg_set_active(uid, ws.id)
    fake = fake or FakeClient()
    proj = TelegramProjection(fake)
    WorkspaceGroups().link_group(uid, CHAT, proj)
    return eng, ws, fake, proj


def _wire(uid, proj):
    return build_tool_registry(uid, projection=proj)


def _entity(reg, name, kind=None):
    args = {"name": name}
    if kind:
        args["entity_type"] = kind
    return reg.execute("create_entity", args)


def _topic_bindings(ws_id):
    from core.storage import Storage
    return Storage().tg_bindings.get_entity_topics(ws_id)


# ── item 10: generic TopicProjection tool surface ─────────────────────────
def _ensure_fixture(uid):
    """A linked game workspace with an entity created WITHOUT a projection
    (so no topic exists yet) -- the exact legacy/pre-projection shape
    ensure_entity_topic exists to fix."""
    eng, ws, fake, proj = _linked_game(uid)
    m = eng.add_milestone(uid, ws.id, "Xiao", entity_type="character")
    eng.update_field(uid, m.id, "level", 90)
    return eng, ws, fake, proj


def test_ensure_creates_exactly_one_topic_with_card(temp_db, uid):
    eng, ws, fake, proj = _ensure_fixture(uid)
    r = _wire(uid, proj).execute("ensure_entity_topic", {"entity": "Xiao"})
    assert r.ok and r.data["created"] is True
    assert r.data["topic_id"] == 500 and r.data["title"] == "Xiao"
    assert len(_topic_bindings(ws.id)) == 1          # exactly one binding
    assert len(fake.topics) == 1                     # exactly one topic
    # The initial card was posted (bot-rendered HTML, from the STORED row).
    assert any("<b>Xiao</b>" in txt for _, _, txt, _ in fake.messages)
    assert any("Level: 90" in txt for _, _, txt, _ in fake.messages)


def test_ensure_idempotent_no_duplicate_topic_or_card(temp_db, uid):
    eng, ws, fake, proj = _ensure_fixture(uid)
    reg = _wire(uid, proj)
    r1 = reg.execute("ensure_entity_topic", {"entity": "Xiao"})
    r2 = reg.execute("ensure_entity_topic", {"entity": "Xiao"})
    assert r2.ok and r2.data["created"] is False
    assert r2.data["topic_id"] == r1.data["topic_id"]
    assert len(_topic_bindings(ws.id)) == 1          # canonical, never two
    assert len(fake.topics) == 1                     # no second topic
    # The card is posted only into a NEWLY created topic -- never duplicated.
    assert len(fake.messages) == 1


def test_get_topic_read_only(temp_db, uid):
    eng, ws, fake, proj = _ensure_fixture(uid)
    reg = _wire(uid, proj)
    reg.execute("ensure_entity_topic", {"entity": "Xiao"})
    r = reg.execute("get_entity_topic", {"entity": "Xiao"})
    assert r.ok and r.data["topic_id"] == 500
    assert r.data["locked"] is False
    assert len(fake.topics) == 1                     # read never creates


def test_get_topic_no_topic_is_ok_not_error(temp_db, uid):
    eng, ws, fake, proj = _linked_game(uid)
    eng.add_milestone(uid, ws.id, "Xiao")
    r = _wire(uid, proj).execute("get_entity_topic", {"entity": "Xiao"})
    assert r.ok and r.data["topic_id"] is None
    assert r.data["locked"] is False


def test_topic_tools_entity_resolution_missing_raises(temp_db, uid):
    eng, ws, fake, proj = _linked_game(uid)
    reg = _wire(uid, proj)
    r = reg.execute("get_entity_topic", {"entity": "Nope"})
    assert not r.ok and r.error_code == "invalid_args"


def test_topic_tools_without_projection_are_honest(temp_db, uid):
    """No projection wired → every topic tool reports not_wired instead of
    crashing or inventing a topic (the create_entity stance for a missing
    projection)."""
    eng = EntityEngine()
    ws = eng.create_workspace(uid, "Genshin", template="game",
                              seed_milestones=False)
    db.tg_set_active(uid, ws.id)
    reg = build_tool_registry(uid)                   # no projection
    for name, args in [("ensure_entity_topic", {"entity": "Xiao"}),
                       ("get_entity_topic", {"entity": "Xiao"}),
                       ("set_entity_topic_locked", {"entity": "Xiao",
                                                    "locked": True}),
                       ("delete_entity_topic", {"entity": "Xiao"}),
                       ("list_entity_topics", {})]:
        r = reg.execute(name, args)
        assert r.ok, (name, r)
        assert r.data.get("reason") == "not_wired", (name, r)


def test_list_entity_topics_reports_bindings_and_locks(temp_db, uid):
    eng, ws, fake, proj = _linked_game(uid)
    reg = _wire(uid, proj)
    _entity(reg, "Xiao", kind="character")
    _entity(reg, "Furina", kind="character")
    reg.execute("ensure_entity_topic", {"entity": "Xiao"})
    reg.execute("ensure_entity_topic", {"entity": "Furina"})
    reg.execute("set_entity_topic_locked", {"entity": "Xiao", "locked": True})
    r = reg.execute("list_entity_topics", {})
    assert r.ok and len(r.data) == 2
    by_title = {d["title"]: d for d in r.data}
    assert by_title["Xiao"]["locked"] is True
    assert by_title["Furina"]["locked"] is False
    assert {d["topic_id"] for d in r.data} == {500, 501}


def test_list_entity_topics_empty_workspace(temp_db, uid):
    eng, ws, fake, proj = _linked_game(uid)
    r = _wire(uid, proj).execute("list_entity_topics", {})
    assert r.ok and r.data == []


# ── item 8: durable lock ──────────────────────────────────────────────────
def test_lock_is_durable_across_registry_and_projection(temp_db, uid):
    eng, ws, fake, proj = _linked_game(uid)
    reg = _wire(uid, proj)
    _entity(reg, "Xiao", kind="character")
    r = reg.execute("set_entity_topic_locked", {"entity": "Xiao",
                                                "locked": True})
    assert r.ok and r.data["locked"] is True
    # A fresh registry + projection (new process path) still sees the lock.
    proj2 = TelegramProjection(FakeClient())
    r2 = _wire(uid, proj2).execute("get_entity_topic", {"entity": "Xiao"})
    assert r2.ok and r2.data["locked"] is True


def test_unlock_clears_lock(temp_db, uid):
    eng, ws, fake, proj = _linked_game(uid)
    reg = _wire(uid, proj)
    _entity(reg, "Xiao", kind="character")
    reg.execute("set_entity_topic_locked", {"entity": "Xiao", "locked": True})
    r = reg.execute("set_entity_topic_locked", {"entity": "Xiao",
                                                "locked": False})
    assert r.ok and r.data["locked"] is False
    assert _wire(uid, TelegramProjection(FakeClient())).execute(
        "get_entity_topic", {"entity": "Xiao"}).data["locked"] is False


# ── item 7: DELETE ENTITY ≠ DELETE TOPIC ─────────────────────────────────
def test_locked_topic_refuses_ordinary_delete(temp_db, uid):
    eng, ws, fake, proj = _linked_game(uid)
    reg = _wire(uid, proj)
    _entity(reg, "Xiao", kind="character")
    reg.execute("ensure_entity_topic", {"entity": "Xiao"})
    reg.execute("set_entity_topic_locked", {"entity": "Xiao", "locked": True})
    r = reg.execute("delete_entity_topic", {"entity": "Xiao"})
    assert not r.ok and r.data["reason"] == "locked"
    assert len(fake.deleted) == 0                    # nothing deleted
    assert len(_topic_bindings(ws.id)) == 1          # binding intact
    # The ENTITY is untouched.
    assert [m.title for m in eng.list_milestones(uid, ws.id)] == ["Xiao"]


def test_force_delete_overrides_lock(temp_db, uid):
    eng, ws, fake, proj = _linked_game(uid)
    reg = _wire(uid, proj)
    _entity(reg, "Xiao", kind="character")
    reg.execute("ensure_entity_topic", {"entity": "Xiao"})
    reg.execute("set_entity_topic_locked", {"entity": "Xiao", "locked": True})
    r = reg.execute("delete_entity_topic", {"entity": "Xiao", "force": True})
    assert r.ok
    assert len(fake.deleted) == 1
    assert _topic_bindings(ws.id) == []              # binding removed
    # Entity still exists -- DELETE TOPIC ≠ DELETE ENTITY.
    assert [m.title for m in eng.list_milestones(uid, ws.id)] == ["Xiao"]


def test_delete_topic_leaves_entity_with_fields(temp_db, uid):
    eng, ws, fake, proj = _linked_game(uid)
    reg = _wire(uid, proj)
    m = eng.add_milestone(uid, ws.id, "Xiao")
    eng.update_field(uid, m.id, "level", 80)
    reg.execute("ensure_entity_topic", {"entity": "Xiao"})
    r = reg.execute("delete_entity_topic", {"entity": "Xiao"})
    assert r.ok
    assert _topic_bindings(ws.id) == []
    live = eng.get_milestone(uid, m.id)
    assert live.title == "Xiao" and live.fields.get("level") == 80


def test_delete_no_topic_is_honest_refusal(temp_db, uid):
    eng, ws, fake, proj = _ensure_fixture(uid)   # entity, but no topic yet
    r = _wire(uid, proj).execute("delete_entity_topic", {"entity": "Xiao"})
    assert not r.ok and r.data["reason"] == "no_topic"
    assert [m.title for m in eng.list_milestones(uid, ws.id)] == ["Xiao"]


def test_delete_topic_confirmation_gate_fires_before_execute(temp_db, uid):
    """The Worker's MECHANICAL gate: a DESTRUCTIVE tool never executes
    silently -- the run ends CONFIRMATION_NEEDED and main.py routes through
    the existing conversation_state machine."""
    def _tool(name, args=None):
        return json.dumps({"action": "tool", "tool": name, "arguments": args or {}})

    eng, ws, fake, proj = _linked_game(uid)
    reg = _wire(uid, proj)
    _entity(reg, "Xiao", kind="character")
    reg.execute("ensure_entity_topic", {"entity": "Xiao"})

    class FakeModel:
        def __call__(self, messages, timeout):
            return _tool("delete_entity_topic", {"entity": "Xiao"})

    run = Worker(model_fn=FakeModel(), timeout=30.0).run(WorkerRequest(
        user_id=uid, text="delete the topic", registry=reg))
    assert run.termination is TerminationReason.CONFIRMATION_NEEDED
    assert "delete" in run.reply.lower()
    assert len(fake.deleted) == 0                    # gate stopped execution
    assert len(_topic_bindings(ws.id)) == 1          # nothing was deleted


# ── item 9: self-heal repair ──────────────────────────────────────────────
def _duplicate_workspace(uid, fake):
    """A linked workspace with two SAME-title rows (the historical root cause
    of one entity appearing as two topics): 'Xiao' typed as character and a
    duplicate untyped 'Xiao'. Bypasses the canonical create contract on
    purpose to simulate pre-canonical legacy data."""
    eng, ws, _f, proj = _linked_game(uid, fake=fake)
    m1 = eng.add_milestone(uid, ws.id, "Xiao", entity_type="character")
    eng.update_field(uid, m1.id, "level", 90)
    eng.add_milestone(uid, ws.id, "Xiao")            # legacy untyped duplicate
    return eng, ws, proj


def test_repair_collapses_duplicates_one_topic_one_entity(temp_db, uid):
    fake = FakeClient()
    eng, ws, proj = _duplicate_workspace(uid, fake)
    report = WorkspaceGroups().repair_topics(uid, proj)
    info = report[ws.id]
    assert info["linked"] is True
    assert len(info["created"]) == 1 and info["created"] == ["Xiao"]
    assert len(info["duplicates"]) == 1              # the duplicate was seen
    assert info["duplicates"][0]["merged"] == "Xiao"
    # Canonical binding: ONE topic, ONE row, kind adopted onto the canonical.
    assert len(_topic_bindings(ws.id)) == 1
    assert len(fake.topics) == 1
    rows = eng.list_milestones(uid, ws.id)
    # Both DB rows persist (repair never deletes data); only the canonical
    # row carries a topic -- the duplicate is skipped, never projected twice.
    assert len(rows) == 2
    assert rows[0].entity_type == "character"        # kind adopted
    assert rows[0].fields.get("level") == 90         # canonical row preserved
    assert all(b[1] == rows[0].id for b in _topic_bindings(ws.id))  # (type, eid, topic)


def test_repair_is_idempotent_no_new_topics_on_rerun(temp_db, uid):
    fake = FakeClient()
    eng, ws, proj = _duplicate_workspace(uid, fake)
    app = WorkspaceGroups()
    app.repair_topics(uid, proj)
    report2 = app.repair_topics(uid, proj)
    info = report2[ws.id]
    assert info["created"] == []
    assert info["existing"] == ["Xiao"]
    assert len(fake.topics) == 1                     # nothing new created
    assert len(_topic_bindings(ws.id)) == 1


def test_repair_reports_unlinked_workspace_and_no_topic_calls(temp_db, uid):
    eng, ws, fake, proj = _linked_game(uid)          # linked
    eng2 = EntityEngine()
    ws2 = eng2.create_workspace(uid, "Drone", template="generic",
                                seed_milestones=False)
    eng2.add_milestone(uid, ws2.id, "Dji")           # never linked
    report = WorkspaceGroups().repair_topics(uid, proj)
    assert report[ws2.id]["linked"] is False
    assert report[ws.id]["linked"] is True
    # The unlinked workspace triggered no Telegram call at all.
    assert all(c != ws2.id for c, _ in fake.topics)


# ── matrix H cross-check: renderer formats topic steps ────────────────────
def test_render_topic_ops_formatted_not_prose(temp_db, uid):
    eng, ws, fake, proj = _linked_game(uid)
    reg = _wire(uid, proj)
    _entity(reg, "Xiao", kind="character")

    class FakeModel:
        def __init__(self, *responses):
            self._r = list(responses)
        def __call__(self, messages, timeout):
            return self._r.pop(0)

    def _tool(name, args=None):
        return json.dumps({"action": "tool", "tool": name, "arguments": args or {}})

    run = Worker(model_fn=FakeModel(
        _tool("ensure_entity_topic", {"entity": "Xiao"}),
        _tool("set_entity_topic_locked", {"entity": "Xiao", "locked": True}),
        _tool("list_entity_topics", {}),
        json.dumps({"action": "final", "reply": "ok"})), timeout=30.0).run(
        WorkerRequest(user_id=uid, text="make a topic and lock it", registry=reg))
    reply = render_run_reply(run, user_id=uid)
    assert "<b>Xiao</b>" in reply                    # formatted, not bare prose
    assert "topic" in reply.lower()
    assert "locked" in reply.lower()
    assert "topic #500" in reply or "500" in reply


def test_render_refused_delete_is_honest_not_failed(temp_db, uid):
    """A locked-refusal via direct registry is an honest non-action (reason
    'locked'), never a silent delete or an internal failure."""
    eng, ws, fake, proj = _linked_game(uid)
    reg = _wire(uid, proj)
    _entity(reg, "Xiao", kind="character")
    reg.execute("ensure_entity_topic", {"entity": "Xiao"})
    reg.execute("set_entity_topic_locked", {"entity": "Xiao", "locked": True})
    r = reg.execute("delete_entity_topic", {"entity": "Xiao"})
    assert not r.ok and r.data["reason"] == "locked"
