"""
Tests for core/selftest/ -- the admin-only Self-Test framework (v14.22).

Two layers:
1. Framework MECHANICS in isolation -- registration/dedup, and the
   runner's status mapping (PASS/FAIL/WARNING/SKIPPED/uncaught-exception)
   and continue-after-failure aggregation -- exercised with synthetic
   tests in a cleared registry (restored afterward).
2. The REAL checks as an integration run under a temp DB (excluding the
   network-bound AI probe): every check passes and leaves no rows behind
   under the synthetic user id.

Plus the two admin-only UI builders' contracts (callbacks + shape).
"""
import sqlite3

import pytest

from core import selftest
from core.selftest import registry, runner
from core.selftest.models import (
    SELFTEST_USER_ID, SelfTestFail, SelfTestSkip, SelfTestWarning, Status,
)


@pytest.fixture
def clean_registry(monkeypatch):
    """Snapshot the registry, hand back a cleared one, restore after.
    Also pins runner._discovered=True so runner.run() does NOT re-import
    and re-register the real test modules during a mechanics test."""
    saved = registry.registered_tests()
    monkeypatch.setattr(runner, "_discovered", True)
    registry.clear()
    yield registry
    registry.clear()
    for t in saved:
        registry.register(t.name, t.category, t.func)


# ── Registration ──────────────────────────────────────────────────────────

def test_register_and_categories(clean_registry):
    clean_registry.register("A", "Cat1", lambda: None)
    clean_registry.register("B", "Cat2", lambda: None)
    names = [t.name for t in clean_registry.registered_tests()]
    assert names == ["A", "B"]
    assert clean_registry.categories() == ["Cat1", "Cat2"]


def test_register_dedups_by_name(clean_registry):
    clean_registry.register("Dup", "Cat1", lambda: "first")
    clean_registry.register("Dup", "Cat2", lambda: "second")
    tests = clean_registry.registered_tests()
    assert len(tests) == 1
    assert tests[0].category == "Cat2"          # last write wins


def test_decorator_registers(clean_registry):
    @clean_registry.selftest(name="Deco", category="Cat")
    def check():
        return "ok"
    assert check() == "ok"                       # returned unchanged
    assert [t.name for t in clean_registry.registered_tests()] == ["Deco"]


@pytest.mark.parametrize("bad", [
    ("", "Cat", lambda: None),
    ("N", "", lambda: None),
    ("N", "Cat", "not callable"),
])
def test_invalid_registration_rejected(clean_registry, bad):
    with pytest.raises(ValueError):
        clean_registry.register(*bad)


# ── Runner mechanics ──────────────────────────────────────────────────────

def test_runner_maps_every_outcome(clean_registry):
    clean_registry.register("p", "C", lambda: "done")
    clean_registry.register("f", "C", lambda: (_ for _ in ()).throw(SelfTestFail("boom")))
    clean_registry.register("w", "C", lambda: (_ for _ in ()).throw(SelfTestWarning("degraded")))
    clean_registry.register("s", "C", lambda: (_ for _ in ()).throw(SelfTestSkip("n/a")))
    clean_registry.register("x", "C", lambda: (_ for _ in ()).throw(RuntimeError("kaboom")))

    report = runner.run()
    by_name = {r.name: r for r in report.results}
    assert by_name["p"].status is Status.PASS and by_name["p"].message == "done"
    assert by_name["f"].status is Status.FAIL and by_name["f"].message == "boom"
    assert by_name["w"].status is Status.WARNING
    assert by_name["s"].status is Status.SKIPPED
    # Uncaught exception -> FAIL with type in message + traceback details.
    assert by_name["x"].status is Status.FAIL
    assert "RuntimeError: kaboom" in by_name["x"].message
    assert by_name["x"].details and "Traceback" in by_name["x"].details


