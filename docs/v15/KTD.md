# KTD — Knowledge Timeline Design (v15.0)

*Design only.*

## 1. Principle

**Every meaningful action generates an immutable event. The user never
writes the timeline — BAKA maintains it automatically.** The timeline is
the workspace's journal, audit log, and the raw material for summaries,
reports, and (later) semantic search.

Event-sourcing-*lite*: the SQLite entity tables remain the authoritative
*state*; the timeline is a derived, append-only *history*. We do not
rebuild state from events (that would be a rewrite); we record what
happened alongside the state change, in one transaction.

## 2. Event model

```sql
timeline_events (
  id INTEGER PK,
  user_id INTEGER NOT NULL,
  workspace_id INTEGER,              -- nullable (global/Inbox events)
  entity_type TEXT,                  -- workspace | goal | milestone | task | note | file
  entity_id INTEGER,
  event_type TEXT NOT NULL,          -- see catalogue below
  summary TEXT NOT NULL,             -- human-readable one-liner (for the journal)
  payload TEXT,                      -- JSON: structured before/after detail
  source TEXT DEFAULT 'user',        -- user | ai | system
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  synced_at TEXT                     -- set by TWID when posted to Telegram
)
```

**Append-only:** the engine never UPDATEs or DELETEs a timeline row
except (a) `synced_at` stamping and (b) retention pruning (§5). No edit,
no rewrite — immutability is what makes it a trustworthy record.

### Event-type catalogue (extensible)

`workspace.created` · `workspace.archived` · `workspace.progress_changed`
· `goal.added` · `goal.met` · `milestone.added` · `milestone.started` ·
`milestone.completed` · `task.created` · `task.completed` ·
`note.added` · `knowledge.added` · `file.uploaded` · `summary.refreshed`
· `journal.daily` / `.weekly` / `.monthly`.

New event types are added as string constants — no schema change (same
open string-key approach as the Offline warning codes / selftest
categories).

## 3. Automatic generation

Events are emitted at the **write boundary**, not scattered through call
sites. A single `Timeline.record(event_type, entity, summary, payload,
source)` helper is called by the Workspace Engine's mutation methods
(create workspace, complete milestone, add note, …) inside the same
Storage-Facade operation. Design rule:

> If a workspace mutation does not emit a timeline event, it is a bug.

This mirrors how the Offline Engine logs a `[Offline]` block for every
dispatch — the timeline is the persisted, user-facing version of that
discipline. The AI Orchestrator (AWOD) is a heavy producer: "I finished
chapter six" → `task.completed` + `milestone.progress` +
`workspace.progress_changed` + `knowledge.added` events, all from one
utterance.

## 4. Storage & performance

- Indexed on `(user_id, workspace_id, created_at)` and `(entity_type,
  entity_id)` for the two access patterns: a workspace's journal, and an
  entity's history.
- Writes are cheap (one INSERT per event); reads are windowed (latest N
  per workspace). No rollup-on-write — summaries/reports are computed on
  demand or on a schedule (see §6).

## 5. Retention

- **Events are never edited**, but old ones can be **pruned or rolled
  up** to bound growth: after a configurable age (e.g. 180 days), a
  workspace's fine-grained events collapse into a single monthly
  `journal.monthly` summary event, and the originals are deleted. The
  journal stays readable; the DB stays small.
- Retention is per-user-configurable; default keeps everything for
  active workspaces and rolls up archived ones.
- Pruning runs as a low-frequency `job_queue` task, off the hot path.

## 6. Journal, reports, reviews

Derived views, not new state:
- **Daily journal:** the day's events per workspace, rendered to the
  Telegram Journal Topic (TWID) — a `journal.daily` event summarizing.
- **Weekly report / monthly review:** aggregate events → progress deltas,
  completed milestones, notes added → an AI-written summary
  (`summary.refreshed`). Scheduled via `job_queue`.
- These reuse the existing scheduler; they read the timeline, they do not
  duplicate state.

## 7. Search

- **v15 (ships): full-text search** over `notes` + `timeline_events.summary`
  + `workspaces.title/ai_summary` via SQLite **FTS5** (a virtual table
  kept in sync on write). Extends the current `search` command
  (tasks/memories/habits/goals) with workspace knowledge.
- **Future (designed-for, not built): semantic search.** An `embeddings`
  table (`entity_type, entity_id, vector`) populated by an embedding
  model, queried by cosine similarity. The timeline + notes are already
  the corpus; adding embeddings is additive. Knowledge graphs and
  cross-workspace linking build on the same event/entity data (an
  `entity_links` table) — all deferred, but the schema above does not
  block them.

## 8. What this preserves

- The timeline is a *new* table + a *new* service; nothing existing
  writes to it. `interaction_log`/`completions_log`/`snooze_log` (the
  current learning logs) are untouched — the timeline is the user-facing
  workspace journal, a different concern, and can later subsume them if
  desired (not in v15).
