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

1. A Telegram update arrives; PTB dispatches to a `CommandHandler` (if it
   starts with `/`) or the catch-all `MessageHandler` for free text.
2. Free text first checks the reply-keyboard menu, then
   `conversation_state.get_state(user_id)`:
   - `confirming` — handles yes/no replies, AM/PM disambiguation, or
     admin-reset confirmation phrases
   - `editing` — re-parses the message as an update to `get_editing_id()`
   - `gathering` — merges new entities into `partial_data`, either asks the
     next missing question or moves to `confirming`
3. Otherwise, a ~40-entry slashless-command table
   (`_starts_with_handlers`/`_exact_handlers`) lets every command work
   without a leading `/`, and a keyword shortcut handles plain view
   requests (today/week/month/...) without invoking the AI at all.
4. Anything left falls to `baka_brain.get_baka_response()`, which classifies
   the message into one of 11 intents (`TASK`, `HABIT`, `EDIT`, `DELETE`,
   `VIEW`, `MEMORY_SAVE`, `MEMORY_GET`, `GOAL`, `PLAN`, `ADVICE`, `CHAT`,
   `MULTIPLE`) and extracts entities. `date_parser.parse_all()` runs in
   parallel and **overrides** the AI's date/time for phrasings it's known to
   get wrong (see [docs/ai_system.md](docs/ai_system.md)).
5. Low-confidence responses, or CHAT-intent replies to messages containing
   action verbs, get logged to `missed_capabilities` for later review via
   `/misses` (admin-only) — this is the bot's feature-gap-mining mechanism.
6. The result is rendered via `fmt.py`/`ui.py` helpers (all user content is
   HTML-escaped) and sent back.

Full command inventory: [API.md](API.md). Full state-machine detail:
[docs/telegram_integration.md](docs/telegram_integration.md).

## Module map

| Module | Role | Notes |
|---|---|---|
| `main.py` | All ~90 command handlers, callback router, job registration, `main()` entrypoint | 5,300+ lines; see [API.md](API.md) for the full command table |
| `database.py` | All SQLite schema + CRUD, in-place migrations via `ALTER TABLE ... except: pass` | See [docs/database.md](docs/database.md) |
| `baka_brain.py` | NVIDIA NIM calls, intent detection, planning, vision/image/video | See [docs/ai_system.md](docs/ai_system.md) |
| `date_parser.py` | Deterministic regex date/time parser (EN/Hindi/Hinglish); wins over the AI for known-ambiguous phrasings | Pure functions, no I/O |
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
| `run.sh` | Crash-loop restarter (`while true; python3 main.py; sleep 5`) | Assumes `~/telegram-planner-bot` and a pre-existing `venv/` |

## Scheduled jobs

All 13 jobs are registered inline in `main()` via `app.job_queue`. Full
per-job detail (interval, what it does, quiet-hours behavior) lives in
[docs/scheduler.md](docs/scheduler.md) and [docs/reminders.md](docs/reminders.md).

## Data layer

13 active SQLite tables in `planner.db`, created/migrated by
`database.py`'s `init_db()` (idempotent `ALTER TABLE` calls wrapped in
`try/except`). Full schema: [docs/database.md](docs/database.md). A
separate `bugs.db` holds `debug_system.py`'s bug reports and interaction
traces, intentionally isolated from user data.

## AI layer

Single provider (NVIDIA NIM) accessed via an OpenAI-compatible client, with
a hand-rolled retry loop (SDK retries disabled deliberately — see
[docs/ai_system.md](docs/ai_system.md)) and automatic MAIN→FAST model
fallback on hard failures. Full detail, including current model IDs (which
have drifted from what earlier docs/comments say) and the broken analytics
pipeline: [docs/ai_system.md](docs/ai_system.md).

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
