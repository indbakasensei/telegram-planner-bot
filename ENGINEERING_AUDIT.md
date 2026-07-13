# BAKA — Production Engineering Audit

**Date:** 2026-07-13
**Scope:** Full repository, read-only. No application code, configuration, or
database was modified as part of this audit.
**Method:** Documentation reviewed first (README, PROJECT, ARCHITECTURE,
ROADMAP, DEBUGGING, CHANGELOG, TESTING, API, MEMORY, PROMPTS, `docs/`), then
the entire codebase inspected in six parallel focus areas: runtime bugs +
code quality; logic bugs + Telegram integration; database; scheduler + state
management; AI system + security; performance + architecture risk.
**Rule applied throughout:** anything the reviewer wasn't confident was a
real bug is marked **Needs Investigation** with an explanation, not asserted
as a defect.

---

## 1. Executive Summary

BAKA is a well-documented, single-owner Telegram bot with a coherent feature
set built up carefully over 12 major versions, each with real bug-fix
discipline visible in its own changelog. The audit found two **CRITICAL**
production-blocking issues, both confirmed independently by more than one
investigation angle:

1. **Every AI call and every database call blocks the bot's entire asyncio
   event loop** — there is no async offload anywhere in the codebase. A
   single `/video` request can freeze the bot for up to 5 minutes for
   *every* user, not just the requester.
2. **All six daily clock-time scheduled jobs (morning briefing, evening
   review, weekly report, observation engine, project nudges, midnight
   carry-forward) fire 5.5 hours late**, because the bot never tells
   `python-telegram-bot`'s job queue it's running in IST — it defaults to
   UTC. One of the six (`end_of_day_summary`) likely never fires at all
   under default quiet-hours settings as a second-order effect.

Beyond those two, the audit found five **HIGH**-severity issues: three
god-functions dominating `main.py` (one is 841 lines and handles every
free-text message the bot receives), a reminder-sending path with no flood
protection against Telegram's rate limits, admin reset commands that leave
orphaned data and can cause ID-collision data corruption, a timezone
regression in `database.py` that silently misdates habit completions logged
between midnight and 5:30am IST, and no protection against the bot
accidentally being run as two instances at once.

None of this is a case of sloppy engineering — the codebase shows clear
evidence of iterative bug-fixing (the changelog documents real production
incidents being fixed one at a time). What's missing is the class of issue
that's invisible until you specifically go looking for it: async/sync
boundary correctness, scheduler timezone wiring, and admin-tooling data
hygiene. All are fixable without architectural upheaval.

**Bottom line:** solid for continued single-owner personal use as-is (most
issues either don't manifest at low concurrency or are minor annoyances at
that scale). **Not production-ready for multi-user or "long-running
autonomous assistant" goals** until the two CRITICAL items are fixed — they
compound each other (a blocked event loop makes a mistimed job's effects
worse, and vice versa).

---

## 2. Overall Architecture Score: 5/10

Clean separation of concerns exists at the module level (Telegram handling,
data access, AI, scheduling, presentation are each their own file) and the
project's own documentation (produced in an earlier pass this session) maps
cleanly onto the real code. The score is held down by two structural facts:
`main.py` is a 5,306-line monolith mixing routing, business logic, and
direct SQL in one file with no internal boundaries (§9 CQ-1, CQ-7), and the
entire codebase is synchronous code force-fit into an async framework with
no offload boundary (§9 PERF-1) — a mismatch that will only get more
expensive to unwind the longer it's deferred.

## 3. Reliability Score: 4/10

Two CRITICAL and two HIGH-severity correctness bugs (§9: daily jobs firing
at the wrong time, blocking event loop causing bot-wide freezes, admin reset
commands corrupting data via ID reuse, missed recurring reminders with no
catch-up) directly undermine the "reminds you until it's done" and
"long-running autonomous assistant" premises the project is built on. No
automated tests exist to catch regressions in this area going forward
(`TESTING.md` — everything is manual). Positive: the global `error_handler`
prevents any single bug from crashing the whole process, and the retry/
fallback logic in the AI layer is genuinely well thought out.

## 4. Security Score: 6/10

