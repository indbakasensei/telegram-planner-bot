# BAKA Telegram Bot — System Architecture Baseline

**Document Version:** 1.0  
**Commit Baseline:** `c35cbd0` (v15.5 M7)  
**Status:** Engineering Baseline & Implementation Contract  
**Generated:** 2026-08-20  

---

## Executive Summary

BAKA (Behavioral Adaptive Knowledge Assistant) is a **single-process, single-event-loop** Telegram personal-assistant bot written in Python 3.11+. It runs as a long-lived polling bot (no webhook) with APScheduler for background jobs.

The codebase contains **two major architectural generations** running simultaneously behind feature flags:

| Generation | Codename | Scope | Flag | Default |
|------------|----------|-------|------|---------|
| **v14** | Autonomous Core | Intent Engine (5-tier), Routing Layer (shadow mode), Offline Engine, Action Registry | `OFFLINE_TASKS`, `OFFLINE_HABITS`, `OFFLINE_GOALS`, `OFFLINE_PROJECTS` | `OFF` |
| **v15** | Workspace OS | Entity Engine, Milestone hierarchy, Knowledge Timeline, Sync Engine, AI Orchestrator, Manual Control Plane | `WORKSPACE`, `WORKER` | `OFF` |

**All v14/v15 infrastructure ships complete but dormant.** With all flags `OFF` (factory default), the bot behaves byte-identically to the legacy v13 planner bot. This document describes the **full superset** — what exists in the repo at commit `c35cbd0` — regardless of flag state.

---

## 1. High-Level Component Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            TELEGRAM UPDATES                                   │
│                         (polling via python-telegram-bot)                     │
└────────────────────────────────────┬──────────────────────────────────────────┘
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              MAIN.PY                                          │
│  ┌─────────────┐  ┌──────────────────┐  ┌────────────────────────────────┐  │
│  │ Dispatcher  │──│ ConversationState │──│ Instance Lock (single process) │  │
│  │ + Handlers  │  │ (in-memory dicts)   │  │ (instance_lock.py)           │  │
│  └──────┬──────┘  └──────────────────┘  └────────────────────────────────┘  │
└─────────┼────────────────────────────────────────────────────────────────────┘
          │ handle_message(update, context)
          ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        MESSAGE CASCADE (main.py:handle_message)               │
│                                                                              │
│  1. /claimadmin (owner bootstrap)                                           │
│  2. is_admin() gate for admin commands                                      │
│  3. ConversationState.claims_messages() — ADR-011 Option A                 │
│     (interactive state ownership: confirming/gathering/editing)            │
│  4. IntentEngine.classify() → 5-tier rule-based classification             │
│  5. RoutingLayer.route() → ALWAYS Destination.LEGACY (shadow mode)         │
│  6. OfflineEngine.execute() — if intent in OFFLINE_ENGINE_IMPLEMENTED_INTENTS│
│     AND corresponding feature flag ON                                       │
│  7. AI Worker (core/ai/worker.py) — if WORKER=1 AND is_admin(user)        │
│  8. Legacy fallback (baka_brain.call_main)                                 │
└─────────┬────────────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           LAYERING ARCHITECTURE                               │
│                                                                              │
│   ┌──────────────┐     ┌─────────────────┐     ┌──────────────────────┐    │
│   │  AI Worker   │────▶│  ToolRegistry   │◀────│  Manual Control Plane │    │
│   │ (LLM loop)   │     │ (63 tools)      │     │ (ctl: callbacks)      │    │
│   └──────────────┘     └────────┬────────┘     └──────────┬───────────┘    │
│                                 │                          │               │
│                                 ▼                          ▼               │
│                        ┌─────────────────┐         ┌───────────────┐       │
│                        │ Domain Services │         │ Domain Services│       │
│                        │ (TaskStorage,   │         │ (EntityEngine, │       │
│                        │  HabitStorage,  │         │  MilestoneSvc, │       │
│                        │  GoalStorage,   │         │  KnowledgeSvc) │       │
│                        │  MemoryStorage) │         └───────┬───────┘       │
│                        └────────┬────────┘                 │               │
│                                 │                          │               │
│                                 ▼                          ▼               │
│                        ┌──────────────────────────────────────────┐       │
│                        │           DATABASE.PY (SQLite)            │       │
│                        │  42 tables, 10 indexes, WAL mode,        │       │
│                        │  SCHEMA_VERSION=2, idempotent migrations │       │
│                        └──────────────────────────────────────────┘       │
│                                                                              │
│                        ┌──────────────────────────────────────────┐       │
│                        │         TELEGRAM API (httpx)              │       │
│                        │  notification_service.TelegramSender      │       │
│                        │  (rate-limited, flood-aware, sanitized)   │       │
│                        └──────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Layering Contract (Non-Negotiable)

**Rule:** All outbound effects flow through exactly one of two sanctioned entry points:

