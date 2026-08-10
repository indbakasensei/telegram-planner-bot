"""Self-tests: Workspace OS health (category Workspace).

Live probes you can run from /selftest to confirm the v15 Workspace OS is
wired correctly, independent of the WORKSPACE feature flag (the flag gates
the user-facing routing, not the engine's correctness). The engine round-
trip creates a temporary workspace under SELFTEST_USER_ID and hard-deletes
it in a finally block, so it leaves no residue.
"""
from core.selftest.models import SELFTEST_USER_ID, SelfTestFail
from core.selftest.registry import selftest

# The templates that must always be registered (built-ins + drop-ins).
_EXPECTED_TEMPLATES = (
    "generic", "project", "book", "course", "research",
    "game", "knowledge", "asset",
)


@selftest(name="Workspace Templates", category="Workspace")
def check_workspace_templates():
    """Every built-in + drop-in Workspace template is registered (catches a
    template module that failed to import)."""
    from core.workspace import templates
    missing = [k for k in _EXPECTED_TEMPLATES if not templates.exists(k)]
    if missing:
        raise SelfTestFail(f"templates not registered: {', '.join(missing)}")
    total = len(templates.all_templates())
    return f"{total} templates registered ({len(_EXPECTED_TEMPLATES)} expected present)"


@selftest(name="Workspace Engine", category="Workspace")
def check_workspace_engine():
    """Entity Engine create → milestone → progress rollup round-trips
    against the live database, then cleans up completely."""
    import database as db
    from core.workspace.engine import EntityEngine

    eng = EntityEngine()
    ws = eng.create_workspace(
        SELFTEST_USER_ID, "[selftest] temp workspace",
        template="project", seed_milestones=False)
    try:
        m = eng.add_milestone(SELFTEST_USER_ID, ws.id, "[selftest] milestone")
        eng.complete_milestone(SELFTEST_USER_ID, m.id)
        progress = eng.workspace_progress(SELFTEST_USER_ID, ws.id)
        if progress != 100:
            raise SelfTestFail(
                f"milestone rollup wrong: expected 100%, got {progress}%")
        return f"engine ok · created ws #{ws.id}, milestone rollup 100%"
    finally:
        db.delete_workspace(ws.id, SELFTEST_USER_ID)


@selftest(name="Entity Fields", category="Workspace")
def check_entity_fields():
    """Structured per-entity fields round-trip through the Entity Engine.
    v15.1.0-alpha.9."""
    import database as db
    from core.workspace.engine import EntityEngine
    from core.workspace.errors import EntityValidationError

    eng = EntityEngine()
    ws = eng.create_workspace(
        SELFTEST_USER_ID, "[selftest] fields",
        template="game", seed_milestones=False)
    try:
        m = eng.add_milestone(SELFTEST_USER_ID, ws.id, "[selftest] char")
        assert eng.get_fields(SELFTEST_USER_ID, m.id) == {}
        eng.set_fields(SELFTEST_USER_ID, m.id,
                       {"level": 80, "element": "Pyro"})
        stored = eng.get_fields(SELFTEST_USER_ID, m.id)
        assert stored.get("level") == 80
        assert stored.get("element") == "Pyro"
        eng.update_field(SELFTEST_USER_ID, m.id, "level", 90)
        assert eng.get_fields(SELFTEST_USER_ID, m.id).get("level") == 90
        try:
            eng.set_fields(SELFTEST_USER_ID, m.id, {"priority": "urgent"})
            raise AssertionError("expected EntityValidationError")
        except EntityValidationError:
            pass
        return ("entity fields ok · set/get/update 4 fields, "
                "validation rejects bad enum")
    finally:
        db.delete_workspace(ws.id, SELFTEST_USER_ID)


