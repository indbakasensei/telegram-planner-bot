# Architecture

## Overview

BAKA is a single Python process: `main.py` builds a
`telegram.ext.Application`, registers ~90 command handlers plus callback and
message handlers, schedules 13 background jobs on the PTB `job_queue`, and
runs `run_polling()`. There is no web server and no external queue — the
whole app is one process talking to SQLite and to NVIDIA NIM.

```
Telegram ──▶ python-telegram-bot (polling) ──▶ main.py handlers
                                                     │
                          ┌──────────────────────────┼──────────────────────┐
                          ▼                           ▼                      ▼
                  conversation_state.py         database.py          baka_brain.py
                  (in-memory state machine)     (SQLite: planner.db)  (NVIDIA NIM via
                                                                        OpenAI-compat SDK)
                          │                           │                      │
                          └─────────────┬─────────────┘                      │
                                        ▼                                     │
                                 fmt.py / ui.py  ◀───────────────────────────┘
                                 (HTML formatting, dashboard cards)
                                        │
                                        ▼
                                 Telegram (reply)
```

`scheduler.py` (query helpers) + PTB's `job_queue` (the actual timer) drive
all proactive behavior — reminders, deadline buffers, wellness nudges,
stagnation nudges, daily/weekly digests.

## Message lifecycle

**Before v14.0:**

```
Incoming Message
      │
      ▼
Legacy Router (menu / state machine / slashless commands / AI fallback)
```

