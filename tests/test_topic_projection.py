"""
Tests for v15.1.0-alpha.13 -- Telegram Entity Topic Projection (M10).

Covers the two projection contracts the milestone adds:
  1. TelegramProjection.ensure_entity_topic  (idempotent topic + initial card)
  2. TelegramProjection.post_entity_update   (append-only update, self-healing)
  3. WorkspaceGroups.backfill_topics         (idempotent, generic, per-entity)

Everything runs offline with a configurable fake Telegram client -- no PTB,
no network. The fake can be told to fail topic creation, message posting, or
binding writes so partial-failure / retry consistency is exercised directly.
"""
import database as db
import pytest
from core.storage import Storage
from core.workspace.adapters.projection import (
    TelegramClient, TelegramProjection,
)
from core.workspace.engine import EntityEngine
from core.workspace.groups_app import WorkspaceGroups


class FakeClient(TelegramClient):
    """Records calls; can be told to fail topic creation or message sends.

    ``fail_topics`` (callable or set of names) makes create_forum_topic
    raise; ``fail_send`` makes send_message raise. Used to simulate a
    transient Telegram outage mid-backfill."""

    def __init__(self, fail_topics=None, fail_send=False):
        self.topics = []      # (chat_id, name)
        self.messages = []    # (chat_id, topic_id, text, parse_mode)
        self.photos = []      # (chat_id, topic_id, file_id, caption)
        self._fail_topics = fail_topics or set()
        self._fail_send = fail_send

    def create_forum_topic(self, chat_id, name):
        if self._fail_topics is True:
            raise RuntimeError(f"topic creation failed for {name}")
        if isinstance(self._fail_topics, set) and name in self._fail_topics:
            raise RuntimeError(f"topic creation failed for {name}")
        if callable(self._fail_topics) and self._fail_topics(name):
            raise RuntimeError(f"topic creation failed for {name}")
        self.topics.append((chat_id, name))
        return 100 + len(self.topics)

    def send_message(self, chat_id, topic_id, text, parse_mode=None):
        if self._fail_send:
            raise RuntimeError("send_message failed")
        self.messages.append((chat_id, topic_id, text, parse_mode))
        return 1000 + len(self.messages)

    def send_photo(self, chat_id, topic_id, file_id, caption):
        self.photos.append((chat_id, topic_id, file_id, caption))
        return 2000 + len(self.photos)


def _wire(fail_topics=None, fail_send=False):
    client = FakeClient(fail_topics=fail_topics, fail_send=fail_send)
    proj = TelegramProjection(client)
    app = WorkspaceGroups()
    return app, proj, client


def _linked_ws(uid, title="Genshin", kind="game"):
    app, proj, client = _wire()
    ws = app.create(uid, kind, title)
    app.link_group(uid, -100999, proj)
    return app, proj, client, ws


# ── ensure_entity_topic ─────────────────────────────────────────────────────
def test_ensure_entity_topic_creates_topic_binding_and_initial_card(temp_db, uid):
    app, proj, client = _wire()
    ws = app.create(uid, "game", "Genshin")
    app.link_group(uid, -100999, proj)
    m = app._eng.add_milestone(uid, ws.id, "Arlecchino")

    topic_id = proj.ensure_entity_topic(
        uid, ws.id, "milestone", m.id, m.title,
        initial_message=f"<b>Arlecchino</b> card")

    assert topic_id == 101
    assert client.topics == [(-100999, "Arlecchino")]
    assert db.tg_get_entity_topic("milestone", m.id) == 101
    # initial card posted into the NEW topic, marked as bot HTML
    assert client.messages == [(-100999, 101, "<b>Arlecchino</b> card", "HTML")]


def test_ensure_entity_topic_is_idempotent_no_duplicate_topic_or_card(temp_db, uid):
    app, proj, client = _wire()
    ws = app.create(uid, "game", "Genshin")
    app.link_group(uid, -100999, proj)
    m = app._eng.add_milestone(uid, ws.id, "Hu Tao")

    first = proj.ensure_entity_topic(uid, ws.id, "milestone", m.id, m.title,
                                     initial_message="card")
    second = proj.ensure_entity_topic(uid, ws.id, "milestone", m.id, m.title,
                                      initial_message="card")

    assert first == second == 101
    assert len(client.topics) == 1          # exactly one topic ever
    assert len(client.messages) == 1        # exactly one initial card ever


def test_ensure_entity_topic_unlinked_returns_none_no_call(temp_db, uid):
    app, proj, client = _wire()
    ws = app.create(uid, "game", "Genshin")
    m = app._eng.add_milestone(uid, ws.id, "Xiao")
    # workspace NOT linked to any group
    topic_id = proj.ensure_entity_topic(uid, ws.id, "milestone", m.id, m.title,
                                        initial_message="card")
    assert topic_id is None
    assert client.topics == [] and client.messages == []


