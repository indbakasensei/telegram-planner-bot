"""
registry.py -- lightweight, decorator-based registration for BAKA's
Self-Test framework (v14.22).

A future feature adds a self-test by creating a module under
core/selftest/tests/ and decorating a function:

    from core.selftest.registry import selftest
    from core.selftest.models import SelfTestFail

    @selftest(name="My Feature", category="MyCat")
    def check_my_feature():
        if not ...:
            raise SelfTestFail("reason")
        return "ok, all good"      # optional PASS message

No edit to the runner, the UI, or this file is ever needed -- the
runner discovers the module automatically (runner.discover()). Same
registration-based, edit-nothing-central philosophy as the Offline
Engine's ActionRegistry (ADR-012), applied to diagnostics.

Registration is deduplicated by name: importing a module twice (e.g.
once by the runner's discovery, once by pytest) registers it only
once, because Python caches the module in sys.modules and the dedup
guard covers any residual double-call.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True, slots=True)
class RegisteredTest:
    """One registered check: its display name, its category (for the
    grouped UI), and the zero-arg callable that performs it."""
    name: str
    category: str
    func: Callable[[], "str | None"]


_REGISTRY: list[RegisteredTest] = []


def register(name: str, category: str, func: Callable[[], "str | None"]) -> None:
    """Programmatic registration (the decorator delegates here).
    Idempotent by name -- a duplicate name replaces the prior entry so
    a reloaded module never double-runs."""
    if not name or not isinstance(name, str):
        raise ValueError("self-test name must be a non-empty string")
    if not category or not isinstance(category, str):
        raise ValueError(f"self-test {name!r}: category must be a non-empty string")
    if not callable(func):
        raise ValueError(f"self-test {name!r}: func must be callable")
    global _REGISTRY
    _REGISTRY = [t for t in _REGISTRY if t.name != name]
    _REGISTRY.append(RegisteredTest(name, category, func))


def selftest(name: str, category: str) -> Callable:
    """Decorator form. Registers the function and returns it unchanged
    (so it stays independently callable/testable)."""
    def decorator(func: Callable[[], "str | None"]) -> Callable:
        register(name, category, func)
        return func
    return decorator


def registered_tests() -> tuple[RegisteredTest, ...]:
    """All registered tests, in registration order (= execution order)."""
    return tuple(_REGISTRY)


def categories() -> list[str]:
    """Distinct categories present, in first-seen order -- drives the
    'Available Tests' grouping on the Self-Test screen."""
    seen: list[str] = []
    for t in _REGISTRY:
        if t.category not in seen:
            seen.append(t.category)
    return seen


def clear() -> None:
    """Empty the registry -- used only by unit tests that build a
    synthetic registry in isolation."""
    _REGISTRY.clear()
