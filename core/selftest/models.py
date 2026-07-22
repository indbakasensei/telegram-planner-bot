"""
models.py -- the standard result contract for BAKA's Self-Test
framework (v14.22).

Every registered self-test resolves to exactly one SelfTestResult, so
the runner, the UI, and the logs all speak one shape regardless of what
the test does. A test signals a non-PASS outcome by RAISING one of the
signal exceptions below (SelfTestSkip/Warning/Fail); any other
exception is treated as a FAIL with the traceback captured -- the
runner never lets a single test abort the run.

This module is intentionally dependency-free (stdlib only) so the
contract can be imported anywhere -- test modules, the runner, the UI
layer, and the offline pytest suite -- without pulling in database,
telegram, or AI code.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

# A synthetic user id for tests that must create temporary rows. It is
# far outside Telegram's real id range (~10 digits), so it can never
# collide with a real user; write-tests create data under this id and
# clean it up in a finally block.
SELFTEST_USER_ID = 10 ** 15 + 42


class Status(str, Enum):
    """The four outcomes a self-test may report. Ordering (PASS <
    SKIPPED < WARNING < FAIL) is by severity -- results.py uses it to
    pick a run's worst outcome."""
    PASS = "PASS"
    SKIPPED = "SKIPPED"
    WARNING = "WARNING"
    FAIL = "FAIL"


# Severity rank for "worst outcome" aggregation.
_SEVERITY = {Status.PASS: 0, Status.SKIPPED: 1, Status.WARNING: 2, Status.FAIL: 3}


def severity(status: Status) -> int:
    return _SEVERITY[status]


@dataclass(slots=True)
class SelfTestResult:
    """One test's outcome. `message` is a one-line human summary;
    `details` is optional longer text (e.g. a traceback) shown only on
    expansion."""
    name: str
    category: str
    status: Status
    duration_ms: float
    message: str = ""
    details: str | None = None

    @property
    def ok(self) -> bool:
        return self.status is Status.PASS


# ── Signal exceptions (how a test reports a non-PASS outcome) ─────────────

class SelfTestSignal(Exception):
    """Base for the intentional non-PASS signals. Carries an optional
    `details` payload for the expandable view."""

    def __init__(self, message: str = "", details: str | None = None):
        super().__init__(message)
        self.message = message
        self.details = details


class SelfTestSkip(SelfTestSignal):
    """Raise when a test cannot run in this environment (e.g. a feature
    is disabled) -- reported as SKIPPED, not a failure."""


class SelfTestWarning(SelfTestSignal):
    """Raise for a degraded-but-not-broken condition (e.g. AI main
    model unavailable, fallback works) -- reported as WARNING."""


class SelfTestFail(SelfTestSignal):
    """Raise for a genuine failure -- reported as FAIL. (Any
    unhandled exception is also a FAIL, with its traceback captured.)"""
