"""Quick Release Suite: Tasks + Reminders + Dashboard."""
from core.regression.models import (
    Priority, RegressionTest, ScenarioClass, Suite,
)
from core.regression.registry import register

_QUICK = frozenset({Suite.QUICK})


def _t(**kw):
    register(RegressionTest(**kw))


# ── Tasks ─────────────────────────────────────────────────────────────────
_t(
    test_id="TASK-001", category="Tasks", feature="Task creation",
    introduced_version="v1.0", priority=Priority.CRITICAL,
    scenario=ScenarioClass.NORMAL, estimated_seconds=40, suites=_QUICK,
    objective="Create a simple task from natural language, with confirmation.",
    preconditions="Idle state; AI reachable.",
    steps=("Send: Remind me to call mom tomorrow at 5pm",
           "Tap ✅ Yes, save it!"),
    expected=("Confirmation card with title 'Call mom', tomorrow, 17:00",
              "After confirm, exactly one task is created",
              "Task appears in /today or /list"),
    failure_conditions=("No confirmation step", "Wrong date/time", "Duplicate task"),
)

_t(
    test_id="TASK-002", category="Tasks", feature="Task completion",
    introduced_version="v1.0", priority=Priority.CRITICAL,
    scenario=ScenarioClass.NORMAL, estimated_seconds=25, suites=_QUICK,
    objective="Complete a task by id.",
    preconditions="At least one open task exists (note its id).",
    steps=("Send: done <id>",),
    expected=("A 'Done!' confirmation", "Task no longer in /list"),
    failure_conditions=("Task still open", "Wrong task completed", "Error"),
)

_t(
    test_id="TASK-003", category="Tasks", feature="Task deletion",
    introduced_version="v1.0", priority=Priority.CRITICAL,
    scenario=ScenarioClass.NORMAL, estimated_seconds=25, suites=_QUICK,
    objective="Delete a task by id.",
    preconditions="At least one task exists (note its id).",
    steps=("Send: delete <id>",),
    expected=("A deletion confirmation", "Task removed from /list"),
    failure_conditions=("Task still present", "Wrong task deleted"),
)

_t(
    test_id="TASK-004", category="Tasks", feature="Recurring task (habit)",
    introduced_version="v3.0", priority=Priority.CRITICAL,
    scenario=ScenarioClass.NORMAL, estimated_seconds=40, suites=_QUICK,
    objective="A recurring phrase creates a HABIT, not a goal/one-time task.",
    preconditions="Idle state; AI reachable.",
    steps=("Send: Go to gym every day at 6 AM", "Tap ✅ Yes, save it!"),
    expected=("Classified HABIT daily 06:00 (NOT GOAL/TASK)",
              "Appears in /habits with streak 0", "No duplicate"),
    failure_conditions=("Classified GOAL or one-time TASK", "Not in /habits"),
    related_bugs=("BUG-002",),
    notes="A FAIL here is often AI degradation (fallback model), not code.",
)

_t(
    test_id="TASK-005", category="Tasks", feature="Invalid time handling",
    introduced_version="v3.0", priority=Priority.HIGH,
    scenario=ScenarioClass.INVALID, estimated_seconds=25, suites=_QUICK,
    objective="An impossible time is rejected, not silently saved.",
    preconditions="Idle state.",
    steps=("Send: Create task tomorrow at 25 PM",),
    expected=("An invalid-time warning OR a re-prompt for a valid time",
              "No task saved with a bogus time"),
    failure_conditions=("Task saved with an invalid/garbage time", "Crash"),
)

# ── Reminders ─────────────────────────────────────────────────────────────
_t(
    test_id="REM-001", category="Reminders", feature="Reminder fires + buttons",
    introduced_version="v2.0", priority=Priority.CRITICAL,
    scenario=ScenarioClass.NORMAL, estimated_seconds=120, suites=_QUICK,
    objective="A due reminder is delivered with action buttons; Done works.",
    preconditions="Create a task due in ~1-2 minutes.",
    steps=("Wait for the reminder ping", "Tap ✅ Done"),
    expected=("Ping arrives at/after due time with buttons "
              "(Done/10m/1h/Tomorrow/Stop/Delete)",
              "Tapping Done completes the task"),
    failure_conditions=("No ping", "Missing buttons", "Done does nothing"),
)

_t(
    test_id="REM-002", category="Reminders", feature="Snooze",
    introduced_version="v1.1", priority=Priority.HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=90, suites=_QUICK,
    objective="Snooze from a reminder reschedules it.",
    preconditions="A reminder ping is showing.",
    steps=("Tap ⏰ 10m",),
    expected=("Confirmation that it's snoozed", "The task re-fires later, not now"),
    failure_conditions=("No snooze", "Fires immediately again", "Task lost"),
)