```
AI Worker (LLM)          Manual Control Plane (Human)
       │                        │
       ▼                        ▼
┌─────────────────────────────────────────┐
│           ToolRegistry                  │  ← Single source of truth for
│  (validates, executes, audits tools)    │     tool contracts & side effects
└─────────────────────────────────────────┘
       │                        │
       ▼                        ▼
┌──────────────┐         ┌──────────────┐
│ Domain Svc A │         │ Domain Svc B │  ← Business logic, invariants
│ (e.g. Task   │         │ (e.g. Entity │
│  Storage)    │         │  Engine)     │
└──────┬───────┘         └──────┬───────┘
       │                        │
       └───────────┬────────────┘
                   ▼
         ┌─────────────────┐
         │  database.py    │  ← Raw SQL, WAL, migrations
         │  (SQLite)       │
         └─────────────────┘
```

**Violations are architecture bugs.** No component bypasses `ToolRegistry`. No component imports `database.py` directly except `core/storage/storage.py` (the Storage facade).

---

## 3. Core Subsystems

### 3.1 Intent Engine (`core/intent/intent_engine.py`, `core/intent/rules.py`)

**Purpose:** Deterministic, rule-based intent classification — zero ML, zero external calls.

**5-Tier Classification Pipeline:**

| Tier | Name | Mechanism | Confidence | Example |
|------|------|-----------|------------|---------|
| 0 | Command Mirror | Exact match against `_PREFIX_COMMANDS` (96) + `_EXACT_COMMANDS` (49) | 1.0 | `/task`, `task buy milk` |
| 1 | Date/Time | Regex for relative dates, times, durations | 0.9 | "tomorrow 3pm", "in 2 hours" |
| 2 | Recurrence | Cron-like patterns, "every X" | 0.85 | "daily", "every monday" |
| 3 | Greeting/Help | Keyword sets (hi, hello, help, thanks) | 0.8 | "hey", "what can you do" |
| 4 | Keyword Heuristics | Domain keyword scoring (task, habit, goal, note, project) | 0.6–0.75 | "add a task to..." |
| 5 | UNKNOWN | Fallback | 0.0 | — |

**Output:** `IntentResult(intent: str, confidence: float, entities: dict, matched_pattern: str, trace_id: uuid4)`

**Duplication Debt:** Tier 0 mirrors `main.py`'s command lists (acknowledged in `rules.py` header). Single source of truth is `main.py`; `rules.py` imports at runtime.

**Logging:** `DEBUG` to `debugbot.log` with structured block (intent, confidence, entities, pattern, trace_id, latency_ms). Zero-cost when disabled (lazy `%-formatting`).

### 3.2 Routing Layer (`core/routing/router.py`, `core/routing/confidence.py`)

**Purpose:** Decision-logging only. **v14.1B Shadow Mode** — never changes behavior.

**Contract:**
```python
@dataclass
class RoutingDecision:
    intent: str
    confidence: float
    recommended_destination: Destination  # OFFLINE | LEGACY | CLARIFY
    actual_destination: Destination       # HARD-CODED Destination.LEGACY
    trace_id: uuid4
    fallback_reason: str
    clarification_required: bool
    decision_latency_ms: float
```

**Destination Enum:**
- `OFFLINE` — Offline Engine should handle
- `LEGACY` — Legacy handler (current behavior)
- `CLARIFY` — Ask user for clarification

**Thresholds** (`confidence.py`):
- `OFFLINE_THRESHOLD = 0.85`
- `CLARIFY_THRESHOLD = 0.60`
- Below 0.60 → `LEGACY` with `fallback_reason="low_confidence"`

**Offline-Implemented Intents Set** (checked at runtime):
`QUERY_TASK, ADD_TASK, EDIT_TASK, DELETE_TASK, QUERY_HABIT, ADD_HABIT, EDIT_HABIT, DELETE_HABIT, QUERY_GOAL, ADD_GOAL, EDIT_GOAL, DELETE_GOAL, QUERY_PROJECT, ADD_PROJECT, EDIT_PROJECT, DELETE_PROJECT`

**Logging:** `DEBUG` to `debugbot.log` — every decision includes recommended vs actual for shadow-mode analysis.

### 3.3 Offline Engine (`core/offline/engine.py`, `core/offline/registry.py`, `core/offline/registrations.py`)

**Purpose:** Deterministic, non-LLM action execution for high-confidence intents.

**Architecture:**
```
OfflineEngine (thin dispatcher)
    │
    ▼
ActionRegistry (ordered list of ActionSpec)
    │
    ├── match(intent, entities) → bool
    └── run(entities, context) → ActionResult
```

**ActionSpec:**
```python
@dataclass
class ActionSpec:
    name: str
    match: Callable[[IntentResult, dict], bool]
    run: Callable[[dict, dict], Awaitable[ActionResult]]
    domain: str  # "tasks" | "habits" | "goals" | "projects"
    risk: RiskLevel  # READ_ONLY | MUTATING | DESTRUCTIVE
    confirmation_message: str | None
```

