# M13 — Telegram Entity Topic Projection (v15.1.0-alpha.13)

**Date:** 2026-08-10
**Status:** implemented, offline-verified (full pytest suite 1301 green;
Workspace self-tests green). Live-Telegram acceptance pending the manual
matrix in `TESTING.md` / the regression suite `TOP-001…TOP-009`.

## What changed

The M10 gap was that entities created through **natural language**
(`EntityManager._handle_create`) called `engine.add_milestone` directly and
bypassed the Telegram topic projection — so NL-created entities had no topic,
no binding, and no initial card, and the owner would have had to run `/add`
or a manual backfill. Alpha.13 closes that gap by giving every entity-creation
path the same **entity ⇒ topic ⇒ initial card** projection, and adds an
idempotent backfill (`/topicbackfill`) for entities that predate the feature.

The design constraint throughout: **do not build a second topic-management
implementation.** NL creation, `/add`, and backfill all converge on the
existing `TelegramProjection.ensure_entity_topic`; the only new machinery is a
shared card renderer and a thin, Telegram-agnostic projection seam inside
`EntityManager`.

## The single entity/projection contract

Every successful entity creation goes through one consistent
entity/projection contract. There are two entry points, but they compose the
**same primitives** and share the same `ensure_entity_topic` call:

```
WorkspaceGroups.create_entity(user_id, ws_id, name, projection)   # shared contract
  ├─ engine.add_milestone(...)                  # the single DB mutation
  ├─ projection.ensure_entity_topic(..., initial_message=card)   # topic + binding + card
  └─ tg_bindings.set_active(...)                # active entity (M1)

WorkspaceGroups.add_entity(user_id, name, projection)   # /add path
  └─ delegates to create_entity(active_ws, ...)

EntityManager._handle_create(user_id, ws_id, name, projection)   # NL path
  ├─ duplicate-title guard (caller-level, kept)
  ├─ engine.add_milestone(...)                  # same mutation choke-point
  ├─ projection.ensure_entity_topic(..., initial_message=card)
  ├─ _activate_entity(...)                      # set_active + M1 mention note
  └─ confirmation reply
```

`EntityManager` does **not** call `WorkspaceGroups.create_entity` because it
keeps caller-level concerns the groups layer doesn't own — its duplicate-title
guard, its `_activate_entity` (which additionally notes the mention for M1
reference resolution), and its richer reply. But it calls the exact same
`engine.add_milestone` + `projection.ensure_entity_topic` + `set_active`
sequence, so the invariant holds: **one creation site per mechanism, one
idempotent projection call for the topic.**

## The projection seam (Telegram-agnostic)

`EntityManager.process(user_id, text, projection=None)` accepts an optional
**duck-typed** projection. `EntityManager` never imports a Telegram module;
`main.py` injects the live `TelegramProjection` (built by
`_ws_projection(context)`) and tests inject a fake/recorder. The only methods
the seam uses:

- `ensure_entity_topic(user_id, ws_id, entity_type, entity_id, title,
  initial_message=None) -> int | None`
- `post_entity_update(user_id, ws_id, entity_type, entity_id, entity_title,
  text, initial_message=None) -> ProjectionResult`

A projection failure **never fails or rolls back the DB operation** — it is
logged and surfaced in the reply ("⚠️ topic NOT created — repair with
/topicbackfill"), or swallowed into the backfill's `errors[]`.

Because the live projection client bridges to the async bot via
`asyncio.run_coroutine_threadsafe(...).result(timeout)`, main.py runs
`EntityManager.process` on a worker thread (`asyncio.to_thread`), exactly like
the existing `/add` handler. The projection object itself is safe to build on
the event loop.

## Shared renderer: `core/workspace/render.py`

The chat reply card and the topic's initial card previously could diverge (two
formatting implementations). Alpha.13 introduces one renderer:

- `format_entity_card(entity, with_timestamp=False)` — title, status,
  current fields, optional IST timestamp. Used by the chat reply, the topic's
  initial card, and (fresh) the self-heal card. Fields that are `None` or
  dict/list values are skipped; everything user-supplied is HTML-escaped.
