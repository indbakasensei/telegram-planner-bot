"""
Tests for core/regression/ -- the manual-regression SPECIFICATION
foundation (v14.23, QA Phase 1). No runner/UI exists yet; these cover
the data model, registry validation/queries, the version-aware history
store, and the integrity of the authored Quick Release Suite.
"""
import tempfile

import pytest

from core import regression as reg
from core.regression import registry, store
from core.regression.categories import CATEGORIES
from core.regression.models import (
    Priority, RegressionHistory, RegressionTest, ScenarioClass, Suite,
    suite_includes,
)


def _spec(test_id="TASK-001", category="Tasks", suites=frozenset({Suite.QUICK}),
          priority=Priority.HIGH, steps=("do",), expected=("ok",)):
    return RegressionTest(
        test_id=test_id, category=category, feature="f",
        introduced_version="v1.0", priority=priority,
        scenario=ScenarioClass.NORMAL, estimated_seconds=10,
        objective="o", preconditions="p", steps=steps, expected=expected,
        suites=suites)


@pytest.fixture
def clean_registry(monkeypatch):
    """Snapshot the registry, hand back a cleared one, restore after.
    Pins _discovered so a mechanics test doesn't re-import real suites."""
    saved = registry.all_tests()
    monkeypatch.setattr(reg, "_discovered", True)
    registry.clear()
    yield registry
    registry.clear()
    for t in saved:
        registry.register(t)


# ── Models ────────────────────────────────────────────────────────────────

def test_suite_nesting():
    quick = frozenset({Suite.QUICK})
    full_only = frozenset({Suite.FULL})
    assert suite_includes(Suite.FULL, quick)      # FULL includes QUICK-tagged
    assert suite_includes(Suite.QUICK, quick)
    assert not suite_includes(Suite.QUICK, full_only)   # QUICK excludes FULL-only
    assert suite_includes(Suite.MAJOR, quick)     # MAJOR includes QUICK-tagged


def test_history_roundtrip():
    h = RegressionHistory("T-001", last_passed_version="v14.23",
                          pass_count=3, linked_bugs=["DBG-0001"])
    assert RegressionHistory.from_dict(h.to_dict()) == h


# ── Registry validation + queries ────────────────────────────────────────

def test_register_and_dedup(clean_registry):
    clean_registry.register(_spec("TASK-001", priority=Priority.LOW))
    clean_registry.register(_spec("TASK-001", priority=Priority.CRITICAL))
    assert clean_registry.count() == 1
    assert clean_registry.get("TASK-001").priority is Priority.CRITICAL


@pytest.mark.parametrize("kw", [
    {"test_id": "bad id"},                 # bad id format
    {"test_id": "task-1"},                 # lowercase / too short
    {"category": "Nope"},                  # unknown category
    {"steps": ()},                         # empty steps
    {"expected": ()},                      # empty expected
    {"suites": frozenset()},               # no suite
])
def test_invalid_specs_rejected(clean_registry, kw):
    with pytest.raises((ValueError, TypeError)):
        clean_registry.register(_spec(**kw))


def test_queries(clean_registry):
    clean_registry.register(_spec("CORE-001", "Core", frozenset({Suite.QUICK}),
                                  Priority.CRITICAL))
    clean_registry.register(_spec("TASK-050", "Tasks", frozenset({Suite.MAJOR}),
                                  Priority.MEDIUM))
    assert [t.test_id for t in clean_registry.by_category("Core")] == ["CORE-001"]
    assert [t.test_id for t in clean_registry.by_priority(Priority.CRITICAL)] == ["CORE-001"]
    # QUICK run includes only QUICK-tagged; MAJOR run includes both.
    assert [t.test_id for t in clean_registry.by_suite(Suite.QUICK)] == ["CORE-001"]
    assert {t.test_id for t in clean_registry.by_suite(Suite.MAJOR)} == {"CORE-001", "TASK-050"}
    assert clean_registry.all_tests()[0].test_id == "CORE-001"   # sorted by id


# ── History store ─────────────────────────────────────────────────────────

def test_store_records_and_persists():
    path = tempfile.mktemp(suffix=".json")
    assert store.load(path) == {}                    # missing file -> empty
    store.record("TASK-001", "PASS", "v14.23", path=path)
    store.record("TASK-001", "FAIL", "v14.24", linked_bugs=("DBG-0001",), path=path)
    store.record("TASK-001", "FAIL", "v14.24", linked_bugs=("DBG-0001",), path=path)
    h = store.get_history("TASK-001", path=path)
    assert h.pass_count == 1 and h.fail_count == 2
    assert h.last_passed_version == "v14.23"          # unchanged by the fails
    assert h.last_executed_version == "v14.24"
    assert h.linked_bugs == ["DBG-0001"]              # deduped
    # survives a reload
    assert store.load(path)["TASK-001"].fail_count == 2


def test_store_skip_and_bad_status():
    path = tempfile.mktemp(suffix=".json")
    assert store.record("T-001", "SKIP", "v1", path=path).skip_count == 1
    with pytest.raises(ValueError):
        store.record("T-001", "MAYBE", "v1", path=path)


def test_store_load_corrupt_file_is_empty(tmp_path):
    p = tmp_path / "corrupt.json"
    p.write_text("{ not json", encoding="utf-8")
    assert store.load(str(p)) == {}                   # never raises


# ── Authored Quick Release Suite integrity ────────────────────────────────

def test_quick_suite_is_valid_and_covers_focus_areas():
    reg.discover()
    quick = reg.by_suite(Suite.QUICK)
    assert len(quick) >= 40                            # the completed gate

    ids = [t.test_id for t in quick]
    assert len(ids) == len(set(ids))                   # unique ids

    valid_cats = set(CATEGORIES)
    for t in quick:
        assert t.category in valid_cats, t.test_id
        assert t.steps and t.expected, t.test_id       # every test is executable
        assert t.estimated_seconds > 0, t.test_id
        assert Suite.QUICK in t.suites, t.test_id

    # Every critical user-facing feature area has at least one test
    # (the Quick Suite is BAKA's mandatory release gate).
    covered = {t.category for t in quick}
    required = {"Core", "Tasks", "Reminders", "Dashboard", "Memory", "AI",
                "Habits", "Goals", "Projects", "Search/Files", "Settings",
                "Admin", "Documentation"}
    assert required <= covered, required - covered
    # Self-Test coverage lives under Developer/Debug.
    assert covered & {"Developer", "Debug"}


def test_every_registered_test_has_a_known_category():
    reg.discover()
    valid = set(CATEGORIES)
    assert all(t.category in valid for t in reg.all_tests())