**Registration Order = Precedence.** First match wins.

**Two Registry Builders** (`registrations.py`):
- `build_default_registry()` — all 28 actions registered (used by tests)
- `build_enabled_registry()` — **feature-flag gated**:
  - `OFFLINE_TASKS` → QUERY_TASK, ADD_TASK, EDIT_TASK, DELETE_TASK
  - `OFFLINE_HABITS` → QUERY_HABIT, ADD_HABIT, EDIT_HABIT, DELETE_HABIT
  - `OFFLINE_GOALS` → QUERY_GOAL, ADD_GOAL, EDIT_GOAL, DELETE_GOAL
  - `OFFLINE_PROJECTS` → QUERY_PROJECT, ADD_PROJECT, EDIT_PROJECT, DELETE_PROJECT

**Execution Flow:**
1. `OfflineEngine.execute(intent_result, context)` → finds matching ActionSpec
2. Validates args against spec (fail-closed)
3. If `confirmation_message` set → stores pending action in `conversation_state._PENDING`, returns `ActionResult(needs_confirmation=True, ...)`
4. User confirms via callback → `OfflineEngine.continue_editing()` / `execute_pending()`
4. Executes `run()` → returns `ActionResult(ok, data, error, needs_confirmation)`

**Logging:** `DEBUG` traces (`[Offline]`), `INFO` commits (`[Offline Commit]`) with action name, args, result summary, affected entity IDs.

### 3.4 AI Worker (`core/ai/worker.py`)

**Purpose:** LLM-driven tool-use loop for complex/ambiguous requests. **Owner-only canary** (`WORKER=1` + `is_admin(uid)`).

**Configuration:**
- `MAX_TOOL_CALLS = 4` per run (bounded loop)
- Model: GLM-5.2 via NVIDIA NIM (configured via `NVIDIA_API_KEY`)
- Runs **only after** all deterministic layers decline
- Falls through to legacy on decline/failure

**Loop Structure:**
```
while tool_calls < MAX_TOOL_CALLS:
    1. Build system prompt + tool schemas (from ToolRegistry)
    2. Call LLM → get tool calls or final response
    3. For each tool call:
       a. Validate via ToolRegistry.validate_args (fail-closed)
       b. If tool.risk in {MUTATING, DESTRUCTIVE}:
            → Confirmation Gate (MECHANICAL)
            → Store pending, return "awaiting confirmation" to user
            → On confirm: execute via ToolRegistry.execute_tool_async
       c. If tool.risk == READ_ONLY:
            → Execute directly via ToolRegistry
       d. Append ToolResult to conversation
    4. If LLM returns final response (no tool calls):
            → Return to user
```

**Confirmation Gate (MECHANICAL):** Not an LLM prompt. Hard-coded: any `MUTATING` or `DESTRUCTIVE` tool **requires explicit user confirmation** via inline keyboard (`ctl:confirm:<tool>:<args_hash>`). Worker pauses, yields control to callback router.

**Honesty Guard:** If a tool returns `ToolResult(ok=False, error=...)`, the Worker **must not fabricate success**. It returns the error to the user verbatim. Verified by `/selftest` probe `worker_honesty_guard`.

**Structured Logging:**
- `INFO`: `Worker run started: trace_id=..., user=admin, turns=3`
- `DEBUG`: `Tool call: create_task(args={...}) → ToolResult(ok=True, ...)`
- `INFO`: `Confirmation required: create_task — waiting for user`
- `INFO`: `Worker terminated: reason=MAX_TURNS_REACHED|SUCCESS|ERROR, steps=N`
- `WARNING`: `Worker refused to fabricate success for delete_task`

### 3.5 Tool Contract (`core/ai/tools.py`, `core/ai/tool_adapters.py`)

**Foundation Types** (`tools.py`):

```python
class RiskLevel(Enum):
    READ_ONLY = 0      # No side effects, safe to auto-execute
    MUTATING = 1       # Creates/updates data, requires confirmation
    DESTRUCTIVE = 2    # Deletes data, requires confirmation
    SYSTEM = 3         # System-level (migrations, admin), admin-only

@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict  # JSON Schema
    risk: RiskLevel
    confirmation_message: str | None
    returns: dict     # JSON Schema for result

@dataclass
class ToolResult:
    ok: bool
    data: Any | None
    error: str | None
    needs_confirmation: bool = False
    confirmation_payload: dict | None = None
```

**Validation (Fail-Closed):**
- `ToolRegistry.validate_spec(spec)` — raises on schema violations at registration time
- `ToolRegistry.validate_args(spec, args)` — raises on invalid args at call time
- **No silent coercion.** Invalid args → `ToolError` → surfaced to caller.

**ToolRegistry:** Single global instance (`core/ai/tools.py:TOOL_REGISTRY`). Thread-safe registration, lookup, execution.

**63 Tool Adapters** (`tool_adapters.py` — 150KB):

