# Testing

BAKA has no automated test suite (no `pytest`/`unittest` files found in the
repo). Testing is manual, driven by two overlapping resources that grew
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
