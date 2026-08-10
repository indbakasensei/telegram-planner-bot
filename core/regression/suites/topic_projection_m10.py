"""Quick Release Suite: v15.1.0-alpha.13 Telegram Entity Topic Projection.

Manual tests for the topic-projection milestone (M10): natural-language
entity creation automatically projects a Telegram topic + binding + initial
card, updates append to the topic, and /topicbackfill idempotently backfills
topics for every existing entity in Telegram-linked workspaces. These need a
live bot (Telegram), so they live in the manual Quick Release Suite, not the
offline pytest suite.

Acceptance examples referenced below (Xiao, Kinich, Xilonen, Nefer, Lauma,
Columbina, Arlecchino) are ONLY illustrations -- the feature is generic and
applies to any entity in any linked workspace.
"""
from core.regression.models import (
    Priority, RegressionTest, ScenarioClass, Suite,
)
from core.regression.registry import register

_QUICK = frozenset({Suite.QUICK})


def _t(**kw):
    register(RegressionTest(**kw))


# ── NL create auto-projects a topic (acceptance D) ─────────────────────────
_t(
    test_id="TOP-001", category="Workspace Groups", feature="NL create → topic",
    introduced_version="v15.1.0-alpha.13", priority=Priority.CRITICAL,
    scenario=ScenarioClass.NORMAL, estimated_seconds=30, suites=_QUICK,
    objective="'Create character <name>' creates the DB entity AND a Telegram "
              "topic with an initial card, binds it, sets it active, and "
              "confirms -- with NO manual topic/linking commands.",
    preconditions="A linked workspace is active (e.g. /newgame Genshin, then "
                  "in the group /linkhere).",
    steps=("In private chat, send: Create character Arlecchino",),
    expected=("Bot confirms the entity was created",
              "A new topic 'Arlecchino' appears in the linked group with an "
              "initial card (name, status, any fields)",
              "/current shows Arlecchino as the active entity",
              "No /add, /topicbackfill, or manual topic creation was needed"),
    failure_conditions=("Entity created but no topic appeared",
                        "Topic appeared but no initial card",
                        "Bot asked the user to create the topic manually"),
)

# ── Backfill existing entities (acceptance A) ───────────────────────────────
_t(
    test_id="TOP-002", category="Workspace Groups", feature="Backfill existing",
    introduced_version="v15.1.0-alpha.13", priority=Priority.CRITICAL,
    scenario=ScenarioClass.MULTI_STEP, estimated_seconds=120, suites=_QUICK,
    objective="Entities that predate the projection get exactly one topic "
              "each via /topicbackfill -- e.g. the existing Genshin roster "
              "(Xiao, Kinich, Xilonen, Nefer, Lauma, Columbina, ...).",
    preconditions="A linked workspace with several entities created BEFORE "
                  "this milestone (no topics yet).",
    steps=("Send: /topicbackfill",),
    expected=("Bot reports each entity: 'N created' listing them",
              "Exactly one topic appears in the group for each listed entity",
              "Each new topic contains an initial card from CURRENT DB state "
              "(fields match /show -- never invented)",
              "Entity ids/fields are unchanged"),
    failure_conditions=("Zero topics for entities that lacked one",
                        "A topic created for an entity that already had one",
                        "Entities recreated or fields altered"),
)

# ── Idempotent re-run / no duplicates (acceptance B) ────────────────────────
_t(
    test_id="TOP-003", category="Workspace Groups", feature="Backfill idempotent",
    introduced_version="v15.1.0-alpha.13", priority=Priority.HIGH,
    scenario=ScenarioClass.MULTI_STEP, estimated_seconds=60, suites=_QUICK,
    objective="Re-running /topicbackfill creates nothing; entities that "
              "already had a topic (e.g. Hu Tao, Akasha Ranking) get no "
              "duplicate topic and no duplicate initial card.",
    preconditions="A workspace where TOP-002 ran and/or where some entities "
                  "already have topics.",
    steps=("Send: /topicbackfill", "Send: /topicbackfill",),
    expected=("Second run reports '0 created' (all existing)",
              "No duplicate topics in the group",
              "No duplicate initial-card messages posted"),
    failure_conditions=("Second run created any topic",
                        "Duplicate topics/messages for already-bound entities"),
)

# ── Topic contents reflect DB (acceptance C) ────────────────────────────────
_t(
    test_id="TOP-004", category="Workspace Groups", feature="Initial card = DB",
    introduced_version="v15.1.0-alpha.13", priority=Priority.HIGH,
    scenario=ScenarioClass.MULTI_STEP, estimated_seconds=60, suites=_QUICK,
    objective="The initial card in a topic reflects the entity's ACTUAL "
              "current fields -- e.g. a character at level 70 shows Level: 70.",
    preconditions="An entity whose fields were set before its topic existed "
                  "(or were updated after creation).",
    steps=("Send: /topicbackfill (or check a freshly created topic)",
           "Compare the topic's card with /show <entity>",),
    expected=("The card's status and every field match /show exactly",
              "The card has an IST timestamp",
              "Nothing is invented that isn't in the DB"),
    failure_conditions=("Card shows stale or fabricated fields",
                        "Card shows no fields that /show displays"),
)

