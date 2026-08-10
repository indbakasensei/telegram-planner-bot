# M10 — Telegram Topic Wiring Through WorkspaceGroups

**Date:** 2026-08-10
**Status:** **IMPLEMENTED in v15.1.0-alpha.13.** The plan below was carried out
as specified: the backfill and the NL-creation wiring both exist and are
covered by the offline pytest suite, a regression suite, and a self-test.
The only deviations from the plan are documented in
[`docs/engineering/M13_TOPIC_PROJECTION.md`](M13_TOPIC_PROJECTION.md): the
initial-card contract (cards are now posted into new topics), the shared
renderer, and the explicit consistency model for partial failures. The live
DB state table below is retained for reference; `B. Backfill` below is the
actual implemented design, not a sketch.

---

## Why this matters

Entities created through the `/add` command path get a Telegram topic (via
`WorkspaceGroups.add_entity`). Entities created through **natural language**
(`EntityManager._handle_create`) call `engine.add_milestone` directly and
bypass the projection — so NL-created entities have **no topic** and no
entity↔topic binding. Real entities already exist in the database (the Genshin
test workspace), and the owner must **not** be required to recreate them.
M10 has two parts:

1. **Backfill** — safely create missing topics for existing entities.
2. **Wiring** — make NL entity creation call the existing topic projection.

## Existing topic creation API (reuse, don't build new)

`core/workspace/adapters/projection.py` — `TelegramProjection`:

- `ensure_entity_topic(user_id, workspace_id, entity_type, entity_id, title) -> int | None`
  — **already idempotent.** Looks up the workspace binding; returns `None` if
  the workspace isn't linked to a group. Otherwise checks
  `get_entity_topic(entity_type, entity_id)` and returns the existing topic;
  only if none exists does it call `client.create_forum_topic(chat_id, title)`
  and persist the binding via `set_entity_topic`. **Re-running is safe by
  construction** — it can never create a duplicate topic.
- The production `TelegramClient` (create_forum_topic / send_message /
  send_photo) is constructed in `main.py` (`make_projection_client` in
  `core/workspace/app.py`); tests inject a fake.

## Existing entity-topic binding API

`core/storage/storage.py` → `TelegramBindingStorage` (thin passthrough to
`database.py`):

| Function | Purpose |
|---|---|
| `tg_link_workspace(user_id, workspace_id, chat_id, general_topic_id=None)` | bind workspace ↔ group |
| `tg_get_binding(workspace_id)` | `(chat_id, general_topic_id)` or `None` |
| `tg_get_workspace_for_chat(chat_id)` | reverse lookup |
| `tg_set_entity_topic(user_id, workspace_id, entity_type, entity_id, topic_id)` | persist entity ↔ topic |
| `tg_get_entity_topic(entity_type, entity_id)` | existing topic for one entity |
| `tg_get_entity_topics(workspace_id)` | all entity topics in a workspace |
| `tg_set_active / get_active / clear_active` | per-user active context |

Tables: `tg_workspace_bindings`, `tg_entity_topics` (entity_type='milestone'
is the workspace-entity entity type, `ENTITY_TYPE` in `groups_app.py`),
`tg_active_context`.

## Current entity/topic state (inspected 2026-08-10, `planner.db`)

**Genshin workspace (id 1), user 793991074 — linked to chat
`-1003859227721`, general_topic_id `None`.** 16 entities, 2 with topics:

| Entity (milestone id) | Topic | Has topic? |
|---|---|---|
| Hu Tao (1) | 5 | ✅ |
| Akasha Ranking (12) | 7 | ✅ |
| Furina (20) | — | ❌ |
| Golden Troupe (21) | — | ❌ |
| Neuvillette (22) | — | ❌ |
| Raiden Shogun (23) | — | ❌ |
| Diluc (24) | — | ❌ |
| Kaeya (25) | — | ❌ |
| Sucrose (26) | — | ❌ |
| Zhongli (27) | — | ❌ |
| Xiao (37) | — | ❌ |
| Kinich (38) | — | ❌ |
| Xilonen (39) | — | ❌ |
| Nefer (40) | — | ❌ |
| Lauma (41) | — | ❌ |
| Columbina (42) | — | ❌ |

→ **14 Genshin entities are missing topics.**

**Valorant workspace (id 8), user 793991074 — linked to chat
`-1004347614441`.** 7 milestones, 5 with topics (15,16,17,18,19); milestones
13 and 14 ("50 Bot Elimination" — apparent duplicates) have none.

**Workspaces 9/10/11 ("Test Game", user 555001999)** are self-test residue,
**not linked to any group** — no topics possible or needed.