def test_runner_continues_after_failure_and_aggregates(clean_registry):
    order = []
    clean_registry.register("1", "C", lambda: order.append(1))
    clean_registry.register("2", "C", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    clean_registry.register("3", "C", lambda: order.append(3))
    report = runner.run()
    assert order == [1, 3]                        # test 3 ran despite test 2 failing
    assert report.total == 3
    assert report.passed == 2 and report.failed == 1
    assert report.worst is Status.FAIL
    assert report.all_passed is False
    assert all(r.duration_ms >= 0 for r in report.results)


def test_runner_category_filter(clean_registry):
    clean_registry.register("a", "Keep", lambda: None)
    clean_registry.register("b", "Drop", lambda: None)
    assert [r.name for r in runner.run(categories={"Keep"}).results] == ["a"]
    assert [r.name for r in runner.run(exclude={"Drop"}).results] == ["a"]


def test_report_worst_empty_is_pass():
    from core.selftest.results import SelfTestReport
    assert SelfTestReport(results=[], duration_ms=0.0).worst is Status.PASS


# ── Real discovery + integration run ──────────────────────────────────────

def test_discovery_registers_expected_categories():
    selftest.discover()
    cats = set(selftest.categories())
    assert {"Core", "AI", "Memory", "Tasks", "Goals", "Habits",
            "Dashboard", "Routing", "Database"} <= cats


def test_real_checks_pass_and_clean_up(temp_db):
    # Runs every real check except the network AI probe, against the
    # isolated temp DB, and confirms it leaves no rows behind.
    report = selftest.run(exclude={"AI"})
    assert report.total >= 9
    failures = [r for r in report.results if r.status is Status.FAIL]
    assert not failures, [f"{r.name}: {r.message}" for r in failures]
    conn = sqlite3.connect(temp_db)
    for table in ("tasks", "goals", "memories"):
        n = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE user_id=?",
                         (SELFTEST_USER_ID,)).fetchone()[0]
        assert n == 0, f"{table} left {n} rows under the self-test user id"
    conn.close()


# ── UI builders ───────────────────────────────────────────────────────────

def test_dev_menu_card_callbacks_and_toggle_label():
    import ui
    text, kb = ui.dev_menu_card(debug_on=True)
    assert "DEVELOPER CENTER" in text.upper()
    cbs = {b.callback_data for row in kb.inline_keyboard for b in row}
    assert cbs == {"dev:st", "dev:toggle", "dev:menu"}
    labels = [b.text for row in kb.inline_keyboard for b in row]
    assert any("🐞 Debug ON" in x for x in labels)
    off_labels = [b.text for row in ui.dev_menu_card(False)[1].inline_keyboard
                  for b in row]
    assert any("🐞 Debug OFF" in x for x in off_labels)


def test_selftest_screen_and_results_cards():
    import ui
    text, kb = ui.selftest_screen_card(["Core", "AI"], 5)
    assert "SELF TEST" in text.upper() and "Available Tests (5)" in text
    assert [b.callback_data for row in kb.inline_keyboard for b in row] == [
        "dev:st:run", "dev:menu"]

    from core.selftest.models import SelfTestResult
    from core.selftest.results import SelfTestReport
    results = [
        SelfTestResult("DB", "Database", Status.PASS, 4.0, "ok"),
        SelfTestResult("AI", "AI", Status.WARNING, 20.0, "degraded"),
        SelfTestResult("X", "Core", Status.FAIL, 5.0, "boom", details="Traceback\nErr: boom"),
    ]
    text, kb = ui.selftest_results_card(SelfTestReport(results, 29.0))
    assert "RESULTS" in text.upper()
    assert "✅" in text and "⚠️" in text and "❌" in text
    assert "Passed: 1" in text and "Failed: 1" in text and "Warnings: 1" in text
    assert "0.03s" in text                       # 29ms -> 0.03s
    assert [b.callback_data for row in kb.inline_keyboard for b in row] == [
        "dev:st:run", "dev:menu"]
