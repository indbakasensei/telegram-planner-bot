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
        def send_message(self, chat_id, topic_id, text):
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
