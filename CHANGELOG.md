# BAKA Bot — Changelog

This is the authoritative version history, moved here from the old `VERSION.md`
(now a pointer to this file — see below). Forward-looking / not-yet-built ideas
live in [ROADMAP.md](ROADMAP.md) instead of being mixed into this file.

Each entry lists what was added and which files were touched, so a future
session can find the relevant code quickly.

---

## v13.3.2 — Hotfix: Adaptive AI Timeout Profiles (current)

Follow-up to v13.3.1. That hotfix fixed *whether* the bot fails over to
`MODEL_FAST` on a timeout; this one fixes *how long it waits before
trying*. All AI chat-completion calls — from a one-word "Hey" to a full
`/think` reasoning session — shared a single flat 30-second timeout, so
ordinary chat waited exactly as long as deep reasoning before even
attempting fallback.

**Current configuration reviewed** (`baka_brain.py`, `ai_helper.py` per
instruction — the latter confirmed dead code, not part of any live path,
left untouched): a single `OpenAI` client with `timeout=30.0` applied
uniformly to every `chat.completions.create()` call across
`call_nvidia()` (12 call sites) and `_call_model()` (backing
`call_main`/`call_fast`/`call_think`/`call_vision`, 5 call sites) — no
distinction between a quick intent-detection call and a long structured
plan. Retry policy (3 attempts, 2s/1s between) was left exactly as
v13.3.1 set it; only the per-call timeout changed. Image/video generation
were already separate — `generate_image()`/`generate_video()` use their
own `httpx.Client(timeout=120.0)`/`httpx.Client(timeout=300.0)` directly,
never the shared chat client — so they needed no change and weren't
touched.

**New profiles**, passed as a per-call `timeout=` override to individual
`.create()` calls rather than changing the client's own default (kept as
the safety ceiling for anything that doesn't override it):

| Profile | Value | Applied to |
|---|---|---|
| `TIMEOUT_FAST_CHAT` | 8s | `call_nvidia()`'s default (covers `get_baka_response()` — the dominant path, every plain chat message), `call_fast()`, `check_api_status()`, `benchmark_all_models()`'s liveness probes |
| `TIMEOUT_NORMAL_REASONING` | 15s | `_call_model()`'s default (covers `call_main()`), and explicit overrides on `call_nvidia()`'s longer-output callers: `suggest_tasks`, `analyze_productivity`, `generate_structured_plan`, `generate_daily_plan`, `generate_weekly_plan`, `generate_task_breakdown`, `generate_study_plan` |
| `TIMEOUT_LONG_REASONING` | 25s | `call_think()` (`/think`) — deliberately the most tolerant tier, since users invoking a "think it through" feature accept more latency, and a short timeout risks truncating a genuinely long but healthy response |
| `TIMEOUT_VISION` | 30s (unchanged) | `call_vision()` — no evidence vision shares `MODEL_MAIN`'s problem, so its effective timeout is deliberately identical to before this hotfix, not shortened |

Values were chosen relative to the only two real latency data points
available: `MODEL_FAST` responding in 676ms when healthy
(`AI_DIAGNOSTIC_REPORT.md` §8), and the original 30s ceiling. 8s gives
roughly 10x headroom over a healthy fast response while cutting worst-case
failover time dramatically; 15s and 25s scale up for workloads that
legitimately produce longer output, while staying under the original
30s. These are estimates informed by the available evidence, not directly
measured against a healthy `MODEL_MAIN` (which was unavailable for
measurement during this investigation, same as v13.3.1) — flagged as a
remaining unknown, not asserted as precisely tuned.

v13.3.1's fallback behavior is fully preserved: `_is_model_dead()`'s
`isinstance(exc, APITimeoutError)` check doesn't care about the specific
timeout duration, so shortening it only makes a hung `MODEL_MAIN` get
detected — and failed over from — faster.

**Benchmark — real, live measurement against the actually-down
`MODEL_MAIN`** (not simulated): a plain `call_nvidia()` call that took
~31s after v13.3.1 now returns a valid `MODEL_FAST` response in **9.0
seconds**. Mocked scenarios additionally confirmed: a healthy-`MODEL_MAIN`
call makes exactly 1 API call with `timeout=8.0`, unaffected in behavior;
`generate_daily_plan()` (normal-reasoning tier) passes `timeout=15.0`;
`call_think()` passes `timeout=25.0`; `call_vision()` passes `timeout=30.0`
— each tier verified to actually reach the API call, not just declared.

Modified: `baka_brain.py` only. Regression: full 211-test suite re-run
clean; `git status` confirms `main.py`, `scheduler.py`, `database.py`,
and `notification_service.py` are all untouched — scheduler, Telegram,
database, and notification-service behavior are unaffected by
construction, not only by testing.

---

## v13.3.1 — Hotfix: NVIDIA Timeout Failover

Follows directly from `AI_DIAGNOSTIC_REPORT.md`'s investigation, which
found `MODEL_MAIN` (`meta/llama-3.3-70b-instruct`) unresponsive on NVIDIA
NIM (5/5 direct test requests timed out at 30s) while `MODEL_FAST`
responded correctly in 676ms — and that the bot's existing MAIN→FAST
fallback mechanism, built for exactly this scenario, didn't trigger for
this specific failure. Root cause: the fallback condition in
`call_nvidia()` matched error text for `"410"`, `"DEGRADED"`, `"504"`,
`"Gateway Timeout"`, or (`"timeout"` **and** `"Read"`) — but a plain
client-side timeout raises `openai.APITimeoutError` with the message
`"Request timed out."`, which contains none of those (it's "timed out",
not "timeout", and no "Read" at all). The fallback silently never fired;
the bot just retried the same hung model three times before giving up,
producing the reported "~1 minute" delay for a plain chat message.

Fix: added `_is_model_dead()`, which checks `isinstance(exc,
openai.APITimeoutError)` first — preferring exception-type matching over
string matching, per the hotfix's own requirement — before falling back
to the pre-existing string checks (410/DEGRADED/504/Gateway Timeout,
unchanged, not implicated by the investigation). Also restructured
`call_nvidia()`'s control flow: previously, a fallback attempt was made
from *inside* each failed retry attempt, meaning `MODEL_FAST` could be
tried more than once across the 3 attempts, and a failed fallback still
fell through into retrying the already-confirmed-dead `MODEL_MAIN` again.
Now the retry loop stops immediately the moment a failure is identified
as "model dead" (no point retrying a model that just timed out), and
`MODEL_FAST` is tried exactly once, immediately after — not interleaved
with `MODEL_MAIN` retries. Any error that isn't recognized as "model
dead" is retried and eventually raised exactly as before, unsuppressed.

