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

## Definition of Done (v14.23 — permanent rule)

> **⛔ NON-NEGOTIABLE (owner directive, v15.0-rc.2).** Every time you add a
> **command, capability, or user feature**, you MUST — in the same
> change-set — update **(a) the README**, **(b) the `/help` menu**
> (`ui.help_cards`), and **(c) a `/selftest` check** (`core/selftest/tests/`)
> so the owner can *see how it works* and *run a live test to confirm the
> bot behaves as planned*. Do not report a feature "done" without these.
> **This applies even to backend/flag-gated work:** if it has no user
> command yet, it still needs a Self-Test probe so its health is verifiable
> from `/selftest`, and README/CHANGELOG must state plainly that it is
> dormant and how to enable it (the flag) — never imply a dormant feature
> is usable. The owner should never have to discover a missing help entry or
> self-test by running the bot.

A **user-visible feature is not complete** until ALL of these exist in
the same change-set (see [QA_SYSTEM_DESIGN.md](QA_SYSTEM_DESIGN.md) R2):

1. ✅ Production implementation
2. ✅ Regression test spec(s) in `core/regression/suites/` (the feature
   owns its manual tests — [docs/regression.md](docs/regression.md))
3. ✅ Self-Test check(s) in `core/selftest/tests/` where a live health
   probe applies ([docs/selftest.md](docs/selftest.md))
4. ✅ `/help` updated (`ui.help_cards`) if a command/capability changed
5. ✅ `/start` updated if onboarding changed
6. ✅ CHANGELOG.md
7. ✅ ROADMAP.md if roadmap-affecting
8. ✅ README.md if user-facing
9. ✅ Feature documentation (`docs/` / the permanent docs)

Non-user-visible / infra changes need at least 1, 6, and the relevant
docs. This is enforced by review, and increasingly by automatable
checks (a Self-Test asserting every `CommandHandler` appears in
`help_cards`).

## Antigravity Era Engineering Constitution (Permanent Rules)

1. **RULE 1 — Documentation Synchronization (MANDATORY)**: Every completed phase updates `README.md`, `ROADMAP.md`, `CHANGELOG.md`, `ARCHITECTURE.md`, and feature docs in `docs/`. If commands change, update help documentation, dashboard, and reference tables.
2. **RULE 2 — No Random Markdown Files**: Do NOT create ad-hoc markdown files (e.g., `PHASE_REPORT.md`, `SUMMARY.md`, `FIXES.md`). Update existing permanent docs.
3. **RULE 3 — Organized Docs**: Keep directory hierarchy clean without duplicate or obsolete files.
4. **RULE 4 — Explain Every Change**: Every implementation must detail: Purpose, Files changed, Risk, Rollback strategy, Validation, Documentation updated, and Git commands.
5. **RULE 5 — No Silent Production Changes**: Never modify production logic (`database.py`, `main.py`, `baka_brain.py`, callback handlers, storage APIs, conversation engine) during test stabilization phases without explicit review and approval. If a test exposes a production defect, document it and stop.
