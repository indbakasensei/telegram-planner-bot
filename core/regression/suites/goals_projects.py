"""Quick Release Suite: Goals + Projects."""
from core.regression.models import (
    Priority, RegressionTest, ScenarioClass, Suite,
)
from core.regression.registry import register

_QUICK = frozenset({Suite.QUICK})


def _t(**kw):
    register(RegressionTest(**kw))


# ── Goals ─────────────────────────────────────────────────────────────────
_t(
    test_id="GOAL-001", category="Goals", feature="Goal creation",
    introduced_version="v4.0", priority=Priority.MEDIUM,
    scenario=ScenarioClass.NORMAL, estimated_seconds=35, suites=_QUICK,
    objective="An aspiration phrase creates a goal (not a task/habit).",
    preconditions="Idle state; AI reachable.",
    steps=("Send: I want to read 12 books this year", "Send: goals"),
    expected=("Classified GOAL (NOT TASK/HABIT)",
              "Appears in /goals with a progress bar at 0%"),
    failure_conditions=("Classified as task/habit", "Not in /goals"),
    notes="Goal progress ± is covered by DASH-003 (dashboard inline buttons).",
)

# ── Projects ──────────────────────────────────────────────────────────────
_t(
    test_id="PROJ-001", category="Projects", feature="Project creation",
    introduced_version="v12.0", priority=Priority.MEDIUM,
    scenario=ScenarioClass.NORMAL, estimated_seconds=35, suites=_QUICK,
    objective="A project can be created and viewed.",
    preconditions="Idle state.",
    steps=("Send: project build drone by month end", "Send: projects"),
    expected=("Project created", "Appears in /projects with a progress card"),
    failure_conditions=("Not created", "Not shown in /projects"),
)

_t(
    test_id="PROJ-002", category="Projects", feature="Project materials",
    introduced_version="v12.0", priority=Priority.MEDIUM,
    scenario=ScenarioClass.NORMAL, estimated_seconds=40, suites=_QUICK,
    objective="Materials can be added to a project and marked acquired.",
    preconditions="A project exists (note its id).",
    steps=("Send: need <id> motor, propeller, battery", "Send: got motor"),
    expected=("Three materials added (comma-separated)",
              "'motor' is marked acquired (fuzzy match)"),
    failure_conditions=("Materials not added", "got fails to match"),
)

_t(
    test_id="PROJ-003", category="Projects", feature="Project worklog",
    introduced_version="v12.0", priority=Priority.MEDIUM,
    scenario=ScenarioClass.NORMAL, estimated_seconds=30, suites=_QUICK,
    objective="A worklog entry can be logged against a project.",
    preconditions="A project exists (note its id).",
    steps=("Send: worklog <id> assembled the frame", "Send: project <id>"),
    expected=("Worklog entry recorded",
              "The project card reflects the logged progress/entry"),
    failure_conditions=("Entry not recorded", "Project card unchanged"),
)