| Domain | READ_ONLY | MUTATING | DESTRUCTIVE | Total |
|--------|-----------|----------|-------------|-------|
| Tasks | 6 | 8 | 3 | 17 |
| Habits | 4 | 5 | 2 | 11 |
| Goals | 3 | 4 | 2 | 9 |
| Workspace/Entities | 4 | 6 | 1 | 11 |
| Media | 2 | 2 | 0 | 4 |
| Notes | 1 | 2 | 0 | 3 |
| Tags | 2 | 3 | 1 | 6 |
| Search | 1 | 0 | 0 | 1 |
| **Total** | **23** | **30** | **9** | **62** |

*(Note: One additional SYSTEM tool for index rebuild)*

**Base Class:** `_BoundTool` — wraps domain service method, injects `user_id`, handles `ToolResult` wrapping, logging.

### 3.6 Manual Control Plane (`core/control/router.py`)

**Purpose:** Admin-facing UI for workspace/entity management via inline keyboards. **v15.3 M5** — single shared confirm flow.

**Callback Namespace:** `ctl:` (all callbacks route through `core/control/router.py::route_control_callback`)

**Page Targets** (read-only navigation):
- `ctl:page:workspaces`
- `ctl:page:entities:<workspace_id>`
- `ctl:page:entity:<entity_id>`
- `ctl:page:milestones:<entity_id>`
- `ctl:page:equipment:<entity_id>`
- `ctl:page:identity:<workspace_id>`
- `ctl:page:knowledge:<workspace_id>`
- `ctl:page:settings`

**Action Targets** (mutating — execute via `execute_tool_async`):
- `ctl:create:workspace`, `ctl:create:entity`, `ctl:create:milestone`, `ctl:create:note`
- `ctl:edit:entity:<id>`, `ctl:edit:milestone:<id>`, `ctl:edit:identity:<id>`
- `ctl:delete:entity:<id>`, `ctl:delete:milestone:<id>`, `ctl:delete:note:<id>`
- `ctl:focus:<entity_id>`, `ctl:unfocus`
- `ctl:equip:add:<entity_id>`, `ctl:equip:remove:<entity_id>`
- `ctl:tag:add:<entity_id>`, `ctl:tag:remove:<entity_id>`
- `ctl:link:add:<entity_id>`, `ctl:link:remove:<entity_id>`
- `ctl:reindex` (knowledge index rebuild)

**Shared Confirm Flow (M5-F):**
1. Action callback received → builds `ConfirmationSpec(tool_name, args, message)`
2. Stores in `conversation_state._PENDING[user_id] = ConfirmationSpec`
3. Returns inline keyboard: `[Confirm] [Cancel]` with callback data `ctl:confirm:<action>:<hash>` / `ctl:cancel`
4. On confirm → retrieves spec, calls `execute_tool_async(tool_name, args, user_id)`
5. On cancel → clears pending, returns to page

**Security:** All `ctl:*` callbacks gated by `is_admin(uid)`. Non-admin → silent "Unknown command" (same as unknown slash command).

### 3.7 Workspace OS (`core/workspace/`)

**Files:**
- `engine.py` (32KB) — `EntityEngine` with validation, lifecycle enforcement, event seam
- `lifecycle.py` — Entity state machine (DRAFT → ACTIVE → ARCHIVED → DELETED)
- `templates.py` — Workspace templates (project, game, goal, habit, custom)
- `milestones.py` — Milestone hierarchy (parent/child, ordering, progress rollup)
- `equipment.py` — Equipment registry (RPG metaphor)
- `identity.py` — Workspace identity (name, description, icon, color)
- `media.py` — Media library (photos, videos, documents per workspace)
- `notes.py` — Notes with entity/project binding
- `tags.py` — Tag system (workspace-scoped, hierarchical)
- `events.py` — Event constants (`EV_ENTITY_CREATED`, `EV_MILESTONE_COMPLETED`, etc.) + `EventBus`

**EntityEngine** (`engine.py`):
```python
class EntityEngine:
    def __init__(self, storage: Storage, event_bus: EventBus)
    
    # Workspace lifecycle
    create_workspace(template: str, name: str, ...) → Workspace
    get_workspace(workspace_id) → Workspace
    list_workspaces(user_id) → List[Workspace]
    set_current_workspace(user_id, workspace_id) → None
    
    # Entity lifecycle (enforced by lifecycle.py)
    create_entity(workspace_id, type, name, ...) → Entity
    get_entity(entity_id) → Entity
    update_entity(entity_id, **fields) → Entity
    delete_entity(entity_id) → None
    transition_entity(entity_id, new_state) → Entity  # validates transitions
    
    # Milestones
    create_milestone(entity_id, title, ...) → Milestone
    complete_milestone(milestone_id) → Milestone  # fires EV_MILESTONE_COMPLETED
    
    # Equipment, Tags, Notes, Media — delegated to respective modules
```