def test_initial_card_send_failure_is_swallowed_topic_survives(temp_db, uid):
    app, proj, client = _wire(fail_send=True)
    ws = app.create(uid, "game", "Genshin")
    app.link_group(uid, -100999, proj)
    m = app._eng.add_milestone(uid, ws.id, "Nefer")

    topic_id = proj.ensure_entity_topic(uid, ws.id, "milestone", m.id, m.title,
                                        initial_message="card")

    # topic + binding are the durable unit; a failed card send is best-effort
    assert topic_id == 101
    assert db.tg_get_entity_topic("milestone", m.id) == 101
    # and a re-run is a no-op (does NOT post a duplicate card)
    again = proj.ensure_entity_topic(uid, ws.id, "milestone", m.id, m.title,
                                     initial_message="card")
    assert again == 101 and len(client.messages) == 0


def test_long_topic_name_passes_through_existing_mechanism(temp_db, uid):
    app, proj, client = _wire()
    ws = app.create(uid, "game", "Genshin")
    app.link_group(uid, -100999, proj)
    long_title = "人" * 200  # long + Unicode; truncation lives in the live client
    m = app._eng.add_milestone(uid, ws.id, long_title)
    topic_id = proj.ensure_entity_topic(uid, ws.id, "milestone", m.id, m.title,
                                        initial_message=None)
    assert topic_id == 101
    # the adapter passes the title through unchanged; [:128] is the live client's
    assert client.topics == [(-100999, long_title)]


# ── post_entity_update ──────────────────────────────────────────────────────
def test_post_entity_update_appends_to_existing_topic(temp_db, uid):
    app, proj, client = _wire()
    ws = app.create(uid, "game", "Genshin")
    app.link_group(uid, -100999, proj)
    m = app._eng.add_milestone(uid, ws.id, "Kinich")
    topic = proj.ensure_entity_topic(uid, ws.id, "milestone", m.id, m.title,
                                     initial_message="card")
    res = proj.post_entity_update(uid, ws.id, "milestone", m.id, m.title,
                                  "<b>Kinich</b> updated")
    assert res.ok and res.topic_id == topic and res.message_id == 1002
    assert client.messages[-1] == (-100999, topic, "<b>Kinich</b> updated", "HTML")
    assert len(client.topics) == 1      # no new topic


def test_post_entity_update_self_heals_missing_topic(temp_db, uid):
    app, proj, client = _wire()
    ws = app.create(uid, "game", "Genshin")
    app.link_group(uid, -100999, proj)
    m = app._eng.add_milestone(uid, ws.id, "Legacy")   # no topic yet
    res = proj.post_entity_update(uid, ws.id, "milestone", m.id, m.title,
                                  "<b>Legacy</b> updated",
                                  initial_message="<b>Legacy</b> card")
    assert res.ok
    # topic created, initial card posted, THEN the update
    assert client.messages[0] == (-100999, 101, "<b>Legacy</b> card", "HTML")
    assert client.messages[1] == (-100999, 101, "<b>Legacy</b> updated", "HTML")


def test_post_entity_update_unlinked_is_not_linked_no_call(temp_db, uid):
    app, proj, client = _wire()
    ws = app.create(uid, "game", "Genshin")
    m = app._eng.add_milestone(uid, ws.id, "Xilonen")
    res = proj.post_entity_update(uid, ws.id, "milestone", m.id, m.title, "x")
    assert not res.ok and res.reason == "not_linked"
    assert client.topics == [] and client.messages == []


# ── backfill_topics ─────────────────────────────────────────────────────────
def test_backfill_creates_missing_and_lists_existing(temp_db, uid):
    app, proj, client, ws = _linked_ws(uid)
    app.add_entity(uid, "Bound", proj)                    # already has topic
    app.add_entity(uid, "Legacy", None)                   # pre-alpha.13: none
    report = app.backfill_topics(uid, proj)
    info = report[ws.id]
    assert info["linked"] is True
    assert info["created"] == ["Legacy"]
    assert info["existing"] == ["Bound"]
    assert info["errors"] == []


def test_backfill_is_idempotent_second_run_creates_nothing(temp_db, uid):
    app, proj, client, ws = _linked_ws(uid)
    app.add_entity(uid, "Legacy", None)
    first = app.backfill_topics(uid, proj)
    second = app.backfill_topics(uid, proj)
    assert first[ws.id]["created"] == ["Legacy"]
    assert second[ws.id]["created"] == []
    assert second[ws.id]["existing"] == ["Legacy"]
    assert len(client.topics) == 1


