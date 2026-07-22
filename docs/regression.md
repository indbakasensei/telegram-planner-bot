# Manual Regression Test Specifications (`core/regression/`)

*Added v14.23 (QA Phase 1). Specification foundation only — no runner,
no UI yet. See [QA_SYSTEM_DESIGN.md](../QA_SYSTEM_DESIGN.md).*

## What this is

The authored **specifications** of BAKA's manual regression tests — the
human-performed behaviour checks that guarantee a release never breaks
existing behaviour. This is **Layer 3** of the three-layer QA system
(the other two: `pytest` for automated developer tests, `core/selftest`
for runtime health). Each layer is independent.

This package holds the *specs* and a *version-aware history store*. The
**runner** that a human drives (record PASS/FAIL/SKIP → auto-create a
bug) is a **later milestone**; the data model here is its foundation.

## The growing-forever model

Every user-visible feature **owns** its regression tests. The suite
grows with the project — it is never a fixed size that gets rewritten.
A feature adds tests by adding/extending a module under
`core/regression/suites/`; nothing central changes.

## Authoring a test

```python
# core/regression/suites/tasks_reminders.py  (extend, or add a new module)
from core.regression.models import Priority, RegressionTest, ScenarioClass, Suite
from core.regression.registry import register

register(RegressionTest(
    test_id="TASK-006",                 # <CAT>-###, unique
    category="Tasks",                   # must be in categories.CATEGORIES
    feature="Task editing",
    introduced_version="v14.4",
    priority=Priority.HIGH,
    scenario=ScenarioClass.NORMAL,      # Normal/Boundary/Invalid/Recovery/...
    estimated_seconds=40,
    objective="Edit a task's time via natural language.",
    preconditions="A task with a time exists.",
    steps=("Send: edit <id>", "Send: set time to 7pm"),
    expected=("The task's time becomes 19:00", "Confirmation shown"),
    failure_conditions=("Time unchanged", "Wrong task edited"),
    related_bugs=(),                     # DBG-#### links, optional
    notes="",
    suites=frozenset({Suite.QUICK}),     # QUICK ⊆ MAJOR ⊆ FULL
))
```

`register()` validates the spec (id format, known category, non-empty
steps/expected, at least one suite) and dedups by id — a malformed test
fails loudly at authoring time. `core.regression.discover()` imports the
suite modules so specs register.

### Suite membership (QUICK ⊆ MAJOR ⊆ FULL)

Tag `suites=` with the smallest suite a test belongs to; larger suites
include it automatically. A `QUICK` test runs in Quick, Major, and Full;
a `FULL`-only test runs only in the Full regression. Query with
`regression.by_suite(Suite.QUICK)`.

## Version-aware history

Specs are static; **execution history accumulates** in
`regression_history.json` (gitignored, safe to delete) via `store.py`.
Per test id it tracks last-executed / last-passed version, pass / fail /
skip counts, and linked bug ids. A test that passed for many versions
and now fails is the regression signal. `store.record(test_id, status,
version, linked_bugs)` is the single mutation the future runner calls.

## Release suites (current targets)

| Suite | ~Size | When | Time |
|---|---|---|---|
| **Quick** | **44 (complete, v14.24)** | every release — mandatory gate | ~29 min |
| **Major** | ~130 (not yet authored) | minor/feature releases | ~2.5 hr |
| **Full** | ~315 (estimate) | major releases / pre-launch | ~1 day |

The Quick Release Suite is the **mandatory release gate**: no version
ships until it passes. It covers every critical user workflow across 15
categories (see QA_SYSTEM_DESIGN.md).

Sizes are estimates, not caps — the suite grows with features.

## Running the suite in Telegram (v14.25)

Admins run the Quick Suite manually from **`/debug` → 🧯 Run Tests**. It
walks the suite one test at a time, showing each test's objective,
steps, and expected result with **✅ Pass / ❌ Fail / ⏭ Skip** buttons.
On **Fail** it asks for a short note and logs a bug (a `DBG-####` id via
`debug_system`), then continues. At the end it shows a summary
(passed / failed / skipped + the bug ids created). This is the manual
release gate — no automated runner or history tracking (deliberately
simple; a future feature just adds more specs to the same list).

## Definition of Done

A user-visible feature is not complete until its regression spec(s)
exist here — one clause of BAKA's [Definition of Done](../CLAUDE.md).

## What's next (not in this milestone)

Major/Full suite authoring → the Regression Runner (human-driven,
PASS/FAIL/SKIP → auto-bug via `debug_system` DBG-ids) → the 🧯
Regression Tests and 🐞 Bugs Developer Center screens → Test History &
Statistics. All build on this foundation.
