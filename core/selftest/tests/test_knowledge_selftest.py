"""Self-tests: v15.4 M6 — Knowledge + Media + Tags (category AI).

Live, offline probes confirming the M6 knowledge/media/tag tool surface
(core/ai/tool_adapters.py) is healthy in the running app: the 22 M6 tools
(notes 9, media 9, tags 4) register with the M2 contract and honest risk
classifications, and a deterministic note+media+tag round-trip through ONE
registry drives the domain services. Checks create data under SELFTEST_USER_ID
and clean it up in finally blocks, so they leave no residue and are safe to
re-run.
"""
from core.selftest.models import SELFTEST_USER_ID, SelfTestFail
from core.selftest.registry import selftest

# The full M6 knowledge/media/tag tool surface (22 names; the 9+9+4 split
# is deliberate — see V15_4_KNOWLEDGE_MEDIA.md).
_M6_TOOLS = frozenset({
    # Notes (9)
    "create_note", "update_note", "delete_note",
    "get_note", "list_notes",
    "link_note_entity", "unlink_note_entity",
    "link_note_tag", "unlink_note_tag",
    # Media (9)
    "store_media", "update_media", "delete_media",
    "get_media", "list_media",
    "link_media_entity", "unlink_media_entity",
    "link_media_tag", "unlink_media_tag",
    # Tags (4)
    "create_tag", "rename_tag", "delete_tag", "list_tags",
})

# M6 tools that MUST be classified as writing state (never READ_ONLY).
_M6_WRITING = frozenset({
    "create_note", "update_note",
    "link_note_entity", "unlink_note_entity",
    "link_note_tag", "unlink_note_tag",
    "store_media", "update_media",
    "link_media_entity", "unlink_media_entity",
    "link_media_tag", "unlink_media_tag",
    "create_tag", "rename_tag",
})

# M6 DESTRUCTIVE tools (must carry confirmation_message).
_M6_DESTRUCTIVE = frozenset({
    "delete_note", "delete_media", "delete_tag",
})


@selftest(name="M6 Knowledge Tool Registry", category="AI")
def check_m6_knowledge_tool_registry():
    """build_tool_registry registers the complete M6 surface under the M2
    contract with honest risk classifications: every write tool is MUTATING,
    delete_note/delete_media/delete_tag are DESTRUCTIVE with confirmation
    messages, and nothing is misclassified as SYSTEM. The registry also
    includes pre-M6 tools (37) + post_note (M6 projection helper) = 60 total."""
    from core.ai.tool_adapters import build_tool_registry
    from core.ai.tools import RiskLevel

    reg = build_tool_registry(SELFTEST_USER_ID)
    names = set(reg.names())
    missing = _M6_TOOLS - names
    if missing:
        raise SelfTestFail(f"M6 tools missing: {sorted(missing)}")

    for name in _M6_WRITING:
        spec = reg.get(name).spec
        if spec.risk is RiskLevel.READ_ONLY:
            raise SelfTestFail(f"M6 {name} misclassified as READ_ONLY")
    for name in _M6_DESTRUCTIVE:
        if reg.get(name).spec.risk is not RiskLevel.DESTRUCTIVE:
            raise SelfTestFail(f"M6 {name} not classified DESTRUCTIVE")
        if not reg.get(name).spec.confirmation_message:
            raise SelfTestFail(f"M6 {name} DESTRUCTIVE without confirmation message")
    if any(t.spec.risk is RiskLevel.SYSTEM for t in reg.all() if t.spec.name in _M6_TOOLS):
        raise SelfTestFail("an M6 tool is classified SYSTEM (no admin surface)")
    # post_note is the 23rd M6-related tool (projection helper)
    assert "post_note" in names
    return f"M6 registry ok · {len(_M6_TOOLS)} M6 tools + post_note = 23, risks honest · total {len(names)} tools"