**Event Seam:** `EventBus` (simple pub/sub) fires `EV_*` constants. Consumers: Knowledge Timeline indexer, Sync Engine, audit log. **No business logic in event handlers** — they're side-effect only.

### 3.8 Storage Facade (`core/storage/storage.py`)

**Purpose:** Single delegation layer over `database.py`. Domain-specific storage classes:

```python
class Storage:
    def __init__(self, db: Database):
        self.tasks = TaskStorage(db)
        self.habits = HabitStorage(db)
        self.goals = GoalStorage(db)
        self.memory = MemoryStorage(db)
        self.workspaces = WorkspaceStorage(db)
        self.entities = EntityStorage(db)
        self.milestones = MilestoneStorage(db)
        self.notes = NoteStorage(db)
        self.media = MediaStorage(db)
        self.tags = TagStorage(db)
        self.knowledge = KnowledgeStorage(db)
```

Each `*Storage` class wraps raw SQL with parameterized queries. **No SQL in callers.** All callers (ToolRegistry, Control Plane, Worker) go through `Storage`.

### 3.9 Conversation State (`conversation_state.py`)

**In-Memory Dicts** (process lifetime, no persistence):
```python
_STATE: dict[int, str]           # user_id → state ("confirming", "gathering", "editing", None)
_CONTEXT: dict[int, dict]        # user_id → arbitrary context dict
_HISTORY: dict[int, list[str]]   # user_id → last N messages
_PENDING: dict[int, Any]         # user_id → pending action (ConfirmationSpec, etc.)
```

**INTERACTIVE_STATES** = `("confirming", "gathering", "editing")`

**ADR-011 Option A — `claims_messages(user_id, update)`**:
- Returns `True` if user has an active interactive state
- If true, `handle_message` **short-circuits** — the message goes to the active flow, not the cascade
- Prevents intent classification from stealing messages mid-flow

### 3.10 Database Layer (`database.py`)

**Schema:** 42 `REQUIRED_TABLES`, 10 `REQUIRED_INDEXES`, `SCHEMA_VERSION = 2`

**Key Tables:**
- `users`, `tasks`, `habits`, `goals`, `projects`, `notes`, `memories`
- `workspaces`, `entities`, `milestones`, `equipment`, `tags`, `entity_tags`
- `media`, `knowledge_chunks`, `knowledge_index`, `cross_references`
- `scheduler_jobs`, `reminders`, `escalations`, `instance_lock`
- `schema_migrations` (applied migration tracking)

**WAL Mode:** Enabled at connection (`PRAGMA journal_mode=WAL`)

**Migrations:** Idempotent `ALTER TABLE ADD COLUMN` via `_safe_add_column(table, column, ddl)`. Tracks applied migrations in `schema_migrations` table. Runs at startup.

**Backup:** `backup_database()` → timestamped `.bak` file. Called by admin `/backup` and pre-migration.

**Connection Pool:** Single `sqlite3.Connection` per process (thread-safe via `check_same_thread=False`). All access via `Database` class methods.

### 3.11 Scheduler (`scheduler.py`)

**APScheduler** (background scheduler, `BackgroundScheduler`).

**Jobs:**
- Reminder dispatch (per-task, respects quiet hours)
- Quiet hours enforcement (per-user `quiet_start`/`quiet_end`)
- Escalation levels (1→2→3, configurable intervals)
- Carry-forward (overdue tasks → next day at configurable hour)
- Follow-up reminders (max 3 attempts)
- Topic backfill/repair (forum topics, admin-only)

**TelegramSender** (`notification_service.py`):
- Per-chat rate limiter (token bucket)
- Global rate limiter
- FloodWaitError handling with exponential backoff (max 3 retries)
- `safe_edit_message_text`, `safe_answer_callback_query` helpers

---

## 4. Feature Flags (`core/feature_flags.py`)

| Flag | Default | Gates |
|------|---------|-------|
| `OFFLINE_TASKS` | `false` | Task actions in OfflineEngine |
| `OFFLINE_HABITS` | `false` | Habit actions in OfflineEngine |
| `OFFLINE_GOALS` | `false` | Goal actions in OfflineEngine |
| `OFFLINE_PROJECTS` | `false` | Project actions in OfflineEngine |
| `WORKSPACE` | `false` | Entire Workspace OS (EntityEngine, Milestones, Knowledge, Media, Control Plane, 18 slash commands) |
| `WORKER` | `false` | AI Worker (owner-only canary) |

**Convention:** Read once at import from `os.getenv`. Flip via `.env` + restart. No runtime toggle.

**Flag Interaction:**
- `WORKSPACE=1` enables 18 commands: `/newproject`, `/newgame`, `/newgoal`, `/workspaces`, `/use`, `/linkhere`, `/add`, `/open`, `/current`, `/note`, `/topicbackfill`, `/topicrepair`, `/control`, `/diag`, `/ws`, `/query`, `/projects`, `/home`
- `WORKER=1` + `is_admin()` enables AI Worker for owner only
- Offline flags independent — can enable tasks without habits, etc.

