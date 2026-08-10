# 🤖 BAKA — AI Personal Assistant (Telegram)

**Behavioral Adaptive Knowledge Assistant** — an offline-first AI Telegram bot that manages your tasks, deadlines, habits, goals, and hobby/build projects through natural conversation in **English, Hindi, and Hinglish**.

> BAKA doesn't just remind you — it **owns your tasks until they're done**, learns your patterns, and handles its deterministic core without ever calling an AI.

> 📚 This README is the quick-start guide. For full documentation —
> architecture, command reference, database schema, known issues, and
> more — start at [CLAUDE.md](CLAUDE.md) or [PROJECT.md](PROJECT.md).
> Current version: **v15.1.0-alpha.12** — see [CHANGELOG.md](CHANGELOG.md).

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
| Routing Layer | `core/routing/` | Confidence policy + decision logging ([DRG-001](docs/history/DRG-001_Intent_Aware_Routing.md)) |
| Offline Engine | `core/offline/` | Registry-based dispatch to pure actions ([ADR-012](docs/adr/ADR-012-registry-based-dispatch.md)) |
| Action Registry | `core/offline/registry.py` | Per-intent ordered specs; per-domain construction ([ADR-013](docs/adr/ADR-013-per-domain-registry-construction.md)) |
| Actions | `core/actions/` | Task + Habit domains, feature-complete, Legacy-equivalent |
| Storage Facade | `core/storage/` | Thin, zero-logic delegation to `database.py` |
| Feature Flags | `core/feature_flags.py` | `OFFLINE_TASKS` / `OFFLINE_HABITS` / `OFFLINE_GOALS` / `OFFLINE_PROJECTS` — all default OFF |

Design decisions live in [docs/adr/](docs/adr/) (ADR-001…013); the
architecture deep-dive is [ARCHITECTURE.md](ARCHITECTURE.md). Behavioral
equivalence with Legacy is enforced by a 700+-test suite
([TESTING.md](TESTING.md)) with query-count and row-level parity checks.

### 🧱 Workspace OS — Foundation · Engine · Projects · Timeline · Sync · AI Orchestrator (v15.0-beta.1 — flag-gated, wired into production)

As of **beta.1** the completed backend is **wired into the running bot**
behind `WORKSPACE`: **OFF ⇒ byte-identical to v14.26**; **ON ⇒** free-text
messages flow `Interpreter → Orchestrator → Entity Engine → Timeline →
Sync → Telegram`, and a repeating job on the existing scheduler drains the
sync outbox off the event loop. The AI (`LLMInterpreter`) and the Telegram
sender are injected, so the offline suite stays AI/Telegram-free.


The next evolution, the **Workspace OS**, turns Projects/Books/Games/
Courses/Goals/Memory into one **Workspace** abstraction differentiated
only by a **Template** (full design: [docs/v15/](docs/v15/)). Alpha lands
the *backend only* — no user-facing features yet — behind a new
`WORKSPACE` flag (default **OFF**). With the flag off it is completely
inert: empty tables, no handlers, byte-identical to v14.