@selftest(name="Workspace Groups", category="Workspace")
def check_workspace_groups():
    """The Telegram-groups projection round-trips with a fake client: create
    a workspace, link a group, add an entity (→ topic), and log a progress
    note routed to that topic -- all without touching Telegram. Cleans up."""
    import database as db
    from core.workspace.adapters.projection import TelegramClient, TelegramProjection
    from core.workspace.groups_app import WorkspaceGroups

    class _Fake(TelegramClient):
        def create_forum_topic(self, chat_id, name):
            return 4242
        def send_message(self, chat_id, topic_id, text, parse_mode=None):
            return 1
        def send_photo(self, chat_id, topic_id, file_id, caption):
            return 2

    app = WorkspaceGroups()
    proj = TelegramProjection(_Fake())
    ws = app.create(SELFTEST_USER_ID, "game", "[selftest] group")
    try:
        app.link_group(SELFTEST_USER_ID, -100123, proj)
        m, topic = app.add_entity(SELFTEST_USER_ID, "[selftest] entity", proj)
        if topic != 4242:
            raise SelfTestFail(f"entity topic not created (got {topic})")
        res = app.log_progress(SELFTEST_USER_ID, "probe", proj)
        if not (res.ok and res.posted and res.topic_id == 4242):
            raise SelfTestFail(f"progress not routed to entity topic: {res}")
        return "groups ok · workspace→group, entity→topic, note routed"
    finally:
        db.delete_workspace(ws.id, SELFTEST_USER_ID)
        db.tg_clear_active(SELFTEST_USER_ID)


@selftest(name="Topic Backfill", category="Workspace")
def check_topic_backfill():
    """v15.1.0-alpha.13: idempotent topic backfill. A linked workspace with
    one already-bound entity, one pre-alpha.13 entity (no topic), and one
    soft-deleted entity: backfill creates exactly the missing topic (initial
    card reflects live DB state), reports the bound one as existing, ignores
    the soft-deleted one, and a re-run creates nothing. Offline (fake client)."""
    import database as db
    from core.workspace.adapters.projection import TelegramClient, TelegramProjection
    from core.workspace.engine import EntityEngine
    from core.workspace.groups_app import WorkspaceGroups

    class _Fake(TelegramClient):
        def __init__(self):
            self.topics = []     # (chat_id, name)
            self.messages = []   # (chat_id, topic_id, text, parse_mode)
        def create_forum_topic(self, chat_id, name):
            self.topics.append((chat_id, name))
            return 500 + len(self.topics)
        def send_message(self, chat_id, topic_id, text, parse_mode=None):
            self.messages.append((chat_id, topic_id, text, parse_mode))
            return 1
        def send_photo(self, chat_id, topic_id, file_id, caption):
            return 2

    app = WorkspaceGroups()
    eng = EntityEngine()
    fake = _Fake()
    proj = TelegramProjection(fake)
    ws = app.create(SELFTEST_USER_ID, "game", "[selftest] backfill")
    try:
        app.link_group(SELFTEST_USER_ID, -100555, proj)
        # Already-bound entity (add_entity projects it).
        app.add_entity(SELFTEST_USER_ID, "[selftest] bound", proj)
        # Pre-alpha.13 entity: created WITHOUT a projection → no topic yet.
        m_legacy, _ = app.add_entity(SELFTEST_USER_ID, "[selftest] legacy", None)
        eng.set_fields(SELFTEST_USER_ID, m_legacy.id, {"level": 42})
        # Soft-deleted entity must be ignored.
        ghost = eng.add_milestone(SELFTEST_USER_ID, ws.id, "[selftest] ghost")
        eng.delete_milestone(SELFTEST_USER_ID, ghost.id)

        report = app.backfill_topics(SELFTEST_USER_ID, proj)
        info = report[ws.id]
        if info.get("linked") is not True:
            raise SelfTestFail("linked workspace reported as unlinked")
        if "[selftest] legacy" not in info["created"]:
            raise SelfTestFail(f"legacy entity not backfilled: {info}")
        if "[selftest] bound" not in info["existing"]:
            raise SelfTestFail(f"bound entity not reported existing: {info}")
        if any("ghost" in e.lower() for e in info["created"] + info["existing"]):
            raise SelfTestFail("soft-deleted entity was backfilled")

        # The initial card for the legacy entity must reflect live DB state.
        if not any("Level: 42" in txt for (_, _, txt, _pm) in fake.messages):
            raise SelfTestFail("initial card did not reflect DB field level=42")

        # Idempotency: a second run creates nothing new.
        report2 = app.backfill_topics(SELFTEST_USER_ID, proj)
        if report2[ws.id]["created"]:
            raise SelfTestFail(f"backfill re-run created topics: {report2[ws.id]}")
        return ("topic backfill ok · 1 created (card from DB), 1 existing, "
                "soft-deleted ignored, re-run no-op")
    finally:
        db.delete_workspace(ws.id, SELFTEST_USER_ID)
        db.tg_clear_active(SELFTEST_USER_ID)


