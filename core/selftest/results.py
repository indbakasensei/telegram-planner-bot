"""
results.py -- aggregation of a self-test run into a summary (v14.22).

The runner produces a list of SelfTestResult; SelfTestReport wraps them
with the counts and total duration the UI and logs need, plus the run's
worst outcome (for a single headline status). Pure: stdlib + models
only.
"""
from __future__ import annotations

from dataclasses import dataclass

from core.selftest.models import SelfTestResult, Status, severity


@dataclass(slots=True)
class SelfTestReport:
    """The outcome of one full run."""
    results: list[SelfTestResult]
    duration_ms: float

    def _count(self, status: Status) -> int:
        return sum(1 for r in self.results if r.status is status)

    @property
    def passed(self) -> int:
        return self._count(Status.PASS)

    @property
    def failed(self) -> int:
        return self._count(Status.FAIL)

    @property
    def warnings(self) -> int:
        return self._count(Status.WARNING)

    @property
    def skipped(self) -> int:
        return self._count(Status.SKIPPED)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def duration_s(self) -> float:
        return self.duration_ms / 1000.0

    @property
    def worst(self) -> Status:
        """The most severe outcome in the run (PASS if empty) -- lets
        the UI pick one headline colour/icon for the whole run."""
        if not self.results:
            return Status.PASS
        return max((r.status for r in self.results), key=severity)

    @property
    def all_passed(self) -> bool:
        return self.failed == 0 and self.warnings == 0