# ── NL update appends to topic (acceptance E) ───────────────────────────────
_t(
    test_id="TOP-005", category="Workspace Groups", feature="NL update → topic",
    introduced_version="v15.1.0-alpha.13", priority=Priority.HIGH,
    scenario=ScenarioClass.MULTI_STEP, estimated_seconds=60, suites=_QUICK,
    objective="An update like '<name> is level 90' persists to the DB and "
              "appends an update message to the entity's topic (old value "
              "shown only when it was real).",
    preconditions="An active entity with a topic (TOP-001 or /add).",
    steps=("Send: Arlecchino is level 90",
           "Open Arlecchino's topic in the group",),
    expected=("Private-chat reply confirms the update",
              "The topic shows an update message 'Level: <old> → 90' "
              "(old value only if it existed)",
              "The initial card is untouched (append-only, no rewrite)"),
    failure_conditions=("No update message in the topic",
                        "The initial card was rewritten/deleted",
                        "An invented old value is shown"),
)

# ── Reference resolution still works (acceptance F) ─────────────────────────
_t(
    test_id="TOP-006", category="Workspace Groups", feature="References intact",
    introduced_version="v15.1.0-alpha.13", priority=Priority.HIGH,
    scenario=ScenarioClass.MULTI_STEP, estimated_seconds=60, suites=_QUICK,
    objective="M1 reference resolution is unchanged after the projection "
              "seam: Show all / first / last / <name> / pronouns still work.",
    preconditions="A workspace with several entities.",
    steps=("Send: Show all characters",
           "Send: Show the first one",
           "Send: Show Arlecchino",
           "Create one, then: Show her",),
    expected=("Each resolves to the correct entity/entities",
              "'Show her' after a create resolves to the just-created entity",
              "No AI call for a bare reference (responds immediately)"),
    failure_conditions=("A reference resolves to the wrong entity",
                        "'Show her' fails after a create"),
)

# ── Task commands unaffected (acceptance G) ─────────────────────────────────
_t(
    test_id="TOP-007", category="Workspace Groups", feature="Task routing intact",
    introduced_version="v15.1.0-alpha.13", priority=Priority.HIGH,
    scenario=ScenarioClass.MULTI_STEP, estimated_seconds=60, suites=_QUICK,
    objective="Regular task commands are NOT swallowed by the entity manager "
              "now that a projection is injected.",
    preconditions="A user with tasks.",
    steps=("Send: Show today's tasks",
           "Send: Create task <something>",),
    expected=("Both are handled exactly as before this milestone",
              "No entity/topic is created for a task phrase"),
    failure_conditions=("A task command is misrouted to entity management",
                        "A task phrase creates an entity or a topic"),
)

# ── Unlinked workspace is skipped ───────────────────────────────────────────
_t(
    test_id="TOP-008", category="Workspace Groups", feature="Backfill unlinked skip",
    introduced_version="v15.1.0-alpha.13", priority=Priority.MEDIUM,
    scenario=ScenarioClass.MULTI_STEP, estimated_seconds=45, suites=_QUICK,
    objective="/topicbackfill reports unlinked workspaces as skipped and "
              "makes NO Telegram call for them.",
    preconditions="A user with one linked and one unlinked workspace, the "
                  "unlinked one holding entities.",
    steps=("Send: /topicbackfill",),
    expected=("Report lists the unlinked workspace as 'not linked, skipped'",
              "No topic is created in ANY group for the unlinked workspace",
              "The linked workspace is still backfilled normally"),
    failure_conditions=("A topic appears for an unlinked workspace",
                        "The unlinked workspace is reported as created"),
)

# ── Backfill error reporting ────────────────────────────────────────────────
_t(
    test_id="TOP-009", category="Workspace Groups", feature="Backfill reports errors",
    introduced_version="v15.1.0-alpha.13", priority=Priority.MEDIUM,
    scenario=ScenarioClass.MULTI_STEP, estimated_seconds=45, suites=_QUICK,
    objective="Per-entity failures during backfill are reported and retryable "
              "-- a transient topic failure leaves the DB intact.",
    preconditions="A linked workspace with entities; bot still admin in the "
                  "group (simulate failure by temporarily removing the bot's "
                  "manage-topics right if feasible).",
    steps=("Remove the bot's forum rights, send: /topicbackfill",
           "Restore rights, send: /topicbackfill",),
    expected=("First run reports per-entity errors, no crash",
              "Entities are NOT recreated and DB rows are intact",
              "Second run (rights restored) succeeds and reports 'created'"),
    failure_conditions=("The bot crashes on a topic failure",
                        "A failed topic blocks other entities' backfill",
                        "A failed backfill corrupts DB state"),
)
