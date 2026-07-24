# BAKA Bot — Roadmap

This consolidates every "not yet built" idea found across the old
`VERSION.md`'s planned-roadmap section, `feature_list.md`'s "Known
Limitations", and gaps found during the 2026-07 documentation pass.

> **v15.0 — Workspace OS**: the next major evolution unifies
> Tasks/Habits/Projects/Goals/Memory under a single **Workspace**
> abstraction (Project/Book/Game/… = same engine, different template),
> with a Milestone hierarchy, an append-only Knowledge Timeline,
> Telegram-Topic sync, and an AI Orchestrator. Full design:
> [docs/v15/](docs/v15/) (WED · TWID · KTD · AWOD · MIGRATION). Built
> additively behind a `WORKSPACE` flag (ships dark, canary-enabled) so no
> existing behaviour regresses — the v14 Autonomous Core playbook.
>
> **Status:** `v15.0-alpha.7` — built in `core/workspace/`, all dormant
> behind `WORKSPACE=off`: the **Workspace Foundation** (alpha.1: schema,
> Storage Facade, Repository, Service, Template registry, migration), the
> reusable **Entity Engine** (alpha.2: ownership + input validation,
> lifecycle state machines, event seam), **Project Integration** (alpha.3:
> `ProjectAdapter` routes v14 Projects through the Workspace layer with
> proven data equivalence — no data moved), **Milestone Management**
> (alpha.4: archive + soft-delete), the append-only **Knowledge Timeline**
> (alpha.5: `TimelineEngine` subscribes to the engine's `EntityEvent`
> hook), the **Synchronization Engine + Telegram Adapter** (alpha.6: TWID
> outbox, idempotent enqueue, retrying drain — Telegram is the first
> `SyncAdapter`, delivering through an injected sender), and the generic
> **AI Workspace Orchestrator** (alpha.7/AWOD: NL → validated engine op via
> interpret → select → resolve → safety gate → apply, with the AI injected
> as an `Interpreter` — no live LLM import, template-agnostic).
>
> **`v15.0-beta.1` — the platform is wired into production** (integration
> only, no architecture change): a flag-gated branch in the free-text
> handler routes to the orchestrator when `WORKSPACE=on` (else Legacy,
> byte-identical); a `SyncWorker` drains the outbox on the existing
> scheduler; the production Telegram sender and the `LLMInterpreter`
> (baka_brain, with a rule-based fallback) are injected. The Workspace OS
> now runs inside the real app behind the flag. **Next:** Workspace
> templates (Game, Books, Research, richer Projects) built on this
> production-ready platform, plus Workspace UI/commands — see
> docs/v15/MIGRATION.md §7.
>
> **`v15.0-beta.2` — Game template (reference implementation):** the first
> new Workspace type added on the production platform, proving a full
> Workspace drops in as one module (`templates/game.py`: schema +
> validation + registration) with **zero OS changes**.
>
> **`v15.0-beta.3` — Knowledge template:** the pattern applied a second
> time, to an educational/knowledge domain
> (`templates/knowledge.py`: 🧠 concepts → milestones, sources/notes →
> notes, mastery% via `PROGRESS_MANUAL`), again with **zero OS changes** and
> coexisting with the Game template.
>
> **`v15.0-beta.4` — Asset template:** the pattern applied a third time and
> at its broadest — **one reusable template for any physical asset**
> (`templates/asset.py`: 📦 vehicle/computer/drone/robot/…, the kind is just
> `metadata['asset_type']`; maintenance → milestones, service records →
> notes, components → tags, ownership/maintenance history → Timeline,
> maintenance completion via `PROGRESS_MILESTONES`), with no per-type logic
> and **zero OS changes**.
>
> **`v15.0-beta.5` — Project template:** the pattern applied a fourth time,
> to an **execution-focused domain** (`templates/project.py`: 🛠 a project
> driven through the Research→Documentation milestone pipeline; phases/tasks
> → milestones, worklog → notes, execution % via `PROGRESS_MILESTONES`).
> This milestone also **took ownership of the `project` template** — moved
> out of `builtin.py` into its own module (as beta.2 did for `game`), shape
> preserved so the alpha.3 `ProjectAdapter` bridge is unaffected. Four
> independent drop-in templates now coexist. **The Workspace OS is frozen.**
> **Next templates** (Finance, Personal Knowledge, …) follow this exact
> pattern, plus Workspace UI/commands.

