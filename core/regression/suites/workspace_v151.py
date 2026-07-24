"""Quick Release Suite: v15.1 Workspace groups + Cognitive Engine + GLM 5.2.

Manual tests for the features shipped in the v15.1.0 line — the Telegram
photo-journal (groups/topics), the grounded /ws question answering, and the
GLM 5.2 default model. These need a live bot (Telegram + AI), so they live
in the manual Quick Release Suite, not the offline pytest suite.
"""
from core.regression.models import (
    Priority, RegressionTest, ScenarioClass, Suite,
)
from core.regression.registry import register

_QUICK = frozenset({Suite.QUICK})


def _t(**kw):
    register(RegressionTest(**kw))


# ── Workspace groups (v15.1.0-alpha.1) ────────────────────────────────────
_t(
    test_id="WSG-001", category="Workspace Groups", feature="Create workspace",
    introduced_version="v15.1.0-alpha.1", priority=Priority.HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=30, suites=_QUICK,
    objective="A project/game/goal workspace is created and made active.",
    preconditions="Private chat with the bot.",
    steps=("Send: /newgame Genshin", "Send: /current"),
    expected=("Confirms 'Created game Genshin' + how to link a group",
              "/current shows Genshin as the active workspace, not linked"),
    failure_conditions=("No workspace created", "/current shows nothing active"),
)

_t(
    test_id="WSG-002", category="Workspace Groups", feature="Link a Telegram group",
    introduced_version="v15.1.0-alpha.1", priority=Priority.HIGH,
    scenario=ScenarioClass.MULTI_STEP, estimated_seconds=60, suites=_QUICK,
    objective="A private forum group is bound to the active workspace.",
    preconditions="A workspace is active (WSG-001). Create a private group, "
                  "enable Topics in its settings, and add the bot as admin.",
    steps=("In the group, send: /linkhere",),
    expected=("Bot confirms 'Linked this group to <workspace>'",
              "/current (in private chat) now shows Group linked: yes"),
    failure_conditions=("'open a workspace first' (no active ws)",
                        "An error about admin/Topics with the bot correctly set up"),
    notes="If the group is NOT a forum (Topics off) or the bot isn't admin, a "
          "clear error is expected — that is correct behavior, not a failure.",
)

_t(
    test_id="WSG-003", category="Workspace Groups", feature="Add entity → topic",
    introduced_version="v15.1.0-alpha.1", priority=Priority.HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=30, suites=_QUICK,
    objective="Adding an entity creates its own topic in the linked group.",
    preconditions="A linked workspace (WSG-002).",
    steps=("Send: /add Hu Tao",),
    expected=("Bot confirms the entity was added + a topic was created",
              "A new topic 'Hu Tao' appears in the group"),
    failure_conditions=("No topic created despite a linked forum group",
                        "Entity not added"),
)

_t(
    test_id="WSG-004", category="Workspace Groups", feature="Photo progress journal",
    introduced_version="v15.1.0-alpha.1", priority=Priority.CRITICAL,
    scenario=ScenarioClass.NORMAL, estimated_seconds=45, suites=_QUICK,
    objective="A photo + caption logs progress into the active entity's topic.",
    preconditions="An active entity with a topic (WSG-003).",
    steps=("Send the bot a photo with caption: got her 4th artifact",),
    expected=("Bot confirms 'Progress → Hu Tao: posted to your group'",
              "The photo + caption appear inside Hu Tao's topic in the group"),
    failure_conditions=("Photo treated as generic vision/todo instead of a log",
                        "Nothing posted to the topic"),
    notes="With no active workspace, a photo still does the old vision/todo "
          "behavior — that path must remain unchanged.",
)

# ── Cognitive Engine (v15.1.0-alpha.3) ────────────────────────────────────
_t(
    test_id="WSQ-001", category="Workspace Groups", feature="/ws grounded answer",
    introduced_version="v15.1.0-alpha.3", priority=Priority.HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=40, suites=_QUICK,
    objective="A question is answered from REAL workspace data, never invented.",
    preconditions="A workspace with a blocked entity (e.g. /newproject Drone, "
                  "/add Flight controller, mark it blocked).",
    steps=("Send: /ws which component is blocked in Drone?",),
    expected=("Names the blocked entity (Flight controller) from real data",
              "Does NOT invent components that weren't added"),
    failure_conditions=("Fabricates a component", "Generic/ungrounded AI answer"),
)

_t(
    test_id="WSQ-002", category="Workspace Groups", feature="/ws conversation context",
    introduced_version="v15.1.0-alpha.3", priority=Priority.MEDIUM,
    scenario=ScenarioClass.MULTI_STEP, estimated_seconds=40, suites=_QUICK,
    objective="A follow-up infers the workspace from context (no repeat).",
    preconditions="At least two workspaces exist.",
    steps=("Send: /ws open Drone", "Send: /ws how far along is it?"),
    expected=("First sets Drone active",
              "Second answers about Drone WITHOUT naming it again"),
    failure_conditions=("Asks which workspace", "Answers about the wrong one"),
)

# ── GLM 5.2 default (v15.1.0-alpha.4) ──────────────────────────────────────
_t(
    test_id="AI-011", category="AI", feature="GLM 5.2 is the default model",
    introduced_version="v15.1.0-alpha.4", priority=Priority.CRITICAL,
    scenario=ScenarioClass.NORMAL, estimated_seconds=30, suites=_QUICK,
    objective="Out of the box (no MODEL_MAIN override) the bot runs GLM 5.2.",
    preconditions="No MODEL_MAIN set in .env; NVIDIA key configured.",
    steps=("Run /selftest → AI → 'AI Configuration'",
           "Run /selftest → AI → 'AI Provider'"),
    expected=("AI Configuration shows nvidia-nim · z-ai/glm-5.2",
              "AI Provider is online (or WARNING → Llama-8b fallback serving)"),
    failure_conditions=("Configuration still shows a Llama model as main",
                        "AI Provider FAIL (invalid key)"),
    notes="A WARNING on AI Provider means glm-5.2 is briefly degraded and the "
          "Llama-8b fallback is answering — the bot still works.",
)
