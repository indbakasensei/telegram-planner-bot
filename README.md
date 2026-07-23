# 🤖 BAKA — AI Personal Assistant (Telegram)

**Behavioral Adaptive Knowledge Assistant** — an offline-first AI Telegram bot that manages your tasks, deadlines, habits, goals, and hobby/build projects through natural conversation in **English, Hindi, and Hinglish**.

> BAKA doesn't just remind you — it **owns your tasks until they're done**, learns your patterns, and handles its deterministic core without ever calling an AI.

> 📚 This README is the quick-start guide. For full documentation —
> architecture, command reference, database schema, known issues, and
> more — start at [CLAUDE.md](CLAUDE.md) or [PROJECT.md](PROJECT.md).
> Current version: **v15.0-alpha.1** — see [CHANGELOG.md](CHANGELOG.md).

---

## ✨ What makes BAKA different

| Feature | Other reminder bots | BAKA |
|---------|---------------------|------|
| Language | English only | English + Hindi + Hinglish |
| Core commands | Round-trip to an AI | **Offline-first**: deterministic engine, zero AI calls, sub-2ms |
| Reminders | Fires once | Persists until done, escalates |
| Intelligence | Rule-based | Configurable AI provider for planning/reasoning |
| Learning | None | Learns your patterns, active hours, tone |
| Deadlines | At the time | **Before** — warns 7d/3d/1d/6h/1h ahead |
| Habits | Not built-in | Full habit engine with streaks + grid |
| Dashboard | None | Interactive hub with inline buttons |
| Photos | Not supported | Vision model describes images / extracts todos |

---

## 🏗 Architecture (v14 — Autonomous Core)

Every free-text message flows through a staged, feature-flag-gated
pipeline. With all flags OFF the bot behaves exactly like the pre-v14
Legacy bot; each flag moves one domain onto the deterministic path.

```
            Telegram message
                   │
                   ▼
        Conversation State ──── claims it? ──▶ state machine (confirm / gather / edit)
                   │ idle
                   ▼
             Intent Engine        deterministic classifier (no AI, no network)
                   │
                   ▼
             Routing Layer        confidence policy → destination recommendation
                   │
                   ▼
            Offline Engine        ActionRegistry → registered action → Storage Facade
                   │ unmatched
                   ▼
                Legacy            original handlers + AI (NL understanding, planning)
```

| Component | Where | What it does |
|---|---|---|
| Intent Engine | `core/intent/` | Tiered deterministic classification (11 intents) |
| Routing Layer | `core/routing/` | Confidence policy + decision logging ([DRG-001](DRG-001_Intent_Aware_Routing.md)) |
| Offline Engine | `core/offline/` | Registry-based dispatch to pure actions ([ADR-012](docs/adr/ADR-012-registry-based-dispatch.md)) |
| Action Registry | `core/offline/registry.py` | Per-intent ordered specs; per-domain construction ([ADR-013](docs/adr/ADR-013-per-domain-registry-construction.md)) |
| Actions | `core/actions/` | Task + Habit domains, feature-complete, Legacy-equivalent |
| Storage Facade | `core/storage/` | Thin, zero-logic delegation to `database.py` |
| Feature Flags | `core/feature_flags.py` | `OFFLINE_TASKS` / `OFFLINE_HABITS` / `OFFLINE_GOALS` / `OFFLINE_PROJECTS` — all default OFF |

Design decisions live in [docs/adr/](docs/adr/) (ADR-001…013); the
architecture deep-dive is [ARCHITECTURE.md](ARCHITECTURE.md). Behavioral
equivalence with Legacy is enforced by a 700+-test suite
([TESTING.md](TESTING.md)) with query-count and row-level parity checks.

### 🧱 Workspace Foundation (v15.0-alpha.1 — dormant)

The next evolution, the **Workspace OS**, turns Projects/Books/Games/
Courses/Goals/Memory into one **Workspace** abstraction differentiated
only by a **Template** (full design: [docs/v15/](docs/v15/)). `alpha.1`
lands the *foundation only* — no user-facing features yet — behind a new
`WORKSPACE` flag (default **OFF**). With the flag off it is completely
inert: empty tables, no handlers, byte-identical to v14.

| Component | Where | What it does |
|---|---|---|
| Schema | `database.py` | `workspaces` / `milestones` / `notes` / `attachments` / `tags` (+ nullable `workspace_id` on tasks/goals/memories); additive & idempotent |
| Storage Facade | `core/storage/` | `WorkspaceStorage` / `MilestoneStorage` / `NoteStorage` — thin delegation |
| Models | `core/workspace/models.py` | Frozen `Workspace` / `Milestone` / `Note` dataclasses |
| Repository | `core/workspace/repository.py` | Typed CRUD over the facade (tuples → models) |
| Service | `core/workspace/service.py` | Template application, progress rollup, flag-gated migration/bootstrap |
| Templates | `core/workspace/templates/` | `WorkspaceTemplate` registry (composition, not inheritance) + built-ins |
| Feature flag | `core/feature_flags.py` | `WORKSPACE` — default OFF |