---

## 5. Security Hygiene

| Requirement | Implementation |
|-------------|----------------|
| **Admin Model** | Single owner via `/claimadmin` (writes `admin_id.txt`). `is_admin(uid)` checks exact match. |
| **Silent Denial** | Non-admin + unknown command → "Unknown command" (no distinction). Admin commands silently ignored. |
| **Log Sanitizer** | `log_sanitizer.py` installed at import (main.py:159). Redacts: bot tokens, API keys, admin ID → `admin`, other IDs → `user_***XXX`. Attached to all root handlers. |
| **No Raw SQL in Logs** | Parameterized queries only; no query logging. |
| **No Conversation Content in Logs** | Only metadata (intent, entities) at DEBUG. |
| **Log Files Gitignored** | `.gitignore` includes `*.log`, `debugbot.log*` |
| **Timezone** | IST (Asia/Kolkata) — `_now()` helpers per module, never bare `datetime.now()` |
| **HTML Output** | User-facing text via `fmt.py` (`esc`, `b`, `i`, `code`, `pre`, `link`) — never raw Markdown. |

---

## 6. Logging Architecture

**Two Files:**
| File | Level | Rotation | Purpose |
|------|-------|----------|---------|
| `bot.log` | `INFO` | None (append) | Production audit trail |
| `debugbot.log` | `DEBUG` | 2 MB × 3 backups | Developer diagnostics |

**Noise Suppression:** `httpx`, `httpcore`, `apscheduler` → `WARNING` level (prevents token leaks + chatter).

**Structured Logging Discipline:**
- Lazy `%-formatting` for all `DEBUG` (zero cost when disabled)
- No f-strings in DEBUG paths
- Trace IDs (UUID4) per request for correlation
- Module-named loggers (`logging.getLogger(__name__)`)

**Subsystem Log Levels:**
| Subsystem | File | Level | Key Events |
|-----------|------|-------|------------|
| Intent Engine | debugbot.log | DEBUG | Every classification |
| Routing Layer | debugbot.log | DEBUG | Every decision (shadow) |
| Offline Engine | debugbot.log / bot.log | DEBUG / INFO | Traces + commits |
| Scheduler | bot.log | INFO | Reminders, quiet hours, escalations |
| TelegramSender | bot.log | INFO/WARNING | Sends, rate limits, flood retries |
| AI Worker | bot.log / debugbot.log | INFO / DEBUG | Run boundaries, tool calls, confirmations |
| Instance Lock | bot.log | INFO/ERROR | Acquisition, conflict exit |
| Self-Test | bot.log | INFO | Probe results, suite summary |

---

## 7. Testing Architecture

### 7.1 Offline Pytest Suite (1700+ tests)
- `tests/` — unit/integration tests for all subsystems
- Run via `pytest` (no external deps beyond test requirements)
- Covers: Intent Engine, Routing, Offline Engine, ToolRegistry, Storage, Workspace, Database migrations

### 7.2 Self-Test Framework (`core/selftest/`)
**72 Runtime Health Probes** (executed via `/selftest` command):

| Category | Probes | Examples |
|----------|--------|----------|
| Database | 12 | schema_version, required_tables, required_indexes, wal_mode, migrations_applied |
| Intent Engine | 8 | tier0_exact_match, tier1_datetime, tier2_recurrence, tier3_greeting, tier4_keywords, unknown_fallback, trace_id_generation, latency_under_threshold |
| Routing Layer | 6 | shadow_mode_enforced, offline_threshold, clarify_threshold, low_confidence_fallback, trace_correlation, decision_latency |
| Offline Engine | 10 | registry_building, flag_gating, action_spec_validation, confirmation_gate, dry_run, commit_logging, action_precedence, domain_isolation, error_handling, idempotency |
| AI Worker | 9 | max_tool_calls_enforced, confirmation_gate_mechanical, honesty_guard, fallback_to_legacy, trace_logging, tool_schema_validation, risk_level_enforcement, admin_only_gate, error_recovery |
| ToolRegistry | 8 | spec_validation_fail_closed, args_validation_fail_closed, 63_tools_registered, risk_level_distribution, tool_execution_audit, duplicate_registration, missing_tool_error, parameter_schema |
| Control Plane | 6 | ctl_namespace_routing, page_targets, action_targets, shared_confirm_flow, admin_gate, callback_payload_integrity |
| Workspace OS | 7 | entity_lifecycle_enforcement, milestone_hierarchy, template_application, event_bus_firing, equipment_registry, tag_hierarchy, media_library |
| Storage Facade | 4 | delegation_correctness, parameterized_queries, transaction_boundaries, error_propagation |
| Logging/Security | 6 | sanitizer_installed, token_redaction, api_key_redaction, id_pseudonymization, log_rotation, gitignore |

