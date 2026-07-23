# Migration Strategy — v14 → v15 Workspace OS

*Design only. Goal: no data loss, minimal breaking changes, reversible.*

## 1. Core stance: backfill, never move

Migration is **additive backfilling**, not data movement. We add nullable
columns and new tables, create per-user default workspaces, and point
existing rows at them via `workspace_id`. **No existing row is deleted or
relocated; no existing table is dropped.** Flag OFF restores today's
behaviour exactly, so migration is reversible.

This is the same idempotent, ALTER-in-try/except pattern `init_db()`
already uses for every column added since v1.0 — v15 adds more of the
same, guarded so re-running is safe.

## 2. The default workspaces

On first enable, per user, create (idempotently):
- **Inbox** (template `generic`) — holds all loose tasks/habits/reminders
  that don't belong to a real workspace. Invisible/implicit in the UI, so
  users who never organize see no change.
- **Personal** (template `generic`) — holds standalone memories/notes.

These make "everything belongs to a workspace" true without forcing
organization (WED §2, decision #2).

## 3. Per-domain mapping

| Existing | Becomes | Mechanism | Data moved? |
|---|---|---|---|
| **Tasks** (incl. reminders, deadlines, recurrence) | Tasks in Inbox | `ALTER tasks ADD workspace_id`; backfill NULL→Inbox at read, or one-time set | No — same rows |
| **Habits** (tasks with `is_habit=1`) | Habit-tasks in Inbox (or a "Habits" workspace) | same column; unchanged behaviour | No |
| **Goals** | Workspace Goals | `ALTER goals ADD workspace_id`; standalone goals → Inbox | No |
| **Projects** (goal + `project_materials` + `project_worklog`) | Workspace, template `project` | create a workspace per project-goal; link materials/worklog by the project's `workspace_id`; seed the project template's material/worklog/milestone sections | No — referenced, not copied |
| **Memory** (`memories`) | Workspace Knowledge (notes, kind `knowledge`) | `ALTER memories ADD workspace_id`; unassigned → Personal; memory commands keep reading `memories` | No |
| **Regression / Self-Test / Debug** | unchanged | — | No |

**Projects detail:** a "project" today is a goal that has materials or
worklog. Migration: for each such goal, create a `workspaces` row
(template `project`, title = goal title), set `goals.workspace_id` and
the goal's tasks' `workspace_id` to it, and treat the existing
`project_materials`/`project_worklog` as that workspace's material/worklog
sections (the project template exposes them). The tables stay; the
workspace is the new lens over them.

## 4. Migration procedure (ordered, idempotent)

1. **Schema add** (idempotent ALTERs + `CREATE TABLE IF NOT EXISTS`): the
   new tables (WED §3) and nullable FK columns. Runs in `init_db()`; safe
   on every startup.
2. **Backfill defaults:** ensure Inbox + Personal exist per user (only
   users with data).
3. **Project conversion:** detect project-goals → create their
   Workspaces, link goals/tasks/materials/worklog. Skip if already linked
   (idempotent).
4. **Leave the rest NULL:** unassigned tasks/goals/memories keep
   `workspace_id = NULL`, interpreted as Inbox/Personal at read time —
   no bulk UPDATE needed (cheaper, and trivially reversible).
5. **Verify:** an integrity check (extend `verify_schema_integrity`)
   confirms every new table/index exists and that every workspace_id, if
   set, points to a real workspace. A Self-Test check (`core/selftest`)
   probes it live.

`workspace_id = NULL means Inbox` is the key simplification: it makes the
backfill *lazy and optional*, so migration is near-instant and fully
reversible.

## 5. Breaking-change avoidance

- **Commands:** all current commands (`list`, `done`, `projects`, `need`,
  `memory`, `habits`, …) keep working on the same tables. New workspace
  commands/NL are additive.
- **Dashboard / Offline Engine / Storage Facade:** unchanged read paths;
  they ignore `workspace_id` until the flag is on.
- **Flag-gated rollout:** `WORKSPACE=false` (default) ⇒ none of the above
  engages; behaviour is byte-identical to v14.26. Enable via canary
  (single-user temporal canary, the v14.7.1 RC playbook).

## 6. No-regression proof

The acceptance gate is the existing test corpus, run in **both** flag
states:
- **Automated:** the pytest suite (860 tests) must stay green with
  `WORKSPACE` OFF and ON. New workspace-engine tests are additive.
- **Manual:** the 44-test Quick Release Suite (`core/regression`) must
  pass — every existing behaviour (tasks, reminders, habits, projects,
  memory, AI, dashboard, admin) verified unchanged. Add workspace tests
  to the same growing suite (Definition of Done), never rewrite it.
- **Reversibility:** flag off + restart = today's bot, with the new
  tables lying dormant. If a canary reveals a problem, disable and ship.

## 7. Rollout phases (implementation milestones — not built here)

1. Schema + Storage Facade + Templates registry (dark).
2. Workspace Engine CRUD + Milestones + progress rollup (dark).
3. Timeline service + FTS search (dark).
4. Telegram sync outbox + worker (dark, then canary group).
5. AI Orchestrator resolvers (dark, then canary).
6. Migration/backfill + integrity + self-test.
7. Canary enable `WORKSPACE`, observe, then default-on.

Each phase is additive, flag-gated, tested, and independently
reversible — the same discipline that shipped the v14 Autonomous Core.