**A note on version numbers:** the original `VERSION.md` roadmap section
labeled ideas `v12.0` (Voice Notes) through `v14.3` (Themes) — written
*before* v12.0 actually shipped as "Project Management" (see
[CHANGELOG.md](CHANGELOG.md)). Those numbers now collide with real
released versions. This file drops fixed version numbers for backlog items
and groups by priority/theme instead. Treat "Next up" as literally next;
everything else is unordered backlog, not a commitment.

---

## v14.0 Autonomous Core migration status

Tracking `DESIGN_SPEC_v14_AUTONOMOUS_CORE.md` §11's 6-stage migration.
**Stage numbers, not version numbers, on purpose** — see the note above
about the old `VERSION.md` roadmap's fixed version labels colliding with
what actually shipped; the authoritative design doc itself uses Stage
0–5 for the same reason.

- ☐ **Stage 0** — AI-call analytics. Reframed by v14.12: the stranded,
  never-importable source files were deleted in the repository cleanup,
  so this is now a **build-from-scratch v15 item** (alongside the AI
  Router, which wants the health data), not a packaging fix.
- ✅ **Stage 1 — Intent Engine (Shadow Mode).** Shipped v14.0
  (`core/intent/`). Classifies every message deterministically via a
  tiered rule set reusing `date_parser.py`; does not yet affect routing.
  See [CHANGELOG.md](CHANGELOG.md).