def test_backfill_initial_card_reflects_db_state(temp_db, uid):
    app, proj, client, ws = _linked_ws(uid)
    m, _ = app.add_entity(uid, "Nefer", None)
    app._eng.set_fields(uid, m.id, {"level": 70, "element": "Pyro"})
    app.backfill_topics(uid, proj)
    card = client.messages[0][2]
    assert "Nefer" in card and "Level: 70" in card and "Pyro" in card


def test_backfill_skips_unlinked_workspace_without_telegram_call(temp_db, uid):
    app, proj, client = _wire()
    ws = app.create(uid, "goal", "Read 12 books")     # never linked
    app.add_entity(uid, "Book", None)
    report = app.backfill_topics(uid, proj)
    assert report[ws.id]["linked"] is False
    assert client.topics == [] and client.messages == []


def test_backfill_ignores_soft_deleted_entities(temp_db, uid):
    app, proj, client, ws = _linked_ws(uid)
    app.add_entity(uid, "Alive", None)
    ghost = app._eng.add_milestone(uid, ws.id, "Ghost")
    app._eng.delete_milestone(uid, ghost.id)
    report = app.backfill_topics(uid, proj)
    info = report[ws.id]
    assert info["created"] == ["Alive"]
    assert not any("Ghost" in (e or "") for e in info["created"] + info["existing"])


def test_backfill_empty_workspace_is_noop(temp_db, uid):
    app, proj, client, ws = _linked_ws(uid)
    report = app.backfill_topics(uid, proj)
    assert report[ws.id]["created"] == []
    assert report[ws.id]["existing"] == []
    assert client.topics == []


def test_backfill_collects_per_entity_errors_others_still_processed(temp_db, uid):
    app, proj, client, ws = _linked_ws(uid)
    app.add_entity(uid, "Broken", None)
    app.add_entity(uid, "Fine", None)
    # fail topic creation for "Broken" only
    proj2 = TelegramProjection(FakeClient(fail_topics={"Broken"}))
    report = app.backfill_topics(uid, proj2)
    info = report[ws.id]
    assert "Fine" in info["created"]
    assert len(info["errors"]) == 1 and "Broken" in info["errors"][0]


def test_backfill_partial_then_retry_recovers(temp_db, uid):
    app, proj, client, ws = _linked_ws(uid)
    app.add_entity(uid, "A", None)
    app.add_entity(uid, "B", None)
    # first run: everything fails (transient outage)
    proj_bad = TelegramProjection(FakeClient(fail_topics=lambda n: True))
    report1 = app.backfill_topics(uid, proj_bad)
    assert len(report1[ws.id]["errors"]) == 2
    assert report1[ws.id]["created"] == []
    # retry with a working client: both now succeed, no dupes, no dup cards
    report2 = app.backfill_topics(uid, proj)
    assert sorted(report2[ws.id]["created"]) == ["A", "B"]
    report3 = app.backfill_topics(uid, proj)
    assert report3[ws.id]["created"] == []
    # exactly one initial card per entity (no duplicate cards)
    assert len(client.messages) == 2


def test_topic_failure_on_create_leaves_entity_retryable_via_backfill(temp_db, uid):
    """The consistency model: the DB entity is durable; a topic failure must
    be observable and retryable -- never silently swallowed."""
    app, proj, client = _wire()
    ws = app.create(uid, "game", "Genshin")
    app.link_group(uid, -100999, proj)
    proj_bad = TelegramProjection(FakeClient(fail_topics=True))
    with pytest.raises(RuntimeError):
        app.add_entity(uid, "Arlecchino", proj_bad)
    # entity exists in the DB despite the topic failure
    entities = app._eng.list_milestones(uid, ws.id)
    assert [m.title for m in entities] == ["Arlecchino"]
    # /topicbackfill repairs it
    report = app.backfill_topics(uid, proj)
    assert report[ws.id]["created"] == ["Arlecchino"]
    assert db.tg_get_entity_topic("milestone", entities[0].id) == 101


def test_unlink_after_binding_prevents_new_topic_creation(temp_db, uid):
    """Stale binding: the workspace binding is gone, so no topic may be
    created -- even though an entity topic row might linger."""
    app, proj, client, ws = _linked_ws(uid)
    app.add_entity(uid, "Hu Tao", proj)                 # bound entity → topic
    db.tg_unlink_workspace(ws.id)
    m2 = app._eng.add_milestone(uid, ws.id, "Stale")
    topic_id = proj.ensure_entity_topic(uid, ws.id, "milestone", m2.id, m2.title,
                                        initial_message="card")
    assert topic_id is None
    assert db.tg_get_entity_topic("milestone", m2.id) is None
    assert len(client.topics) == 1                      # no new topic


