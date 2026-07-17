# CLAUDE.md

Guidance for Claude Code (or any AI assistant) working in this repository.

## What this project is

BAKA — a Telegram personal-assistant bot (tasks, habits, goals, hobby
projects, AI planning) in Python, single process, SQLite-backed, NVIDIA
NIM for AI. Start with [PROJECT.md](PROJECT.md) for the overview, then
[ARCHITECTURE.md](ARCHITECTURE.md) for how the pieces fit together.

## Documentation map

| Need to know... | Read |
|---|---|
| What the project does, current status | [PROJECT.md](PROJECT.md) |
| How it's structured, message lifecycle | [ARCHITECTURE.md](ARCHITECTURE.md) |
| Every command + internal function inventory | [API.md](API.md) |
| Version history | [CHANGELOG.md](CHANGELOG.md) |
| Planned work / backlog | [ROADMAP.md](ROADMAP.md) |
| How to test a change | [TESTING.md](TESTING.md) |
| How to debug, and current known bugs | [DEBUGGING.md](DEBUGGING.md) |
| AI prompt locations and structure | [PROMPTS.md](PROMPTS.md) |
| UI standards (frozen spec — all UI work cites its § numbers) | [UI_SPEC_v1.md](UI_SPEC_v1.md) |
| Cross-session context/decisions | [MEMORY.md](MEMORY.md) |
| Scheduler, AI system, database, dashboard, reminders, Telegram integration deep-dives | `docs/*.md` |

**Read [DEBUGGING.md's Known Issues section](DEBUGGING.md#known-issues)
before assuming any AI-analytics command (`/usage`, `/performance`,
`/errors`) or a "current" model name is correct — several were found
stale or broken during the 2026-07 documentation pass.**

## Conventions that aren't obvious from reading one file

- **All datetime handling must use IST** (`Asia/Kolkata`). The system clock
  is UTC. Never use a bare `datetime.now()` for anything user-facing —
  every module that needs the current time defines its own IST-aware
  helper (e.g. `date_parser.py`'s `_now()`). This has caused real bugs
  before (see `CHANGELOG.md`'s v7.0 entry).
- **`httpx` must stay pinned to `0.25.2`** — newer versions break
  `python-telegram-bot` 20.7. Don't let a dependency-update pass bump this
  without testing.
- **Every DB write goes through `database.py`**, not raw `sqlite3` calls in
  `main.py` — with one known exception (`check_deadlines`, tracked in
  [DEBUGGING.md](DEBUGGING.md#known-issues)). Don't add a second one.
- **Migrations are additive and idempotent**: `database.py`'s `init_db()`
  runs `ALTER TABLE ... ADD COLUMN` inside `try/except: pass` for every
  column that might not exist yet, rather than versioned migration files.
  Follow this pattern for new columns; don't introduce a separate migration
  system for one change.
- **User-facing text is Telegram HTML**, not Markdown (switched in v7.1
  specifically because Markdown corrupted on titles containing `.`, `-`,
  `(`, `+`, `&`). Always build messages through `fmt.py`'s helpers
  (`esc()`, `b()`, `i()`, `code()`, `task_line()`, `confirm_box()`) so user
  content gets escaped — don't hand-format HTML strings.
- **Commands work with or without the leading `/`** via a slashless-command
  table in `main.py`. If you add a new `CommandHandler`, also consider
  whether it needs a slashless/natural-language entry point for
  consistency with the rest of the bot.
- **Admin commands deny silently** ("Unknown command", not "access
  denied") — this is deliberate obscurity, not a bug. Keep new admin
  commands consistent with this.
- **Secrets live in `.env`** (`BOT_TOKEN`, `AI_API_KEY` — legacy name
  `NVIDIA_API_KEY` still works — `OWNER_ID`), gitignored. Never hardcode
  a key in source — the one historical violation (`ai_helper.py`, dead
  code) was deleted in v14.12, but its key is still in git history and
  needs rotating (see [DEBUGGING.md](DEBUGGING.md#known-issues)).

## Working in this repo

- **Do not modify application logic while only updating documentation.**
  If a doc-only task surfaces a real bug (as this pass did — see
  [DEBUGGING.md](DEBUGGING.md#known-issues)), document it and flag it
  explicitly rather than silently fixing it, unless asked to fix it.
- **An automated pytest suite exists since v14** (700+ offline tests,
  `pytest`, ~20s — see [TESTING.md](TESTING.md)). Run it for every
  change. Live-Telegram behavior (handlers, callbacks, formatting) still
  needs `/selftest` + the manual smoke checklist in TESTING.md — the
  suite deliberately never touches Telegram.
- **`ai_helper.py` and `bot_state.py` were deleted in v14.12** (they
  were unreferenced dead code). Use `baka_brain.py`/
  `conversation_state.py`; don't resurrect the old names.
- **When you learn something surprising about this codebase that doesn't
  fit neatly into one of the permanent docs yet, add it to
  [MEMORY.md](MEMORY.md)** rather than letting it live only in a chat
  transcript.
