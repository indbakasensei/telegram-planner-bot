"""
models.py -- the regression test SPECIFICATION contract (v14.23,
QA Phase 1). Foundation only: data structures, no runner/UI.

Two shapes, deliberately separated:

- RegressionTest -- the immutable, authored SPEC of a manual test
  (id, steps, expected, priority, which release suites include it, the
  version it was introduced in). Authored in code under
  core/regression/suites/ and registered; never mutated at runtime.

- RegressionHistory -- the mutable, PERSISTED execution record for a
  test id (last executed/passed version, pass/fail/skip counts, linked
  bug ids). Accumulates across releases so regressions are detectable
  over time (a test that passed for 18 versions and now fails is a
  signal). Written by the future runner via store.py; here we only
  define the shape and the foundation.

Stdlib-only so the contract imports anywhere (suites, store, the
offline pytest suite) with no heavy dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Priority(str, Enum):
    CRITICAL = "Critical"
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class ScenarioClass(str, Enum):
    """The nine scenario classes every feature is exercised across
    (QA_SYSTEM_DESIGN.md Part 2)."""
    NORMAL = "Normal"
    BOUNDARY = "Boundary"
    INVALID = "Invalid"
    RECOVERY = "Recovery"
    FAILURE = "Failure"
    REPEATED = "Repeated"
    MULTI_STEP = "Multi-step"
    INTERRUPTED = "Interrupted"
    RESTART = "Restart"


class Suite(str, Enum):
    """Release-suite membership. A test may belong to several (a QUICK
    test is also in MAJOR and FULL); by_suite() honours the natural
    QUICK ⊆ MAJOR ⊆ FULL nesting."""
    QUICK = "Quick"
    MAJOR = "Major"
    FULL = "Full"


# QUICK ⊆ MAJOR ⊆ FULL: a QUICK test runs in every larger suite too.
_SUITE_CONTAINS = {
    Suite.QUICK: {Suite.QUICK},
    Suite.MAJOR: {Suite.QUICK, Suite.MAJOR},
    Suite.FULL: {Suite.QUICK, Suite.MAJOR, Suite.FULL},
}


def suite_includes(run_suite: Suite, test_suites: "frozenset[Suite]") -> bool:
    """True if a test tagged `test_suites` should run under `run_suite`.
    Running FULL includes everything; running QUICK includes only
    QUICK-tagged tests."""
    return bool(_SUITE_CONTAINS[run_suite] & test_suites)


@dataclass(frozen=True, slots=True)
class RegressionTest:
    """One manual regression test's authored specification. Immutable
    and hashable (all collection fields are tuples/frozensets)."""
    test_id: str                       # <CAT>-### e.g. TASK-014
    category: str                      # one of categories.CATEGORIES
    feature: str                       # inventory feature name
    introduced_version: str            # e.g. "v14.3"
    priority: Priority
    scenario: ScenarioClass
    estimated_seconds: int
    objective: str
    preconditions: str
    steps: tuple[str, ...]
    expected: tuple[str, ...]
    failure_conditions: tuple[str, ...] = ()
    related_bugs: tuple[str, ...] = ()
    notes: str = ""
    suites: frozenset[Suite] = frozenset({Suite.FULL})


@dataclass(slots=True)
class RegressionHistory:
    """The persisted, version-aware execution record for one test id.
    Foundation shape; the runner (a later milestone) updates it via
    store.py."""
    test_id: str
    last_executed_version: "str | None" = None
    last_passed_version: "str | None" = None
    pass_count: int = 0
    fail_count: int = 0
    skip_count: int = 0
    linked_bugs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "test_id": self.test_id,
            "last_executed_version": self.last_executed_version,
            "last_passed_version": self.last_passed_version,
            "pass_count": self.pass_count,
            "fail_count": self.fail_count,
            "skip_count": self.skip_count,
            "linked_bugs": list(self.linked_bugs),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "RegressionHistory":
        return cls(
            test_id=d["test_id"],
            last_executed_version=d.get("last_executed_version"),
            last_passed_version=d.get("last_passed_version"),
            pass_count=d.get("pass_count", 0),
            fail_count=d.get("fail_count", 0),
            skip_count=d.get("skip_count", 0),
            linked_bugs=list(d.get("linked_bugs", [])),
        )