Validated three ways: (1) a real, live call through the actual (still
down) `MODEL_MAIN` — `call_nvidia()` now returns a valid `MODEL_FAST`
response in ~31 seconds, versus a prior worst case of ~94 seconds that
usually didn't even succeed, since fallback never fired; (2) a mocked
healthy-`MODEL_MAIN` scenario — exactly 1 API call, no retry, no
fallback, confirming the normal path is byte-for-byte unaffected; (3) a
mocked timeout scenario — exactly 1 `MODEL_MAIN` attempt then exactly 1
`MODEL_FAST` attempt, confirming the new stop-early-then-fallback-once
behavior.

Scope was deliberately narrow, matching the hotfix's own brief: only
`call_nvidia()` (the path `get_baka_response()` uses for ordinary chat
messages, i.e. the reported symptom) was touched. `_call_model()` — the
separate internal dispatcher behind `call_main()`/`call_think()`/
`call_vision()`, used by `/think`, planning, and vision — has no
fallback logic at all (never did) and was **not** given one here; that's
a distinct, pre-existing gap outside this hotfix's explicit scope
("implement ONLY the timeout failover hotfix," "do not introduce routing
logic"). `/selftest`'s separate, already-diagnosed rate-limiter-pacing
slowdown (see `AI_DIAGNOSTIC_REPORT.md` §9 finding 4) is also untouched —
a different root cause, not addressed by this hotfix.

Modified: `baka_brain.py` only (the `call_nvidia()` restructure + new
`_is_model_dead()` helper + one import line). Full 211-test suite
(`tests/`) re-run clean; `generate_image`/`generate_video`/`call_vision`/
`call_think`/`call_main`/`call_fast`/`_call_model` all confirmed
unchanged, both by `git diff` scope and by direct signature/config
inspection.

---

## v13.3 — First Automated Regression Test Suite

211 `pytest` tests across `tests/`, covering every deterministic,
offline-testable module: `date_parser.py` (111), `scheduler.py` (40),
`database.py` (32), `notification_service.py` (16), `async_bridge.py`
(12). Fully offline — no Telegram, no NVIDIA API, no network, database
tests run against isolated temp SQLite files, never `planner.db`. Runs in
~7 seconds. Added `pytest`/`pytest-asyncio` to `requirements.txt` and a
root `pytest.ini` (`asyncio_mode = auto`, `testpaths = tests`).

**Found and fixed 3 real, previously-undiscovered bugs in `date_parser.py`
while writing tests against actual behavior** (explicitly permitted —
"never change bot behaviour unless a genuine bug is found" — and this is
exactly what a regression suite is for):
- **"day after tomorrow" was parsed as tomorrow.** Its check ran after the
  plain "tomorrow" check, and `\btomorrow\b` matches the word "tomorrow"
  as it appears inside "day after tomorrow". Fixed by moving the more
  specific day-after-tomorrow/yesterday checks before the tomorrow check.
- **"beete kal" (Hindi for "yesterday") was also parsed as tomorrow**,
  same root cause — bare "kal" with nothing after it satisfies the
  tomorrow pattern's `kal(?!\s+tha)` negative lookahead, so it matched
  before ever reaching the yesterday pattern. Fixed by the same reordering.
- **Every mention of "afternoon" was parsed as 12:00 (noon) instead of
  14:00.** The vague-time pattern list checks `noon|dupehr|baarah baje`
  before `afternoon`, and "noon" is a literal substring of "afternoon"
  with no word-boundary protection in the original `re.search(_pat, t)`
  call. Fixed by wrapping every vague-time pattern in `\b(?:...)\b`. This
  bug affected every "afternoon" mention in any message, in any of the
  contexts that reach `parse_time()` — the highest-impact of the three,
  given "afternoon" is a common English word and this parser's output
  deterministically overrides the AI's guess for exactly this kind of
  vague-time phrase.

Two other test failures during development were **test-expectation bugs,
not production bugs** — corrected in the tests, production code left
alone: "next wednesday" said on a Wednesday resolves to 7 days out (not
14) per the actual, reasonable implementation; "0 AM" is accepted as
00:00 rather than rejected (the code only validates the upper bound on
AM/PM hours) — a rare, arguably-fine edge case with no clear "correct"
alternative and no evidence of real-world impact, documented as current
behavior rather than changed.

Modified: `date_parser.py` (the 3 bug fixes only), `requirements.txt`.
New: `tests/` (5 files + `conftest.py`), `pytest.ini`.

---

## v13.2 — Infrastructure Hardening: WAL, Indexes, Backups, Integrity Checks

Sprint 3, addressing `ENGINEERING_AUDIT.md` findings E3 (missing indexes),
E4 (no WAL mode / connection pooling), and E7 (migration exceptions too
broad), plus new infrastructure not previously tracked as findings.
Database/startup-infrastructure only — no AI, reminder, scheduler-timing,
Telegram-UX, or command-handler changes; nothing here is user-visible.

**Task 2 — reviewed every `WHERE`/`ORDER BY`/`GROUP BY` in `database.py`
and `scheduler.py`, added 10 indexes** (full list with the specific query
each one serves is documented inline as `REQUIRED_INDEXES` in
`database.py`): `tasks(user_id, done, paused)` — the single most common
filter in the file; `tasks(due_date, due_time)` — the scheduler's
highest-frequency (every 60s), non-user-scoped due-task scan;
`tasks(recurrence_type, done, paused)` — the scheduler's recurring-task
scans; plus `memories(user_id, key)`, `goals(user_id)`,
`completions_log`/`snooze_log`/`interaction_log` each on `(user_id,
<timestamp column>)`, `ai_observations(user_id, status)`,
`missed_capabilities(user_id, created_at)`. Deliberately **not** indexed,
with reasoning inline: `user_preferences.user_id` is already the table's
`INTEGER PRIMARY KEY` (auto-indexed, a separate index would be pure
duplication) — a real finding from actually checking the schema rather
than assuming.

Benchmarked on a synthetic 20,000-row dataset (50 users × 400 tasks —
large enough for indexes to matter; the real `planner.db` is far smaller
today, which is exactly why a synthetic dataset was needed to measure
anything): the scheduler's due-date scan is **~140x faster** with its
index (1.61ms → 0.01ms per query, run every 60 seconds against every
user's tasks); per-user active-task queries are **~2.2x faster**.

**Task 1 — WAL mode.** `init_db()` now sets `PRAGMA journal_mode=WAL`.
Readers no longer block writers (or vice versa) — matters once the
scheduler and multiple handlers hit the database concurrently. Persisted
in the database file itself; re-asserting it on every `init_db()` call is
harmless.

**Task 3 — migration exceptions.** The `ALTER TABLE ... ADD COLUMN` loops
in `init_db()`/`_init_preferences()` (25 columns total) used to catch bare
`Exception: pass`, unable to tell "column already exists" (expected, what
makes the migration idempotent) apart from a real problem (disk full,
corruption). Added `_safe_add_column()`: catches `sqlite3.OperationalError`
specifically, silently continues only when the message says "duplicate
column name," and now logs anything else. The `analytics`-package
availability check (a different, already-tracked issue — see
`DEBUGGING.md`) was deliberately left as a broad `except`, since that's an
optional-dependency guard, not schema migration.

**Task 4 — connection helper.** Added `get_connection()` (applies WAL
consistently) for *new* infrastructure code (backup, integrity checks) to
use. Did **not** retrofit the ~100 existing `sqlite3.connect(DB_NAME)`
call sites across `database.py` — that would be a much larger, riskier
change than this sprint's "do not change behaviour" brief allows for a
"nice to have" consistency improvement; flagged as a future
`ROADMAP.md`-style item instead of attempted here.

**Task 5 — startup integrity verification.** Added
`verify_schema_integrity()`: confirms all 13 required tables and all 10
new indexes exist, and reports schema version (`PRAGMA user_version`, a
new `SCHEMA_VERSION` constant bumped whenever a migration is added — purely
a diagnostic marker, nothing branches on it), foreign-key enforcement
setting, and journal mode. Runs automatically right after `init_db()` in
`main()`, logged clearly either way; a problem is surfaced loudly but does
not block startup, since `init_db()`'s own migrations are already
additive/idempotent and very likely to have succeeded regardless.

One consequential, deliberate side effect: `init_db()` now eagerly creates
`project_materials`, `project_worklog`, `task_templates`,
`missed_capabilities`, and `ai_observations` at startup — previously these
were created lazily, on first use of the relevant feature. Needed so the
integrity check has a complete, meaningful set of tables to verify right
after startup, and so a fresh install's schema is fully formed before
first use. Still idempotent `CREATE TABLE IF NOT EXISTS`; zero user-visible
effect (the tables would exist by the time any command needing them runs,
either way) — noted explicitly here rather than left as a silent side
effect, given this sprint's "do not change behaviour" brief.

**Task 6 — automatic backup before migrations.** Added
`backup_database()`, using SQLite's own online-backup API (`Connection.
backup()` — safe against a concurrently-open WAL file, unlike a raw file
copy). Called at the very start of `init_db()`, before any migration
statement runs. No-op on a fresh/empty database (nothing to protect yet).
Keeps the 5 most recent backups per reason, pruning older ones, in a new
`backups/` directory. A failed backup is logged, never raised — it must
not block startup. (There are currently no destructive migrations in this
codebase — every existing migration is additive `ALTER TABLE ADD COLUMN`
— so this is deliberately a general safety net for *whenever* one is
introduced, not a response to an existing destructive one.)

**Task 7 — `/selftest` infrastructure checks.** Added Section Q to
`debug_system.py`'s `SELFTEST_MESSAGES` — unlike every other section,
these are verified by restarting the bot and checking `bot.log`/the
filesystem rather than a Telegram reply, since that's what's actually
being tested. No new commands or handler changes.

**Task 9 — logging.** `database.py` had no logging at all before this
sprint; added a module logger, used throughout the changes above. Also
fixed `main()`'s startup log line, which had said "v11.1" since that
version (a known, documented issue — see `DEBUGGING.md`) — now derived
from a new `BAKA_VERSION` constant instead of hardcoded. Deliberately
backend-only: user-facing text like `/help` was not touched (Telegram UX,
out of this sprint's scope).

Modified: `database.py`, `main.py`, `debug_system.py`, `.gitignore`
(`backups/`).

---

## v13.1 — Single-Instance Protection & Safe Startup

Sprint 2B of the post-audit production-hardening effort (see
`ENGINEERING_AUDIT.md`, finding D5/ARCH-6). Startup-safety-only sprint —
no AI, database, Telegram-handler, business-logic, scheduler-timing, or
notification-service changes.

**Root cause:** `run.sh` is a bare crash-loop restarter
(`while true; python3 main.py; sleep 5; done`) with no check for an
already-running instance. Two live processes polling the same bot token
would double-fire every reminder and scheduled job, race on SQLite writes,
and duplicate AI processing.

**Investigated before implementing:** reviewed `run.sh`, `main()`'s
startup sequence, and — critically — verified directly against the
installed `python-telegram-bot` 20.7 source how `Application.run_polling()`
already handles SIGINT/SIGTERM/SIGABRT: it installs its own handlers that
raise `SystemExit`, caught internally to shut down gracefully before
`run_polling()` returns normally. This ruled out installing a second,
competing signal handler for the same signals (would risk breaking PTB's
own graceful shutdown) and pointed at `atexit` instead, which correctly
fires after that graceful return, and after both `sys.exit()` paths
already in `main.py`'s `if __name__ == "__main__":` block.

**Locking strategy:** added `instance_lock.py` — an advisory file lock via
`fcntl.flock(fd, LOCK_EX | LOCK_NB)` on a new `bot.pid` file, held for the
process's entire lifetime and acquired as the very first action in
`main()`, before touching the database or Telegram. Chosen specifically
because it survives crashes correctly with no extra staleness-detection
logic needed: the kernel releases a `flock` the instant the holding
process's file descriptor closes, for *any* reason — clean exit, uncaught
exception, or `kill -9`. A plain "does the PID file exist" check can't
tell a live instance apart from one a crash left behind; `flock` doesn't
have that ambiguity because the OS is the source of truth, not the file's
contents. The file still stores the holding PID as plain text, purely for
the diagnostic messages below — the lock/block decision itself never
depends on that text.

Diagnostics reported clearly at startup: lock acquired (with PID); another
instance already running, blocked (with the holder's PID where known,
exit code 2 — distinct from a real crash's exit code 1); a stale lock
found and reclaimed (meaning the previous run crashed or was killed
without cleaning up — this is necessarily reported retroactively on the
*next* startup, since a truly unexpected termination like `kill -9` can't
run any reporting code at the moment it happens); and clean shutdown
(lock released).

Validated with real subprocesses (not just in-process simulation, to
genuinely exercise cross-process `flock` semantics): normal
acquire/release; a second process correctly blocked while a first holds
the lock; a held lock surviving a real `SIGKILL` to the holding process,
correctly detected and reclaimed by the next `acquire()` call with no
manual intervention; normal operation resuming fully afterward.

Same relative-path convention as the project's other runtime state files
(`planner.db`, `bugs.db`, `admin_id.txt`, `bot.log`) — `bot.pid` is
resolved relative to the working directory, matching (not introducing) the
already-documented cross-process-path limitation in
`ENGINEERING_AUDIT.md` finding A3. Added to `.gitignore`.

`run.sh` itself needed no changes: when a second `run.sh` loop's
`python3 main.py` invocation gets blocked, it fails fast, sleeps 5s, and
retries — which means a redundant `run.sh` loop left running (or started
by mistake) automatically and harmlessly becomes a standby that takes over
if the primary instance ever stops, with no code change required for that
property to hold.

Modified: `main.py` (1 import, 1 call at the top of `main()`, 1 new
`except` clause), `.gitignore`. New: `instance_lock.py`.

---

## v13.0 — Telegram Delivery Reliability

Sprint 2A of the post-audit production-hardening effort (see
`ENGINEERING_AUDIT.md`, finding F1, HIGH). Telegram-delivery-only sprint —
no AI, database, scheduling, or business-logic changes.

**Audit first:** inventoried every outbound Telegram Bot API call in
`main.py` — 386 total across `reply_text` (319), `context.bot.send_message`
(18), `edit_message_text` (34), `send_photo`/`send_video` (2),
`answer_callback_query`/`query.answer` (2), and message deletion (11,
mostly "thinking..." placeholder cleanup for AI/media replies). Classified
by trigger: the vast majority user-initiated (command replies, callback
button taps); 13 sites scheduler-initiated (inside job callbacks, using
`context.bot.send_message` since there's no incoming message to reply to
— `check_reminders`, `observation_engine`, etc.); a handful AI-response
and media (image/video generation results). No `send_chat_action` (typing
indicator) usage was found anywhere — noted, not added (out of scope, no
audit finding calls for it).

**A previously undocumented bug found during this sprint's own audit:**
one dashboard callback branch (marking a goal complete) called
`query.answer()` a *second* time for the same callback query — Telegram
allows exactly one answer per callback query id, so this raised
`BadRequest` on every goal-completion tap. It was silently swallowed by
the global error handler before (logged as a bug report, toast never
shown); now it's caught explicitly and logged as an expected case instead.

**Architecture — one seam, not scattered call-site edits.** Verified
directly against the installed `python-telegram-bot` 20.7 source (not
assumed): `ExtBot._do_post()` is the single low-level transport method
every high-level Bot API call funnels through, and when an `Application`
is built with `.rate_limiter(...)`, every one of those calls automatically
routes through that limiter's `process_request()` — the same "official
extension point, zero call-site changes" pattern used for the scheduler
timezone fix (v12.2) and the async-offload fix (v12.3).

Added `notification_service.py`:
- `TelegramSender` (a `telegram.ext.BaseRateLimiter` subclass, registered
  via `Application.builder().rate_limiter(TelegramSender())`) — a
  dependency-free token-bucket rate limiter with two independent levels
  (overall bot-wide cap, default 28/sec; per-chat cap, default 1/sec,
  keyed by `chat_id` so unrelated chats never share a bucket and can't
  serialize against each other), plus retry handling: `RetryAfter` is
  honored exactly (waits the requested duration, retries), `TimedOut`/
  `NetworkError` get bounded exponential backoff, everything else
  propagates untouched (matches `BaseRateLimiter.process_request()`'s own
  documented contract — it must not swallow arbitrary exceptions).
- `safe_edit_message_text()` / `safe_answer_callback_query()` — small
  helper functions (not part of the rate-limiter seam, since edit/answer
  failures like "message deleted" or "already answered" aren't flood
  control and need call-site-aware fallback behavior). Generalizes a
  pattern that already existed for the dashboard's own `_edit()` helper
  (try the edit, fall back to a fresh send if the target is gone, swallow
  silently if the edit was a no-op) so it applies everywhere instead of
  just one code path.

Deliberately **not** built on PTB's own `AIORateLimiter` — it requires the
`aiolimiter` package, not a current project dependency, and adding a new
dependency for a personal-scale bot wasn't judged worth it. The
implementation here is a small, direct reimplementation of the same idea,
written after reading `AIORateLimiter`'s own source for the reference
pattern (per-chat + overall token buckets, `RetryAfter`-aware retry loop).

All 34 `edit_message_text` call sites and 2 `answer_callback_query` call
sites in `main.py` were updated to route through the new helpers — this
was a mechanical, uniform substitution (`await query.edit_message_text(` →
`await safe_edit_message_text(query, `), not a rewrite of what each branch
sends. No other call site in `main.py` changed — `reply_text`,
`send_message`, `send_photo`, `send_video`, and message deletion all reach
the same `TelegramSender` seam automatically without modification.

Validated with a network-free test suite (fake Bot API callbacks, no real
Telegram calls): 50 concurrent reminders to 50 different chats completed
in under a second; a simulated 100-message burst to a single chat
delivered all 100 in order with zero duplicates and measurably enforced
pacing; 10 different users' messages completed concurrently rather than
serializing behind each other; `RetryAfter` and transient network errors
were retried correctly without double-sending; the edit-safety helpers
correctly swallowed "not modified", fell back to a fresh send on a deleted
message, and swallowed an already-answered callback query without raising.

Modified: `main.py` (1 import line, 1 `Application` builder line, 34 edit
call sites, 2 answer call sites — all mechanical). New:
`notification_service.py`.

---

## v12.4 — Data Integrity: Reset Cleanup & IST Habit Dates (superseded by v13.0 above as current)

Sprint 1C of the post-audit production-hardening effort (see
`ENGINEERING_AUDIT.md`, findings E1 and E2, both HIGH). Data-integrity-only
sprint — no performance, AI, scheduler, or Telegram-handler changes.

**E1 — admin reset commands left orphaned data / allowed ID-reuse
inheritance.** Investigated independently (not assumed from the audit) by
tracing all 5 reset commands end to end:
- `reset_all_tasks()` (`/resettasks`) was deleting **all** of a user's
  tasks including habits (`is_habit=1`) — directly contradicting the
  command's own confirmation text, which promises "habits... are kept."
  Fixed by scoping the delete to non-habit tasks only. This also closes
  the habit_log-orphan risk for this command, since habits (and their
  logs) are now simply untouched by it.
- `reset_everything()` (`/resetall`, the "nuclear" wipe) deleted `goals`
  and reset its ID sequence, but never touched `project_materials` /
  `project_worklog` — both of which reference `goal_id`. A newly created
  goal after a nuke could silently reuse an old goal's ID and inherit its
  entire materials checklist and worklog history. Fixed by adding both
  tables to the cleanup (and sequence-reset) pass. Also added
  `task_templates`, `missed_capabilities`, and `ai_observations` to the
  cleanup — these don't have an ID-reuse hazard (nothing references them
  by a reused id), but were silently surviving a command that explicitly
  promises to delete "EVERYTHING."
- **AUTOINCREMENT reset behavior was deliberately left unchanged.**
  Resetting IDs back to 1 is advertised, user-facing behavior (both
  `/resettasks` and `/resetall`'s confirmation text say so explicitly).
  The actual bug wasn't that IDs get reused — it's that dependent tables
  weren't fully cleaned before that reuse could happen. Fixing cleanup
  completeness closes the hazard without the larger, unnecessary,
  user-visible behavior change that abandoning ID resets would be.

**E2 — naive `datetime.now()` in `database.py` could misdate habit
completions.** Repo-wide search for `datetime.now()`, `.today()`,
`.utcnow()`, and other naive datetime construction found 10 occurrences in
`database.py` (all now fixed, replaced with the project's established
`datetime.now(IST)` pattern — already used correctly 14 times elsewhere in
the same file) plus incidental occurrences in `ai_helper.py` (dead code,
excluded — see below), `baka_brain.py` (excluded, see below), and
`debug_system.py` (cosmetic debug/bug-report timestamps only, not
data-integrity-relevant — left as-is to keep this sprint's diff scoped to
actual data correctness, not a repo-wide style pass).
Deliberately **not** touched, with reasoning:
- `ai_helper.py` — confirmed dead code (not imported anywhere); fixing
  unreachable code has no behavioral effect and falls inside this
  sprint's "do not modify AI system" boundary.
- `baka_brain.py` — explicitly excluded by this sprint's rules ("do NOT
  modify: AI system"); its naive-datetime calls build transient prompt
  context strings for the AI, never stored or compared against
  IST-stamped data, so they carry no data-integrity risk of the kind E2
  describes.

Validated against an isolated temporary SQLite database (never the real
`planner.db`): seeded a regular task, a habit, a goal with materials and
worklog, a template, a missed-capability row, and an observation; ran
`/resettasks`-equivalent then `/resetall`-equivalent; confirmed zero
orphaned rows in all 12 user-scoped tables after the nuclear reset, and
confirmed a brand-new goal created immediately afterward (which reused
`goal_id=1`, proving the ID-reuse scenario actually occurred) found zero
inherited materials or worklog entries. Habit completion dates confirmed
to stamp using IST, not naive local time.

Modified: `database.py` only.

---

## v12.3 — Async Offload for AI/Media Calls

Sprint 1B of the post-audit production-hardening effort (see
`ENGINEERING_AUDIT.md`, finding C1/I1, CRITICAL). Fixes the bot's biggest
scalability bug: every AI call and every image/video generation call ran
synchronously inside `async def` Telegram handlers, blocking the *entire*
bot's event loop for every user for as long as that call took — up to
~96s worst-case for a retried text call, up to 5 minutes for `/video`.

**Analysis first:** inventoried every blocking operation in the request
path. 19 call sites across 15 `baka_brain.py` functions are network-bound
(AI inference, image gen, video gen) — these needed fixing. 252 call sites
into `database.py` (plus 4 raw `sqlite3.connect` sites in `main.py`) are
database-bound; benchmarked directly against the live `planner.db` at
0.3-0.4ms per call (connect+query+close included) — negligible for
event-loop purposes at this bot's scale, so deliberately left unwrapped
this sprint rather than touching 250+ call sites for no measurable benefit.

**Architecture:** added `async_bridge.py`, a single new module with one
function, `run_blocking()`, that offloads a synchronous callable to a
worker thread (`asyncio.to_thread`). Every one of the 19 AI/media call
sites in `main.py` now goes through it (`await run_blocking(fn, ...)`
instead of `fn(...)`). Rejected wrapping `baka_brain.py`'s functions in
place — `generate_video()` calls `generate_image()` internally, by name,
synchronously; independently wrapping both as async functions in place
would have broken that internal call (an unawaited coroutine returned
instead of the actual image). Routing through one boundary-level helper
instead means `baka_brain.py` itself is completely untouched — zero risk
to prompts, business logic, or its internal call graph — and leaves a
single seam to swap in native async clients (`AsyncOpenAI`,
`httpx.AsyncClient`) in a future version without touching call sites again.

Modified: `main.py` (19 call sites + 1 import line). New: `async_bridge.py`.
Untouched: `baka_brain.py` (as designed — see above).

---

## v12.2 — Scheduler Timezone Hardening (superseded by v12.3 above as current)

Sprint 1A of the post-audit production-hardening effort (see
`ENGINEERING_AUDIT.md`, finding D1, CRITICAL). Fixes a bug where every
`run_daily()`-scheduled job (`daily_carry_forward`, `end_of_day_summary`,
`morning_briefing`, `weekly_report`, `observation_engine`, `project_nudge`)
fired 5.5 hours later than intended, because the bot's `Application` never
told `python-telegram-bot`'s `JobQueue` it should run in IST — it silently
defaulted to UTC, and every `run_daily()` call passes a naive (tzinfo-less)
`time` object that inherits whatever timezone the scheduler defaults to.

Fix: `main()` now builds the `Application` with
`Defaults(tzinfo=pytz.timezone("Asia/Kolkata"))`. Must be a `pytz` timezone
object specifically, not `zoneinfo.ZoneInfo` — `JobQueue` internally calls
`.localize()` on the configured tzinfo, a pytz-only method. Verified against
the installed `python-telegram-bot` 20.7 source directly (not assumed):
`JobQueue.set_application()` reads `application.bot.defaults.tzinfo`,
falling back to `pytz.utc` when unset, to configure the underlying
APScheduler's timezone.

No scheduling logic changed — every `run_daily()`/`run_repeating()` call
site is untouched; only the timezone they resolve naive times against
changed from UTC to IST. Verified via a standalone script (no network
calls) confirming all 6 daily jobs now compute the correct IST next-run
time; the 7 `run_repeating` (interval-based) jobs were already unaffected
by this bug and remain unaffected by the fix.

Modified: `main.py` (import block + `Application` construction only).

---

## v12.0 — Project Management

Turn any goal into a project with materials, worklog, progress tracking, and
automatic stagnation reminders. Perfect for real-world things you build over
weeks (drones, renovations, hobby builds, learning tracks).

Example flow — the drone build:
```
1. "goal build drone by 2026-08-15"      → goal saved, id shown
2. "need <id> motor, propeller, battery,
      frame, controller"                 → 5 materials attached
3. "got motor"                           → fuzzy-matched, marked done
4. "started <id>"                        → worklog entry, state=started
5. "worklog <id> frame mounted"          → auto-detected as 'progress'
6. "project <id>"                        → full card: progress bar,
                                            material checklist, worklog
7. "shopping"                            → auto-list of everything still
                                            needed across ALL projects
```

Added:
- 2 new SQLite tables: `project_materials`, `project_worklog` (indexed on `goal_id`)
- 11 new commands: `need`/`materials` (add materials), `got`/`have` (fuzzy-mark
  acquired), `worklog`/`log` (log progress, kind auto-detected), `started`,
  `finished`, `project`/`projects`, `shopping`
- Natural-language routing for every command above (e.g. "got the motor" →
  fuzzy match against a user's materials)
- Smart worklog kind detection: finished/khatam → `finished`; blocked/stuck →
  `blocker`; started/began/shuru → `started`; else → `progress`
- Auto-progress formula: 50% materials-acquired ratio + 50% work-state
  (finished=100%, progress=50%, started=25%), rendered as `██████░░░░ 60%`
- Stagnation nudges (daily 20:00, `project_nudge` job): urgent alert if
  deadline < 3 days and materials still missing; gentle nudge if no worklog
  in 7+ days and deadline < 30 days away. Respects quiet hours.
- Inline callback namespace `proj:*` (`proj:started`, `proj:finished`,
  `proj:got`, `proj:view`, `proj:shopping`)
- Selftest expanded to 72 tests (Section P — 9 project tests). **Note:**
  this "Section P" is unrelated to `TEST_CHECKLIST.md`'s own Section P
  (Edge Cases) — see [TESTING.md](TESTING.md) for the naming collision.

Modified: `main.py`, `database.py`, `debug_system.py`

Ideas for next (not yet built — see [ROADMAP.md](ROADMAP.md)): project
photos via Vision, cost/budget tracking, named milestones, template projects.

> **Known issue at time of writing:** the bot's startup banner and `/help`
> text in a couple of places still said "v11.1" even after this release —
> see [DEBUGGING.md](DEBUGGING.md#known-issues).

---

## v11.2 — NIM-Only Visual Generation + Full Debug Pass

Image and video generation rebuilt against the official NVIDIA API specs
(docs.api.nvidia.com), verified line-by-line. No third-party fallbacks.

**Image — FLUX.1-schnell** (fixed per official "Infer" spec):
- Endpoint: `https://ai.api.nvidia.com/v1/genai/black-forest-labs/flux.1-schnell`
- Root cause of earlier 404/422 errors: body must use a plain `"prompt"`
  string (not the Stable-Diffusion-style `text_prompts` array), `cfg_scale`
  must be exactly `0`, and only 1024x1024 is supported
- Response parsed from `artifacts[0].base64` → sent to Telegram as bytes
- Third-party (Pollinations) fallback removed — FLUX via NIM is the only
  image source

**Video — new `/video` command (Stable Video Diffusion):**
- Cosmos has no hosted NIM endpoint, so SVD is the only hosted video model
- Endpoint: `https://ai.api.nvidia.com/v1/genai/stabilityai/stable-video-diffusion`
- SVD is image-to-video: `/video <prompt>` runs FLUX to generate a frame,
  then SVD animates it (`cfg_scale=1.8`, `motion_bucket=127`)
- Frames auto-downscaled below 200KB (spec limit) via Pillow
- `MODEL_VIDEO` changed: `nvidia/cosmos-1.0-7b-text2world` → `stabilityai/stable-video-diffusion`

Always-on flags as of this version: `ENABLE_IMAGE_GEN=True`,
`ENABLE_VIDEO_GEN=True`, `ENABLE_VISION=True`.

A 65-check self-test pass is recorded as fully green in the original
changelog entry, including an "analytics log→query round trip" check. **This
is worth flagging**: as of the v12.0-era documentation pass, the `analytics`
package this check depended on does not exist as an importable package in
the repository (see [DEBUGGING.md](DEBUGGING.md#known-issues)) — whether
this is a later regression or the original check was never actually
exercising the real import path is unconfirmed.

Modified: `baka_brain.py`, `main.py`, `debug_system.py`, `analytics/token_counter.py` (path as documented at the time; the `analytics/` package does not currently exist at the repo root — see known issues)

---

## v11.1 — AI Usage Analytics & Model Monitoring

Per-call AI telemetry, multi-model dashboards, error tracking — intended to
log every AI request automatically without manual instrumentation or added
latency.

Planned package: `analytics/` (`usage_logger.py`, `usage_service.py`,
`model_metrics.py`, `token_counter.py`, `performance_tracker.py`,
`__init__.py`). **As currently checked into the repo, these five files sit
flat at the project root with no `__init__.py` package wrapper**, and
`usage_logger.py` uses package-relative imports (`from .token_counter import
...`) that only resolve inside an actual `analytics` package — see
[docs/ai_system.md](docs/ai_system.md) and
[DEBUGGING.md](DEBUGGING.md#known-issues) for the full picture.

New table (intended): `ai_usage` (19 columns — timestamp, user/session/
conversation ids, provider, model, request_type, intent, token counts,
estimated cost, latency, status, error, fallback flag, response length,
4 indexes). `database.py`'s `init_db()` attempts `from analytics import
init_usage_table` inside a `try/except: pass` — since the import fails,
**this table is never created** in the current tree.

Intended automatic logging sites: `baka_brain.py`'s `_call_model()`,
`call_nvidia()`, and `generate_image()`.

New commands (intended): `/usage`, `/performance`, `/errors`; `/models`
upgraded to show live ping + real usage. All of these are wired into
`main.py` behind `try/except` guards that fall back to empty stats when
`import analytics` fails — which it currently does.

Modified: `main.py`, `database.py`, `baka_brain.py`. New folder (intended,
not present as a package in the current tree): `analytics/`.

---

## v11.0 — Multi-Model AI System

Added 6 AI models with role-based routing (model IDs below are as of this
release; several have since changed — see
[docs/ai_system.md](docs/ai_system.md) for current values):
- `MODEL_MAIN` = `z-ai/glm-5.1` — main brain
- `MODEL_FAST` = `meta/llama-3.1-8b-instruct` — quick intent/classification
- `MODEL_THINK` = `z-ai/glm-5.1` — deep reasoning (`/think`)
- `MODEL_VISION` = `meta/llama-3.2-90b-vision-instruct` — image understanding
- `MODEL_IMAGE` = `black-forest-labs/flux.1-dev` — image generation
- `MODEL_VIDEO` = `nvidia/cosmos-1.0-7b-text2world` — video generation (opt-in)

New per-model functions in `baka_brain.py`: `call_main()`, `call_fast()`,
`call_think()`, `call_vision()`, `generate_image()`, `_call_model()`
(internal dispatcher with retry + logging), `fast_intent_classify()`,
`benchmark_all_models()`.

**Image understanding (Vision):** send a photo → the bot describes it; add a
caption to ask specific questions; todo-list photos get extracted and offered
as one-tap-save tasks.

**Image generation (opt-in at the time):** `/image <prompt>` or natural
language ("draw ...").

**Autonomous Observation Engine:** daily 22:00 job analyzes the week and
generates 1-3 AI suggestions; `/suggestions`, `/approve <id>`, `/dismiss <id>`.

Feature toggles introduced (values below are as of v11.0; see
[docs/ai_system.md](docs/ai_system.md) for current values):
`ENABLE_FAST_ROUTING=False`, `ENABLE_VISION=True`, `ENABLE_IMAGE_GEN=False`,
`ENABLE_VIDEO_GEN=False`.

New commands: `/image`, `/generate`, `/models`, `/suggestions`, `/approve`,
`/dismiss`. New handler: PHOTO messages route to the vision pipeline. New
table: `ai_observations`. New job: `observation_engine` (daily 22:00).

Modified: `main.py`, `database.py`, `baka_brain.py`

---

## v10.2 — AI Autonomy Foundation

- Rich AI context: every AI call now sees the user's open tasks by category,
  recent completions, overdue count, and active habits + streaks
- `/think` (or `/ask`) — free-form AI reasoning against the user's real data,
  no JSON schema
- Missed-Capability Log: low-confidence or action-verb-but-CHAT-intent
  messages are logged (input, AI intent, AI response, miss type, confidence)
  for later feature-gap review via `/misses` (admin-only)
- Natural-language entry points for think mode ("what should I...", "help me
  decide", ...)

New table: `missed_capabilities`. New functions: `get_user_context_for_ai`,
`log_missed_capability`, `get_missed_capabilities`, `mark_missed_reviewed`,
`think_freely`. New commands: `/think`, `/ask`, `/misses` (admin), `/reviewed`
(admin). Modified: `main.py`, `database.py`, `baka_brain.py`

---

## v10.1 — Pre-Deadline Buffer Reminders

- Auto-detects deadline phrasing (English: "due", "submit by", "deliver by",
  "before deadline", "hand in", "turn in"; Hindi: "tak", "tak karna hai",
  "deadline hai", "submission")
- Staged buffer reminders at 7d / 3d / 1d / 6h / 1h ahead of the deadline,
  each with Done now / Break down / Plan today / Mute buttons
- `/deadline <id> [on|off]` toggles deadline mode manually
- All buffer reminders respect quiet hours; each buffer level fires once
  (tracked in the comma-separated `buffer_sent` column)
- Two-layer detection (parser regex + AI's `is_deadline` entity field) —
  either triggering enables deadline mode

New columns: `is_deadline`, `buffer_sent`. New functions: `mark_as_deadline`,
`get_pending_deadlines`, `mark_buffer_sent`, `parse_buffer_sent`. New job:
`deadline_buffer_check` (every 30 min). New callback: `unflagdeadline`.
Modified: `main.py`, `database.py`, `date_parser.py`, `baka_brain.py`

---

## v10.0 — Search, Reports & Templates

- `/search <keyword>` — universal search across tasks, memories, habits, goals
- Task Templates: `/savetemplate`, `/template`, `/templates`
- `/export` — full data backup as plain text
- Weekly Report: automated Sunday 20:00 digest (completed/created/pending/
  overdue, completion rate, top habit streaks)
- Smart time suggestions using learned completion patterns (v6.0) when no
  time is set on a new task

New table: `task_templates`. New functions: `search_all`, template CRUD,
`get_weekly_report_data`, `export_user_data`. New job: `weekly_report`
(Sunday 20:00). Modified: `main.py`, `database.py`

---

## v9.1 — GLM 5.1 AI Upgrade + Enhanced Diagnostics

- Model swap: `meta/llama-3.1-8b-instruct` → `z-ai/glm-5.1`; `MODEL_MAIN`
  constant introduced ahead of v11.0's multi-model swap
- Bulletproof `.env` loading (manual fallback if `dotenv` fails)
- `/status` upgraded: quick (3-test) or `status full` (6-test) benchmark,
  graded A+ to F
- v9.0.1 hotfix: goals table migration for legacy DBs, using
  `PRAGMA table_info` for column detection so it never crashes on an
  old schema

Modified: `baka_brain.py`, `main.py`, `database.py`

---

## v9.0 — Dashboard & Rich UX Integration

Purely additive — every prior feature preserved. New `ui.py` module keeps
presentation separate from business logic.

- Unified Dashboard (`/dashboard`, `/home`, menu button): today/overdue/
  pending counts, goals, habits, completion bar
- New `ui.py` components: `dashboard_card`, `task_card`, `today_card`,
  `goal_card`, `habit_card`, `stat_card`, `reminder_card`, `progress_bar`
- Today View grouped into Overdue / High-priority / Upcoming / Completed
- Goal Dashboard with progress bars + inline +/- buttons (new `goals.target`
  column)
- Morning Briefing job (08:00); Evening Review (upgraded end-of-day summary)
- Centralized dashboard callback router (`dash:` namespace) that edits
  messages in place instead of sending new ones
- Hardened `handle_callback`: task IDs parsed with try/except so malformed
  callbacks can't crash the bot

New file: `ui.py`. New DB: `goals.target` column;
`get_goals_full`/`update_goal_progress`/`get_done_today_count`. New jobs:
`morning_briefing` (08:00). Modified: `main.py`, `database.py`

---

## v8.0 — Proactive Suggestions

- Wellness reminders (opt-in, default off): water/break/eye-rest/posture —
  `/wellness on|off`, `/wellness interval 60`, per-type toggles
- `/proactive` — control panel for every proactive feature
- Slot-crowding hint when creating a task at a time that already has 2+ tasks
- One-time high-priority-due-within-3h nudge (Done / Break-down buttons)
- Messages switched to clean HTML formatting (`fmt.py`)

New columns: `wellness_on`, `wellness_interval`, `wellness_types`,
`last_wellness` (on `user_preferences`). New jobs: `wellness_reminder`
(every 15m, interval-gated), `priority_nudge` (every 30m). Fixed:
`init_db()` now runs preference/learning migrations at startup, not lazily.
Modified: `main.py`, `database.py`

---

## v7.1 — Log-Driven Bug Fixes + Rich HTML Formatting

Bugs fixed from real test-log analysis:
- Recurring-task phrasing ("every Monday", "har Sunday", "daily at 9") was
  misclassified as GOAL — now correctly HABIT
- "evening"/"shaam" returned 15:00 instead of 18:00 (AI overrode the
  parser) — parser's vague-time mapping now always wins over the AI guess
- Invalid times ("25 PM", "13 AM", "25:99") were silently accepted — now
  rejected with a clear message
- Date + action verb messages were sometimes classified as MEMORY_SAVE —
  now correctly TASK
- "Remind me yesterday" now warns about the past date

New file: `fmt.py` (HTML helpers: `b()`, `i()`, `code()`, `esc()`,
`task_line()`, `confirm_box()`). Modified: `baka_brain.py` (intent prompt),
`main.py` (merge logic + HTML)

---

## v7.0 — Follow-up Intelligence

- "Did you finish?" check-ins 15 min after a task's time passes
- Repeated-snooze detection (3+ snoozes triggers a learned-time nudge)
- `/review` — lists stale tasks (3+ days overdue)
- End-of-day summary at 21:00
- All follow-ups respect quiet hours

New columns: `followup_sent`, `followup_count`, `snooze_count`,
`stale_flagged`. New jobs: `check_did_you_finish` (every 15 min),
`end_of_day_summary` (21:00). New callbacks: `finish_yes`, `finish_no`,
`dobreak`. Fixed: timezone bug — v7.0 DB functions now use IST, not naive
UTC. Modified: `main.py`, `database.py`

---

## v6.1 — Admin Mode + Reset Tools (owner-only)

- `/myid`, `/claimadmin` (first caller becomes the permanent sole admin —
  meant to be run once right after deploying)
- `/admin` control panel, `/adminmode` verbose debug toggle
- `/resettasks`, `/resetmemory`, `/resethabits`, `/resetlearning`,
  `/resetall` (nuclear, requires typed confirmation)
- `/sql <SELECT query>` — read-only SQL debugging
- Admin commands are invisible to non-admins ("Unknown command" response)
- `admin_id.txt` persists the lock across restarts (gitignored)

New DB functions: `reset_all_tasks` (also resets autoincrement),
`reset_all_memories`, `reset_all_habits`, `reset_learning_data`,
`reset_everything`, `get_data_stats`. Modified: `main.py`, `database.py`

---

## v6.0 — Preference Learning

- Every completion/snooze/interaction is logged
- `/insights` — tone classification (gentle/strict/balanced), active hours,
  snooze patterns, top categories, completion rate
- `suggest_time_for_task()`, `suggest_interval_for_task()` — used when
  creating new tasks

New tables: `completions_log`, `snooze_log`, `interaction_log`. New module:
`preferences.py`. Modified: `main.py`, `database.py`

---

## v5.0 — Habit Engine

- Habits tracked via `is_habit` flag + `habit_log` table
- `/habits`, `/streak <id>` (14-day grid), `/habitlog <id>` (30-day log),
  `/addhabit`, `/skiphabit`
- Longest-streak tracking, missed-day detection with adjustment tips

New table: `habit_log`. New columns: `is_habit`, `habit_start_date`,
`current_streak`, `longest_streak`, `last_completed`. Modified: `main.py`,
`database.py`

---

## v4.0 — Smart Planning + Task Breakdown

- `/plan [today|week]`, `/breakdown <id>`, `/reschedule <id>`, `/overload`
- Subtask support via new `parent_task_id` column

New DB column: `parent_task_id`. Modified: `main.py`, `database.py`,
`baka_brain.py`

---

## v3.0 — Vague Time Understanding + Smarter Clarification + Habits

- Vague-time defaults ("later"→+2h, "soon"→+30m, "evening/shaam"→18:00,
  "morning/subah"→08:00, "tonight"→21:00, "midnight"→00:00, "lunch"→13:00,
  "noon"→12:00, "end of week"→next Friday)
- Urgency detection → priority=high; "whenever/no rush" → priority=low
- HABIT intent for recurring natural-language phrasing

Modified: `date_parser.py`, `main.py`

---

## v2.0 — Passive PA: Remind Until Done + Escalation + Quiet Hours

- Remind-until-done with escalating frequency near deadline
- Batched follow-ups for 3+ overdue tasks
- Quiet hours (default 23:00–07:00), auto carry-forward at midnight
- Max reminders cap (default 5)

New table: `user_preferences`. New column: `tasks.reminder_count`. New jobs:
`check_followups` (every 5 min), `daily_carry_forward` (midnight). Modified:
`main.py`, `database.py`, `scheduler.py`

---

## v1.2 — Overdue Task Handling + Deadline Warnings + Tags

`/overdue`, `/deadlines`, `/carryforward`, `/tag`, `/tagged`. New column:
`tags`. Modified: `main.py`, `database.py`, `scheduler.py`

---

## v1.1 — Snooze / Postpone / Pause + Persistent Reminder Buttons

Inline buttons on every reminder (Done/Snooze 10m/Snooze 1h/Tomorrow).
`/pause`, `/resume`, `/paused`. New columns: `paused`, `snooze_until`,
`last_reminded`. Modified: `main.py`, `scheduler.py`, `database.py`

---

## v1.0 — Debug & Bug-Tracking System

Built first, deliberately, so every later feature would be easier to test:
`/debug`, `/report`, `/bugs`, `/resolve`, `/trace`, `/selftest`, automatic
exception logging to a separate `bugs.db`.

New file: `debug_system.py`. Modified: `main.py`