def test_cross_workspace_same_name_gets_distinct_topics(temp_db, uid):
    app, proj, client = _wire()
    ws_a = app.create(uid, "game", "Genshin")          # active = ws_a
    app.link_group(uid, -100111, proj)                 # binds ws_a
    ws_b = app.create(uid, "game", "Genshin 2")        # active = ws_b
    app.link_group(uid, -100222, proj)                 # binds ws_b
    mb, tb = app.add_entity(uid, "Hu Tao", proj)       # on ws_b
    app.open_workspace(uid, ws_a.title)                # switch to ws_a
    ma, ta = app.add_entity(uid, "Hu Tao", proj)       # on ws_a
    assert ta != tb
    assert db.tg_get_entity_topic("milestone", ma.id) == ta
    assert db.tg_get_entity_topic("milestone", mb.id) == tb
    assert len(client.topics) == 2
    assert set(n for (_c, n) in client.topics) == {"Hu Tao"}


def test_duplicate_create_one_topic_each_no_cross_dupe(temp_db, uid):
    """Two entities with the same title each get exactly ONE topic; calling
    ensure again on either never creates a duplicate."""
    app, proj, client, ws = _linked_ws(uid)
    m1, _ = app.add_entity(uid, "Hu Tao", proj)
    m2, _ = app.add_entity(uid, "Hu Tao", proj)
    assert m1.id != m2.id
    assert len(client.topics) == 2
    # re-ensuring either entity is a no-op
    proj.ensure_entity_topic(uid, ws.id, "milestone", m1.id, "Hu Tao",
                             initial_message="card")
    proj.ensure_entity_topic(uid, ws.id, "milestone", m2.id, "Hu Tao",
                             initial_message="card")
    assert len(client.topics) == 2
    assert len(client.messages) == 2


def test_binding_write_transient_failure_is_self_healed(temp_db, uid):
    """A single transient DB-write failure right after topic creation is
    retried once inside ensure_entity_topic -- no orphan, no duplicate."""
    app, proj, client, ws = _linked_ws(uid)
    m, _ = app.add_entity(uid, "Nefer", None)

    real = db.tg_set_entity_topic
    calls = {"n": 0}

    def flaky(user_id, workspace_id, etype, eid, topic_id):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient db write failed")
        return real(user_id, workspace_id, etype, eid, topic_id)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(db, "tg_set_entity_topic", flaky)
    try:
        report = app.backfill_topics(uid, proj)
    finally:
        monkeypatch.undo()

    assert report[ws.id]["errors"] == []                 # self-healed
    assert db.tg_get_entity_topic("milestone", m.id) == 101
    assert len(client.topics) == 1                       # no duplicate topic


def test_binding_write_persistent_failure_is_observable_and_retryable(temp_db, uid):
    """A PERSISTENT binding failure surfaces in errors[] (the topic exists but
    is unbound -- the orphan). A re-run with a working writer binds a NEW
    topic; the orphan is unreachable, which is the documented non-atomicity
    (we do not pretend distributed atomicity)."""
    app, proj, client, ws = _linked_ws(uid)
    m, _ = app.add_entity(uid, "Nefer", None)

    def always_fail(*_a, **_k):
        raise RuntimeError("db down")

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(db, "tg_set_entity_topic", always_fail)
    try:
        report = app.backfill_topics(uid, proj)
    finally:
        monkeypatch.undo()

    assert len(report[ws.id]["errors"]) == 1
    assert db.tg_get_entity_topic("milestone", m.id) is None  # unbound
    assert len(client.topics) == 1                             # the orphan
    # re-run with the real writer: retryable, binding lands on a NEW topic
    report2 = app.backfill_topics(uid, proj)
    assert report2[ws.id]["created"] == ["Nefer"]
    assert db.tg_get_entity_topic("milestone", m.id) is not None
    assert len(client.topics) == 2


# ── card escaping ───────────────────────────────────────────────────────────
def test_card_escapes_user_titles_and_field_values(temp_db, uid):
    from core.workspace.render import format_entity_card
    import types
    ent = types.SimpleNamespace(
        title="X & <b>Y</b>", status="in_progress",
        fields={"note": "a<b>&amp;</b>"})
    card = format_entity_card(ent)
    # the title's markup is escaped, not emitted as live HTML
    assert "&lt;b&gt;Y&lt;/b&gt;" in card
    assert "<b>Y</b>" not in card        # no raw user tag
    # the field value's markup is escaped too
    assert "a&lt;b&gt;" in card
    # status is humanized
    assert "In Progress" in card


def test_card_missing_and_many_fields(temp_db, uid):
    from core.workspace.render import format_entity_card
    import types
    sparse = types.SimpleNamespace(
        title="Sparse", status="active", fields={"level": None})
    card = format_entity_card(sparse)
    assert "Level" not in card            # None field skipped
    dense = types.SimpleNamespace(
        title="Dense", status="active",
        fields={f"f{i}": i for i in range(30)})
    card = format_entity_card(dense)
    assert all(f"F{i}: {i}" in card for i in (0, 29))