@selftest(name="M6 Knowledge Round-trip", category="AI")
def check_m6_knowledge_roundtrip():
    """A deterministic note+media+tag round-trip through ONE registry against
    the live database, with a fake Telegram client proving the domain services
    work end-to-end. Cleans up completely."""
    import database as db
    from core.ai.tool_adapters import build_tool_registry
    from core.workspace.adapters.projection import (
        TelegramClient, TelegramProjection,
    )
    from core.workspace.engine import EntityEngine

    class _Fake(TelegramClient):
        def __init__(self):
            self.topics = []
            self.messages = []
        def create_forum_topic(self, chat_id, name):
            self.topics.append(name)
            return 900 + len(self.topics)
        def send_message(self, chat_id, topic_id, text, parse_mode=None):
            self.messages.append((topic_id, text, parse_mode))
            return 1
        def send_photo(self, chat_id, topic_id, file_id, caption):
            return 2

    eng = EntityEngine()
    ws = eng.create_workspace(SELFTEST_USER_ID, "[selftest] m6 knowledge",
                              template="game", seed_milestones=False)
    note_id = media_id = tag_id = None
    try:
        db.tg_set_active(SELFTEST_USER_ID, ws.id)
        fake = _Fake()
        proj = TelegramProjection(fake)
        proj.link_group(SELFTEST_USER_ID, ws.id, -100777)
        reg = build_tool_registry(SELFTEST_USER_ID, engine=eng, projection=proj)

        # 1) Create an entity to link to
        e = reg.execute("create_entity", {"name": "[selftest] m6 hero"})
        if not (e.ok and e.data.get("topic_created")):
            raise SelfTestFail(f"create_entity failed: {e}")

        # 2) Create a note linked to the entity with a tag
        r = reg.execute("create_note", {
            "title": "[selftest] M6 Note",
            "content": "M6 round-trip content",
            "kind": "general",
            "entities": ["[selftest] m6 hero"],
            "tags": ["M6_TEST_TAG"]
        })
        if not r.ok:
            raise SelfTestFail(f"create_note failed: {r}")
        note_id = r.data["note_id"]

        # 3) Get the note and verify links
        g = reg.execute("get_note", {"note_id": note_id})
        if not (g.ok and g.data["title"] == "[selftest] M6 Note"):
            raise SelfTestFail(f"get_note failed: {g}")
        if not any(t["name"] == "M6_TEST_TAG" for t in g.data.get("tags", [])):
            raise SelfTestFail(f"note tag not linked: {g.data.get('tags')}")

        # 4) Store media linked to the entity with a tag
        m = reg.execute("store_media", {
            "file_id": "AgAA-M6Selftest",
            "media_type": "photo",
            "caption": "M6 media caption",
            "entities": ["[selftest] m6 hero"],
            "tags": ["M6_TEST_TAG"]
        })
        if not m.ok:
            raise SelfTestFail(f"store_media failed: {m}")
        media_id = m.data["media_id"]

        # 5) Get media and verify
        g = reg.execute("get_media", {"media_id": media_id})
        if not (g.ok and g.data["caption"] == "M6 media caption"):
            raise SelfTestFail(f"get_media failed: {g}")
        if not any(t["name"] == "M6_TEST_TAG" for t in g.data.get("tags", [])):
            raise SelfTestFail(f"media tag not linked: {g.data.get('tags')}")

        # 6) List tags and verify the tag exists
        l = reg.execute("list_tags", {})
        if not (l.ok and any(t["name"] == "M6_TEST_TAG" for t in l.data)):
            raise SelfTestFail(f"list_tags failed: {l}")

        # 7) Search notes by entity
        s = reg.execute("list_notes", {"entity": "[selftest] m6 hero"})
        if not (s.ok and any(n["note_id"] == note_id for n in s.data)):
            raise SelfTestFail(f"list_notes by entity failed: {s}")

        # 8) Search media by tag
        s = reg.execute("list_media", {"tag": "M6_TEST_TAG"})
        if not (s.ok and any(m["media_id"] == media_id for m in s.data)):
            raise SelfTestFail(f"list_media by tag failed: {s}")

        # 9) Rename tag
        r = reg.execute("rename_tag", {"tag": l.data[0]["name"], "new_name": "M6_RENAMED"})
        if not r.ok:
            raise SelfTestFail(f"rename_tag failed: {r}")

        # 10) Delete note (soft) - verify it's gone from list
        d = reg.execute("delete_note", {"note_id": note_id})
        if not d.ok:
            raise SelfTestFail(f"delete_note failed: {d}")
        s = reg.execute("list_notes", {})
        if not (s.ok and not any(n["note_id"] == note_id for n in s.data)):
            raise SelfTestFail(f"deleted note still appears in list: {s}")

        return ("M6 round-trip ok · note+media+tag create/link/get/list/rename/delete, "
                "entity links verified, soft-delete works")
    finally:
        # Cleanup
        if note_id is not None:
            # Note is already soft-deleted, but ensure workspace is cleaned
            pass
        if media_id is not None:
            try:
                reg.execute("delete_media", {"media_id": media_id})
            except Exception:
                pass
        db.delete_workspace(ws.id, SELFTEST_USER_ID)
        db.tg_clear_active(SELFTEST_USER_ID)


@selftest(name="M6 Control Pages Render", category="AI")
def check_m6_control_pages_render():
    """The control panel pages for Knowledge/Media/Tags render without error
    (smoke test — no live Telegram required, uses a FakeClient)."""
    import database as db
    import ui_components as uic
    from core.control.registry import build_context, build_control_registry
    from core.workspace.adapters.projection import TelegramClient, TelegramProjection
    from core.workspace.engine import EntityEngine

    class _Fake(TelegramClient):
        def __init__(self):
            self.topics = []
            self.messages = []
        def create_forum_topic(self, chat_id, name):
            self.topics.append(name)
            return 900 + len(self.topics)
        def send_message(self, chat_id, topic_id, text, parse_mode=None):
            self.messages.append((topic_id, text, parse_mode))
            return 1
        def send_photo(self, chat_id, topic_id, file_id, caption):
            return 2

    eng = EntityEngine()
    ws = eng.create_workspace(SELFTEST_USER_ID, "[selftest] m6 control",
                              template="game", seed_milestones=False)
    try:
        fake = _Fake()
        proj = TelegramProjection(fake)
        proj.link_group(SELFTEST_USER_ID, ws.id, -100777)
        ctx = build_context(SELFTEST_USER_ID, engine=eng)
        ctx = ctx.with_projection(proj)

        # Render each M6 section home page via the pages module
        import core.control.pages as pages
        for page_fn in (pages.note_home, pages.media_home, pages.tag_home):
            text, kb = page_fn(ctx)
            if not text or not isinstance(text, str):
                raise SelfTestFail(f"page {page_fn.__name__} rendered empty/invalid: {text}")

        return "M6 control pages render ok · note/media/tag list pages smoke-tested"
    finally:
        db.delete_workspace(ws.id, SELFTEST_USER_ID)
        db.tg_clear_active(SELFTEST_USER_ID)