"""Quick Release Suite: Memory + Settings."""
from core.regression.models import (
    Priority, RegressionTest, ScenarioClass, Suite,
)
from core.regression.registry import register

_QUICK = frozenset({Suite.QUICK})


def _t(**kw):
    register(RegressionTest(**kw))


# ── Memory ────────────────────────────────────────────────────────────────
_t(
    test_id="MEM-001", category="Memory", feature="Memory save/get",
    introduced_version="v3.0", priority=Priority.HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=40, suites=_QUICK,
    objective="A stored fact can be retrieved.",
    preconditions="Idle state; AI reachable.",
    steps=("Send: Remember my exam is on June 20", "Send: When is my exam?"),
    expected=("First stores the fact", "Second returns 'June 20'"),
    failure_conditions=("Not stored", "Retrieval returns nothing/wrong value"),
)

_t(
    test_id="MEM-002", category="Memory", feature="Memory overwrite",
    introduced_version="v3.0", priority=Priority.HIGH,
    scenario=ScenarioClass.BOUNDARY, estimated_seconds=40, suites=_QUICK,
    objective="Updating the same fact overwrites it (no duplicate).",
    preconditions="Idle state.",
    steps=("Send: Remember my favorite color is blue",
           "Send: Remember my favorite color is red",
           "Send: memory"),
    expected=("The stored favourite colour is 'red'",
              "There is ONE favourite-colour memory, not two"),
    failure_conditions=("Both blue and red persist under different keys"),
    related_bugs=("BUG-007",),
    notes="Known bug: the AI may vary the key ('favorite color' vs "
          "'favorite_color'), keeping both. Guards the regression.",
)

_t(
    test_id="MEM-003", category="Memory", feature="Forget memory",
    introduced_version="v3.0", priority=Priority.MEDIUM,
    scenario=ScenarioClass.NORMAL, estimated_seconds=30, suites=_QUICK,
    objective="A stored fact can be deleted.",
    preconditions="A memory exists (e.g. exam).",
    steps=("Send: forget exam", "Send: When is my exam?"),
    expected=("Deletion acknowledged", "Retrieval now finds nothing"),
    failure_conditions=("Still retrievable after forget"),
)

# ── Settings ──────────────────────────────────────────────────────────────
_t(
    test_id="SET-001", category="Settings", feature="View settings",
    introduced_version="v2.0", priority=Priority.MEDIUM,
    scenario=ScenarioClass.NORMAL, estimated_seconds=20, suites=_QUICK,
    objective="Settings render with current preferences.",
    preconditions="Bot running.",
    steps=("Send /settings",),
    expected=("Quiet hours, reminder interval, and max-reminders shown as HTML"),
    failure_conditions=("Raw HTML", "Missing fields", "Error"),
)

_t(
    test_id="SET-002", category="Settings", feature="Change quiet hours",
    introduced_version="v2.0", priority=Priority.MEDIUM,
    scenario=ScenarioClass.NORMAL, estimated_seconds=30, suites=_QUICK,
    objective="Quiet hours can be changed and are reflected back.",
    preconditions="Bot running.",
    steps=("Send: quiethours 22:00 07:00", "Send /settings"),
    expected=("Change acknowledged", "/settings shows 22:00 — 07:00"),
    failure_conditions=("Not persisted", "Settings still show the old window"),
)


_t(
    test_id="SET-003", category="Settings", feature="Reminder interval",
    introduced_version="v2.0", priority=Priority.MEDIUM,
    scenario=ScenarioClass.NORMAL, estimated_seconds=30, suites=_QUICK,
    objective="The reminder repeat interval can be changed and reflected back.",
    preconditions="Bot running.",
    steps=("Send: interval 15", "Send /settings"),
    expected=("Change acknowledged (15 min)",
              "/settings shows the reminder interval as 15 min"),
    failure_conditions=("Not persisted", "Settings show the old interval",
                        "Accepts an out-of-range value silently"),
)