**Output:** `SelfTest suite: 72 probes, 71 PASS, 1 FAIL, 0 SKIP`

---

## 8. Data Flow: Message → Response

```
Telegram Update
       │
       ▼
main.py:handle_message(update, context)
       │
       ├─▶ /claimadmin (writes admin_id.txt)
       │
       ├─▶ is_admin(uid) check for admin commands
       │
       ├─▶ ConversationState.claims_messages(uid, update)
       │       └─▶ True → route to active flow (confirming/gathering/editing)
       │
       ├─▶ IntentEngine.classify(text) → IntentResult
       │
       ├─▶ RoutingLayer.route(intent_result) → RoutingDecision
       │       (logs recommended vs actual=LEGACY)
       │
       ├─▶ OfflineEngine.execute() — IF:
       │       • intent in OFFLINE_ENGINE_IMPLEMENTED_INTENTS
       │       • corresponding feature flag ON
       │       • ActionSpec.match() returns True
       │       └─▶ ActionResult (may need_confirmation → callback)
       │
       ├─▶ AI Worker (core/ai/worker.py) — IF:
       │       • WORKER=1 AND is_admin(uid)
       │       • All above declined
       │       └─▶ ToolRegistry loop (max 4 calls, confirmation gate)
       │
       └─▶ Legacy fallback (baka_brain.call_main)
               │
               ▼
         Response sent via TelegramSender (rate-limited, sanitized)
```

---

## 9. Deployment & Operations

### 9.1 Process Model
- **Single process**, single event loop (asyncio)
- `instance_lock.py` prevents duplicate processes (file lock on `bot.lock`)
- `dev_reset.sh` — development reset (deletes logs, lock, planner.db, recreates schema)

### 9.2 Configuration (`.env`)
```
BOT_TOKEN=<telegram bot token>
OWNER_ID=<telegram user id>          # Used by is_admin() before /claimadmin
NVIDIA_API_KEY=<nim api key>         # For AI Worker (GLM-5.2)
OFFLINE_TASKS=false
OFFLINE_HABITS=false
OFFLINE_GOALS=false
OFFLINE_PROJECTS=false
WORKSPACE=false
WORKER=false
```

### 9.3 Log Rotation
- `bot.log`: External `logrotate` recommended
- `debugbot.log`: Built-in `RotatingFileHandler` (2 MB × 3 backups), `delay=True` (lazy creation), safe to `rm` anytime

### 9.4 Health Checks
- `/selftest` — 72 probes, returns summary
- `/diag` — system diagnostics (memory, DB size, uptime, flag state)
- Instance lock prevents double-run

---

## 10. Known Architecture Gaps (Documented, Not Fixes)

| Gap | Impact | Location |
|-----|--------|----------|
| Tier 0 command duplication | `rules.py` mirrors `main.py` command lists | `core/intent/rules.py` |
| No structured/JSON logging | Hard to ingest into log aggregation | `main.py`, all subsystems |
| No correlation IDs across async boundaries | Trace ID not propagated through `run_blocking()` threads | `async_bridge.py` |
| No log sampling | High-volume DEBUG fills `debugbot.log` fast | `main.py` |
| No centralized log config | Levels hardcoded; no runtime adjustment | `main.py` |
| Scheduler lacks DEBUG traces | No internals visibility in `debugbot.log` | `scheduler.py` |
| AI model requests/responses not logged | Intentional (privacy) but no audit trail | `core/ai/worker.py` |
| No `/undo` action reversal | Users request regularly; only `/sql` recovery | `main.py`, `database.py` |
| 18 workspace commands silent when flag OFF | No "feature dormant" feedback | `main.py` command handlers |
| `/commands` catalog incomplete | 27 handlers missing from help (DoD gap) | `ui/help_cards.py` |

---

## 11. Definition of Done (v14.23) — Enforced by `/selftest`

Every feature **must** have:
1. ✅ Implementation
2. ✅ Regression tests (pytest)
3. ✅ `/selftest` probe
4. ✅ `/help` entry (`ui/help_cards.py`)
5. ✅ CHANGELOG entry
6. ✅ ROADMAP update
7. ✅ README update
8. ✅ Documentation update

**This document (SYSTEM_ARCHITECTURE.md) is itself a DoD artifact for the architecture baseline phase.**

---

## 12. File Map (Key Files)