No *new* exposed secrets were found beyond the already-documented hardcoded
key in the dead-code file `ai_helper.py` (flagged to the repo owner earlier
this session, not yet confirmed rotated — see §9 Security). Log sanitization
is correctly and early installed. No SQL injection, shell injection, or
unsafe serialization surface was found anywhere in the codebase. The score
isn't higher because: raw exception text is returned directly to users in
several AI-layer functions (information disclosure), and the admin `/sql`
console's safety net is a single string-prefix check rather than a real
read-only guarantee (low risk today only because admin access is
single-owner).

## 5. Performance Score: 3/10

This is the most severe score in the audit, driven entirely by the blocking
event-loop finding (§9, CRITICAL) — a synchronous architecture wrapped in an
async framework with zero offload means the bot can only truly serve one
AI-driven or DB-driven interaction at a time, full stop, regardless of how
many users are configured. Secondary findings (no indexes on 11 of 13
tables, no connection pooling, full-table scans every 60 seconds) are all
real but individually minor at current scale — they compound with, rather
than independently cause, the primary issue.

## 6. Maintainability Score: 5/10

Documentation is now thorough and accurate (produced earlier this session)
— a real asset for maintainability that most projects at this stage lack.
Pulled down by three god-functions and a god-file (`main.py`), near-total
absence of type hints, zero automated tests, and a handful of duplicated
patterns (hand-rolled "not found" messages, inconsistent import styles).
None of these block a confident change today, but each one raises the cost
of the *next* change, compounding over time.

## 7. AI Readiness Score: 5/10

