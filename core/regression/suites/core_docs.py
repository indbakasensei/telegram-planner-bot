"""Quick Release Suite: Core + Documentation."""
from core.regression.models import (
    Priority, RegressionTest, ScenarioClass, Suite,
)
from core.regression.registry import register

_QUICK = frozenset({Suite.QUICK})


def _t(**kw):
    register(RegressionTest(**kw))


_t(
    test_id="CORE-001", category="Core", feature="Bot startup / /start",
    introduced_version="v1.0", priority=Priority.CRITICAL,
    scenario=ScenarioClass.NORMAL, estimated_seconds=20, suites=_QUICK,
    objective="Bot responds to /start with a greeting and the menu keyboard.",
    preconditions="Bot running; any user.",
    steps=("Send /start",),
    expected=("A greeting appears naming BAKA",
              "The reply keyboard (menu) is shown",
              "No error / no crash"),
    failure_conditions=("No reply", "No menu keyboard", "Error message"),
)

_t(
    test_id="CORE-002", category="Core", feature="/help",
    introduced_version="v11.1", priority=Priority.HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=25, suites=_QUICK,
    objective="/help renders the full grouped command reference.",
    preconditions="Bot running.",
    steps=("Send /help",),
    expected=("Two messages render as formatted HTML (no raw <b> tags)",
              "Expandable category sections are present",
              "Admin section shows ONLY for the admin account"),
    failure_conditions=("Raw HTML tags visible", "Missing sections",
                        "Admin section shown to a non-admin"),
    notes="Admin visibility is the security-relevant part.",
)

_t(
    test_id="CORE-003", category="Core", feature="Natural-language entry",
    introduced_version="v3.0", priority=Priority.HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=25, suites=_QUICK,
    objective="A plain-language greeting gets a conversational reply, not an error.",
    preconditions="Idle state; AI reachable.",
    steps=("Send: How are you?",),
    expected=("A natural conversational reply",
              "No task/goal is created from a greeting"),
    failure_conditions=("Greeting misclassified into a task/goal", "Error"),
    notes="Under AI degradation the reply may come from the fallback model.",
)

_t(
    test_id="DOC-001", category="Documentation", feature="Help coverage",
    introduced_version="v14.23", priority=Priority.MEDIUM,
    scenario=ScenarioClass.NORMAL, estimated_seconds=60, suites=_QUICK,
    objective="Every user-facing command appears in /help (Definition of Done).",
    preconditions="Latest /help output.",
    steps=("Compare the registered command handlers against /help's listing",),
    expected=("Every non-admin, non-broken command is documented in /help",
              "Admin commands appear only in the admin section"),
    failure_conditions=("A shipped command is missing from /help"),
    notes="Automatable later as a Self-Test check (CommandHandler ⊆ help_cards).",
)

_t(
    test_id="DOC-002", category="Documentation", feature="Version accuracy",
    introduced_version="v14.23", priority=Priority.LOW,
    scenario=ScenarioClass.NORMAL, estimated_seconds=20, suites=_QUICK,
    objective="The reported version is current in /help and /selftest.",
    preconditions="Admin account.",
    steps=("Send /help and note the version", "Send /selftest and note the version"),
    expected=("Both show the current BAKA_VERSION", "The two agree"),
    failure_conditions=("Stale version string", "Mismatch between surfaces"),
)


_t(
    test_id="DOC-003", category="Documentation", feature="Onboarding validity",
    introduced_version="v14.23", priority=Priority.LOW,
    scenario=ScenarioClass.NORMAL, estimated_seconds=30, suites=_QUICK,
    objective="Every command/example referenced by /start actually works.",
    preconditions="Latest /start output.",
    steps=("Read the /start greeting", "Try each command/example phrase it shows"),
    expected=("Every referenced command/example is valid and produces the "
              "described behaviour", "No dead or renamed references"),
    failure_conditions=("/start references a removed/renamed command or a "
                        "broken example"),
    notes="Part of the Definition of Done: /start must stay in sync with the "
          "real command surface.",
)