| Component | Where | What it does |
|---|---|---|
| Schema | `database.py` | `workspaces` / `milestones` / `notes` / `attachments` / `tags` (+ nullable `workspace_id` on tasks/goals/memories); additive & idempotent |
| Storage Facade | `core/storage/` | `WorkspaceStorage` / `MilestoneStorage` / `NoteStorage` — thin delegation |
| Models | `core/workspace/models.py` | Frozen `Workspace` / `Milestone` / `Note` dataclasses |
| Repository | `core/workspace/repository.py` | Typed CRUD over the facade (tuples → models) |
| **Entity Engine** | `core/workspace/engine.py` | **Reusable core: ownership + input validation, lifecycle enforcement, and an event seam — the single choke-point for entity mutations. Milestones support archive + soft-delete (`deleted_at`, row retained)** |
| Lifecycle | `core/workspace/lifecycle.py` | Declarative state machines (workspace / milestone transitions, incl. `archived`) |
| Errors | `core/workspace/errors.py` | Typed refusals: `EntityNotFound` / `EntityValidationError` / `InvalidTransition` |
| Service | `core/workspace/service.py` | Use-cases on top of the engine: flag-gated migration/bootstrap, Inbox |
| Templates | `core/workspace/templates/` | `WorkspaceTemplate` registry (composition, not inheritance) + built-ins |
| **Project Adapter** | `core/workspace/project_adapter.py` | **Routes v14 Projects through the Workspace layer (goal ↔ `template='project'` workspace) — data referenced, not moved; progress stays the v14 materials/worklog computation** |
| **Timeline** | `core/workspace/timeline.py` + `events.py` | **Append-only Knowledge Timeline: `TimelineEngine` subscribes to the engine's `EntityEvent` hook and persists one immutable `timeline_events` row per mutation** |
| **Sync Engine** | `core/workspace/sync.py` | **Reliable outbound sync (TWID outbox): durable `sync_outbox`, idempotent enqueue, oldest-first drain with bounded retries; `SyncAdapter` contract** |
| **Telegram Adapter** | `core/workspace/adapters/telegram.py` | **First `SyncAdapter` — renders a timeline event to Telegram HTML and delivers through an injected sender (no live-bot import)** |
| **AI Orchestrator** | `core/workspace/orchestrator.py` | **Generic NL → validated engine op: interpret → select workspace → resolve entity → safety gate → apply. AI injected as an `Interpreter` (no live LLM import); template-agnostic** |
| **LLM Interpreter** | `core/workspace/llm_interpreter.py` | Production `Interpreter` over `baka_brain` (lazy) → JSON `Proposal`; falls back to `RuleBasedInterpreter` on any AI failure |
| **Production wiring** | `core/workspace/app.py` | `process_message` (handler entry), `SyncWorker` + `register_workers` (scheduler), `make_telegram_sender` (async bridge) — all flag-gated |
| **Templates** (Game 🎮, Knowledge 🧠, Asset 📦, Project 🛠) | `core/workspace/templates/*.py` | Each Workspace type is one drop-in module — schema + validation + a registered `WorkspaceTemplate` — added **without touching the OS**. `game.py` (🎮) is the reference; `knowledge.py` (🧠) an educational domain; `asset.py` (📦) one reusable template for **any** physical asset (kind = `metadata['asset_type']`); `project.py` (🛠) an execution-focused project (milestone pipeline, `PROGRESS_MILESTONES`); future ones follow it too |
| Feature flag | `core/feature_flags.py` | `WORKSPACE` — default OFF (activates the whole pipeline when ON) |

**Adding a Workspace type** (the beta.2 pattern, `game.py`): declare a
metadata schema + validation rules, `register(WorkspaceTemplate(...))`, and
a thin validating `create_*` helper that calls the unchanged
`engine.create_workspace(..., template=<key>)`. Game concepts reuse the
generic entities (objectives → milestones, notes → notes, completion% →
`metadata` via the `PROGRESS_MANUAL` model) — no new tables, no OS changes.
**`knowledge.py` (beta.3)** is the second application of this exact pattern
to an educational/knowledge domain (concepts → milestones, sources/notes →
notes, mastery% → `metadata`). **`asset.py` (beta.4)** is the third and
broadest: one reusable template for **any** physical asset — the kind is
just `metadata['asset_type']` (vehicle/computer/drone/…), maintenance →
milestones, service records → notes, components → tags, and maintenance
completion via `PROGRESS_MILESTONES`. **`project.py` (beta.5)** applies it
to an execution-focused project (Research→Documentation milestone pipeline,
execution % via `PROGRESS_MILESTONES`) and took ownership of the `project`
template out of `builtin.py`, shape preserved so the `ProjectAdapter` bridge
is unaffected. Four independent drop-in templates now coexist, confirming
the extension model — and the **Workspace OS is frozen**.

When `WORKSPACE` is ON, a Project is a `template='project'` workspace whose
backing goal (via `goals.workspace_id`) still owns its materials/worklog —
so `ProjectAdapter` returns values identical to the legacy `/projects`
path (proven by `tests/test_workspace_project_integration.py`). The
production handler swap that consumes this is a later, user-facing phase.

### Supported Workspace templates

Each template is one self-contained module in
`core/workspace/templates/`; adding one requires **no change to the
Workspace OS** (schema, engine, orchestrator, timeline, sync).

| Template | Icon | Domain | Progress model | Where |
|---|---|---|---|---|
| Generic | 📁 | Fallback / Inbox | milestones | `builtin.py` |
| Project | 🛠 | Execution (milestone pipeline) | milestones | `project.py` |
| Book | 📖 | Reading tracker | chapters | `builtin.py` |
| Course | 🎓 | Study / modules | checklist | `builtin.py` |
| Research | 🔬 | Questions & findings | manual | `builtin.py` |
| Game | 🎮 | Playthrough tracker (reference) | manual | `game.py` |
| Knowledge | 🧠 | Learning / mastery | manual | `knowledge.py` |
| Asset | 📦 | Any physical asset (kind = metadata) | milestones | `asset.py` |

---

## 📔 Project Groups — your Telegram photo journal (v15.1)

