"""
registry.py -- registration + querying of regression test specs
(v14.23, QA Phase 1).

Feature-driven, growing-forever design: each feature's tests live in a
module under core/regression/suites/ and call register(RegressionTest).
The suite grows by adding tests, never by rewriting a central list --
so the "regression suite grows naturally with the project" rule
(QA_SYSTEM_DESIGN Part 1) is structural, not aspirational.

Registration validates the spec (id format, known category, non-empty
steps/expected) and deduplicates by test_id. Querying supports the
three release suites and the category/priority filters the future
runner and Developer Center will need -- but this milestone ships NO
runner and NO UI, only the queryable foundation.
"""
from __future__ import annotations

import re

from core.regression.categories import is_valid_category
from core.regression.models import Priority, RegressionTest, Suite, suite_includes

_ID_RE = re.compile(r"^[A-Z][A-Z0-9]{1,7}-\d{3}$")   # e.g. TASK-014, CORE-001

_REGISTRY: dict[str, RegressionTest] = {}


def register(test: RegressionTest) -> None:
    """Register (or replace, by id) one spec. Raises on an invalid
    spec -- a malformed test must fail loudly at authoring time, never
    silently skew coverage."""
    if not isinstance(test, RegressionTest):
        raise TypeError(f"expected RegressionTest, got {type(test).__name__}")
    if not _ID_RE.match(test.test_id):
        raise ValueError(f"bad test_id {test.test_id!r} (want e.g. TASK-014)")
    if not is_valid_category(test.category):
        raise ValueError(f"{test.test_id}: unknown category {test.category!r}")
    if not test.steps:
        raise ValueError(f"{test.test_id}: steps must be non-empty")
    if not test.expected:
        raise ValueError(f"{test.test_id}: expected must be non-empty")
    if not test.suites:
        raise ValueError(f"{test.test_id}: must belong to at least one suite")
    _REGISTRY[test.test_id] = test


def all_tests() -> tuple[RegressionTest, ...]:
    """Every registered spec, sorted by test_id (stable ordering for
    display and diffs)."""
    return tuple(sorted(_REGISTRY.values(), key=lambda t: t.test_id))


def get(test_id: str) -> "RegressionTest | None":
    return _REGISTRY.get(test_id)


def by_category(category: str) -> tuple[RegressionTest, ...]:
    return tuple(t for t in all_tests() if t.category == category)


def by_priority(priority: Priority) -> tuple[RegressionTest, ...]:
    return tuple(t for t in all_tests() if t.priority is priority)


def by_suite(suite: Suite) -> tuple[RegressionTest, ...]:
    """Tests that run under `suite`, honouring QUICK ⊆ MAJOR ⊆ FULL."""
    return tuple(t for t in all_tests() if suite_includes(suite, t.suites))


def categories_present() -> tuple[str, ...]:
    """Distinct categories that currently have at least one test."""
    seen: list[str] = []
    for t in all_tests():
        if t.category not in seen:
            seen.append(t.category)
    return tuple(seen)


def count() -> int:
    return len(_REGISTRY)


def clear() -> None:
    """Empty the registry -- used only by unit tests building a
    synthetic registry in isolation."""
    _REGISTRY.clear()
