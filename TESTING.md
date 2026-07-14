# Testing

BAKA has two layers of testing: an automated `pytest` regression suite
(added in this project's first dedicated test-writing pass — see below)
covering deterministic, offline-testable logic, and manual Telegram-driven
testing via `/selftest` for everything that actually requires a live bot
(covered in the rest of this document).

## Automated test suite (`tests/`)

**312 tests, all offline** — no Telegram, no NVIDIA API, no network, and
every database test runs against an isolated temporary SQLite file (never
`planner.db`). Run with:

```bash
pip install -r requirements.txt   # includes pytest + pytest-asyncio
pytest                             # ~9 seconds, all 312 tests
```

| File | Tests | Covers |
|---|---|---|
| `tests/test_date_parser.py` | 111 | Every `date_parser.py` function: relative days, weekdays (including "next X" edge cases), month/day/ISO dates, leap years, year-boundary rollover, vague time phrases, Hindi/Hinglish time words, AM/PM, 24h/military time, ambiguous "X baje", recurrence detection, multi-task detection, priority/deadline inference, and `parse_all()`'s integration of all of the above |
| `tests/test_scheduler.py` | 40 | `is_quiet_hours()` (including the overnight-wraparound boundary logic), `should_remind_again()`, `get_escalated_interval()`, `get_due_tasks()`'s five internal cases (one-time/daily/weekly/monthly/snooze-expiry) including de-duplication and "must not re-fire after clearing snooze", `get_tasks_needing_followup()` (quiet-hours and max-reminders-cap respected), `auto_carry_forward()`, and deadline-buffer round-tripping |
| `tests/test_database.py` | 32 | `init_db()` idempotency and completeness (all 13 tables, all 10 indexes, WAL mode, schema version), `verify_schema_integrity()` correctly detecting a missing table/index, `_safe_add_column()`, `backup_database()` (no-op on fresh, fires on existing, prunes old backups), CRUD across tasks/habits/goals/memories/project materials & worklog, and the Sprint 1C reset-command fix (`/resettasks` excludes habits; a goal reusing a deleted goal's ID inherits zero old project data) |
| `tests/test_notification_service.py` | 16 | `TelegramSender`'s per-chat vs. overall rate-limit buckets (unrelated chats don't serialize against each other), pacing under a burst, `RetryAfter`/`TimedOut`/`NetworkError` retry behavior, retry exhaustion (raises, doesn't loop forever), unrelated exceptions passing through untouched, and `safe_edit_message_text()`/`safe_answer_callback_query()`'s failure-mode handling (not-modified, deleted message, already-answered callback) |
| `tests/test_async_bridge.py` | 12 | `run_blocking()` actually executes off the calling thread, a slow wrapped call doesn't block concurrent fast tasks (with a control-group test proving the unwrapped case *does* block), exception propagation (type preserved, one failure doesn't affect concurrent siblings), and nested synchronous calls within a wrapped function (the exact shape of `generate_video()` calling `generate_image()` internally) all running in the same worker thread |
| `tests/test_intent_engine.py` | 40 | `core/intent/`'s tiered classifier (v14.0 Stage 1): all 10 required categories (add/edit/delete reminder, greeting, help, small talk, random/unknown input, time query, schedule query), ambiguity scoring when tiers disagree, purity (same input → same output, never reads the system clock), entity extraction, and latency (100% coverage of `core/intent/`) |
| `tests/test_routing_layer.py` | 23 | `core/routing/`'s Routing Layer (v14.1B): `destination` is always `LEGACY` regardless of input, every `confidence.evaluate()` branch (AI-shaped intents, unknown, high-confidence-not-yet-offline, below-clarify-band, ambiguous middle band, ambiguity safety cap, the currently-unreachable `OFFLINE` branch via `monkeypatch`), `RoutingDecision` contract (trace ID uniqueness/validity, `clarification_required` derivation, purity), and an end-to-end test against the real `IntentEngine` (100% coverage of `core/routing/`) |
| `tests/test_storage_facade.py` | 18 | `core/storage/`'s Storage Facade (v14.1C): every `TaskStorage`/`HabitStorage`/`GoalStorage`/`ProjectStorage` method delegates to exactly the `database.py` function it wraps, verified by asserting the facade's return value equals calling `database.py` directly (not just "doesn't crash") — proves pure delegation, zero reshaping (100% coverage of `core/storage/`) |
| `tests/test_feature_flags.py` | 19 | `core/feature_flags.py`'s rollout flags (v14.1C): the `_flag()` helper across truthy/falsy env-var spellings, all four flags defaulting OFF when unset, and — via `importlib.reload()` — that the exported constants actually pick up an environment variable at import time, not just the helper function in isolation (100% coverage of `core/feature_flags.py`) |

**Found and fixed 3 real bugs in `date_parser.py` while writing tests**
(not scope creep — permitted and expected: writing a test against actual
behavior surfaces bugs a checklist-based manual pass had missed):
- "day after tomorrow" was parsed as tomorrow (its regex is a substring of
  the "tomorrow" pattern, checked first)
- "beete kal" (Hindi "yesterday") was also parsed as tomorrow, same
  root cause
- **every mention of "afternoon" was parsed as 12:00 (noon) instead of
  14:00** — "noon" is a literal substring of "afternoon" with no word
  boundary protecting against it

See `CHANGELOG.md`'s test-suite entry for the exact fixes.

### Remaining uncovered components

Deliberately not covered by the automated suite, and why:
- `main.py` — Telegram handlers; requires a live Telegram connection,
  explicitly out of scope for an offline suite. Covered by `/selftest`
  (manual) instead.
- `baka_brain.py` — requires the NVIDIA API; same reasoning.
- `preferences.py`, `ui.py`, `fmt.py`, `debug_system.py`,
  `log_sanitizer.py`, `instance_lock.py` — not covered yet. All are
  reasonably testable offline (most are pure functions or take an
  injectable DB path) and are good candidates for a future pass;
  `instance_lock.py` in particular already has proven test logic from its
  own Sprint 2B validation that was never ported into `tests/`.
- Full end-to-end command flows (e.g. "user sends a message → intent
  detected → task saved → confirmation sent") — this would need mocking
  the entire Telegram + AI + DB chain together; the individual pieces are
  covered, but integration-level testing was explicitly out of scope for
  this pass.

## Manual testing via `/selftest`

Testing is also driven by two overlapping resources that grew
independently — read the "two checklists" section below before using either.

## Quick start

1. Send `debug` (or `/debug`) to turn on verbose mode — every reply gets a
   debug box showing detected intent + extracted entities
2. Work through a section below
3. On any failure, send `report <what went wrong>` (or `/report ...`) —
   this auto-captures your last message, the detected intent, and context
4. After each section, send `bugs` (or `/bugs`) to review what got logged

## Two checklists — read this first

There are **two separate, independently-maintained test lists** that both
happen to use "Section" + letter naming, which collide:

1. **`TEST_CHECKLIST.md`** (this repo, root) — a hand-written manual testing
   guide, Sections A–R, ~189 tests. It predates v6.0+ features: there is
   nothing in it about the dashboard (v9.0), AI analytics (v11.1), multi-model
   AI (v11.0), or Projects (v12.0). Its own "Section P" is **Edge Cases &
   Error Handling** (15 tests).
2. **`debug_system.py`'s `SELFTEST_MESSAGES`** (in code, shown by the
   `/selftest` command) — 72 tests, Sections A–P, kept up to date through
   v12.0 (its "Section P" is 9 **Project Management** tests, added in
   v12.0). This is the more current of the two, since it's version-controlled
   alongside the features it tests.

**These are not the same Section P.** When someone says "run Section P,"
confirm whether they mean the checklist file or `/selftest`'s output.

**Recommendation:** treat `/selftest`'s output as the living source of
truth going forward (it's harder for it to silently drift from the code,
since a maintainer touching a feature is more likely to also be in
`debug_system.py`), and use `TEST_CHECKLIST.md` for its still-valid deep
coverage of parsing/reminder edge cases (Sections A–I, M–O, Q–R) that
`/selftest` covers more thinly. Whether to renumber one of the two to
remove the collision is tracked in [ROADMAP.md](ROADMAP.md).

## `TEST_CHECKLIST.md` section map

| Section | Covers | Tests |
|---|---|---|
| A | Debug system (`/debug`, `/report`, `/bugs`, `/resolve`, `/trace`, `/selftest`) | 8 |
| B | Basic task creation | 12 |
| C | Hindi & Hinglish | 12 |
| D | Date & time parsing | 15 |
| E | Vague time phrases | 10 |
| F | Recurring tasks | 8 |
| G | Reminders & inline buttons | 12 |
| H | Overdue & deadlines | 8 |
| I | Passive PA (quiet hours, escalation, batching) | 12 |
| J | Habits | 15 |
| K | Smart planning | 12 |
| L | Memory system | 10 |
| M | Slashless commands | 15 |
| N | Multiple tasks in one message | 5 |
| O | Edit & delete | 8 |
| P | Edge cases & error handling | 15 |
| Q | Stress tests | 10 |
| R | Regression tests (catches previously-fixed bugs) | 12 |

For the exact test messages and expected results, read `TEST_CHECKLIST.md`
directly — reproducing all 189 rows here would just create a third copy to
keep in sync.

**Speed-run:** `TEST_CHECKLIST.md` has a 20-test "Quick Validation" section
near the end for when you don't have time for the full pass.

## `/selftest` (debug_system.py `SELFTEST_MESSAGES`)

Run `selftest` (or `/selftest`) to get the current checklist directly from
the code. Its Section P covers the v12.0 project flow end-to-end (P1–P9):
creating a project goal, adding materials, marking them acquired, logging
worklog entries with auto-detected kind, viewing the project card, and the
shopping-list aggregation. Section Q (v13.2, Sprint 3) covers
infrastructure — unlike every other section, these are verified by
restarting the bot and checking `bot.log`/the filesystem rather than a
Telegram reply, since that's what's actually being tested:
- `bot.log` shows `✅ Schema integrity OK` with a schema version,
  `journal_mode=wal`, and a foreign-keys value — not a warning
- `bot.log` shows `Database journal mode: wal`
- a `backups/` directory exists with a `planner.db.startup_migration.
  <timestamp>.bak` file after a restart on an existing database
- no `Migration failed` or `Unexpected database error` lines in `bot.log`

## Database infrastructure validation (v13.2, Sprint 3)

Not part of `/selftest` (nothing here is reachable via a Telegram
message) — validated instead with standalone scripts run against isolated
temporary databases, never the live `planner.db`, during development:
- `init_db()` is fully idempotent: running it twice on the same database
  (fresh, then again as if restarting) produces no errors and an unchanged
  `verify_schema_integrity()` report
- all 10 new indexes (see `ARCHITECTURE.md`) are actually created and
  present in `sqlite_master`
- `backup_database()` correctly no-ops on a fresh/empty database and
  correctly produces a backup file on an existing one
- ordinary CRUD across every major entity (tasks, habits, goals, memories,
  project materials, preferences) behaves identically to before — no
  command-visible regression
- the Sprint 1C reset-command fix (`/resettasks` excludes habits) still
  holds after Sprint 3's `init_db()` changes
- indexes measured on a synthetic 20,000-row dataset (the real
  `planner.db` is too small today for an index to show a measurable
  difference) — see `CHANGELOG.md`'s v13.2 entry for the numbers

## Regression-testing a change

Minimum bar before considering a change done:
1. The relevant `/selftest` section for the feature you touched
2. `TEST_CHECKLIST.md` Section R (regression tests) — these exist
   specifically because each one caught a real past bug
3. If you touched `date_parser.py` or the intent prompt in `baka_brain.py`,
   also run Sections C, D, and E of `TEST_CHECKLIST.md` — date/time parsing
   is the most bug-prone area in this codebase historically (see how many
   `CHANGELOG.md` entries are parser bugfixes)

## Known gaps in test coverage

- No automated tests — every pass above is manual, via live Telegram
  messages to a running bot instance
- No coverage for the AI analytics commands (`/usage`, `/performance`,
  `/errors`) actually returning correct data, only that they don't crash —
  which is moot right now since they're returning empty fallback data
  regardless (see [DEBUGGING.md](DEBUGGING.md#known-issues))
- No coverage for restart behavior of in-memory state
  (`conversation_state.py`, `debug_system.py`'s debug-mode/trace state) —
  see [ROADMAP.md](ROADMAP.md) fix-it list