---

## 🚀 Quick Setup

### Prerequisites
- Python 3.12+
- A Telegram account
- An OpenAI-compatible AI provider key (default: [NVIDIA NIM](https://build.nvidia.com), free tier)

### 1. Clone and install

```bash
git clone https://github.com/indbakasensei/telegram-planner-bot
cd telegram-planner-bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Get your tokens

**Telegram Bot Token:**
```
Open Telegram → @BotFather → /newbot → copy the token
```

**AI provider key:** any OpenAI-compatible endpoint works (NVIDIA NIM,
GLM, …).

### 3. Create `.env`

```bash
cat > .env << 'EOF'
BOT_TOKEN=your_telegram_bot_token_here

# AI provider (defaults shown; all optional — unset = NVIDIA NIM)
AI_PROVIDER=nvidia-nim
AI_BASE_URL=https://integrate.api.nvidia.com/v1
AI_API_KEY=your_provider_key_here        # NVIDIA_API_KEY also still works
# MODEL_MAIN=meta/llama-3.3-70b-instruct
# MODEL_FAST=meta/llama-3.1-8b-instruct
# MODEL_REASONING=meta/llama-3.3-70b-instruct

# Offline Engine rollout flags (default OFF — Legacy behavior)
# OFFLINE_TASKS=true
# OFFLINE_HABITS=true

# Workspace OS (v15) master flag (default OFF — dormant foundation)
# WORKSPACE=true
EOF
```

### 4. Run

```bash
python3 main.py
```

### 5. Claim admin (first run)

In Telegram, send `/claimadmin` — this locks admin access permanently to your Telegram ID.

---

## 📸 Screenshots

> *(placeholders — add before public release)*

| | |
|---|---|
| ![Dashboard](docs/img/dashboard.png) *Dashboard* | ![Help](docs/img/help.png) *Redesigned /help* |
| ![Streak grid](docs/img/streak.png) *Habit streaks* | ![Selftest](docs/img/selftest.png) */selftest diagnostics* |

---

## 💬 Just Talk

No commands needed. Just type naturally:

```
"Remind me to submit assignment by Friday 5pm"    → saves as deadline, warns 7d/3d/1d/6h/1h before
"Kal subah 8 baje gym yaad dila dena"             → tomorrow 08:00 task
"Go to gym every day at 6 AM"                     → daily habit with streak tracking
"I want to read 12 books this year"               → goal with progress dashboard
"think what should I focus on today?"             → AI reasons with your actual task list
"search physics"                                  → finds tasks + memories + habits + goals
```

Slash is optional for every command:
```
/list  =  list  =  "show my tasks"
/done 5  =  done 5
```

`/help` shows the full grouped command reference in-app. The complete,
verified-against-code list is in [API.md](API.md#command-reference).

---

## 📋 Command Highlights

| Domain | Commands |
|---|---|
| 📌 Tasks | `list` · `today` · `week` · `add task <t>` · `done <id>` · `edit <id>` · `delete <id>` · `deadline <id>` |
| 🔔 Reminders | `snooze <id> <min>` · `pause`/`resume <id>` · `paused` · `overdue` · `carryforward` · `review` |
| 🌱 Habits | `habits` · `streak <id>` · `habitlog <id>` · `addhabit <t>` · `skiphabit <id>` · `done <id>` |
| 🎯 Goals & Projects | `goals` · `projects` · `project <id>` · `need` · `got` · `worklog` · `started`/`finished` · `shopping` |
| 🧠 AI & Planning | `think <q>` · `plan today/week` · `breakdown <id>` · `reschedule <id>` · `analyze` · `insights` |
| 🖼 Media | `image <prompt>` · `video <prompt>` · send a photo |
| 🗂 Memory & Tools | `memory` · `forget <key>` · `search <kw>` · `template` · `export` |
| ⚙️ Settings | `settings` · `quiethours` · `interval` · `wellness on/off` · `dashboard` |
| 🛠 Diagnostics | `status` · `selftest` · `report <issue>` · `bugs` · `trace` |
| 🔑 Setup | `claimadmin` (become owner, first run) · `myid` (your Telegram ID) |

### 🛠 Developer Center (owner only, `/debug`)

`/debug` opens an admin-only Developer Center — silent "Unknown command"
for everyone else. Inside:

- **🧪 Self Test** — a live health check (database, scheduler, storage,
  routing, AI provider, …); "Run All" reports PASS/WARNING/FAIL per check.
- **🧯 Run Tests** — the manual regression runner: walks the Quick
  Release Suite (44 tests) one at a time with **Pass / Fail / Skip**; a
  Fail prompts for a note and logs a bug (`DBG-####`), then a summary.
- **🐞 Debug toggle** — the old intent/entity tracer, now a menu button.

Bug reports use independent `DBG-####` ids (never task ids).

> **What's new (v14.21 → v14.25):** DBG-prefixed bug ids + a dedicated
> `debugbot.log`; the `/debug` Developer Center; the Self-Test framework;
> and the manual Run-Tests regression runner. No new *user* commands were
> added in this range — these are owner/diagnostic tools. Full history:
> [CHANGELOG.md](CHANGELOG.md).

Admin commands exist but deny silently for non-admins (deliberate
obscurity) — the admin sees them in `/help`.

---

## 🤖 AI Configuration

All chat/reasoning AI goes through one OpenAI-compatible client in
`baka_brain.py`; the provider, endpoint, key, and every model id are
environment-configurable (`AI_PROVIDER`, `AI_BASE_URL`, `AI_API_KEY`,
`MODEL_MAIN`, `MODEL_FAST`, `MODEL_REASONING`, `MODEL_VISION`, …).
Unset variables fall back to the verified NVIDIA NIM defaults. Image and
video generation still use NVIDIA's genai endpoints directly — making
media provider-agnostic is v15 AI Router scope.

The old stored-analytics commands (`usage`, `performance`, `errors`)
return empty data — the pipeline behind them was never assembled, and
its stranded source files were removed in v14.12. `status` /
`status full` (live benchmarks) work. See
[DEBUGGING.md](DEBUGGING.md#known-issues).

---

## 🗄️ File Structure

```
telegram-planner-bot/
├── main.py               — Handlers, dashboard, state machine, integration point
├── core/                 — v14 Autonomous Core
│   ├── intent/           — Intent Engine (deterministic classifier)
│   ├── routing/          — Routing Layer (decision logging)
│   ├── offline/          — Offline Engine + ActionRegistry + registrations
│   ├── actions/          — Task + Habit action modules (pure, facade-only)
│   ├── storage/          — Storage Facade
│   └── feature_flags.py  — Per-domain rollout flags
├── baka_brain.py         — AI client (provider-agnostic config), reasoning
├── database.py           — SQLite CRUD + all migrations
├── date_parser.py        — Regex date/time parser (EN/Hindi/Hinglish)
├── scheduler.py          — Reminder engine (snooze/escalation/quiet-hours)
├── conversation_state.py — State machine (idle/gathering/confirming/editing)
├── log_sanitizer.py      — Secret masking for bot.log
├── fmt.py                — Telegram HTML helpers
├── ui.py / debug_system.py / preferences.py / notification_service.py
├── tests/                — 700+ offline tests
├── docs/adr/             — ADR-001 … ADR-013
├── .env                  — Secrets (gitignored)
└── planner.db            — Main database (gitignored)
```

Full annotated module map: [ARCHITECTURE.md](ARCHITECTURE.md#module-map).

---

## 🔄 Version History (recent)

| Version | Highlights |
|---------|-----------|
| v12.0 | Project management — materials, worklog, progress tracking |
| v13.x | Production hardening, notification service, async bridge, log sanitizer |
| v14.0–14.1 | Intent Engine (shadow mode), Routing Layer, Storage Facade, feature flags |
| v14.2–14.7 | Task domain migrated: reads, create, update, delete, complete, lifecycle |
| v14.8 | Registry-based dispatch (ADR-012) |
| v14.9–14.11 | Habit domain migrated: views, create/skip, completion |
| v14.12 | Production readiness: ADR-011 state priority, rich UI, token masking, cleanup |

Early history (v1–v11) and full detail per version:
[CHANGELOG.md](CHANGELOG.md). Planned work: [ROADMAP.md](ROADMAP.md)
(next: canary enablement of the offline flags, then v15 — AI Router,
Goals/Projects domains, plugins).

---

## ⚠️ Important Notes

- **httpx must be pinned to 0.25.2** — newer versions break python-telegram-bot 20.7
- **All datetime must use IST** — system clock is UTC, never use bare `datetime.now()`
- **`.env` is gitignored** — never commit it; re-create after cloning
- **`admin_id.txt` is gitignored** — run `/claimadmin` after fresh deploy
- **Offline flags default OFF** — flag-off behavior is byte-identical to Legacy

---

## 📜 License

MIT — build on it freely.
