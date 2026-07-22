"""
core.regression -- BAKA's manual regression test SPECIFICATION system
(v14.23, QA Phase 1 foundation).

This package holds the authored specs of BAKA's manual regression tests
and the version-aware history store -- the foundation the future
Regression Runner and Developer Center will build on. It ships NO
runner, NO UI, and NO callbacks yet (by design: QA_SYSTEM_DESIGN Phase
1). See docs/regression.md and QA_SYSTEM_DESIGN.md.

Public surface:
  discover()              -- import the suite modules so specs register
  all_tests()/by_suite()/by_category()/by_priority()/get()/count()
  RegressionTest / RegressionHistory / Priority / ScenarioClass / Suite
  store.record()/load()/get_history()  (history persistence foundation)
"""
import importlib
import pkgutil

from core.regression.models import (
    Priority, RegressionHistory, RegressionTest, ScenarioClass, Suite,
)
from core.regression.registry import (
    all_tests, by_category, by_priority, by_suite, categories_present,
    count, get,
)

_discovered = False


def discover() -> None:
    """Import every module under core/regression/suites/ so their
    register(...) calls populate the registry. Idempotent; a broken
    suite module is logged and skipped, never fatal."""
    global _discovered
    if _discovered:
        return
    import logging
    from core.regression import suites as _suites_pkg
    for mod in pkgutil.iter_modules(_suites_pkg.__path__):
        try:
            importlib.import_module(f"core.regression.suites.{mod.name}")
        except Exception:
            logging.getLogger(__name__).exception(
                "regression suite discovery failed to import %s", mod.name)
    _discovered = True


__all__ = [
    "discover", "all_tests", "by_suite", "by_category", "by_priority",
    "categories_present", "count", "get",
    "RegressionTest", "RegressionHistory", "Priority", "ScenarioClass", "Suite",
]