## Idempotent backfill design (implemented)

`WorkspaceGroups.backfill_topics(user_id, projection) -> dict` (in
`core/workspace/groups_app.py`) is the implemented version of the sketch
below. It iterates the user's **active** workspaces, skips unlinked ones
(reported `linked: False`, no Telegram call), and for each linked workspace
iterates `engine.list_milestones` (soft-deleted excluded), classifying each
entity as `created` / `existing` by whether a `tg_entity_topics` binding
existed **before** `ensure_entity_topic` ran. Per-entity exceptions land in
`errors[]`; the loop keeps going. The report shape is
`{workspace_id: {title, linked, created[], existing[], errors[]}}`.

```
for ws in engine.list_workspaces(user_id):          # active only
    if not storage.tg_bindings.get_binding(ws.id):
        report[ws.id] = {"linked": False}; continue
    for m in engine.list_milestones(user_id, ws.id):
        had = storage.tg_bindings.get_entity_topic(ENTITY_TYPE, m.id)   # BEFORE
        try:
            topic_id = projection.ensure_entity_topic(                   # shared path
                user_id, ws.id, ENTITY_TYPE, m.id, m.title,
                initial_message=format_entity_card(m, with_timestamp=True))
        except Exception as exc:
            errors.append(f"{m.title}: {type(exc).__name__}: {exc}"); continue
        (created if had is None else existing).append(m.title)
```

Guarantees (unchanged from plan):
- **Idempotent** — `ensure_entity_topic` never calls `create_forum_topic`
  when a binding already exists; re-running a backfill creates nothing and
  never re-posts an initial card.
- **No entity/data changes** — only rows are added to `tg_entity_topics`;
  milestone ids, titles, fields, workspaces are untouched.
- **No cross-workspace collision** — bindings are keyed by
  `(entity_type, entity_id)`; topic creation is scoped per linked chat.
- **Soft-deleted entities excluded** — `list_milestones` already filters them.
- **Initial cards are real** — each new topic receives a card rendered by
  `core/workspace/render.py` from live DB state (never invented), with an IST
  timestamp.
- Safe against a partially-linked workspace (binding guard) and a bot without
  forum-admin rights (Telegram raises; the loop records the title in
  `errors[]`, never silently claims success).

Invocation: **`/topicbackfill`** (admin-only, in main.py) runs it with the
live projection via `asyncio.to_thread` and reports created/existing/skipped/
errors. It is an explicit migration/sync op — no startup-time backfill runs.

## How NL entity creation calls the projection (implemented)

`EntityManager.process(user_id, text, projection=None)` now accepts an
optional duck-typed projection (injected by main.py; tests inject a fake).
EntityManager stays Telegram-agnostic — it never imports a Telegram module.
A successful create routes through `_handle_create`, which:
`engine.add_milestone` → `projection.ensure_entity_topic(..., initial_card)`
→ `tg_bindings.set_active` (M1 active entity, unchanged). This is the SAME
`ensure_entity_topic` contract `WorkspaceGroups.create_entity` uses, so NL
creation, `/add`, and `/topicbackfill` all share exactly one creation site.
A successful update routes through `_handle_update`, which appends a minimal
`post_entity_update` message (old values captured from the pre-update DB
read; topic self-heals with a fresh card if it never existed). Projection
failures are logged and reported in the reply; the DB operation never rolls
back. See `M13_TOPIC_PROJECTION.md` for the full consistency model.

## Duplicate-topic prevention summary

Prevention is **still structural** in `ensure_entity_topic`: it consults
`tg_entity_topics` before calling `create_forum_topic`, and the topic id is
stored immediately after creation. The backfill reuses that single code path,
so there is exactly one creation site. Nothing needs a new lock or dedup
table; the existing binding row *is* the guard. Two alpha.13 hardening
details:

- The binding write after `create_forum_topic` is **retried once** on a
  transient DB error, so a freshly created topic is not orphaned (a re-run
  would otherwise duplicate it). A persistent failure surfaces in the
  backfill `errors[]` and the re-run creates a fresh topic + binding — the
  documented non-atomicity (see `M13_TOPIC_PROJECTION.md`).
- Initial cards are only ever posted into a **newly created** topic, so
  re-running can never post a duplicate card.

## Out of scope for M10

- Workspace Groups' `/add`/`open` command behavior (unchanged).
- Projecting notes/photos or routing conversation into topics (the projection
  already does this via `post_note`; M10 only closes the *creation* gap).
- Recreating or renaming any existing entity, topic, or workspace.