Mirror a **project / game / goal** to a **private Telegram forum group**,
where **each entity is its own topic** and the **photos + notes you send
become a scrollable progress journal**. The database is the source of
truth; the group is the human-readable mirror.

```
/newgame Genshin          → creates the workspace, makes it active
(make a private group, enable Topics, add the bot as admin)
/linkhere                 → (sent in the group) binds it to Genshin
/add Hu Tao               → creates a "Hu Tao" topic in the group
📷 + "got her crown"      → logs it to Hu Tao's topic (photo + note)
/open Nahida  ·  /current ·  /workspaces  ·  /note <text>
```

Architecture note: the Workspace OS never learns about Telegram — chat/topic
ids live only in the adapter's binding tables, and topics are a
*visualization* of entities created by the projection adapter. These
commands are always available and are **not** tied to the `WORKSPACE` flag
below. First slice; editing/removal and richer entities come next.

### 🧠 Ask about your workspaces (Cognitive Engine, v15.1.0-alpha.3)

```
/ws which component is blocked in Drone?
/ws how far along is Drone?
open Drone   →   /ws what's left to do?      (remembers the active workspace)
```

`/ws` (alias `/query`) reasons over your **real** Workspace data: an LLM
**planner** picks which grounded tool answers the question, the **executor**
runs it against the Workspace APIs, and the answer is composed **only from
facts** — so it can't make Workspace data up (if something doesn't exist, it
says so). No feature-specific commands needed. Phase 1 covers read
questions; write-action planning and full free-text routing come next.

### 🗣 Natural Language Entity Management (v15.1.0-alpha.11, conversational references v15.1.0-alpha.12)

With an active workspace open, just chat naturally:

```
Create character Furina               → creates a new entity
Hu Tao is level 80                    → updates entity field
Furina uses Fleuve Cendre Ferryman    → sets weapon name (weapon ≠ weapon_type)
Show Furina                           → displays entity card with all fields
Show all level 90 characters          → retrieves matching entities
Who uses Polearm?                     → searches entity fields
Show Hydro characters                 → filters by element
Show high priority characters         → filters by priority
Open Furina · View Furina · Display   → entity detail display variants
```

**Conversational references** (v15.1.0-alpha.12) — after you've created or
viewed an entity, follow up with pronouns and ordinals instead of names:

```
Show her · Show him · Show it         → the last entity you touched
Show the first one · second one       → an entity from the last list shown
Show the last one                     → the last item of that list
Set her level to 90                   → updates the active entity (no name needed)
```

The last entity you created/viewed/updated becomes the **active entity**;
the last list you were shown is remembered for ordinal navigation. When a
pronoun is genuinely ambiguous the bot asks which one you mean — it never
guesses. References resolve deterministically (no AI call), so they work
even when the fast model would misread them.

The `EntityManager` (`core/ai/entity_manager.py`) interprets free text using
the fast AI model, maps it to the active workspace's template-defined fields
(level, element, priority, etc.), and applies changes through the Entity
Engine — no commands, no JSON, no developer tools. Non-entity messages fall
through to the regular AI chat untouched. Template-agnostic: works with
game, knowledge, asset, project, and any future workspace type.

---

## 🚩 Feature flags

Every major capability ships **dark behind a flag** (default OFF) so a new
release is byte-identical to the previous one until explicitly enabled —
the same rollout discipline used since v14. Set them in `.env`.

| Flag | Default | Enables |
|---|---|---|
| `WORKSPACE` | OFF | The entire v15 Workspace OS pipeline (Interpreter → Orchestrator → Entity Engine → Timeline → Sync). OFF ⇒ dormant, empty tables, byte-identical to v14.26. |
| `OFFLINE_TASKS` | OFF | Deterministic offline handling of task commands (no AI round-trip). |
| `OFFLINE_HABITS` | OFF | Deterministic offline handling of habit commands. |
| `OFFLINE_GOALS` / `OFFLINE_PROJECTS` | OFF | Reserved for the goals/projects offline migration. |

