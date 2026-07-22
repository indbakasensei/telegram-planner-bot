"""Quick Release Suite: AI."""
from core.regression.models import (
    Priority, RegressionTest, ScenarioClass, Suite,
)
from core.regression.registry import register

_QUICK = frozenset({Suite.QUICK})


def _t(**kw):
    register(RegressionTest(**kw))


_t(
    test_id="AI-001", category="AI", feature="AI chat / provider health",
    introduced_version="v3.0", priority=Priority.CRITICAL,
    scenario=ScenarioClass.NORMAL, estimated_seconds=30, suites=_QUICK,
    objective="A free-text message the AI must handle gets a coherent reply.",
    preconditions="Idle state; AI provider configured.",
    steps=("Send: What should I focus on today?",),
    expected=("A relevant, coherent reply (possibly from the fallback model)",
              "No unhandled error to the user"),
    failure_conditions=("Timeout with no reply", "Raw error surfaced to user"),
    related_bugs=("BUG-001",),
    notes="Cross-check with /debug -> Self Test -> AI Provider; a WARNING there "
          "(main model degraded, fallback works) is acceptable for this test.",
)

_t(
    test_id="AI-002", category="AI", feature="/think reasoning",
    introduced_version="v10.2", priority=Priority.MEDIUM,
    scenario=ScenarioClass.FAILURE, estimated_seconds=60, suites=_QUICK,
    objective="/think either answers or fails gracefully — never hangs silently.",
    preconditions="Idle state.",
    steps=("Send: think am I taking on too much?",),
    expected=("Either a reasoned reply, OR a clear 'try again' style message",
              "The bot remains responsive to the next command"),
    failure_conditions=("Silent hang", "Bot becomes unresponsive afterward"),
    related_bugs=("BUG-004",),
    notes="Known: under provider timeouts all retries can fail; a graceful "
          "failure message is a PASS, a silent hang is a FAIL.",
)


_t(
    test_id="AI-003", category="AI", feature="AI planning",
    introduced_version="v4.0", priority=Priority.HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=60, suites=_QUICK,
    objective="A plan request produces a time-blocked plan and offers to apply it.",
    preconditions="Some open tasks exist; AI reachable.",
    steps=("Send: plan today",),
    expected=("A structured, time-blocked plan is returned",
              "An 'apply' style confirmation is offered"),
    failure_conditions=("No plan", "Unhandled error", "Silent hang"),
    related_bugs=("BUG-001",),
    notes="Provider-dependent; a graceful 'try again' is acceptable, a silent "
          "hang is a FAIL.",
)

_t(
    test_id="AI-004", category="AI", feature="Clarification (missing info)",
    introduced_version="v3.0", priority=Priority.HIGH,
    scenario=ScenarioClass.MULTI_STEP, estimated_seconds=45, suites=_QUICK,
    objective="When required info is missing, BAKA asks rather than guessing.",
    preconditions="Idle state; AI reachable.",
    steps=("Send: Remind me in 2 hours", "Provide the title when asked"),
    expected=("BAKA asks WHAT to be reminded about (title missing)",
              "After the reply, the task is created with the given title"),
    failure_conditions=("Uses the raw message as the title",
                        "Saves without asking", "Gathering loop never resolves"),
)