- ◐ **Stage 2 — Offline Engine** for already-offline commands (in progress).
  The Intent-Aware Routing piece of this stage has an approved design
  ([DRG-001_Intent_Aware_Routing.md](DRG-001_Intent_Aware_Routing.md),
  informally "v14.1A"; see [ADR-006](docs/adr/ADR-006-intent-aware-routing.md))
  and its Sub-stage B ("Decision") is now shipped as v14.1B — a real
  Routing Layer (`core/routing/`) runs on every message and logs a
  recommended destination, but always executes via Legacy (hard-coded).
  Sub-stage C (real routing, one command group at a time) and Sub-stage D
  (Legacy removal) are not started — the Offline Engine itself
  (`OFFLINE_ENGINE.md`) does not exist yet, so `core/routing/`'s
  `OFFLINE_ENGINE_IMPLEMENTED_INTENTS` set stays empty until it does.
  v14.1C added the plumbing the Offline Engine needed: a Storage Facade
  (`core/storage/`, thin delegation to `database.py`, no new data-access
  abstraction — see that sprint's Phase 0 review in `CHANGELOG.md`) and
  four gradual-rollout feature flags (`core/feature_flags.py`:
  `OFFLINE_TASKS`/`OFFLINE_HABITS`/`OFFLINE_GOALS`/`OFFLINE_PROJECTS`).
  v14.2 shipped the Offline Engine itself (`core/offline/`, `core/actions/`,
  [ADR-007](docs/adr/ADR-007-offline-engine-stage1.md)) — read-only task
  actions only (list/today/week/search). **v14.3 shipped its first write
  operation, task creation**
  ([ADR-008](docs/adr/ADR-008-offline-write-operations.md)) — a two-phase
  propose/confirm/commit flow reusing `conversation_state.py`'s existing
  machinery so Legacy's "always confirm before writing" property holds
  for the Offline path too. Still gated behind `OFFLINE_TASKS` (still
  OFF — no deployment has enabled it yet). Recognizes exactly four
  explicit verb commands (`add task`/`create task`/`new task`/`todo`);
  free-form natural-language task creation ("remind me to...") remains
  Legacy-only, since title extraction needs the AI this Offline Engine
  explicitly excludes. **v14.4 shipped a second write operation, task
  update** ([ADR-009](docs/adr/ADR-009-offline-task-update.md)) — applies
  directly with no confirm step, genuinely matching Legacy's real update
  behavior (verified: Legacy itself doesn't confirm updates either,
  despite the task brief that requested this sprint assuming it did).
  Supports date/time/priority/category/title changes; recurrence changes
  remain unsupported in *both* paths (verified: `database.update_task()`
  has no recurrence parameters — not an Offline gap, a real Legacy
  limitation). **v14.5 shipped a third write operation, task delete**
  ([ADR-010](docs/adr/ADR-010-destructive-operations-policy.md)) — the
  first (and so far only) case where Offline deliberately does *not*
  match Legacy's real behavior: Legacy's `/delete <id>` deletes
  immediately with zero confirmation (verified), but Offline Delete adds
  one, justified by irreversibility. `ADR-010` generalizes this into a
  reusable policy for future write operations: confirm when irreversible,
  match Legacy otherwise. Idempotent (a repeated confirmation or
  concurrent delete is reported gracefully, never double-executed) and
  self-verifying (re-checks the row is actually gone before reporting
  success). **v14.6 shipped a fourth write operation, task completion** —
  direct apply matching Legacy's real no-confirm behavior, exactly as
  `ADR-010`'s policy predicted for a row-preserving operation.
  Replicates Legacy's learning-log side effects
  (`completions_log`/`interaction_log`, including the exception swallow)
  via a new `LearningStorage` facade domain; habits branch away to
  Legacy's streak logic untouched; no undo exists in either path
  (verified Legacy has none — documented per the Reversibility Review,
  not invented). **v14.7 shipped the final Task-domain stage, task
  lifecycle** — pause/resume/snooze/stop-reminders/carry-forward/
  paused-view, all direct apply matching Legacy's real no-confirm
  behavior, with snooze's learning-log side effects replicated. Verified
  non-existent in Legacy and deliberately not invented: archive/restore/
  hide/unhide/unsnooze. Delreminder needed nothing (a delete alias,
  already covered by v14.5's delete path). Also produced
  [ADR-011](docs/adr/ADR-011-conversation-state-priority.md): the
  conversation-state-ordering question is now a documented architectural
  decision (recommendation: state outranks intent-gated dispatch;
  implementation deliberately deferred — a named pre-enablement
  blocker). Still gated behind `OFFLINE_TASKS` (still OFF — no
  deployment has enabled any stage yet).
  `OFFLINE_HABITS`/`OFFLINE_GOALS`/`OFFLINE_PROJECTS` remain
  unimplemented. **The Task domain is feature-complete under the new
  architecture** — every deterministic, message-path Task operation
  Legacy supports now exists behind the flag. v14.7.1 completed the
  Release Candidate architecture validation
  ([RC_v14_ARCHITECTURE_VALIDATION.md](RC_v14_ARCHITECTURE_VALIDATION.md)
  — review only, no defects requiring code found; includes the canary
  deployment plan and the three-phase Legacy removal plan). **v14.8
  executed the RC's required pre-Habits refactor**: `OfflineEngine`'s
  if/elif intent ladder replaced by registry-based dispatch
  ([ADR-012](docs/adr/ADR-012-registry-based-dispatch.md) —
  `core/offline/registry.py` mechanism + `registrations.py` explicit
  build; byte-identical behavior verified against the pre-refactor
  commit; adding an Offline action no longer touches the dispatcher).
  **v14.9 began the second domain — Offline Habits Stage 1** (the three
  read-only views: habits list, streak detail, habit log), the
  registry's proof sprint: shipped with zero engine/registry edits.
  Per-domain flags now gate at registry construction
  ([ADR-013](docs/adr/ADR-013-per-domain-registry-construction.md));
  `OFFLINE_HABITS` is consumed for the first time (still OFF).
  **v14.10 completed Habit Stage 2** — creation and skip migrated
  (both direct-apply/no-confirm, matching Legacy per ADR-010); habit
  "update"/"delete" verified to need no habit code (task edit/delete
  flows already cover habit rows — test-pinned). **v14.11 completed
  the Habit domain** — completion migrated (the habit branch of
  `done_task()`: streak log only, NO learning logs — verified and
  mirrored; v14.6's `habit_not_supported` branch-away retired in every
  Habit-enabled configuration, retained only as the cross-domain guard
  for tasks-without-habits builds). **The Habit domain now has 100%
  deterministic message-path parity with Legacy.** Verified
  non-existent, never to build: habit update/delete/today/search/
  statistics/archive/restore commands. Callback-driven habit surfaces
  (dashboard card, reminder done-buttons) remain Legacy, like all
  callbacks. **v14.12 (Production Readiness) applied ADR-011 Option A**
  — the last architecture blocker — plus rich UI (/help, /selftest),
  the bot-token log-leak fix, provider-agnostic AI config,
  requirements audit, and repository cleanup. **The only step left
  before enabling `OFFLINE_TASKS`/`OFFLINE_HABITS` is running the
  canary per RC_v14_ARCHITECTURE_VALIDATION.md's plan** (plus rotating
  the two exposed credentials — see DEBUGGING.md).

  **UI Overhaul** (Board-approved, spec frozen —
  [UI_SPEC_v1.md](UI_SPEC_v1.md)): Phase 0 shipped in v14.13
  (`ui_components.py` + tests, deliberately unwired). Remaining phases
  per spec §15: 1 (re-express `ui.py` cards) → 2 (Dashboard) → 3–8
  (Tasks+Duplicate, Habits, AI Hub, Developer Center, Statistics,
  Settings) → 9 (Polish); each gates on spec §13.3's review checklist.

  **QA system** (design: [QA_SYSTEM_DESIGN.md](QA_SYSTEM_DESIGN.md)):
  three independent layers — pytest (automated), `core/selftest`
  (runtime health), and `core/regression` (manual behaviour). **Phase 1
  shipped in v14.23**: the regression *specification* foundation
  (`core/regression/` — spec model, registry, categories, version-aware
  history store) + the authored **Quick Release Suite** (28 tests). The
  **Definition of Done** rule (CLAUDE.md) is now permanent: every
  user-visible feature owns its regression tests + docs. Remaining QA
  phases (later milestones, per the design's Q-roadmap): expand toward
  the Major/Full suites, then the Regression Runner, the 🐞 Bugs and
  🧯 Regression Tests Developer Center screens, and Test History/Stats.

  **Self-Test framework** (v14.22, `core/selftest/`): admin-only runtime
  health runner reached from the Debug Menu's 🧪 Self Test button —
  registration-based, so every future feature registers its own live
  checks without editing the runner ([docs/selftest.md](docs/selftest.md)).
  This also delivered the first piece of UI_SPEC §10's Developer Center
  (the admin-only `/debug` menu); the rest of S39–S44 (logs, engines,
  flags panels) can hang off the same `dev:*` namespace when their
  phase runs. Natural next additions: register self-tests for reminders/
  deadlines, projects/materials, and the AI-router health once it lands.

  **Naming note**: task creation/update are sometimes called "Offline
  Engine Stage 2/Stage 3" in their own commit messages and ADR titles
  (`ADR-008`/`ADR-009`) — this is a *different*, nested numbering from
  the master-spec "Stage 3 — AI Router" entry immediately below, which
  hasn't started. Same kind of numbering collision this file's own intro
  note already warns about; flagged explicitly here rather than left to
  cause confusion.
- ☐ **Stage 3 — AI Router**, NVIDIA-only.
- ☐ **Stage 4** — additional AI providers (OpenAI/Anthropic/Gemini adapters).
- ☐ **Stage 5 — Plugin System** (proof of concept via Projects).

**On version labeling:** an earlier task brief for this milestone
suggested fixed version numbers per stage (`v14.1`/`v14.2`/`v14.3`/
`v14.4`/`v15.0`). Deliberately not adopted — it would reintroduce the
exact collision problem this file already moved away from once (see the
note at the top of this file), and it doesn't match
`DESIGN_SPEC_v14_AUTONOMOUS_CORE.md` §11's own Stage-based language.
Flagged here rather than silently diverging without explanation.

---

## Fix-it list (found during the 2026-07 documentation pass)

These aren't feature requests — they're real gaps between what the code
does and what earlier docs/comments claimed. Tracked here since there was
nowhere else to put them. Full detail in [DEBUGGING.md](DEBUGGING.md#known-issues).

- **Analytics package — RESOLVED differently (v14.12).** The five
  stranded source files (+ `init.py`) were deleted in the repository
  cleanup; `/usage`, `/performance`, `/errors` still return empty data.
  Building analytics is now a clean v15 item (see Stage 0 above).
- **Hardcoded-looking API key in `ai_helper.py:9` — file deleted
  (v14.12).** The key remains in git history; **rotating it is the one
  remaining action**.
- **Dead code — RESOLVED (v14.12):** `ai_helper.py` and `bot_state.py`
  deleted in the repository cleanup.
- **`token_counter.py`'s stale `MODEL_COSTS` table — MOOT (v14.12):**
  the file was deleted with the rest of the never-assembled analytics
  code. A future analytics build should source model costs from
  configuration, not a hardcoded table.
- **`conversation_state.py`'s docstring claims state "survives across
  messages reliably"** via module-level dicts. True within a running
  process, but it does **not** survive a process restart — contrary to
  `feature_list.md`'s claim that state "survive[s] bot restarts". Either
  fix the docs (cheap) or back the state with SQLite (more work, but would
  also fix `/trace` and debug-mode state in `debug_system.py`, which have
  the same in-memory-only limitation).
- **`check_reminders` and `check_followups` jobs don't check quiet hours**,
  unlike every other scheduled job. Confirm whether this is intentional
  (primary reminders should always fire) or a gap.
- **`check_deadlines` job bypasses `database.py`**, opening its own raw
  `sqlite3.connect("planner.db")` — the only place in `main.py` that
  doesn't go through the data-access layer. Worth aligning for consistency.
- **`anthropic` SDK is in `requirements.txt`** but no `import anthropic`
  was found anywhere in the reviewed modules — confirm whether it's a
  leftover dependency or used by code not yet located, and prune if unused.

---

## Next up (from v12.0's own "ideas for next")

- **Project photos via Vision** — send a photo, Llama Vision describes
  progress, auto-adds a worklog entry
- **Cost/budget tracking** — sum material costs, show budget vs. spent per
  project
- **Milestones** — split projects into named stages, each with its own
  progress
- **Template projects** — save a project's material list as a template so
  the next similar build populates instantly

---

## Backlog (from the original roadmap, unordered, numbers dropped)

- **Voice notes** — accept Telegram voice messages, transcribe (Whisper or
  similar), treat transcript as regular text input with a confirm-before-act
  step
- **Task dependencies** — "Task B depends on Task A"; B's reminder only
  fires after A is done. `parent_task_id` column already exists as a
  possible foundation
- **Location-based reminders** — geofence check in the reminder scheduler,
  using Telegram's live-location sharing
- **Personalized briefing times** — use `interaction_log`'s active-hours
  data (already collected since v6.0) instead of a fixed 08:00 morning
  briefing
- **Bulk task import** — paste a numbered/bulleted list, one AI call
  extracts and confirms all of them
- **Named goal milestones + task linking** — `ai_observations`'
  `action_type` hook was built with this in mind
- **GLM 5.2 upgrade** — swap `MODEL_MAIN` once NVIDIA's GLM 5.2 endpoint is
  stable (GLM 5.1 was EOL'd, see [docs/ai_system.md](docs/ai_system.md));
  benchmark both once the analytics pipeline actually works
- **Fast routing enabled** — flip `ENABLE_FAST_ROUTING=True` so Llama 3.1
  8B pre-filters simple intents before escalating to the main model
- **`/replay` command** — full debug timeline for any interaction by
  timestamp, pulling from `ai_usage`, `missed_capabilities`,
  `interaction_log`, and `debug_system.py` — blocked on the analytics
  fix-it item above
- **`/export_usage`** — export `ai_usage` as CSV/JSON — also blocked on the
  analytics fix-it item
- **Multi-user admin mode** — the data model already scopes everything by
  `user_id`; the admin panel itself is currently single-user only
- **Pomodoro mode** — `/pomodoro <task_id>` timer, new `pomodoro_log` table
- **AI weekly insights** — narrative (not just pattern-based) weekly
  productivity summary
- **Themes/personalities** — switchable communication style stored in
  `user_preferences`, applied in `think_freely()`'s system prompt

---

## Future integrations (no timeline)

- Calendar sync (Google Calendar, two-way)
- Email integration (e.g. "did I get a reply from them yet?")
- Notion/Obsidian export
- Music integration (e.g. "play study playlist")
- Streak heatmap (GitHub-style year view of completed tasks)

---

## Known limitations carried over from `feature_list.md`

Reconciled against the current code — some of these are actually already
built; kept here only where still true:

- No web dashboard — all interaction is through Telegram only. **Still
  true.**
- Smart scheduling (`/plan`) creates a schedule and can apply it to the DB
  (v4.0+) — the original "text plan only, no DB tasks" limitation is
  **resolved**.
- Productivity scoring exists via `/analyze` and `/insights` (v6.0+) — the
  original "not yet tracked" limitation is **resolved**.
- Proactive suggestions (stagnation nudges, wellness nudges, priority
  nudges) exist (v8.0, v12.0) — the original "not yet implemented"
  limitation is **resolved**.
- Deployment target: To Be Documented — `README.md` said "hosted locally
  (WSL), not yet deployed to Railway cloud" as of its last update; confirm
  current hosting status before relying on this.
