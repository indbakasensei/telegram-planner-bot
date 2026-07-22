"""
store.py -- persistence foundation for version-aware test HISTORY
(v14.23, QA Phase 1).

Regression specs are authored code (registry.py); their execution
history accumulates across releases and must persist. This module is
that persistence layer: a JSON-backed store of RegressionHistory keyed
by test_id, with a single record() mutation the FUTURE runner will call
after each manual result.

This milestone ships the storage foundation ONLY -- no runner writes to
it yet. The file is gitignored (runtime state, like bugs.db) and
safe to delete (history resets, specs are untouched).

Design choices:
- JSON file, not a DB table: history is small, human-readable, and
  independent of bugs.db's schema -- deletable without touching bug
  data.
- Path is a parameter (default REGRESSION_HISTORY_PATH) so tests use a
  temp file and never touch the real one.
- record() is the only mutation, so the version-aware counters
  (pass/fail/skip, last-executed/last-passed) update in exactly one
  place.
"""
from __future__ import annotations

import json
import logging
import os

from core.regression.models import RegressionHistory

logger = logging.getLogger(__name__)

# Beside the bot, gitignored. Runtime state; safe to delete.
REGRESSION_HISTORY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "regression_history.json",
)


def load(path: str = REGRESSION_HISTORY_PATH) -> dict[str, RegressionHistory]:
    """Load all history, keyed by test_id. Missing/corrupt file -> empty
    (never raises; a broken history file must not block anything)."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        return {tid: RegressionHistory.from_dict(d) for tid, d in raw.items()}
    except Exception:
        logger.exception("regression history load failed (%s) -- starting empty", path)
        return {}


def save(history: dict[str, RegressionHistory],
         path: str = REGRESSION_HISTORY_PATH) -> None:
    """Persist the full history map (pretty-printed, stable key order)."""
    data = {tid: h.to_dict() for tid, h in sorted(history.items())}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_history(test_id: str,
                path: str = REGRESSION_HISTORY_PATH) -> RegressionHistory:
    """History for one test id (a fresh zeroed record if none yet)."""
    return load(path).get(test_id, RegressionHistory(test_id=test_id))


def record(test_id: str, status: str, version: str,
           linked_bugs: "tuple[str, ...]" = (),
           path: str = REGRESSION_HISTORY_PATH) -> RegressionHistory:
    """Record one manual result and persist. `status` is
    'PASS'|'FAIL'|'SKIP'. Updates the version-aware counters and merges
    any linked bug ids. Returns the updated record. (The future runner
    is the caller; exposed now so the foundation is complete and
    testable.)"""
    history = load(path)
    h = history.get(test_id, RegressionHistory(test_id=test_id))
    h.last_executed_version = version
    s = status.upper()
    if s == "PASS":
        h.pass_count += 1
        h.last_passed_version = version
    elif s == "FAIL":
        h.fail_count += 1
    elif s == "SKIP":
        h.skip_count += 1
    else:
        raise ValueError(f"unknown status {status!r} (want PASS/FAIL/SKIP)")
    for bug in linked_bugs:
        if bug not in h.linked_bugs:
            h.linked_bugs.append(bug)
    history[test_id] = h
    save(history, path)
    return h
