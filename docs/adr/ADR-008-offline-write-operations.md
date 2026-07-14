# ADR-008: Offline Write Operations — Two-Phase Propose/Commit, Reusing conversation_state.py

**Status:** Accepted — Stage 2 (task creation) implemented and shipped,
v14.3 (`core/actions/create_task.py`).
**Part of:** BAKA v14 Autonomous Core, `DRG-001_Intent_Aware_Routing.md`'s
Sub-stage C.
**Depends on:** `docs/adr/ADR-007-offline-engine-stage1.md` (Offline Engine
Stage 1, Accepted), `STATE_MACHINE.md`.

## Problem

Stage 1's Offline Engine (`ADR-007`) is single-phase: `execute(context) ->
ActionResult`, read-only, no confirmation needed. Task creation is BAKA's
first Offline write operation, and `main.py`'s real `execute_task_action()`
(the function Legacy's `confirming` state calls) revealed, on direct
reading, that it **always** confirms before saving — validates
(`validate_datetime()`), checks for a duplicate (`task_exists()` — if
found, reports the existing task's ID rather than creating a second one),
maps recurrence, saves, conditionally marks a deadline, and only then
shows a success message — with no code path that skips the two-turn
confirm step. This is consistent with `feature_list.md`'s original v1.0
design principle ("BAKA owns your tasks... " confirmation-before-write
discipline), re-affirmed by `docs/adr/ADR-005-autonomous-core.md`'s explicit
statement that v14 does not reduce user confirmation. A single-phase
`execute()` that saves directly would be a real, unjustified behavioral
divergence from this property — not an infrastructure detail.

## Alternatives considered

1. **Single-phase, save directly on high confidence.** Rejected: no
   Legacy precedent exists for direct-save task creation of any kind
   (confirmed by reading `execute_task_action()` directly, not assumed).
   Also directly contradicts `INTENT_ENGINE.md`'s own stated rationale for
   the reversible-write confidence threshold ("Matches today's
   confirmation-flow precedent... BAKA already always confirms saves") —
   that threshold was never meant to justify skipping confirmation, only
   to gate *whether a destination is trusted enough to route to at all*.
2. **Single-phase, but confirmation handled entirely by the caller with no
   Offline Engine involvement in the commit** (i.e., propose only; the
   confirmed reply falls through to Legacy's own `execute_task_action()`
   for the actual save). Rejected: this would mean the Offline Engine
   never actually completes a write in practice — Legacy would still own
   every save, including ones the Offline Engine correctly parsed,
   defeating "the first write operation handled by the Offline Engine."
3. **Two-phase propose/commit, reusing `conversation_state.py`'s existing
   `set_pending_action`/`confirming` machinery (chosen).** `STATE_MACHINE.md`
   already anticipated this need: "it needs these four states to be
   reachable from more entry points... than `main.py`'s hand-written
   transitions currently allow." `propose()` parses, validates, and
   returns a `pending_data` dict without writing; `main.py`'s integration
   point stores it via the *same* `set_pending_action()` Legacy already
   uses, with a distinct `action_type` ("offline_add_task") so the
   confirming-state handler can route it to `OfflineEngine.execute_pending()`
   (which calls `commit()`, writing via the Storage Facade) instead of
   Legacy's `execute_task_action()`.

## Decision

`core/actions/create_task.py` exposes two functions instead of Stage 1's
single `execute()`:

- `propose(context: RequestContext, storage: Storage) -> ActionResult` —
  parses the four recognized verb prefixes ("add task "/"create task "/
  "new task "/"todo "), reuses `date_parser.parse_all()`/`validate_datetime()`
  for date/time/recurrence/priority/is_deadline, checks for a duplicate via
  the Storage Facade, and returns either a duplicate notice, a validation
  error, or `success=True` with `metadata={"needs_confirmation": True,
  "pending_data": {...}}`. **Never writes.**
- `commit(pending_data: dict, user_id: int, storage: Storage) -> ActionResult` —
  the actual save, mirroring `execute_task_action()` field-for-field
  (title check, re-validation, re-check for a duplicate, `storage.tasks.add()`,
  conditional `storage.tasks.mark_as_deadline()`, success message). Called
  only from `OfflineEngine.execute_pending()`, itself called only from
  `main.py`'s `confirming`-state handler after a "yes" reply.

`OfflineEngine` (`core/offline/engine.py`) gains a second public method,
`execute_pending(action_type, pending_data, user_id) -> ActionResult`,
alongside Stage 1's `execute()` — deliberately separate, since there is no
fresh `RequestContext` at confirm time, only the `pending_data` a prior
`propose()` produced.

`TaskStorage` (`core/storage/storage.py`) gains `mark_as_deadline()`,
delegating to `database.mark_as_deadline()` — the same "thin, one-line
delegation" discipline every other Storage Facade method already follows
(v14.1C's Phase 0 review).

**Dispatch recognizes exactly four verb prefixes, checked directly
against raw text** — not via Intent Engine classification. Verified
directly: "todo buy milk" does not match any existing Intent Engine rule
(classifies `UNKNOWN`); "add task buy milk" matches only a weak Tier 4
keyword ("add"), confidence ~0.4 — both below `INTENT_ENGINE.md`'s
approved 0.75 reversible-write threshold. Rather than lower that threshold
or modify the already-Accepted, frozen Intent Engine, this is the same
dispatch-layer stopgap `ADR-007` already established for Stage 1's
`Intent.QUERY_TASK` coarseness — now in a more severe form (missing/weak
classification, not just coarse-but-present). See `DEBUGGING.md`.

**Title is the verb-prefix-stripped remainder, verbatim** — a trailing
date/time phrase (e.g. "buy milk tomorrow at 5pm") is not cleaned out.
Natural-language title cleaning requires understanding, which is
explicitly out of scope (no AI, `OFFLINE_ENGINE.md`'s own stated
limitation). Documented as an accepted, real behavioral difference from
what an AI-mediated Legacy title would look like — not attempted with a
fragile regex approximation.

## Consequences

**Positive:**
- Preserves BAKA's "always confirm before writing" property exactly —
  the property this ADR's Problem section identifies as the thing most at
  risk of being silently broken by infrastructure work.
- `commit()`'s re-validation happens against the real clock at confirm
  time (no injected `now`), which — verified directly by reading
  `execute_task_action()` — is *exactly* what Legacy already does (it
  doesn't thread a `now` through either). A task proposed as valid that
  becomes stale by the time the user confirms is rejected identically in
  both paths, not a new Offline-only behavior.
- Duplicate detection inherits `database.task_exists()` verbatim via the
  Storage Facade, including a real, pre-existing limitation found while
  testing: `WHERE due_date=?` never matches when `due_date` is `NULL`
  (standard SQL semantics — `NULL = NULL` is not true) — meaning
  duplicate detection silently doesn't work for tasks with no due date,
  in Legacy exactly as much as in Offline. Verified as inherited
  behavior, not introduced by this change; documented rather than "fixed"
  (fixing it here would break equivalence).
- `main.py`'s footprint stays small and additive: one new `if action_type
  == "offline_add_task":` branch in the `confirming` handler, styled
  identically to the existing `admin_reset_tasks`/`admin_reset_all`
  branches immediately above it — not a rewrite of that function.

**Negative / accepted tradeoffs:**
- `main.py`'s `confirming`-state branch is now touched for the first
  time by Offline Engine work (Stage 1 only touched the top of
  `handle_message()`) — a larger integration surface than Stage 1's,
  accepted because it's the only way to achieve genuine confirm-flow
  equivalence (see Alternatives, option 2).
- Title verbatim-retention of trailing date/time phrases is a real,
  user-visible quirk (e.g. a task titled "call mom tomorrow at 5pm"
  rather than a clean "call mom") — accepted as honest given the
  no-AI constraint, not silently hidden.
- The `Intent.QUERY_TASK`-coarseness-style dispatch tension from `ADR-007`
  now has a second instance (`Intent.ADD_TASK` under-classifying these
  four verbs) — both remain open, tracked debt pointing at the same
  eventual fix (a structured action/command hint in `IntentResult.entities`
  at classification time), not resolved by either ADR individually.