| File | Lines | Purpose |
|------|-------|---------|
| `main.py` | ~7,500 | Entry point, cascade, logging, handlers |
| `database.py` | ~4,500 | Schema, migrations, WAL, backup |
| `conversation_state.py` | ~120 | In-memory state, ADR-011 Option A |
| `core/intent/intent_engine.py` | ~100 | 5-tier classification |
| `core/intent/rules.py` | ~350 | Tier 0-4 patterns |
| `core/routing/router.py` | ~80 | Shadow-mode decision logging |
| `core/routing/confidence.py` | ~50 | Thresholds, OFFLINE_ENGINE_IMPLEMENTED_INTENTS |
| `core/offline/engine.py` | ~180 | Thin dispatcher |
| `core/offline/registry.py` | ~180 | ActionRegistry, ActionSpec |
| `core/offline/registrations.py` | ~450 | Flag-gated registry builders |
| `core/ai/worker.py` | ~380 | Bounded LLM loop, confirmation gate, honesty guard |
| `core/ai/tools.py` | ~500 | Tool contract, ToolRegistry, fail-closed validation |
| `core/ai/tool_adapters.py` | ~3,800 | 63 tool adapters (_BoundTool) |
| `core/control/router.py` | ~1,300 | ctl: callbacks, pages, actions, confirm flow |
| `core/workspace/engine.py` | ~850 | EntityEngine, validation, lifecycle, events |
| `core/workspace/lifecycle.py` | ~150 | Entity state machine |
| `core/workspace/templates.py` | ~200 | Workspace templates |
| `core/workspace/milestones.py` | ~250 | Milestone hierarchy |
| `core/workspace/equipment.py` | ~180 | Equipment registry |
| `core/workspace/identity.py` | ~100 | Workspace identity |
| `core/workspace/media.py` | ~200 | Media library |
| `core/workspace/notes.py` | ~180 | Notes with binding |
| `core/workspace/tags.py` | ~180 | Tag system |
| `core/workspace/events.py` | ~80 | EventBus, EV_* constants |
| `core/storage/storage.py` | ~650 | Storage facade over database.py |
| `core/feature_flags.py` | ~50 | 6 feature flags from .env |
| `log_sanitizer.py` | ~80 | Log redaction filter |
| `notification_service.py` | ~400 | TelegramSender, rate limiting |
| `scheduler.py` | ~500 | APScheduler jobs |
| `async_bridge.py` | ~80 | run_blocking() for sync AI calls |
| `instance_lock.py` | ~60 | Single-process enforcement |

---

## 13. Implementation Contract

**This document is the binding contract for all subsequent BAKA development.**

### Invariants That Must Never Be Violated
1. **Layering:** AI Worker → ToolRegistry ← Control Plane → Domain Services → DB/Telegram. No bypasses.
2. **Fail-Closed Validation:** `ToolRegistry.validate_args` raises on invalid input — never coerces.
3. **Confirmation Gate:** `MUTATING`/`DESTRUCTIVE` tools require explicit user confirmation (MECHANICAL, not LLM).
4. **Honesty Guard:** Worker never fabricates success on tool failure.
5. **Single-Process:** `instance_lock.py` enforced; no multi-process scaling.
6. **IST Timezone:** `_now()` helpers only; never bare `datetime.now()`.
7. **HTML Output:** `fmt.py` helpers only; never raw Markdown to users.
8. **Silent Admin Denial:** Non-admin + unknown command = "Unknown command".
9. **Log Sanitizer:** Installed before any logging; tokens/IDs never in logs.
10. **Feature Flags:** Read once at import; no runtime toggle; default OFF.

### Extension Points (Where New Code Goes)
| Capability | Extension Mechanism |
|------------|---------------------|
| New intent | Add to `rules.py` tiers + `OFFLINE_ENGINE_IMPLEMENTED_INTENTS` if offline-capable |
| New offline action | Add `ActionSpec` to `registrations.py` (respect flag gating) |
| New tool | Add `_BoundTool` subclass to `tool_adapters.py`, register in `TOOL_REGISTRY` |
| New Control Plane action | Add `ctl:` callback handler in `core/control/router.py` |
| New Workspace entity type | Extend `EntityEngine`, add storage in `core/storage/storage.py`, add DB table |
| New scheduler job | Add to `scheduler.py` with `TelegramSender` |
| New feature flag | Add to `core/feature_flags.py`, gate in `registrations.py`/`main.py` |

---

## 14. Related Documents

| Document | Purpose |
|----------|---------|
| `LOGGING_ARCHITECTURE.md` | Detailed logging subsystem documentation |
| `FEATURE_FLAGS.md` | Feature flag reference |
| `DEBUGGING.md` | Debug workflow, known issues |
| `TESTING.md` | Self-Test framework, pytest conventions |
| `AI_WORKER_CAPABILITIES.md` | Worker tool coverage, NL intents |
| `COMMAND_INVENTORY.md` | All wired commands |
| `MISSING_COMMANDS.md` | Spec-advertised but unwired commands |
| `DESIGN_ASSESSMENT.md` | Spec vs implementation gaps |
| `REFACTOR_PROPOSALS.md` | Prioritized refactor list |
| `IMPLEMENTATION_ORDER.md` | Sequenced implementation plan |

---

## 15. Change Log

| Version | Date | Author | Change |
|---------|------|--------|--------|
| 1.0 | 2026-08-20 | Engineering Baseline | Initial baseline at commit c35cbd0 (v15.5 M7) |

---

**END OF SYSTEM_ARCHITECTURE.md**