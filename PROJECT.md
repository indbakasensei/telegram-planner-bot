# BAKA — Project Overview

**BAKA** (Behavioral Adaptive Knowledge Assistant) is a Telegram bot that
manages tasks, deadlines, habits, goals, and hobby/build projects through
natural-language conversation in English, Hindi, and Hinglish — no commands
required, though every command also has a slash form.

It's a single-process Python application: one long-running `main.py`
polling the Telegram Bot API, backed by SQLite, with an NVIDIA NIM-hosted
LLM doing intent detection and reasoning.

For setup instructions and the full user-facing command list, see
[README.md](README.md). For system design, see
[ARCHITECTURE.md](ARCHITECTURE.md). For version history, see
[CHANGELOG.md](CHANGELOG.md). For planned work, see [ROADMAP.md](ROADMAP.md).

## Current status

**v14.0** (Intent Engine, Shadow Mode) is the latest shipped version. See
[CHANGELOG.md](CHANGELOG.md) for the full history back to v1.0. (This line
previously said v12.0, several releases out of date — corrected during
v14.0's documentation sync; if you're reading this and CHANGELOG.md's top
entry has moved past v14.0 again, trust CHANGELOG.md, not this line.)

v14.0 Stage 1 added a new internal classification layer
(`core/intent/`, see [ARCHITECTURE.md](ARCHITECTURE.md)) that runs
alongside every message but does not yet change any user-visible
behavior — every feature below is unaffected.

Deployment target: To Be Documented — historically run locally under WSL
via `run.sh`'s crash-loop restarter; confirm current hosting before relying
on this.

## What it does (feature summary)

- **Tasks** — natural-language creation, editing, deletion, categories,
  priority, recurrence (daily/weekly/monthly), tags, subtasks
- **Reminders** — persistent (re-fires until done), escalating frequency
  near a deadline, snooze/pause/resume, quiet hours
- **Deadlines** — staged pre-deadline warnings (7d/3d/1d/6h/1h) distinct
  from plain due-date reminders
- **Habits** — streak tracking, 14-day/30-day views, missed-day detection
- **Goals** — progress bars, target-based tracking
- **Projects** (v12.0) — goals extended with materials checklists, worklog
  entries, auto-computed progress, and stagnation nudges — built for
  multi-week real-world builds (see [CHANGELOG.md](CHANGELOG.md#v120--project-management-current))
- **AI planning** — `/think` free-form reasoning, `/plan`, `/breakdown`,
  `/reschedule`, `/analyze`, `/insights`, daily AI-generated suggestions
- **Memory** — key/value personal facts the bot can recall in conversation
- **Search & templates** — cross-entity search, reusable task templates,
  plain-text data export
- **Multi-model AI** — text, vision (photo understanding), image
  generation, video generation, all via NVIDIA NIM (see
  [docs/ai_system.md](docs/ai_system.md))
- **AI analytics** — *intended* per-call usage/latency/cost tracking via
  `/usage`, `/performance`, `/errors`, `/models`. **Currently broken** — see
  [DEBUGGING.md](DEBUGGING.md#known-issues)
- **Dashboard** — inline-button home hub and per-entity cards (see
  [docs/dashboard.md](docs/dashboard.md))
- **Behavioral learning** — infers active hours, tone, and per-category
  reminder intervals from usage patterns
- **Debug/admin tooling** — bug reporting, self-test checklist, single-owner
  admin lock, read-only SQL console

## Tech stack

- Python 3.12
- `python-telegram-bot` 20.7 (async, job-queue-based scheduler)
- SQLite (`planner.db` for app data, `bugs.db` for the debug system)
- NVIDIA NIM via an OpenAI-compatible client (`openai` SDK)
- `httpx` — **pinned to 0.25.2**; newer versions break `python-telegram-bot` 20.7
- Timezone: IST (`Asia/Kolkata`) everywhere user-facing; system clock is UTC

## Repo map

See [ARCHITECTURE.md](ARCHITECTURE.md#module-map) for the annotated version
with responsibilities and known dead code.

## Who this is for

A single-owner personal-assistant bot. Multi-user data isolation exists
(everything is scoped by Telegram `user_id`), but the admin panel and
`/claimadmin` lock are single-owner by design — see
[docs/telegram_integration.md](docs/telegram_integration.md#admin-lock).