- `format_entity_update(entity, changes)` — append-only update message where
  `changes` maps field → `(old_value, new_value)`; old is shown only when it
  was actually read from the pre-update DB.

`EntityManager._format_entity_card` now delegates to `format_entity_card`, so
there is exactly one card format.

## Topic contracts

### `ensure_entity_topic` — idempotent, initial card on new only

- Unlinked workspace → returns `None`, no Telegram call.
- Existing `tg_entity_topics` binding → returns the stored topic id, creates
  **nothing** (no duplicate topic, no duplicate card).
- New → `client.create_forum_topic(chat_id, title)` (title truncated to 128 by
  the live client), writes the binding, then **best-effort** posts
  `initial_message` (an HTML entity card) into the new topic. A card-send
  failure is logged and ignored: the topic + binding are the durable unit, and
  re-running is a no-op rather than a duplicate-card risk.

### `post_entity_update` — append-only, self-healing

- Unlinked → `ok=False, reason="not_linked"` (the caller still commits the DB
  update).
- Ensures the entity's topic (self-heals a missing topic by creating it and
  posting the entity's **current** card), then appends one update message
  (`parse_mode="HTML"`). Old messages are never rewritten or deleted. The
  `initial_message` for the self-heal card is rendered from the fresh
  post-update milestone, never a stale field.

## Backfill: `WorkspaceGroups.backfill_topics`

Generic — operates on whatever workspaces/bindings exist, never hardcoding a
domain or entity list. Iterates the user's active workspaces; skips unlinked
ones (`linked: False`, no Telegram call); for each linked workspace iterates
`engine.list_milestones` (soft-deleted excluded) and calls the shared
`ensure_entity_topic` with a live-DB initial card. Entities whose binding
existed before the call are reported `existing` (no re-post); ones without are
reported `created`. Per-entity exceptions are collected into `errors[]` and the
loop continues. Re-running creates nothing and posts no duplicate card.

Invocation: **`/topicbackfill`** — admin-only, in `main.py`, runs it with the
live projection via `asyncio.to_thread`, and reports
created/existing/skipped/errors. It is an explicit migration/sync op — no
startup-time backfill, and it only ever touches workspaces with a group
binding.

## Consistency model (documented, not fake-atomic)

- **DB entity is durable.** `engine.add_milestone` commits first; a topic
  failure never undoes the entity.
- **Topic + binding is the durable Telegram unit.** The card/update sends are
  best-effort (logged, never fail the caller).
- **Binding-write hardening.** If the binding write right after
  `create_forum_topic` hits a transient DB error, `ensure_entity_topic`
  retries it once — so a freshly created topic is not orphaned (a re-run would
  otherwise duplicate it).
- **Residual non-atomicity.** If the binding write fails *persistently*, the
  topic exists in Telegram but is unbound (an orphan), the failure lands in
  `backfill_topics`'s `errors[]`, and a later re-run creates a fresh topic +
  binding. The orphan is unreachable (Telegram has no topic-listing API we
  use), so we do **not** pretend distributed atomicity — it is documented, not
  silently recovered.
- **Repair path.** `/topicbackfill` is idempotent and is the tool for any
  topic that was missed at create time.

## Coverage

- Offline pytest: `tests/test_topic_projection.py` (24) +
  `tests/test_entity_manager_projection.py` (8) — idempotency, initial cards
  from DB, escaping, soft-deleted exclusion, unlinked skip, partial/permission
  failures, transient vs persistent binding-write failures, cross-workspace
  same-name, duplicate creation, NL create/update projection, projection-
  failure survival, bare-reference/retrieve no-call.
- Self-test: `core/selftest/tests/test_workspace.py::check_topic_backfill`
  (Workspace category, `/selftest`).
- Regression: `core/regression/suites/topic_projection_m10.py` — TOP-001…
  TOP-009 (Quick Release Suite), mapping to the manual live-Telegram
  acceptance matrix (A–G).
