"""Quick Release Suite: Admin + Developer / Self-Test."""
from core.regression.models import (
    Priority, RegressionTest, ScenarioClass, Suite,
)
from core.regression.registry import register

_QUICK = frozenset({Suite.QUICK})


def _t(**kw):
    register(RegressionTest(**kw))


# ── Admin ─────────────────────────────────────────────────────────────────
_t(
    test_id="ADM-001", category="Admin", feature="/debug access control",
    introduced_version="v14.22", priority=Priority.CRITICAL,
    scenario=ScenarioClass.NORMAL, estimated_seconds=40, suites=_QUICK,
    objective="/debug (Developer Center) is admin-only; non-admins are denied.",
    preconditions="One admin account AND one non-admin account.",
    steps=("As admin: send /debug", "As non-admin: send /debug"),
    expected=("Admin: the Developer Center menu opens",
              "Non-admin: silent 'Unknown command' (no menu, no leak)"),
    failure_conditions=("Non-admin sees the menu or any dev feature",
                        "Admin cannot open it"),
    notes="Security-critical: the deny must reveal nothing about the feature.",
)

_t(
    test_id="ADM-002", category="Admin", feature="Admin control panel",
    introduced_version="v6.1", priority=Priority.HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=25, suites=_QUICK,
    objective="The admin panel loads with data stats.",
    preconditions="Admin account.",
    steps=("Send /admin",),
    expected=("Panel renders with task/habit/goal/memory counts",
              "Command list shown"),
    failure_conditions=("Error", "Missing stats", "Shown to a non-admin"),
)

_t(
    test_id="ADM-003", category="Admin", feature="Destructive reset guard",
    introduced_version="v6.1", priority=Priority.CRITICAL,
    scenario=ScenarioClass.RECOVERY, estimated_seconds=40, suites=_QUICK,
    objective="A destructive reset requires an explicit confirmation phrase.",
    preconditions="Admin account on a DISPOSABLE/test database only.",
    steps=("Send /resettasks", "Send anything OTHER than the exact confirm phrase"),
    expected=("A confirmation prompt requiring an exact phrase (e.g. YES RESET)",
              "A non-matching reply CANCELS — nothing is deleted"),
    failure_conditions=("Reset happens without confirmation",
                        "A wrong phrase still deletes"),
    notes="NEVER run against production data.",
)

# ── Developer / Self-Test ─────────────────────────────────────────────────
_t(
    test_id="DEV-001", category="Developer", feature="Self-Test framework",
    introduced_version="v14.22", priority=Priority.HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=30, suites=_QUICK,
    objective="Run All self-tests reports a health summary.",
    preconditions="Admin account.",
    steps=("Send /debug", "Tap 🧪 Self Test", "Tap ▶ Run All Tests"),
    expected=("Per-test results render (✅/⚠️/❌/⏭)",
              "A summary (passed/failed/warnings/skipped/duration) is shown",
              "Non-AI checks pass; the AI check may WARN if the provider is degraded"),
    failure_conditions=("Runner crashes", "A non-AI check FAILs unexpectedly",
                        "No summary"),
)

_t(
    test_id="DEV-002", category="Debug", feature="Bug reporting (DBG-ids)",
    introduced_version="v14.21", priority=Priority.MEDIUM,
    scenario=ScenarioClass.NORMAL, estimated_seconds=40, suites=_QUICK,
    objective="Reporting a bug creates a DBG-prefixed id independent of task ids.",
    preconditions="Admin account.",
    steps=("Send: report test issue from regression suite",
           "Send: bugs",
           "Send: resolve DBG-#### (the id just created)"),
    expected=("Report confirms with a DBG-#### id",
              "/bugs lists it with the DBG- prefix",
              "resolve accepts DBG-#### (and a bare number)"),
    failure_conditions=("Id looks like a task id", "resolve rejects DBG- form"),
)
