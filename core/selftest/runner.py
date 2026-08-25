"""
runner.py -- discovers and executes registered self-tests (v14.22).

Responsibilities (per the framework brief):
  - discover registered tests (auto-import the tests/ package once)
  - execute sequentially, in registration order
  - catch every exception; one failure never stops the run
  - map outcomes to the standard SelfTestResult contract
  - time each test and the whole run
  - aggregate into a SelfTestReport
  - log start / per-test / summary, following existing conventions
    (module logger, lazy %-style formatting)

The runner is synchronous and touches no telegram/async code. Some
tests do real I/O (a database round-trip, an AI health probe), so the
caller runs the whole thing OFF the event loop -- main.py's Debug Menu
does `await run_blocking(run)`. Keeping the runner sync means test
authors write plain functions.
"""
from __future__ import annotations

import importlib
import logging
import os
import pkgutil
import sqlite3
import subprocess
import sys
import tempfile
import traceback
from time import perf_counter

from core.selftest.models import (
    SelfTestFail, SelfTestResult, SelfTestSkip, SelfTestWarning, Status,
)
from core.selftest.registry import registered_tests
from core.selftest.results import SelfTestReport

logger = logging.getLogger(__name__)

_discovered = False

# Global temp DB path used for all self-tests to avoid WSL network share locking issues
_temp_db_path: str | None = None
_original_db_names: dict[str, str] = {}


def _setup_temp_db() -> str:
    """Create a temporary database on the local filesystem and patch DB_NAME
    in all modules that use it. Returns the temp DB path."""
    global _temp_db_path, _original_db_names

    # Clear cached module references to ensure fresh imports with patched
    # DB_NAME values. This prevents stale imports from caching the old
    # DB_NAME before discover() runs test modules (especially important
    # since test modules import database inside functions rather than at
    # module level).
    for mod_name in ['database', 'scheduler']:
        if mod_name in sys.modules:
            del sys.modules[mod_name]

    # Create temp DB file
    _temp_db_path = os.path.join(tempfile.gettempdir(), f'planner_selftest_{os.getpid()}.db')
    if os.path.exists(_temp_db_path):
        os.remove(_temp_db_path)

    # Patch DB_NAME in all modules that reference it
    modules_to_patch = ['database', 'scheduler']
    for mod_name in modules_to_patch:
        try:
            mod = sys.modules.get(mod_name) or __import__(mod_name)
            _original_db_names[mod_name] = getattr(mod, 'DB_NAME', 'planner.db')
            setattr(mod, 'DB_NAME', _temp_db_path)
        except Exception as e:
            logger.debug("Could not patch %s.DB_NAME: %s", mod_name, e)

    # Initialize the temp database
    try:
        import database as db
        db.init_db()
    except Exception as e:
        logger.error("Failed to initialize temp database: %s", e)

    return _temp_db_path


def _cleanup_temp_db() -> None:
    """Clean up the temporary database and restore original DB_NAME values."""
    global _temp_db_path, _original_db_names

    # Restore original DB_NAME values
    for mod_name, original in _original_db_names.items():
        try:
            mod = sys.modules.get(mod_name)
            if mod:
                setattr(mod, 'DB_NAME', original)
        except Exception:
            pass
    _original_db_names.clear()

    # Remove temp DB file
    if _temp_db_path and os.path.exists(_temp_db_path):
        try:
            os.remove(_temp_db_path)
        except Exception:
            pass
    _temp_db_path = None


def discover() -> None:
    """Import every module under core/selftest/tests/ so their
    @selftest decorators register. Runs its body once per process
    (registration is idempotent by name anyway). Import errors in a
    single test module are logged and skipped -- a broken test file
    must not take down the whole runner."""
    global _discovered
    if _discovered:
        return
    from core.selftest import tests as _tests_pkg
    for mod in pkgutil.iter_modules(_tests_pkg.__path__):
        try:
            importlib.import_module(f"core.selftest.tests.{mod.name}")
        except Exception:
            logger.exception("Self-test discovery failed to import %s", mod.name)
    _discovered = True


def _run_one(name: str, category: str, func) -> SelfTestResult:
    """Execute one test, converting its return/raise into a
    SelfTestResult. Never raises."""
    logger.debug("[selftest] started: %s (%s)", name, category)
    t0 = perf_counter()
    status, message, details = Status.PASS, "OK", None
    try:
        returned = func()
        if returned:
            message = str(returned)
    except SelfTestSkip as exc:
        status, message, details = Status.SKIPPED, exc.message or "skipped", exc.details
    except SelfTestWarning as exc:
        status, message, details = Status.WARNING, exc.message or "warning", exc.details
    except SelfTestFail as exc:
        status, message, details = Status.FAIL, exc.message or "failed", exc.details
    except Exception as exc:  # noqa: BLE001 -- containment is the point
        status = Status.FAIL
        message = f"{type(exc).__name__}: {exc}"
        details = traceback.format_exc()
    dur = (perf_counter() - t0) * 1000
    if status is Status.FAIL:
        logger.warning("[selftest] FAIL: %s -- %s (%.0fms)", name, message, dur)
    else:
        logger.debug("[selftest] %s: %s (%.0fms)", status.value, name, dur)
    return SelfTestResult(name=name, category=category, status=status,
                          duration_ms=dur, message=message, details=details)


def run(categories: "set[str] | None" = None,
        exclude: "set[str] | None" = None) -> SelfTestReport:
    """Discover, run, and aggregate. `categories` (if given) limits the
    run to those categories; `exclude` drops categories (used by the
    offline pytest suite to skip the network-bound AI probe). Passing
    neither runs everything -- what the Debug Menu's 'Run All' does."""

    # Set up a temporary database on the local filesystem to avoid
    # WSL network share (//wsl.localhost/Ubuntu) locking issues
    # Must be done BEFORE discover() so test modules see the patched DB_NAME
    _setup_temp_db()

    discover()
    tests = registered_tests()
    if categories is not None:
        tests = tuple(t for t in tests if t.category in categories)
    if exclude:
        tests = tuple(t for t in tests if t.category not in exclude)

    logger.info("[selftest] run started: %d test(s)", len(tests))
    t0 = perf_counter()
    results = [_run_one(t.name, t.category, t.func) for t in tests]
    total = (perf_counter() - t0) * 1000

    # Clean up temp database
    _cleanup_temp_db()

    report = SelfTestReport(results=results, duration_ms=total)
    logger.info(
        "[selftest] run finished: %d passed, %d failed, %d warning, %d skipped in %.2fs",
        report.passed, report.failed, report.warnings, report.skipped, report.duration_s,
    )
    return report