With all flags OFF the bot runs the proven v14 Legacy paths. Enable one at
a time and re-run the suite in both states — the acceptance gate is that
every existing test stays green with the flag OFF **and** ON.

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
AI_API_KEY=your_provider_key_here        # NVIDIA_API_KEY also still works
# AI_BASE_URL=...                         # only needed to override a preset
# MODEL_MAIN=meta/llama-3.3-70b-instruct
# MODEL_FAST=meta/llama-3.1-8b-instruct
# MODEL_REASONING=meta/llama-3.3-70b-instruct
#
# --- Migrate to GLM 5.2 (pick one) ---
# GLM 5.2 on NVIDIA NIM (keep your NIM key):   MODEL_MAIN=z-ai/glm-5.2
# GLM-native (Zhipu):    AI_PROVIDER=glm  and  GLM_API_KEY=your_zhipu_key
# Local (Ollama/LM Studio/vLLM):              AI_PROVIDER=local
#
# Reliability (optional): AI_TIMEOUT=30   AI_MAX_RETRIES=3
# Chat timeouts — raise if a slow (reasoning) model like GLM 5.2 times out,
# lower for snappier fallback: TIMEOUT_FAST_CHAT=30  TIMEOUT_LONG_REASONING=90
# Hot chat path model — keeps replies snappy while GLM 5.2 does the reasoning
# (/think, /ws, plans). Default 'fast'; 'main' = GLM for chat too (if fast);
# or a model id, e.g. CHAT_MODEL=meta/llama-3.3-70b-instruct
# CHAT_MODEL=fast

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

> _Placeholder — screenshots to be added before public release. Drop PNGs
> in `docs/img/` and reference them here:_
>
> - `docs/img/dashboard.png` — the interactive dashboard hub
> - `docs/img/help.png` — the grouped `/help` reference
> - `docs/img/streak.png` — the 14-day habit streak grid
> - `docs/img/selftest.png` — the `/selftest` diagnostics report

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
| 🗂 Workspaces & Entities | `newproject / newgame / newgoal` · `workspaces` · `use <name>` · `add <name>` · `open <name>` · `current` · `note <text>` · `linkhere` · `ws <q>` — also **natural language**: _"Create character Furina"_ · _"Hu Tao is level 80"_ · _"Show all level 70 characters"_ |
| 🖼 Media | `image <prompt>` · `video <prompt>` · send a photo |
| 🗂 Memory & Tools | `memory` · `forget <key>` · `search <kw>` · `template` · `export` |
| ⚙️ Settings | `settings` · `quiethours` · `interval` · `wellness on/off` · `dashboard` · `commands` |
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
environment-configurable. As of **v15.1.0-alpha.2** the config is resolved
centrally by `core/ai/provider.py`, which ships named **presets** so
switching providers is one env var:

| `AI_PROVIDER` | Endpoint | Key | Default model |
|---|---|---|---|
| `nvidia-nim` (default) | NVIDIA NIM | `AI_API_KEY` / `NVIDIA_API_KEY` | **`z-ai/glm-5.2`** (fast-fallback: Llama-8b) |
| `glm` | Zhipu GLM (native) | `GLM_API_KEY` / `ZHIPU_API_KEY` | `glm-4.6` |
| `local` | Ollama / LM Studio / vLLM (`localhost:11434`) | none | `llama3.1` |

Every value stays overridable (`AI_BASE_URL`, `MODEL_MAIN`, `MODEL_FAST`,
`MODEL_REASONING`, `MODEL_VISION`, `AI_TIMEOUT`, `AI_MAX_RETRIES`); an unset
environment reproduces the historical NVIDIA-NIM defaults exactly.

**GLM 5.2 is the default main model on NVIDIA NIM** (`z-ai/glm-5.2`) as of
v15.1.0-alpha.4 — no env change needed. To pin a different model or provider:
```bash
# Different model on NIM:      MODEL_MAIN=meta/llama-3.3-70b-instruct
# GLM-native (Zhipu) instead:  AI_PROVIDER=glm  and  GLM_API_KEY=your_zhipu_key
```
Verify with `/selftest → AI → AI Configuration` (offline — shows the active
provider/model) and `AI Provider` (live liveness). Image and video
generation still use NVIDIA's genai endpoints directly — making media
provider-agnostic is later AI-Router scope. The reliability primitives
(`core/ai/reliability.py`) and the retrieval/tool interfaces
(`core/ai/retrieval.py`, `core/ai/tools.py`) are foundations for the
upcoming AI Intelligence Layer.

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
├── core/                 — v14 Autonomous Core + v15 Workspace OS
│   ├── intent/           — Intent Engine (deterministic classifier)
│   ├── routing/          — Routing Layer (decision logging)
│   ├── offline/          — Offline Engine + ActionRegistry + registrations
│   ├── actions/          — Task + Habit action modules (pure, facade-only)
│   ├── storage/          — Storage Facade
│   ├── selftest/         — Live health-probe framework (/selftest)
│   ├── regression/       — Manual Quick Release Suite specs
│   ├── workspace/        — v15 Workspace OS (engine, timeline, sync, templates/)
│   └── feature_flags.py  — Per-domain + WORKSPACE rollout flags
├── baka_brain.py         — AI client (provider-agnostic config), reasoning
├── database.py           — SQLite CRUD + all migrations
├── date_parser.py        — Regex date/time parser (EN/Hindi/Hinglish)
├── scheduler.py          — Reminder engine (snooze/escalation/quiet-hours)
├── conversation_state.py — State machine (idle/gathering/confirming/editing)
├── log_sanitizer.py      — Secret masking for bot.log
├── fmt.py                — Telegram HTML helpers
├── ui.py / debug_system.py / preferences.py / notification_service.py
├── tests/                — 1100+ offline tests (pytest)
├── docs/
│   ├── adr/              — ADR-001 … ADR-013 (design decisions)
│   ├── architecture/     — Subsystem deep-dives (intent, routing, offline, …)
│   ├── history/          — Point-in-time v14 design & audit records
│   └── v15/              — Workspace OS design docs (WED · TWID · KTD · AWOD · MIGRATION)
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
| v15.0-alpha.1–7 | Workspace OS backend (ships dark): schema, Entity Engine, Project integration, Milestones, Timeline, Sync, AI Orchestrator |
| v15.0-beta.1–5 | Workspace OS wired into production (flag-gated) + Game/Knowledge/Asset/Project templates |
| v15.0-rc.1 | Release-candidate hardening: documentation consolidation, repository cleanup, README + help polish |