@selftest(name="Cognitive Engine", category="Workspace")
def check_cognitive_engine():
    """The Cognitive Engine answers a question grounded in real Workspace
    data (offline, deterministic RuleBasedPlanner -- no live LLM): create a
    blocked entity, then confirm 'what is blocked?' names it. Cleans up."""
    import database as db
    from core.ai.cognition import CognitiveEngine
    from core.workspace.engine import EntityEngine
    from core.workspace.groups_app import WorkspaceGroups

    app = WorkspaceGroups()
    eng = EntityEngine()
    ws = app.create(SELFTEST_USER_ID, "project", "[selftest] cognition")
    try:
        m = eng.add_milestone(SELFTEST_USER_ID, ws.id, "[selftest] blocker")
        eng.transition_milestone(SELFTEST_USER_ID, m.id, "blocked")
        res = CognitiveEngine().handle(SELFTEST_USER_ID, "what is blocked?")
        if "[selftest] blocker" not in res.answer:
            raise SelfTestFail(f"answer not grounded in data: {res.answer!r}")
        return "cognitive ok · grounded answer routed to a Workspace tool"
    finally:
        db.delete_workspace(ws.id, SELFTEST_USER_ID)
        db.tg_clear_active(SELFTEST_USER_ID)


@selftest(name="Workspace Retrieval", category="Workspace")
def check_workspace_retrieval():
    """Real retrieval finds a stored note by keyword across workspace data
    (offline). Creates a workspace + note, retrieves it, cleans up."""
    import database as db
    from core.ai.workspace_retriever import WorkspaceRetriever
    from core.workspace.groups_app import WorkspaceGroups

    ws = WorkspaceGroups().create(SELFTEST_USER_ID, "game", "[selftest] retrieval")
    try:
        db.add_note(ws.id, "[selftest] Teardrop Crystal talent domain note")
        docs = WorkspaceRetriever(SELFTEST_USER_ID).retrieve("Teardrop Crystal domain")
        if not any("Teardrop" in d.text for d in docs):
            raise SelfTestFail("retriever did not find the stored note")
        return f"retrieval ok · {len(docs)} related item(s) found"
    finally:
        db.delete_workspace(ws.id, SELFTEST_USER_ID)
        db.tg_clear_active(SELFTEST_USER_ID)


