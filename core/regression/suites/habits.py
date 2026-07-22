"""Quick Release Suite: Habits."""
from core.regression.models import (
    Priority, RegressionTest, ScenarioClass, Suite,
)
from core.regression.registry import register

_QUICK = frozenset({Suite.QUICK})


def _t(**kw):
    register(RegressionTest(**kw))


_t(
    test_id="HAB-001", category="Habits", feature="Habit creation",
    introduced_version="v5.0", priority=Priority.HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=35, suites=_QUICK,
    objective="Create a habit via the quick command.",
    preconditions="Idle state.",
    steps=("Send: addhabit Drink water at 09:00 daily", "Send: habits"),
    expected=("Habit created (title 'Drink water', 09:00, daily)",
              "It appears in /habits with streak 0"),
    failure_conditions=("Not created", "Wrong recurrence/time",
                        "Not shown in /habits"),
)

_t(
    test_id="HAB-002", category="Habits", feature="Habit completion + streak",
    introduced_version="v5.0", priority=Priority.HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=35, suites=_QUICK,
    objective="Completing a habit increments its streak.",
    preconditions="A habit exists (note its id).",
    steps=("Send: done <habit_id>", "Send: streak <habit_id>"),
    expected=("Completion acknowledged with a streak indicator",
              "Streak shows 1 (or +1 from its prior value)"),
    failure_conditions=("Streak not incremented", "Treated as a plain task",
                        "No streak feedback"),
)

_t(
    test_id="HAB-003", category="Habits", feature="Habit already-logged",
    introduced_version="v5.0", priority=Priority.MEDIUM,
    scenario=ScenarioClass.BOUNDARY, estimated_seconds=25, suites=_QUICK,
    objective="Completing the same habit twice in one day does not double-count.",
    preconditions="A habit already completed today (from HAB-002).",
    steps=("Send: done <habit_id> again",),
    expected=("An 'already logged today' style acknowledgement",
              "Streak does NOT increase a second time"),
    failure_conditions=("Streak double-counts", "Error"),
)