Early history (v1–v11) and full detail per version:
[CHANGELOG.md](CHANGELOG.md). Planned work: [ROADMAP.md](ROADMAP.md)
(next: canary-enable `WORKSPACE` → default-on, then user-facing Workspace
commands/UI and more templates).

---

## ⚠️ Important Notes

- **httpx must be pinned to 0.25.2** — newer versions break python-telegram-bot 20.7
- **All datetime must use IST** — system clock is UTC, never use bare `datetime.now()`
- **`.env` is gitignored** — never commit it; re-create after cloning
- **`admin_id.txt` is gitignored** — run `/claimadmin` after fresh deploy
- **Offline flags default OFF** — flag-off behavior is byte-identical to Legacy

---

## 🧪 Testing

```bash
source venv/bin/activate
pytest -q                       # full offline suite (~20s)
pytest tests/test_workspace_*   # just the Workspace OS suites
```

- **1100+ offline unit/integration tests** — deterministic, and they
  **never touch Telegram or a live AI provider** (senders and the AI
  interpreter are dependency-injected in tests). See [TESTING.md](TESTING.md).
- **`/selftest`** — a live health probe (database, scheduler, storage,
  routing, AI provider) run in-app by the owner; see
  [docs/selftest.md](docs/selftest.md).
- **Manual Quick Release Suite** — the owner-run `/debug → Run Tests`
  regression walk; specs in `core/regression/` ([docs/regression.md](docs/regression.md)).
- **Acceptance gate:** the suite must stay green with every feature flag
  **OFF and ON**, so a dark-shipped capability provably changes nothing
  until enabled.

---

## 🗺 Roadmap

Near-term work and the full backlog live in [ROADMAP.md](ROADMAP.md).
Highlights: canary-enable the `WORKSPACE` flag → default-on, add
user-facing Workspace commands/UI, and more Workspace templates
(Finance, Personal Knowledge, …) following the frozen extension pattern.

---

## 🤝 Contributing

1. Read [CLAUDE.md](CLAUDE.md) (project conventions) and
   [ARCHITECTURE.md](ARCHITECTURE.md) (how the pieces fit).
2. Follow the **Definition of Done** in [CLAUDE.md](CLAUDE.md): a
   user-visible feature ships with production code, regression + self-test
   coverage, `/help` + `/start` updates, and CHANGELOG/README/docs — in one
   change-set.
3. Keep new capabilities **additive and flag-gated** so flag-OFF behavior
   is byte-identical to the prior release.
4. Run `pytest -q` before every commit; add tests for new behavior (never
   rewrite the regression suite — grow it).
5. House rules: all datetime is **IST**; user-facing text is **Telegram
   HTML via `fmt.py`** (never hand-rolled); every DB write goes through
   `database.py`; secrets stay in `.env`; `httpx` stays pinned to `0.25.2`.

---

## 🙏 Acknowledgements

- [python-telegram-bot](https://python-telegram-bot.org/) — the Telegram framework (pinned to 20.7).
- [NVIDIA NIM](https://build.nvidia.com) — the default OpenAI-compatible AI provider (free tier).
- SQLite — the single-file, zero-config datastore the whole bot runs on.

---

## 📜 License

MIT — build on it freely.