The intent-detection/planning prompt design is genuinely sophisticated
(bilingual, context-injected, disambiguation-rule-hardened from real
production bugs) and confirmation-gating before any AI-suggested save
appears to be enforced in the paths checked. Held back by: the blocking
synchronous AI client (the same root cause as the Performance score, but
specifically AI-relevant since it means the bot cannot be "always
responsive" while thinking), a single AI provider with no real fallback
(NVIDIA NIM outage = every AI feature down), an `analytics` package that's
supposed to give visibility into AI cost/latency/errors but doesn't
currently function at all (documented in `DEBUGGING.md`), and unused
`anthropic`/second-provider dependencies that suggest multi-provider support
was planned but never actually built.

## 8. Production Readiness Score: 3/10

Two CRITICAL, five HIGH issues, no automated tests, no instance-duplication
guard, and a scheduler that silently fires six recurring jobs 5.5 hours off
schedule. This is a bot that works well for one careful operator running one
instance and checking in on it — it is not yet ready for unattended,
always-on, multi-user, or "autonomous assistant" operation as the project's
own stated ambition (per the audit brief) describes. The fix list to get to
production-ready is short and concrete (§10/§11), not a rewrite.

---

## 9. Every discovered issue

Organized by audit category. Severity: **CRITICAL** / **HIGH** / **MEDIUM**
/ **LOW** / **Needs Investigation** (uncertain — flagged per the audit's own
accuracy-over-quantity rule, not asserted as confirmed).

### A. Runtime Bugs

| # | Issue | Severity |
|---|---|---|
| A1 | Four `main.py` handlers open raw `sqlite3.connect("planner.db")` directly instead of going through `database.py` (`checktasks_cmd` L2464-2465; `_build_today_groups` L3273, via obfuscated `__import__("sqlite3")`; `deadline_cmd`'s toggle L3609-3610; `check_deadlines` job L5250-5251) — a 5th, `/sql`, is intentionally raw by design | MEDIUM |
| A2 | `/sql` admin console's injection guard is a single `.lower().startswith("select")` string check, not a real read-only enforcement (relies on sqlite3's driver refusing multi-statement `execute()`) | LOW (mitigated by single-owner admin gating) |
| A3 | All persistent file paths (`planner.db`, `bugs.db`, `admin_id.txt`, `bot.log`) are relative to process working directory, not the script location — silently creates/reads files in the wrong place if ever launched with a different cwd (systemd, cron, containerization) | MEDIUM |
| A4 | No circular imports found — verified clean | Not a bug |
| A5 | Startup validation (`main()`'s Python-version/`BOT_TOKEN` checks, `init_db()`'s migration loop) not stress-tested against malformed `.env` edge cases (empty `BOT_TOKEN`, malformed `OWNER_ID`) | Needs Investigation |
| A6 | PEP 701 nested-f-string syntax in `main.py:266`/`ui.py:319` requires Python 3.12+ — consistent with the project's documented requirement, not a defect; `ui.py:319`'s nested-quote reuse is a minor readability concern | Not a bug (cosmetic note only) |

### B. Logic Bugs

| # | Issue | Severity |
|---|---|---|
| B1 | Double-tapping "Done" on a reminder before the first tap's UI update lands inserts two rows into `completions_log` (no idempotency check before logging) — skews `/insights`/behavioral-learning data over time | MEDIUM |
| B2 | User-scoped data lookups (`get_task_by_id`, project material/worklog functions) verified correctly filtered by `user_id` — no cross-user ID-guessing (IDOR) path found | Not a bug |
| B3 | Callback routing (`handle_callback`, `route_dashboard_callback`) verified consistent — every registered `callback_data` prefix has a matching handler branch and vice versa | Not a bug |
| B4 | Not fully verified whether every command handler clears `gathering`/`editing` conversation state before executing when invoked mid-flow (e.g. user mid-`/edit` runs `/list`) — could misroute a later free-text message as an edit instruction if any handler skips this | Needs Investigation |
| B5 | No crash path found for a reminder button tapped after its underlying task was already deleted via another path — `None`-task handling looked graceful in spot checks but wasn't exhaustively traced across every branch | Needs Investigation (low-confidence-resolved) |

### C. AI System

| # | Issue | Severity |
|---|---|---|
| C1 | ✅ **RESOLVED 2026-07-13 (Sprint 1B, v12.3 — see CHANGELOG.md)** for the AI/media layer (19 call sites, via new `async_bridge.py`). Database calls (252 sites) deliberately left as-is — benchmarked at 0.3-0.4ms each, below the threshold where offloading matters; see CHANGELOG.md's v12.3 entry for the reasoning. Original finding: **Every AI call blocks the entire asyncio event loop** — `baka_brain.py` uses the synchronous `openai.OpenAI` client (not `AsyncOpenAI`), blocking `time.sleep()` in retry loops, and a synchronous `httpx.Client` (120s/300s timeouts) for image/video generation, all called directly from `async def` handlers with zero `asyncio.to_thread`/`run_in_executor`/await anywhere. Confirmed independently by two audit angles (also listed as PERF-1). A `/video` call alone can freeze the *entire bot, for every user*, for up to 5 minutes. | **CRITICAL** |
| C2 | Self-directed prompt injection: `get_baka_response()`'s system prompt interpolates a user's own conversation history and saved memories unfiltered — a user could inject instruction-like text that affects only their own future sessions (no cross-user impact; no data-exfiltration path found, since the AI has no tool access to other users' data) | LOW |
| C3 | Unconfirmed whether `main.py`'s save paths treat the AI's `needs_confirm` field as authoritative (trusting AI output) or independently enforce confirmation server-side — if the former, a manipulated/hallucinated response could bypass the "BAKA always confirms before saving" design principle | Needs Investigation |
| C4 | `CHANGELOG.md`'s "provider-independent" claim (v11.1) is true only for cost-tracking metadata — the actual AI client is hardcoded to NVIDIA NIM throughout every call site; the `anthropic` SDK is a fully unused dependency (zero `import anthropic` anywhere), suggesting multi-provider support was planned but never built | LOW |
| C5 | AI-generated content (plans, task breakdowns, observations) verified confirmation-gated before being applied, in every path checked (not exhaustively verified for every branch) | Not a bug |

### D. Scheduler

| # | Issue | Severity |
|---|---|---|
| D1 | ✅ **RESOLVED 2026-07-13 (Sprint 1A, v12.2 — see CHANGELOG.md)** — **All six `run_daily()`-scheduled jobs fire in UTC, not IST** — the `Application` is built with no `Defaults(tzinfo=...)`, and every `run_daily` call passes a naive (tzinfo-less) `time` object, which `python-telegram-bot`'s job queue schedules against its default UTC timezone (verified directly against the installed PTB source). Every affected job fires 5.5 hours later than intended: `morning_briefing` (08:00→13:30 IST), `end_of_day_summary` (21:00→02:30 IST next day — likely **never actually sends**, since 02:30 falls inside the default 23:00–07:00 quiet-hours window checked *inside* the job), `weekly_report` (Sun 20:00→Mon 01:30), `observation_engine`, `project_nudge`, `daily_carry_forward` similarly shifted. Does **not** affect the seven `run_repeating` (interval-based) jobs. | **CRITICAL** |
| D2 | Two different timezone libraries (`pytz` in `scheduler.py`/`date_parser.py`, `zoneinfo` in `database.py`/`main.py`) used for the same fixed-offset zone — produces identical results in practice (no DST in India, and all `pytz` usage correctly avoids the classic `datetime(tzinfo=pytz_tz)` construction bug), purely a maintainability inconsistency | LOW |
| D3 | Missed recurring-task/habit reminders have no catch-up path: if the bot is down more than ~5 minutes spanning a recurring task's fire time, that occurrence is silently skipped (unlike one-time tasks, `get_tasks_needing_followup()` explicitly excludes recurring tasks) — undermines habit-streak reliability specifically around deploys | MEDIUM |
| D4 | No thundering-herd/misfire risk on restart — every `run_repeating` job has an explicit staggered `first=` delay; verified solid | Not a bug |
| D5 | `run.sh` has no PID-file/lock/duplicate-instance guard — if ever started twice, both instances poll the same bot token and write to the same database; likely surfaces as a Telegram 409 Conflict crash-loop on one instance rather than silent duplicate handling, but this wasn't reproduced, only reasoned about from the code. See also ARCH-6 (§ Performance/Architecture), which rates the consequence (scheduler can't scale horizontally) as HIGH. | MEDIUM–HIGH (see ARCH-6) |
| D6 | Module-level per-user state dicts never evict entries for inactive users — unbounded growth in theory, negligible in practice at current/expected single-owner scale | LOW |

### E. Database

| # | Issue | Severity |
|---|---|---|
| E1 | ✅ **RESOLVED 2026-07-13 (Sprint 1C, v12.4 — see CHANGELOG.md)**. Independent re-investigation during the fix found the actual bug was broader than first described: `reset_all_tasks()` was deleting habits too, contradicting `/resettasks`'s own promise that habits are kept; and `reset_everything()`'s missing cleanup of `project_materials`/`project_worklog` was the concrete ID-reuse/inheritance hazard, not `habit_log` (which is a non-issue once habits are correctly excluded from `/resettasks`). See CHANGELOG.md v12.4 for full detail and the validation performed. Original finding: `/resettasks` doesn't clean up matching `habit_log` rows (inconsistent with `/resethabits`, which does); `/resetall` ("nuclear wipe") only touches 7 of the 13 real tables — `project_materials`, `project_worklog`, `task_templates`, `missed_capabilities`, `ai_observations` all survive a supposedly-complete wipe. Combined with `reset_all_tasks()` resetting the ID autoincrement sequence, a **newly created task/habit can silently inherit a stale, unrelated history** from orphaned rows that reused its new ID. | **HIGH** |
| E2 | ✅ **RESOLVED 2026-07-13 (Sprint 1C, v12.4 — see CHANGELOG.md)** — all 10 occurrences in `database.py` fixed. `ai_helper.py` (dead code) and `baka_brain.py` (excluded — AI system, no stored/compared data affected) deliberately left as-is; see CHANGELOG.md for reasoning. Original finding: Several `database.py` functions use naive `datetime.now()` instead of the IST-aware pattern used elsewhere in the same file (`add_habit` L629, `log_habit_completion` L653, `get_habit_log` L694, `get_missed_days` L736, and five behavioral-learning functions L832-887) — a regression of the exact bug class `CHANGELOG.md`'s v7.0 entry says was already fixed once. Between 00:00–05:29 IST, habit completions can be misdated to the previous day. | **HIGH** |
| E3 | Only `project_materials`/`project_worklog` (the two newest tables) have explicit indexes; all other tables (including `tasks`, queried every 60 seconds by the scheduler) rely on full-table scans | MEDIUM |
| E4 | No connection pooling — every one of 100+ `database.py` functions opens and closes its own `sqlite3.connect()`; WAL mode is never enabled for `planner.db` (only ever mentioned for the non-functional `ai_usage` table) | MEDIUM |
| E5 | No SQL injection found — all user-controlled values are parameterized with `?`; the handful of dynamic-column-name query-building patterns (`update_task`, `reset_learning_data`) use hardcoded internal lists, not caller input, but are a fragile *pattern* worth a code comment | Not a bug (informational) |
| E6 | Transaction atomicity verified sound — no partial-commit risk found beyond the orphaned-row issue in E1, which is a data-scope problem, not an atomicity one | Not a bug |
| E7 | Migration `try/except: pass` in `init_db()` catches *all* exceptions, not just "column already exists" — could silently swallow a real failure (disk full, corruption) and let the bot start up believing migration succeeded | LOW–MEDIUM |
| E8 | No foreign keys enforced anywhere; a code comment claiming goal deletion "cascades cleanly" to `project_materials`/`project_worklog` is misleading — there is no cascade, it only appears to work because no `delete_goal()` function currently exists at all | MEDIUM |

### F. Telegram Integration

| # | Issue | Severity |
|---|---|---|
| F1 | ✅ **RESOLVED 2026-07-13 (Sprint 2A, v13.0 — see CHANGELOG.md)**. Fixed at the `Application`/`ExtBot` level via a new `notification_service.py` (`TelegramSender`, a `BaseRateLimiter` subclass) rather than adding pacing to `check_reminders` specifically — this covers every send/edit call bot-wide, not just reminders, with zero call-site changes. Full detail in CHANGELOG.md. Original finding: `check_reminders` (fires every 60s) sends one `send_message` per due task in a tight loop with no pacing or batching, unlike `check_followups` which batches — risks Telegram's ~30/sec global and ~1/sec per-chat rate limits on any tick with a burst of simultaneously-due tasks (e.g. many users sharing a common habit time); failures are caught per-task and logged, not retried | HIGH |
| F2 | ✅ **RESOLVED 2026-07-13 (Sprint 2A, v13.0)** as a side effect of the F1 fix — all 34 `edit_message_text` call sites (not ~14 branches; the actual per-call-site count was higher, verified during Sprint 2A) now route through the same `safe_edit_message_text()` helper the dashboard's `_edit()` used to have exclusively. A related, previously undocumented bug was also found and fixed: one callback branch (goal-complete) answered the same callback query twice, which Telegram rejects — see CHANGELOG.md v13.0. Original finding: Only the dashboard's internal `_edit()` helper guards `edit_message_text` against `BadRequest` (deleted message, "not modified", etc.) — every other callback branch (Done/Snooze/Postpone/Pause/Resume/project actions/etc.) calls `edit_message_text` unprotected; the global error handler prevents a crash, but the user sees no feedback on that specific failed tap | MEDIUM |
| F3 | Several older callback-reply paths still use `parse_mode="Markdown"` with raw, unescaped task titles interpolated directly (e.g. `main.py:1823-1849`) — a task title containing Markdown special characters (`_`, `*`, `` ` ``, `[`) can corrupt message rendering. This is the same bug class `CHANGELOG.md`'s v7.1 entry documents fixing project-wide by switching to HTML — these specific spots were missed in that migration. | MEDIUM |
| F4 | No crash/hang path found for deleted-message or stale-keyboard taps in the branches checked (not exhaustively traced) | Needs Investigation (low-confidence-resolved) |

### G. State Management

Complete inventory of RAM-only (module-level dict) state, verified by
grep across the whole repo:

| Variable(s) | File | Restart impact |
|---|---|---|
| `_states`, `_context`, `_history` | `conversation_state.py` | **Medium** — a user mid-`gathering`/`editing` loses their in-progress task/edit silently, with no explanation, on any restart |
| `_admin_mode` | `main.py` | Trivial — resets to off |
| `_waiting_for_time`, `_pending_tasks`, `_editing_task` | `bot_state.py` | None — confirmed dead code |
| `_last_trace` | `debug_system.py` | Low — loses recent debug trace right when it'd be most useful (post-crash) |
| `_debug_mode` | `debug_system.py` | Trivial — resets to off |

No restart-recovery or user-facing "I restarted, let's start over" messaging
exists for any of these — see §12 Technical Debt. One positive: a user
mid-way through the admin `resetall`'s two-step destructive confirmation
loses that confirmation on restart, which is a *safe* failure mode, not a
risk.

### H. Security

| # | Issue | Severity |
|---|---|---|
| H1 | No new hardcoded secrets found beyond the already-known `ai_helper.py:9` key (flagged separately, dead code but still committed to git — recommend rotation regardless) | (see standing item) |
| H2 | Log sanitizer (`log_sanitizer.py`) verified correctly installed early and covers the root logger plus all propagating child loggers; no bypass found | Not a bug |
| H3 | Several `baka_brain.py` functions (`chat_with_ai`, `suggest_tasks`, `analyze_productivity`, `generate_daily_plan`/`_weekly_plan`/`_study_plan`) return raw exception text (`str(e)`) directly to the Telegram user on failure — information-disclosure risk (internal error detail exposed), no confirmed credential-leak path found | MEDIUM |
| H4 | No shell/eval/pickle injection surface anywhere in the codebase (`os.system`, `subprocess`, `pickle`, `eval`, `exec` — zero matches repo-wide) | Not a bug |
| H5 | No predictable-path temp-file collision risk — exports and generated media are handled entirely in memory, never written to a shared/predictable path | Not a bug |
| H6 | `/sql` admin console's safety net is a string-prefix check, not a hard read-only guarantee (same as A2) | LOW (single-owner-gated) |

### I. Performance

| # | Issue | Severity |
|---|---|---|
| I1 | ✅ **RESOLVED 2026-07-13 (Sprint 1B, v12.3)** — see C1. Same root cause as C1 — confirmed independently: **zero async offload anywhere**, meaning the bot serves at most one AI-driven or DB-driven interaction at a time, freezing for every other user during that window. Worst case: `/video` (up to 5 min). | **CRITICAL** |
| I2 | `get_due_tasks()` runs 5 unconditional queries against `tasks` every 60 seconds regardless of load — fine into the tens of thousands of rows given current lack of indexing (E3), degrades past that | MEDIUM |
| I3 | Some multi-read commands (e.g. `/think`) open 3+ separate DB connections for what could be one batched read — real but minor overhead, compounds with I1 rather than independently mattering | MEDIUM (Needs Investigation on real-world impact) |
| I4 | No redundant/duplicate AI calls found — `fast_intent_classify()` pre-filter exists but is correctly gated off by `ENABLE_FAST_ROUTING=False`, not accidentally double-calling | Not a bug |
| I5 | Image/video generation decode base64 payloads fully into memory before sending — realistic single-request footprint is small, and the blocking nature of I1 naturally serializes concurrent requests (a side effect that happens to cap peak memory today, but would need explicit concurrency limits if I1 is ever fixed) | LOW–MEDIUM (Needs Investigation) |

### J. Code Quality

| # | Issue | Severity |
|---|---|---|
| J1 | Three god-functions dominate `main.py`: `handle_message` (841 lines — the entire free-text pipeline: menu matching, 4-state state machine, ~40-entry slashless-command table, AI-intent fallback, all in one function), `main()` (806 lines, includes all 13 scheduled-job callbacks as nested closures), `handle_callback` (312 lines, the full inline-button router) | **HIGH** |
| J2 | All 13 scheduled-job callbacks are nested closures inside `main()` rather than module-level functions — untestable in isolation, a major contributor to `main()`'s size | MEDIUM |
| J3 | `main.py` as a whole (5,306 lines) mixes routing, business logic, and direct SQL (A1) with no internal module boundaries — a structural/architectural finding independent of J1's specific functions | MEDIUM |
| J4 | "Not found" error replies hand-rolled 24 separate times in `main.py` instead of through a shared helper | LOW |
| J5 | Near-total absence of type hints across the codebase (spot-checked: ~5 typed parameters out of 108 functions in `main.py`) — no static-analysis safety net currently possible | LOW |
| J6 | `fast_intent_classify()` in `baka_brain.py` has zero call sites — but this is intentionally-dormant code for a documented future flag flip (`ROADMAP.md`), not accidental dead code like `ai_helper.py`/`bot_state.py` | LOW (distinguish from real dead code) |
| J7 | Minor inconsistency: some modules import `database.py` lazily inside function bodies (`scheduler.py`, `preferences.py`), others at module top-level — no functional purpose since no circular-import risk actually exists (A4) | LOW |

### K. Documentation

All items in this category were addressed in the documentation pass earlier
in this engagement (`CLAUDE.md`, `PROJECT.md`, `ARCHITECTURE.md`,
`ROADMAP.md`, `CHANGELOG.md`, `TESTING.md`, `DEBUGGING.md`, `API.md`,
`MEMORY.md`, `PROMPTS.md`, `docs/*.md` were all created or corrected against
the actual code). Two residual gaps found *during this audit* that weren't
caught in that pass:
- `database.py:1687`'s comment claiming goal-deletion "cascades cleanly" is
  inaccurate (see E8) — needs correcting now that this audit found it.
- None of the newly-discovered bugs in this audit (D1, E1, E2, F1, F3, I1,
  J1) were yet reflected in `DEBUGGING.md`'s Known Issues section as of
  this report — see §10 for the recommendation to fold this audit's
  findings back into that file.

---

## 10. Recommended priority order

1. ✅ ~~**Fix D1** (daily jobs firing in UTC) — one-line `Defaults(tzinfo=...)`
   fix, highest bug-per-effort ratio in the whole audit.~~ **Done 2026-07-13,
   Sprint 1A — see CHANGELOG.md v12.2.**
2. ✅ ~~**Fix I1/C1** (blocking event loop) — wrap `database.py`/`baka_brain.py`
   call sites in `asyncio.to_thread()`; start with the video/image paths
   (worst-case 5-minute freezes) before the rest.~~ **Done 2026-07-13,
   Sprint 1B — see CHANGELOG.md v12.3.** Scoped to the AI/media layer
   (19 call sites via `async_bridge.py`); the database layer (252 call
   sites) was measured and deliberately left unwrapped — see the
   changelog entry for the benchmark data.
3. ✅ ~~**Fix E1** (admin reset data corruption) — extend `reset_all_tasks`
   to clean `habit_log`; extend `reset_everything` to cover all 13 tables.~~
   **Done 2026-07-13, Sprint 1C — see CHANGELOG.md v12.4** (actual fix
   differed from this original plan — see the changelog entry).
4. ✅ ~~**Fix E2** (naive `datetime.now()` in database.py) — mechanical
   find-and-replace with the `IST`-aware pattern already used elsewhere in
   the same file.~~ **Done 2026-07-13, Sprint 1C — see CHANGELOG.md v12.4.**
5. ✅ ~~**Fix F1** (reminder-burst flood risk) — add pacing/batching to
   `check_reminders`, matching the pattern `check_followups` already uses.~~
   **Done 2026-07-13, Sprint 2A — see CHANGELOG.md v13.0** (fixed bot-wide
   via a rate-limiter seam, not just `check_reminders` specifically — also
   resolved F2 as a side effect).
6. **Fix D5/ARCH-6** (no instance lock) — add a PID-file check to `run.sh`
   or `main()`'s startup.
7. **Fix F3** (Markdown-mode unescaped titles) — finish the v7.1 HTML
   migration in the ~14 callback branches that were missed. **Still open**
   — not touched by Sprint 2A (that sprint fixed delivery pacing/retry/edit
   safety, not message-content formatting).
8. **Then** the already-known analytics-package fix (documented in
   `DEBUGGING.md` from the earlier pass — still open) and the `ai_helper.py`
   key rotation (flagged directly to the repo owner earlier this session,
   status unconfirmed).
9. **Medium-priority cleanup batch**: indexes (E3), connection handling
   (E4), message-edit error guards (F2), migration exception narrowing
   (E7), foreign-key comment fix (E8).
10. **Larger, deliberate refactor** (not urgent, plan for it): split
    `main.py`'s god-functions and god-file structure (J1-J3) — do this
    *after* items 1-7 are fixed and covered by `/selftest`, not before,
    since a refactor without tests is itself risky against a file this
    size.

---

## 11. Suggested Sprint Plan

**Sprint 1 — Stop the bleeding (both CRITICALs + data corruption):** ✅
**complete as of 2026-07-13.** D1 (timezone fix, Sprint 1A/v12.2), I1/C1
(async offload, Sprint 1B/v12.3), E1+E2 (reset cleanup + IST datetime fix,
Sprint 1C/v12.4). All four were fixed individually, each validated against
an isolated environment (standalone scripts for D1/I1/C1, an isolated temp
database for E1/E2 — never the live `planner.db`). Live-traffic
confirmation (via `/selftest` against the running bot) is still
outstanding — recommended before considering Sprint 1 fully closed.

**Sprint 2 — Reliability & Telegram correctness:**
F1 (reminder flood pacing), D5/ARCH-6 (instance lock), F3 (finish HTML
migration), F2 (message-edit error guards), D3 (recurring-reminder
catch-up — this one's a genuine design decision, may need a product call
on whether it's worth the M-effort fix or acceptable as documented
behavior).

**Sprint 3 — Data layer hardening:**
E3 (indexes), E4 (connection pooling / WAL mode), E7 (narrow migration
exception handling), E8 (fix misleading comment + add cascade logic if/when
single-goal deletion is ever built). Low risk, mechanical, good candidate
for a quieter sprint.

**Sprint 4+ (backlog, not urgent):** the already-tracked `ROADMAP.md`
fix-it list (analytics package, `ai_helper.py` cleanup), then the
deliberate `main.py` refactor (J1-J3) once the above have proven out
`/selftest` as a reliable regression gate.

---

## 12. Technical Debt

- **Zero automated tests.** Every fix in this report has to be manually
  validated via live Telegram interaction (`/selftest` + `TEST_CHECKLIST.md`
  — see `TESTING.md`). This is the single biggest multiplier on the cost of
  every other fix in this document, since nothing catches a regression
  except a human running through a checklist.
- **Sync-in-async architecture** (I1/C1) — the longer this is deferred, the
  more call sites accumulate that need to be touched when it's eventually
  fixed. Currently ~15 call sites; will only grow.
- **God-file/god-function structure** in `main.py` (J1-J3) — same
  compounding-cost dynamic; every new command added today makes the
  eventual split more expensive.
- **In-memory-only state** (state machine, debug trace, debug-mode toggle)
  with no restart-recovery messaging (§G) — a known, accepted limitation
  today; worth a deliberate decision (accept forever vs. SQLite-back it)
  rather than continuing to default into it.
- **`analytics` package** — already tracked in `DEBUGGING.md`/`ROADMAP.md`
  from the earlier documentation pass; still unresolved as of this audit.
- **Unused `anthropic` dependency** (C4) — either build the multi-provider
  abstraction the changelog implies exists, or prune the dependency and
  correct the claim.

## 13. Architecture Risks (forward-looking)

| Risk | Assessment |
|---|---|
| **`main.py` size** | Coordination risk (merge conflicts, cognitive load), not yet a runtime cost — but the fix gets more expensive the longer it's deferred |
| **Import graph** | Currently low-risk, single-directional; watch when adding cross-cutting features (e.g. a real multi-provider AI abstraction) that might need both low-level and `main.py`-level concepts |
| **SQLite as the data store** | Single-writer by design; comfortable estimate into the low hundreds of concurrent active users before write-lock contention becomes noticeable, worse if I1 isn't fixed first (blocking calls hold locks longer than necessary) |
| **Single AI provider (NVIDIA NIM)** | A NIM-wide outage takes down every AI feature; the existing MAIN→FAST fallback doesn't help since both are NIM-hosted |
| **In-memory per-user state ceiling** | Generous — comfortably into the tens of thousands of users at current per-user payload size; not a near-term concern |
| **Scheduler cannot horizontally scale** | `job_queue` is in-process; running two instances would double-fire every reminder and race on writes — directly connected to the missing instance-lock finding (D5/ARCH-6) |

## 14. Long-term Recommendations

1. **Decide deliberately on the async question.** Either commit to
   `asyncio.to_thread()` wrapping as a pragmatic fix now, or plan a genuine
   async rewrite (`aiosqlite`, `AsyncOpenAI`, `httpx.AsyncClient`) if the
   "long-running autonomous assistant" ambition is real — don't leave this
   as an ambient, growing debt.
2. **Add a minimal test harness before the next refactor.** Doesn't need to
   be comprehensive — even a handful of `pytest` tests around
   `date_parser.py` (pure functions, no I/O, highest bug-density area
   historically per `CHANGELOG.md`) and `scheduler.py`'s query logic would
   catch the class of regression this audit found by hand.
3. **Split `main.py` once Sprints 1-2 are stable**, not before — a refactor
   without a safety net against a 5,300-line, 90-handler file is itself a
   production risk.
4. **Make a real decision on multi-provider AI support**: either build the
   abstraction the changelog already claims exists, or remove the unused
   dependency and stop implying it's supported.
5. **Persist state to SQLite if multi-user or high-availability is a real
   goal** — the in-memory state model is fine for a single careful operator
   restarting occasionally; it's not fine for an "always-on assistant."
6. **Fold this audit's findings into `DEBUGGING.md`'s Known Issues and
   `ROADMAP.md`'s fix-it list** so they don't live only in this one-time
   report — those files are the ones a future session will actually read
   first (per `CLAUDE.md`'s documentation map).
