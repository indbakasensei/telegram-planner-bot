# BAKA Bot — Changelog

This is the authoritative version history, moved here from the old `VERSION.md`
(now a pointer to this file — see below). Forward-looking / not-yet-built ideas
live in [ROADMAP.md](ROADMAP.md) instead of being mixed into this file.

Each entry lists what was added and which files were touched, so a future
session can find the relevant code quickly.

---

## v13.1 — Single-Instance Protection & Safe Startup (current)

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