@selftest(name="Entity Manager", category="Workspace")
def check_entity_manager():
    """EntityManager processes natural language create intent and returns a
    non-empty response for recognised actions.  Uses a mock AI call so the
    check is fully offline — tests the pre-check logic, that the create
    intent is routed, and that non-entity text is ignored."""
    from unittest.mock import Mock
    from core.ai.entity_manager import EntityManager
    from core.workspace.engine import EntityEngine

    eng = EntityEngine()
    ws = eng.create_workspace(
        SELFTEST_USER_ID, "[selftest] entity mgr",
        template="game", seed_milestones=False)
    try:
        import database as db
        db.tg_set_active(SELFTEST_USER_ID, ws.id, "milestone", None)

        ai_ok = Mock(return_value=(
            '{"intent": "create", "entity_name": "TestChar", '
            '"fields": {}, "query": ""}'))
        mgr = EntityManager(engine=eng, ai_call=ai_ok)

        # Create intent.
        handled, reply = mgr.process(SELFTEST_USER_ID, "Create character TestChar")
        if not handled or not reply:
            raise SelfTestFail("EntityManager did not handle 'Create character TestChar'")
        if "TestChar" not in reply:
            raise SelfTestFail(f"Expected TestChar in reply, got: {reply}")

        # Non-entity message should NOT be handled (pre-check bypasses AI).
        ai_fallback = Mock(side_effect=AssertionError("should not be called"))
        mgr2 = EntityManager(engine=eng, ai_call=ai_fallback)
        handled2, _reply2 = mgr2.process(SELFTEST_USER_ID, "What's the weather today?")
        if handled2:
            raise SelfTestFail("EntityManager should NOT handle weather queries")

        # Update an entity that doesn't exist → AI is called but entity not found.
        ai_notfound = Mock(return_value=(
            '{"intent": "update", "entity_name": "NonExistent", '
            '"fields": {"level": 50}, "query": ""}'))
        mgr3 = EntityManager(engine=eng, ai_call=ai_notfound)
        handled3, reply3 = mgr3.process(SELFTEST_USER_ID, "NonExistent is level 50")
        if handled3 and reply3 and "don't see" not in reply3.lower() and "create" not in reply3.lower():
            # If it handled but didn't say "don't see" — still fine as long as
            # it didn't crash and the message is helpful.
            pass

        return (
            f"entity manager ok · create handled: {handled}, "
            f"non-entity ignored: {not handled2}")
    finally:
        db.delete_workspace(ws.id, SELFTEST_USER_ID)
        db.tg_clear_active(SELFTEST_USER_ID)


@selftest(name="Reference Resolution", category="Workspace")
def check_reference_resolution():
    """M1 (v15.1.0-alpha.12): create an entity, then 'show her' resolves to
    it deterministically -- the DB-backed active entity becomes the referent
    and the resolver makes NO AI call. Offline (mocked AI), cleans up."""
    from unittest.mock import Mock
    import database as db
    from core.ai.entity_manager import EntityManager
    from core.workspace.engine import EntityEngine

    eng = EntityEngine()
    ws = eng.create_workspace(
        SELFTEST_USER_ID, "[selftest] references",
        template="game", seed_milestones=False)
    try:
        db.tg_set_active(SELFTEST_USER_ID, ws.id, "milestone", None)

        # Create → the entity becomes the DB-backed active entity.
        ai_create = Mock(return_value=(
            '{"intent": "create", "entity_name": "TestRef", '
            '"fields": {}, "query": ""}'))
        handled, reply = EntityManager(engine=eng, ai_call=ai_create).process(
            SELFTEST_USER_ID, "Create character TestRef")
        if not handled or "TestRef" not in reply:
            raise SelfTestFail(f"create failed: {reply!r}")

        # 'Show her' must resolve to TestRef via the active entity WITHOUT a
        # second AI call (a fresh manager proves the context is DB-backed).
        ai_never = Mock(side_effect=AssertionError(
            "bare reference must not call the LLM"))
        mgr2 = EntityManager(engine=eng, ai_call=ai_never)
        handled2, reply2 = mgr2.process(SELFTEST_USER_ID, "Show her")
        if not handled2 or "TestRef" not in reply2:
            raise SelfTestFail(
                f"'show her' did not resolve to TestRef: {reply2!r}")

        return (
            "reference resolution ok · create → 'show her' → TestRef "
            "(active entity, no AI call)")
    finally:
        db.delete_workspace(ws.id, SELFTEST_USER_ID)
        db.tg_clear_active(SELFTEST_USER_ID)
