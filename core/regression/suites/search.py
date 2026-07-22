"""Quick Release Suite: Search."""
from core.regression.models import (
    Priority, RegressionTest, ScenarioClass, Suite,
)
from core.regression.registry import register

_QUICK = frozenset({Suite.QUICK})


def _t(**kw):
    register(RegressionTest(**kw))


_t(
    test_id="SRCH-001", category="Search/Files", feature="Search finds a task",
    introduced_version="v10.0", priority=Priority.MEDIUM,
    scenario=ScenarioClass.NORMAL, estimated_seconds=30, suites=_QUICK,
    objective="Search returns a matching task by keyword.",
    preconditions="A task whose title contains a known keyword exists.",
    steps=("Send: search <keyword>",),
    expected=("Results list the matching task under a Tasks heading",
              "The task id/title is shown"),
    failure_conditions=("Matching task not returned", "Error"),
)

_t(
    test_id="SRCH-002", category="Search/Files", feature="Search finds a memory",
    introduced_version="v10.0", priority=Priority.MEDIUM,
    scenario=ScenarioClass.NORMAL, estimated_seconds=30, suites=_QUICK,
    objective="Search returns a matching memory by keyword.",
    preconditions="A stored memory containing a known keyword exists.",
    steps=("Send: search <keyword>",),
    expected=("Results include the matching memory under a Memories heading"),
    failure_conditions=("Matching memory not returned"),
    notes="No-match should return a clean 'no results' message (SRCH boundary, "
          "covered in Major suite).",
)
