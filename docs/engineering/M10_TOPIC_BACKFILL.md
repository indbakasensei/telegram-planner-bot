# M10 — Telegram Topic Wiring Through WorkspaceGroups (plan only)

**Date:** 2026-08-10
**Status:** scope + migration plan only. **Nothing here is implemented in
this pass.** M10 is a later milestone; this document answers the questions the
owner asked before any topic backfill runs.

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

## Idempotent backfill design

Because `ensure_entity_topic` already checks the existing binding before
creating, a backfill is a loop, safe to re-run:

```python
def backfill_topics(user_id, workspace_id, client) -> dict:
    proj = TelegramProjection(client)              # production client
    if not proj.is_linked(workspace_id):
        return {"skipped": "workspace not linked"}
    binding = storage.tg_bindings.get_binding(workspace_id)
    created, existing, skipped = [], [], []
    for m in engine.list_milestones(user_id, workspace_id):
        t = proj.ensure_entity_topic(user_id, workspace_id,
                                     ENTITY_TYPE, m.id, m.title)
        if t is None:
            skipped.append(m.title)
        elif storage.tg_bindings.get_entity_topic(ENTITY_TYPE, m.id) == t:
            existing.append(m.title)  # was already bound before this run
        else:
            created.append(m.title)
    return {"created": created, "existing": existing, "skipped": skipped}
```

Guarantees:
- **Idempotent** — `ensure_entity_topic` never calls `create_forum_topic`
  when a binding already exists; re-running a backfill is a no-op for the
  already-bound entities.
- **No entity/data changes** — only rows are added to `tg_entity_topics`;
  milestone ids, titles, fields, workspaces are untouched.
- **No cross-workspace collision** — bindings are keyed by
  `(entity_type, entity_id)`; topic creation is scoped per linked chat.
- **Soft-deleted entities excluded** — `list_milestones` already filters them.
- Safe against a partially-linked workspace (`is_linked` guard) and a bot
  without forum-admin rights (Telegram raises; the loop should fail loudly
  and record the title, never silently claim success).

## How NL entity creation should eventually call the projection

`EntityManager._handle_create` currently calls `engine.add_milestone`
directly. The existing integration point that does entity **and** topic in
one step is `WorkspaceGroups.add_entity(user_id, name, projection)` — it adds
the milestone, calls `ensure_entity_topic` when a projection is supplied, and
sets the new entity active. The M10 wiring change is therefore to route the
NL create through the groups layer (or the equivalent) rather than inventing
a parallel topic path:

```
EntityManager._handle_create
  → WorkspaceGroups.add_entity(user_id, name, projection)   # projection from main.py
      engine.add_milestone(...)
      projection.ensure_entity_topic(...)   # idempotent, no duplicate
      tg_bindings.set_active(user_id, ws_id, ENTITY_TYPE, m.id)
```

Considerations to resolve in M10 (not this pass):
- EntityManager is deliberately Telegram-agnostic today. The clean seam is
  for main.py to supply the projection (as it does for the `/add` handler),
  or for EntityManager to accept an optional projection, so the core stays
  offline-testable.
- The **active entity** should also remain the M1 `tg_active_context` write —
  `set_active(entity_type, entity_id)` is compatible (M1 stores the same
  shape), so reference resolution keeps working after the wiring.
- Backfill and live creation must share the same code path so new entities
  never desync from the backfill logic.

## Duplicate-topic prevention summary

Prevention is **already structural** in `ensure_entity_topic`: it consults
`tg_entity_topics` before calling `create_forum_topic`, and the topic id is
stored immediately after creation. The backfill reuses that single code path,
so there is exactly one creation site. Nothing in M10 needs a new lock or
dedup table; the existing binding row *is* the guard.

## Out of scope for M10

- Workspace Groups' `/add`/`open` command behavior (unchanged).
- Projecting notes/photos or routing conversation into topics (the projection
  already does this via `post_note`; M10 only closes the *creation* gap).
- Recreating or renaming any existing entity, topic, or workspace.
