"""
Tests for v15.1 -- Workspace groups (Telegram projection).

Exercises the full usable flow with a FAKE Telegram client (no PTB, no
network): create a workspace, link a group, add entities (→ topics), open an
entity, and log progress notes/photos that route to the right topic. Also
asserts the core stays Telegram-agnostic (topic ids live only in the
adapter-owned binding tables, never on the workspace/milestone rows).
"""
import database as db
from core.storage import Storage
from core.workspace.adapters.projection import TelegramClient, TelegramProjection
from core.workspace.groups_app import WorkspaceGroups


class FakeClient(TelegramClient):
    """Records calls; hands out deterministic topic/message ids."""
    def __init__(self):
        self.topics = []      # (chat_id, name) -> id is index+100
        self.messages = []    # (chat_id, topic_id, text)
        self.photos = []      # (chat_id, topic_id, file_id, caption)

    def create_forum_topic(self, chat_id, name):
        self.topics.append((chat_id, name))
        return 100 + len(self.topics)

    def send_message(self, chat_id, topic_id, text, parse_mode=None):
        self.messages.append((chat_id, topic_id, text, parse_mode))
        return 1000 + len(self.messages)

    def send_photo(self, chat_id, topic_id, file_id, caption):
        self.photos.append((chat_id, topic_id, file_id, caption))
        return 2000 + len(self.photos)


def _wire():
    client = FakeClient()
    proj = TelegramProjection(client)
    app = WorkspaceGroups()
    return app, proj, client


def test_create_sets_active(temp_db, uid):
    app, _, _ = _wire()
    ws = app.create(uid, "game", "Genshin")
    assert ws.template == "game"
    ctx = app.current(uid)
    assert ctx.workspace_id == ws.id and ctx.workspace_title == "Genshin"
    assert ctx.linked is False


def test_link_group_binds_without_touching_core(temp_db, uid):
    app, proj, _ = _wire()
    ws = app.create(uid, "game", "Genshin")
    app.link_group(uid, -100999, proj)
    assert db.tg_get_binding(ws.id) == (-100999, None)
    # core workspace row carries no chat/topic id -- binding is separate
    assert db.tg_get_workspace_for_chat(-100999) == ws.id
    assert app.current(uid).linked is True


def test_add_entity_creates_topic_and_sets_active(temp_db, uid):
    app, proj, client = _wire()
    app.create(uid, "game", "Genshin")
    app.link_group(uid, -100999, proj)
    m, topic_id = app.add_entity(uid, "Hu Tao", proj)
    assert m.title == "Hu Tao"
    assert topic_id == 101                       # first topic
    assert client.topics == [(-100999, "Hu Tao")]
    # mapping is stored in the adapter table, keyed by entity
    assert db.tg_get_entity_topic("milestone", m.id) == 101
    ctx = app.current(uid)
    assert ctx.entity_id == m.id and ctx.entity_title == "Hu Tao"


def test_log_progress_photo_routes_to_entity_topic(temp_db, uid):
    app, proj, client = _wire()
    app.create(uid, "game", "Genshin")
    app.link_group(uid, -100999, proj)
    m, topic_id = app.add_entity(uid, "Hu Tao", proj)
    res = app.log_progress(uid, "got her crown", proj, photo_file_id="FILEID1")
    assert res.ok and res.posted and res.topic_id == topic_id
    # posted as a photo to Hu Tao's topic
    assert client.photos == [(-100999, 101, "FILEID1", "got her crown")]
    # persisted: a progress note scoped to the entity + an attachment
    notes = db.get_notes(m.workspace_id, kind="progress")
    assert len(notes) == 1
    # full ATTACHMENT_COLS shape since v15.4 M6 (telegram_file_id = idx 3)
    assert db.get_attachments(m.workspace_id)[0][3] == "FILEID1"


def test_workspace_level_note_goes_to_general(temp_db, uid):
    app, proj, client = _wire()
    ws = app.create(uid, "project", "Drone")
    app.link_group(uid, -100777, proj)
    # no active entity → General topic (topic_id None), text message
    res = app.log_progress(uid, "kickoff", proj)
    assert res.ok and res.posted and res.topic_id is None
    assert client.messages[-1] == (-100777, None, "kickoff", None)


def test_log_progress_persists_even_when_unlinked(temp_db, uid):
    app, proj, _ = _wire()
    ws = app.create(uid, "goal", "Read 12 books")
    res = app.log_progress(uid, "finished book 1", proj)
    assert res.ok and res.posted is False       # nowhere to post yet
    assert len(db.get_notes(ws.id, kind="progress")) == 1   # but it's saved


def test_entity_topic_is_reused_not_recreated(temp_db, uid):
    app, proj, client = _wire()
    app.create(uid, "game", "Genshin")
    app.link_group(uid, -100999, proj)
    m, _ = app.add_entity(uid, "Hu Tao", proj)
    app.log_progress(uid, "one", proj)
    app.log_progress(uid, "two", proj)
    assert len(client.topics) == 1              # topic created once, reused


def test_open_entity_and_workspace(temp_db, uid):
    app, proj, _ = _wire()
    app.create(uid, "game", "Genshin")
    app.link_group(uid, -100999, proj)
    a, _ = app.add_entity(uid, "Hu Tao", proj)
    b, _ = app.add_entity(uid, "Nahida", proj)
    assert app.current(uid).entity_title == "Nahida"
    app.open_entity(uid, "Hu Tao")
    assert app.current(uid).entity_title == "Hu Tao"


def test_delete_workspace_clears_bindings(temp_db, uid):
    app, proj, _ = _wire()
    ws = app.create(uid, "game", "Genshin")
    app.link_group(uid, -100999, proj)
    app.add_entity(uid, "Hu Tao", proj)
    db.delete_workspace(ws.id, uid)
    assert db.tg_get_binding(ws.id) is None
    assert db.tg_get_entity_topics(ws.id) == []