_t(
    test_id="REM-003", category="Reminders", feature="Quiet hours",
    introduced_version="v2.0", priority=Priority.HIGH,
    scenario=ScenarioClass.BOUNDARY, estimated_seconds=60, suites=_QUICK,
    objective="No proactive pings fire inside the quiet-hours window.",
    preconditions="Set quiet hours to cover 'now'; a task due now.",
    steps=("Observe during the quiet window",),
    expected=("No reminder ping is delivered during quiet hours",
              "It resumes after the window"),
    failure_conditions=("A ping is delivered inside quiet hours"),
)

# ── Dashboard ─────────────────────────────────────────────────────────────
_t(
    test_id="DASH-001", category="Dashboard", feature="Dashboard open",
    introduced_version="v9.0", priority=Priority.HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=20, suites=_QUICK,
    objective="The dashboard renders with a status summary and nav buttons.",
    preconditions="Some tasks/habits exist.",
    steps=("Send /dashboard or tap 🏠 Dashboard",),
    expected=("Header + status/productivity cards render as HTML",
              "Nav buttons present (Today/Goals/Habits/Tasks/Statistics/Refresh)"),
    failure_conditions=("Raw HTML", "No buttons", "Error"),
)

_t(
    test_id="DASH-002", category="Dashboard", feature="Dashboard navigation",
    introduced_version="v9.0", priority=Priority.HIGH,
    scenario=ScenarioClass.MULTI_STEP, estimated_seconds=40, suites=_QUICK,
    objective="Dashboard buttons navigate by editing the same message.",
    preconditions="Dashboard open.",
    steps=("Tap 📅 Today", "Tap 🔄 Refresh / a back path"),
    expected=("The message is EDITED in place (no message spam)",
              "Each view renders correctly"),
    failure_conditions=("New message per tap", "A button dead-ends", "Error"),
    notes="Known dead-ends (models/perf/errors views) are documented, not a new fail.",
)

_t(
    test_id="DASH-003", category="Dashboard", feature="Goal progress ±",
    introduced_version="v9.0", priority=Priority.MEDIUM,
    scenario=ScenarioClass.NORMAL, estimated_seconds=30, suites=_QUICK,
    objective="Inline ➕/➖ adjust a goal's progress in place.",
    preconditions="At least one goal exists.",
    steps=("Open goals", "Tap ➕ on a goal, then ➖"),
    expected=("Progress bar updates in the edited message",
              "Value clamps at 0–100%"),
    failure_conditions=("No update", "Value exceeds 100% / goes negative"),
)


_t(
    test_id="TASK-006", category="Tasks", feature="Task editing",
    introduced_version="v14.4", priority=Priority.HIGH,
    scenario=ScenarioClass.MULTI_STEP, estimated_seconds=40, suites=_QUICK,
    objective="Edit an existing task's time via natural language.",
    preconditions="A task with a time exists (note its id).",
    steps=("Send: edit <id>", "Send: set time to 7pm"),
    expected=("The task's time becomes 19:00",
              "A confirmation of the change is shown"),
    failure_conditions=("Time unchanged", "Wrong task edited", "New task created"),
)

_t(
    test_id="TASK-007", category="Tasks", feature="Multi-task extraction",
    introduced_version="v3.0", priority=Priority.HIGH,
    scenario=ScenarioClass.MULTI_STEP, estimated_seconds=45, suites=_QUICK,
    objective="A message with two tasks creates both.",
    preconditions="Idle state; AI reachable.",
    steps=("Send: Tomorrow buy groceries and call mom", "Confirm"),
    expected=("Both 'Buy groceries' and 'Call mom' are proposed",
              "After confirm, two separate tasks are created for tomorrow"),
    failure_conditions=("Only one task created", "Both merged into one title"),
    notes="Under AI degradation the fallback model may mis-split — a FAIL here "
          "is often provider-related, not a code regression.",
)

_t(
    test_id="REM-004", category="Reminders", feature="Postpone to tomorrow",
    introduced_version="v1.1", priority=Priority.HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=90, suites=_QUICK,
    objective="The Tomorrow button on a reminder postpones it to the next day.",
    preconditions="A reminder ping is showing.",
    steps=("Tap 📅 Tomorrow",),
    expected=("Confirmation that it's moved to tomorrow",
              "The task's date advances by one day; it does not fire again today"),
    failure_conditions=("Date unchanged", "Fires again today", "Task lost"),
)
