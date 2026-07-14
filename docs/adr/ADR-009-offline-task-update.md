# ADR-009: Offline Task Update — Direct Apply, No Confirm Step, Matching Legacy's Real (Not Assumed) Behavior

**Status:** Accepted — Stage 3 (task update) implemented and shipped,
v14.4 (`core/actions/update_task.py`).
**Part of:** BAKA v14 Autonomous Core, `DRG-001_Intent_Aware_Routing.md`'s
Sub-stage C.
**Depends on:** `docs/adr/ADR-008-offline-write-operations.md` (task
creation, Accepted).

## Problem

The task brief for this sprint assumed task update should "preserve
Legacy confirmation flow" using "the same Pending Action system" as task
creation, with an explicit "do not modify data before confirmation"
requirement. Direct reading of `main.py`'s real update path —
`edit_task_cmd()` (line 506) and the `state == "editing"` handler (lines
1022-1055) — shows this assumption is factually incorrect: Legacy's
update flow calls `update_task()` **immediately** on the very next
message after `/edit <id>`, with no yes/no step, and does not use
`set_pending_action()` at all (it uses the separate `set_editing()`/
`get_editing_id()` mechanism). Implementing a new confirm step as the
brief described would itself be a behavioral divergence from Legacy —
directly contradicting the same brief's overriding goal ("It must
preserve Legacy behaviour").

A second incorrect assumption was found in the brief's SUPPORTED
examples: "change recurrence" is listed as a capability to migrate, but
`database.update_task()`'s real signature
(`task_id, user_id, title=None, due_date=None, due_time=None,
category=None, priority=None`) has no recurrence parameters at all, and
Legacy's editing handler doesn't pass any — Legacy cannot change a
task's recurrence today, full stop.

## Alternatives considered

1. **Implement the brief literally**: add a new pending-action confirm
   step for updates, and support recurrence changes. Rejected on both
   counts: the confirm step would make Offline Update behave differently
   from Legacy (worse for equivalence, not better), and recurrence
   support would give Offline Update a capability Legacy itself lacks —
   both are the opposite of "preserve Legacy behaviour," which is the
   brief's own stated priority above its specific implementation
   suggestions.
2. **Direct apply, reusing `conversation_state.py`'s real mechanism
   (chosen).** `start_editing()` calls the same `set_editing()`/
   `get_editing_id()` functions `edit_task_cmd()` already uses; the
   change-applying step commits immediately, exactly matching
   `main.py:1039-1045`'s real behavior. Recurrence changes are not
   recognized by any deterministic pattern, matching Legacy's real
   incapability rather than exceeding it.

## Decision

`core/actions/update_task.py` exposes two functions, mirroring Legacy's
real two-message shape (not `create_task.py`'s propose/commit shape,
which models Legacy's *different* create-flow confirm step):

- `start_editing(task_id, user_id, storage) -> ActionResult` — message 1
  ("edit task <id>" / "rename task <id>"). Verifies the task exists.
  Never writes. Caller (`main.py`) calls `conversation_state.set_editing()`
  — the same function `edit_task_cmd()` already calls.
- `apply_change(text, task_id, user_id, storage, now) -> ActionResult` —
  message 2, only reachable when conversation state is already
  `"editing"`. Recognizes date/time (reusing `date_parser.parse_all()`),
  and three new explicit patterns for priority/category/title — `date_parser`
  has no deterministic signal for these, so, per `ADR-007`/`ADR-008`'s
  established pattern, this module defines its own narrow, explicit
  regexes rather than relying on Intent Engine classification or
  modifying the already-Accepted, frozen Intent Engine. Commits
  immediately on a recognized change — no confirmation.

**Entry-point dispatch required broadening beyond `Intent.EDIT_TASK`**:
verified directly that `"rename task 5"` classifies `UNKNOWN` under the
shipped Intent Engine (no Tier 0 `"rename "` prefix exists), while
`"edit task 5"` correctly classifies `EDIT_TASK` at confidence 1.0 (Tier
0's existing `"edit "` prefix). `OfflineEngine.execute()` checks
`context.intent in (Intent.EDIT_TASK, Intent.UNKNOWN)` before attempting
`update_task.match_entry_command()`'s own specific regex — a third
instance of the coarse/missing-classification problem `ADR-007` and
`ADR-008` already found for other explicit commands.

**Change-dispatch required a new, state-gated Offline Engine entry
point**, `continue_editing()`, deliberately separate from `execute()`:
a bare reply like `"set time to 6pm"` carries no reliable `EDIT_TASK`
Intent Engine signal on its own (`core/intent/rules.py` has no notion of
conversation state), so `main.py` checks `state == "editing"` directly —
mirroring how Legacy's own `handle_message()` already prioritizes state
over intent-based routing — and calls `continue_editing()` instead of
routing through intent classification at all.

**Two deliberate, narrow, documented divergences from pure Legacy
equivalence** (both improvements, neither changes the user-visible flow
in a way that could surprise a user comparing the two paths):

1. **Date/time validation before writing.** Legacy's real update path
   never calls `validate_datetime()` — verified by reading the handler.
   This sprint's own Transaction Safety requirement ("validate first...
   if validation fails, no database modification") justifies adding it
   here; it only ever rejects a clearly-invalid date rather than
   silently accepting one.
2. **"cancel"/"nevermind"/"stop" recognition.** Legacy has no special
   handling for these while editing — it would hand them to the AI as if
   they were an edit description, producing a confusing no-op. Offline
   Update recognizes them explicitly and clears state cleanly. This only
   ever improves on that one specific input class; anything else
   unrecognized still falls through to Legacy exactly as before.

## Consequences

**Positive:**
- Genuinely matches Legacy's real, verified update UX (immediate apply,
  two-message flow) rather than the brief's incorrect assumption of a
  confirm step — the more defensible reading of "preserve Legacy
  behaviour" when the brief's specifics and its own stated goal
  conflict.
- `storage.tasks.update()`'s existing per-field-conditional semantics
  (from Stage 1) meant no Storage Facade changes were needed this
  sprint — only the changed field is ever passed non-`None`, verified by
  `test_apply_change_only_changes_the_targeted_field`.
- Falls through to Legacy's real AI-mediated handler for anything not
  deterministically recognized, exactly as the read-only and create
  stages already do — the same safety property, extended a third time.

**Negative / accepted tradeoffs:**
- Recurrence changes remain unsupported in both paths — this ADR
  documents Legacy's real limitation rather than closing it; a future
  sprint that wants recurrence-update support would need to add it to
  `database.update_task()` first, which is out of this sprint's scope
  (Storage Facade / Offline Engine work, not schema/business-logic work).
- A third instance of the Intent-Engine-coarseness pattern now exists
  (`ADR-007`: `QUERY_TASK`, `ADR-008`: `ADD_TASK`, this ADR: `EDIT_TASK`/
  `UNKNOWN`) — the case for a real fix (structured action hints in
  `IntentResult.entities`) grows stronger with each repetition; still not
  built.
- Measured overhead: Offline's `apply_change()` (full validate-then-commit
  cycle) averages ~0.95ms vs. ~0.79ms for Legacy's equivalent-scope
  deterministic work (`parse_all()` + `update_task()` + `get_task_by_id()`)
  — a ~0.16ms difference, from the added `validate_datetime()` call and
  explicit-pattern regex checks. Negligible next to Legacy's real
  production latency, which is dominated by its AI call (hundreds of ms
  to seconds, `AI_DIAGNOSTIC_REPORT.md`) that this benchmark cannot
  exercise offline.