**Design:** [DRG-001_Intent_Aware_Routing.md](DRG-001_Intent_Aware_Routing.md) /
[docs/adr/ADR-006-intent-aware-routing.md](docs/adr/ADR-006-intent-aware-routing.md)
specify how the Routing Layer below will eventually act on its own
recommendation (Offline Engine / transitional Legacy Handler / AI Router)
instead of always executing via Legacy as it does today (v14.1B, Sub-stage B
"Decision" — comparison-logging only, by design; see DRG-001 §10/§13 on why
skipping this period is the migration's dominant risk).

**Since v14.1B (Routing Layer, decision-logging only):**

```
Incoming Message
      │
      ▼
Intent Engine (core/intent/) ── classifies, logs
      │
      ▼
Routing Layer (core/routing/) ── computes + logs a recommended
      │                          destination, ALWAYS executes via Legacy
      ▼
Legacy Router (menu / state machine / slashless commands / AI fallback)
                          ── UNCHANGED ──
```

1. A Telegram update arrives; PTB dispatches to a `CommandHandler` (if it
   starts with `/`) or the catch-all `MessageHandler` for free text.
2. **(v14.0, Shadow Mode)** Free text is first classified by
   `core/intent/`'s `IntentEngine.classify()` — a deterministic, offline
   classifier that reuses `date_parser.py` and mirrors `main.py`'s own
   command tables (see [DEBUGGING.md](DEBUGGING.md#known-issues) for the
   duplication tradeoff this involves) — and the result is logged via
   `logger.debug()`. See
   [docs/adr/ADR-002-intent-engine.md](docs/adr/ADR-002-intent-engine.md).
3. **(v14.1B, decision-logging only)** The resulting `IntentResult` is
   passed to `core/routing/`'s `RoutingLayer.route()`, which computes a
   `RoutingDecision` — a real recommended destination (Offline/Legacy/AI
   Router/Clarify) per `DRG-001_Intent_Aware_Routing.md`'s Confidence
   Policy — and logs it via `logger.debug()`. **`destination` is hard-coded
   to `LEGACY` on every call, unconditionally** — nothing below this step
   reads `recommended_destination`. See
   [docs/adr/ADR-006-intent-aware-routing.md](docs/adr/ADR-006-intent-aware-routing.md).
4. Free text then checks the reply-keyboard menu, then
   `conversation_state.get_state(user_id)`:
   - `confirming` — handles yes/no replies, AM/PM disambiguation, or
     admin-reset confirmation phrases
   - `editing` — re-parses the message as an update to `get_editing_id()`
   - `gathering` — merges new entities into `partial_data`, either asks the
     next missing question or moves to `confirming`
5. Otherwise, a ~40-entry slashless-command table
   (`_starts_with_handlers`/`_exact_handlers`) lets every command work
   without a leading `/`, and a keyword shortcut handles plain view
   requests (today/week/month/...) without invoking the AI at all.
6. Anything left falls to `baka_brain.get_baka_response()`, which classifies
   the message into one of 11 intents (`TASK`, `HABIT`, `EDIT`, `DELETE`,
   `VIEW`, `MEMORY_SAVE`, `MEMORY_GET`, `GOAL`, `PLAN`, `ADVICE`, `CHAT`,
   `MULTIPLE`) and extracts entities. `date_parser.parse_all()` runs in
   parallel and **overrides** the AI's date/time for phrasings it's known to
   get wrong (see [docs/ai_system.md](docs/ai_system.md)).
7. Low-confidence responses, or CHAT-intent replies to messages containing
   action verbs, get logged to `missed_capabilities` for later review via
   `/misses` (admin-only) — this is the bot's feature-gap-mining mechanism.
8. The result is rendered via `fmt.py`/`ui.py` helpers (all user content is
   HTML-escaped) and sent back.

**Note on step 6's 11-intent taxonomy vs. the Intent Engine's 11-value
`Intent` enum (step 2):** these are two different, currently-unrelated
classification systems that happen to both have 11 values — the AI's
taxonomy (`TASK`/`HABIT`/`EDIT`/`DELETE`/`VIEW`/`MEMORY_SAVE`/
`MEMORY_GET`/`GOAL`/`PLAN`/`ADVICE`/`CHAT`/`MULTIPLE`, actually 12) drives
real routing today; the Intent Engine's `Intent` enum
(`ADD_TASK`/`EDIT_TASK`/`DELETE_TASK`/`QUERY_TASK`/`CHAT`/`GREETING`/
`HELP`/`MEDIA`/`FILE`/`SETTINGS`/`UNKNOWN`) is deliberately coarser and
does not drive anything yet (Stage 1, Shadow Mode). Reconciling the two
taxonomies is future work, not done as part of Stage 1 — see
`core/intent/intent_types.py`'s `Intent` docstring.

Full command inventory: [API.md](API.md). Full state-machine detail:
[docs/telegram_integration.md](docs/telegram_integration.md).

## Module map

| Module | Role | Notes |
|---|---|---|
| `main.py` | All ~90 command handlers, callback router, job registration, `main()` entrypoint | 5,300+ lines; see [API.md](API.md) for the full command table |
| `database.py` | All SQLite schema + CRUD, in-place migrations via `ALTER TABLE ... except: pass` | See [docs/database.md](docs/database.md) |
| `baka_brain.py` | NVIDIA NIM calls, intent detection, planning, vision/image/video | Fully synchronous internally (by design — see `async_bridge.py`); see [docs/ai_system.md](docs/ai_system.md) |
| `async_bridge.py` | The single seam offloading `baka_brain.py`'s synchronous AI/media calls onto worker threads so they don't block the bot's event loop (added v12.3, Sprint 1B) | One function, `run_blocking()`; used at all 19 `main.py` call sites into `baka_brain.py`'s public functions. `database.py` calls are deliberately not routed through it — see [docs/ai_system.md](docs/ai_system.md) |
| `notification_service.py` | The single seam every outbound Telegram Bot API call routes through: pacing, flood protection, retry, plus edit/answer failure safety (added v13.0, Sprint 2A) | `TelegramSender` (a `BaseRateLimiter` subclass registered via `Application.builder().rate_limiter(...)`) covers `send_message`/`reply_text`/`send_photo`/etc. with zero call-site changes; `safe_edit_message_text()`/`safe_answer_callback_query()` are separate helpers used explicitly at `main.py`'s edit/answer call sites — see [docs/telegram_integration.md](docs/telegram_integration.md) |
| `date_parser.py` | Deterministic regex date/time parser (EN/Hindi/Hinglish); wins over the AI for known-ambiguous phrasings | Pure functions, no I/O |
| `core/intent/` | v14.0 Stage 1: deterministic, tiered Intent Engine — classifies every message, but Shadow Mode only (observes, doesn't route yet; added v14.0) | Pure, stateless, zero Telegram/database/scheduler/AI/network dependencies; reuses `date_parser.py` directly. See [docs/adr/ADR-002-intent-engine.md](docs/adr/ADR-002-intent-engine.md) and `INTENT_ENGINE.md` |
| `core/routing/` | v14.1B: Routing Layer — computes a recommended destination (Offline/Legacy/AI Router/Clarify) per `IntentResult`, but `destination` is hard-coded to `LEGACY` on every call (decision-logging only; added v14.1B) | Pure, stateless, same zero-dependency constraints as `core/intent/`. See [docs/adr/ADR-006-intent-aware-routing.md](docs/adr/ADR-006-intent-aware-routing.md) and `DRG-001_Intent_Aware_Routing.md` |
| `core/storage/` | v14.1C: Storage Facade — domain-grouped (`tasks`/`habits`/`goals`/`projects`) thin delegation to `database.py`, for the not-yet-built Offline Engine. **Not consumed anywhere yet** | Zero SQL, zero business logic, zero return-value reshaping — a Facade, not a Repository (Phase 0 review, `CHANGELOG.md`'s v14.1C entry) |
| `core/feature_flags.py` | v14.1C: `OFFLINE_TASKS`/`OFFLINE_HABITS`/`OFFLINE_GOALS`/`OFFLINE_PROJECTS`, all default OFF. **Not read anywhere yet** | `.env`-backed, same convention as `BOT_TOKEN`/`OWNER_ID`; gates the Offline Engine's future per-domain rollout, unrelated to `core/routing/`'s own `OFFLINE_ENGINE_IMPLEMENTED_INTENTS` set |
| `scheduler.py` | Query helpers for due/overdue/followup tasks and quiet-hours checks | The actual timer is PTB's `job_queue`, registered in `main.py` |
| `conversation_state.py` | In-memory (module-level dict) state machine: idle/gathering/confirming/editing | **Does not survive process restart**, despite its own docstring's "survives reliably" claim — see [DEBUGGING.md](DEBUGGING.md#known-issues) |
| `debug_system.py` | Bug tracking (`bugs.db`), `/trace`, `/selftest` message bank | Debug-mode/last-trace state is also in-memory only |
| `preferences.py` | Behavioral learning: active hours, tone, per-category interval suggestions | Pure read/derive over `database.py` data, no writes |
| `fmt.py` | Telegram-HTML formatting helpers (`esc`, `b`, `i`, `code`, `task_line`, `confirm_box`) | All user content passes through `esc()` |
| `ui.py` | Dashboard card renderers (7 card types) | See [docs/dashboard.md](docs/dashboard.md) |
| `log_sanitizer.py` | Logging filter that redacts bot tokens, API keys, and Telegram IDs from `bot.log` | Installed in `main.py` at startup |
| `usage_logger.py`, `usage_service.py`, `model_metrics.py`, `token_counter.py`, `performance_tracker.py` | Intended `analytics` package for AI-call telemetry | **Currently broken** — not wired into an actual package; see [DEBUGGING.md](DEBUGGING.md#known-issues) |
| `init.py` | Leftover `__init__.py`-style module for the never-assembled `analytics` package | Misleadingly named; not a project setup script |
| `ai_helper.py` | Legacy AI helper | **Dead code** — not imported anywhere; also has a hardcoded-looking API key, see [DEBUGGING.md](DEBUGGING.md#known-issues) |
| `bot_state.py` | Legacy state module, predecessor to `conversation_state.py` | **Dead code** — not imported anywhere |
| `run.sh` | Crash-loop restarter (`while true; python3 main.py; sleep 5`) | Assumes `~/telegram-planner-bot` and a pre-existing `venv/`. Safe to run redundantly since v13.1 — a second copy just gets blocked by `instance_lock.py` and retries harmlessly, becoming an automatic standby |
| `instance_lock.py` | Single-instance protection: acquired as the first action in `main()`, before the database or Telegram are touched (added v13.1, Sprint 2B) | `fcntl.flock`-based advisory lock on `bot.pid` — survives crashes automatically (the OS releases the lock when the process dies, for any reason) with no separate staleness heuristic needed; see [CHANGELOG.md](CHANGELOG.md) |

## Scheduled jobs

All 13 jobs are registered inline in `main()` via `app.job_queue`. Full
per-job detail (interval, what it does, quiet-hours behavior) lives in
[docs/scheduler.md](docs/scheduler.md) and [docs/reminders.md](docs/reminders.md).

## Data layer

13 active SQLite tables in `planner.db`, created/migrated by
`database.py`'s `init_db()` (idempotent `ALTER TABLE`/`CREATE TABLE IF NOT
EXISTS` calls; column-addition failures are now distinguished — "already
exists" vs. a real problem — by `_safe_add_column()`, added v13.2). Full
schema: [docs/database.md](docs/database.md). A separate `bugs.db` holds
`debug_system.py`'s bug reports and interaction traces, intentionally
isolated from user data.

**Infrastructure added in v13.2 (Sprint 3):** WAL journal mode (set once
in `init_db()`); 10 indexes on the query patterns actually used by
`database.py`/`scheduler.py` (documented inline as `REQUIRED_INDEXES` —
the scheduler's due-task scan, run every 60s, measured ~140x faster on a
synthetic 20k-row benchmark); `verify_schema_integrity()`, run
automatically at startup right after `init_db()`, confirming required
tables/indexes exist and reporting schema version/foreign-key
setting/journal mode; `backup_database()`, using SQLite's own online-backup
API, run at the start of every `init_db()` call before any migration
statement (no-op on a fresh database, keeps the 5 most recent backups per
reason in `backups/`). None of this changes what any command does — it's
purely about the database surviving longer and failing more visibly when
something is actually wrong.

## AI layer

Single provider (NVIDIA NIM) accessed via an OpenAI-compatible client, with
a hand-rolled retry loop (SDK retries disabled deliberately — see
[docs/ai_system.md](docs/ai_system.md)) and automatic MAIN→FAST model
fallback on hard failures. `baka_brain.py` itself is entirely synchronous;
every call from `main.py` is offloaded to a worker thread via
`async_bridge.py`'s `run_blocking()` so a slow AI call or a multi-minute
video-generation request can't freeze the bot for other users (added v12.3,
Sprint 1B — previously this was the audit's top CRITICAL finding). Full
detail, including current model IDs (which have drifted from what earlier
docs/comments say) and the broken analytics pipeline:
[docs/ai_system.md](docs/ai_system.md).

## Admin & security model

Single-owner admin lock: `admin_id.txt` (gitignored) stores one Telegram
ID, set permanently by whoever first runs `/claimadmin`. Seven handlers are
gated behind an `admin_only` decorator with silent denial (non-admins see
"Unknown command", not "access denied"). `/sql` further restricts to
`SELECT`-only queries. Full detail:
[docs/telegram_integration.md](docs/telegram_integration.md#admin-lock).

Secrets (`BOT_TOKEN`, `NVIDIA_API_KEY`, `OWNER_ID`) live in `.env`
(gitignored). `log_sanitizer.py` redacts tokens/keys/IDs from `bot.log`
before they're written.
