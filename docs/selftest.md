# BAKA Self-Test Framework (`core/selftest/`)

*Added v14.22. Admin-only runtime regression runner.*

## What it is (and is not)

A **registration-based runner that verifies BAKA's major features work
in a live process** — real database, real scheduler, real engines, real
AI provider — and reports a PASS/WARNING/FAIL/SKIPPED result per test
plus a summary. It answers *"is the running bot healthy after this
update?"* in a few seconds, from inside Telegram, without a manual
click-through.

It is **not** a replacement for the offline `pytest` suite:

| | offline `pytest` suite | `core/selftest` framework |
|---|---|---|
| Runs | in CI / dev shell | in the live bot, on demand |
| Proves | logic in isolation (mocked/temp DB) | the real wiring end-to-end |
| Audience | developers | admins (owner) |
| Trigger | `pytest` | Debug Menu → 🧪 Self Test |

Both matter; they check different things.

## How an admin runs it

`/debug` (owner only) → **🧪 Self Test** → **▶ Run All Tests**. The
screen shows each test's result, then a summary (passed / failed /
warnings / skipped / duration). Non-admins can't see or reach any of it
(silent "Unknown command", same gate as every admin command).

## Architecture

```
core/selftest/
    models.py     Status enum · SelfTestResult · signal exceptions · SELFTEST_USER_ID
    registry.py   @selftest decorator · dedup-by-name · categories()
    runner.py     discover() · run(categories=, exclude=) · per-test containment + timing
    results.py    SelfTestReport (counts, duration, worst-outcome)
    tests/        one module per feature area; each registers check functions
```

- **Runner** (`runner.run()`): auto-discovers `tests/` modules (their
  `@selftest` decorators register), runs them sequentially in
  registration order, times each, catches every exception so one
  failure never stops the run, and aggregates into a `SelfTestReport`.
  It's synchronous; the Debug Menu calls it via `run_blocking(...)` so
  blocking I/O (the AI probe) stays off the event loop.
- **Result contract** (`models.py`): every test resolves to one
  `SelfTestResult(name, category, status, duration_ms, message, details)`.
  `Status` ∈ PASS / SKIPPED / WARNING / FAIL.
- **UI** (`ui.py` builders + `main.py`'s `dev:*` callback branch): pure
  presentation over the report; the admin gate lives in the handler.

## Adding a new test

Drop a module in `core/selftest/tests/` — **no central edit**:

```python
# core/selftest/tests/test_reminders.py
from core.selftest.registry import selftest
from core.selftest.models import SelfTestFail, SELFTEST_USER_ID

@selftest(name="Reminder Scheduling", category="Reminders")
def check_reminder_scheduling():
    import scheduler                       # lazy import (keep discovery cheap)
    due = scheduler.get_due_tasks()
    if due is None:
        raise SelfTestFail("scheduler returned None")
    return f"scheduler ok · {len(due)} due"  # optional PASS message
```

The runner discovers and runs it automatically; the category appears on
the Self-Test screen. Signalling a non-PASS outcome:

- **PASS** — return normally (optionally a one-line message string).
- **WARNING** — `raise SelfTestWarning("degraded but working")`.
- **FAIL** — `raise SelfTestFail("reason", details="longer text")`.
- **SKIPPED** — `raise SelfTestSkip("not applicable here")`.
- Any other exception → FAIL, with the traceback captured in `details`.

## Best practices

1. **Production-safe.** Prefer read-only checks. If you must write, use
   `SELFTEST_USER_ID` (a synthetic id outside Telegram's range) and
   **clean up in a `finally`** — the integration test asserts zero
   leftover rows under that id.
2. **Lazy imports.** Import heavy deps (`database`, `baka_brain`, `ui`)
   *inside* the check function, not at module top, so discovery stays
   cheap and import-safe.
3. **Fast + decisive.** A self-test should take well under a second
   (the AI probe is the one exception — a bounded network call).
4. **One concern per test.** Small, named, categorized.
5. **Network only where unavoidable.** The offline `pytest` integration
   run excludes the `AI` category; if you add another network-bound
   check, give it a category the suite can exclude too.

## Extension points

- **New categories** appear automatically from `category=`.
- **Per-test live streaming** (edit the message as each test finishes)
  is a future enhancement — today the run executes then shows the full
  result set.
- **The `dev:*` namespace** can host the rest of UI_SPEC §10's Developer
  Center (logs, engine, feature-flag panels) beside 🧪 Self Test.
