# ADR-010: Destructive Operations Policy — Confirm Even When Legacy Doesn't

**Status:** Accepted — Stage 4 (task delete) implemented and shipped,
v14.5 (`core/actions/delete_task.py`).
**Part of:** BAKA v14 Autonomous Core, `DRG-001_Intent_Aware_Routing.md`'s
Sub-stage C.
**Depends on:** `docs/adr/ADR-008-offline-write-operations.md` (create,
Accepted), `docs/adr/ADR-009-offline-task-update.md` (update, Accepted).

## Problem

Three Offline write operations now exist, and each required an
independent Phase 0 finding about whether Legacy actually confirms
before writing — the answer was different every time:

- **Create** (`ADR-008`): Legacy's `execute_task_action()` always
  confirms. Offline matched it.
- **Update** (`ADR-009`): Legacy's editing-state handler never confirms.
  Offline matched *that* — adding a confirm step here would have been a
  behavioral divergence, not equivalence.
- **Delete** (this ADR): Legacy's `delete_task_cmd()` (verified directly,
  `main.py:483-504`) deletes **immediately, with zero confirmation of
  any kind** — even less safety than Update, despite being the one
  operation with no undo path at all.

Two prior architecture documents already anticipated destructive writes
needing confirmation — `INTENT_ENGINE.md`'s confidence-threshold table
("Write, destructive... 0.95, AND always still shows a confirmation
prompt regardless of score... No change from today's behavior") and this
sprint's own task brief (a dedicated Locate→Preview→Confirm→Delete→Verify→Return
safety specification) — but the first document's premise about "today's
behavior" is factually wrong for plain `/delete`, verified above. Without
a clear policy, each future destructive operation (a future Task
Complete, or any other irreversible action) would need to re-litigate
this question from scratch.

## Alternatives considered

1. **Continue the per-operation "match Legacy exactly" pattern verbatim**
   (`ADR-008`/`ADR-009`'s approach): Offline Delete deletes immediately,
   no confirmation, matching Legacy's real behavior precisely. Rejected:
   irreversibility is a categorically different risk than Create's
   "annoying if wrong, but fixable" or Update's "wrong, but correctable
   with another edit." A blind "match Legacy" rule doesn't distinguish
   operations where being wrong is inconvenient from operations where
   being wrong is permanent.
2. **Confirm destructive operations, deliberately diverging from Legacy
   where Legacy is under-safe (chosen).** Offline Delete adds a confirm
   step Legacy itself lacks. Documented prominently as an intentional,
   narrow policy exception — not a silent equivalence gap, and not a
   general license to diverge from Legacy wherever convenient.

## Decision

**Policy**: an Offline write operation confirms before executing when
either (a) Legacy's own real, verified behavior already confirms
(Create), or (b) the operation is irreversible (Delete, and any future
operation with no undo path — e.g. a future permanent data purge).
Operations that are real but *correctable* mistakes (Update — a wrong
edit can be re-edited) do not gain a confirm step merely for being a
write; Legacy's own real behavior remains the default there (`ADR-009`).

This is not "always confirm destructive-sounding actions" — it's
specifically anchored to **irreversibility**, which is the concrete,
checkable property that distinguishes Delete from Update. A future
Task Complete (out of this sprint's scope, `Do NOT begin Task Complete`)
is reversible (a completed task can presumably be un-completed) and
should default to matching Legacy's real behavior first, the same way
Update did — not assumed to need a confirm step just because this ADR
exists.

**Mechanism**: identical to Create's (`ADR-008`) — two-phase
`propose()`/`commit()`, `conversation_state.set_pending_action()` with a
distinct `action_type` (`"offline_delete_task"`), the same
`confirming`-state branch pattern in `main.py`. No new state-machine
primitive was needed.

**Idempotency and verification**, both explicit requirements for this
sprint given the operation's irreversibility: `commit()` re-checks
existence before deleting (a repeated confirmation or a concurrent
delete from another path is reported as `"already_deleted"`, not
attempted a second time or treated as an error), and re-fetches after
deleting to verify the row is actually gone before reporting success —
never claims success on faith.

## Consequences

**Positive:**
- Establishes a checkable, reusable rule (irreversibility, not
  "destructive-sounding") for any future write operation's Phase 0
  review, instead of re-deriving one from scratch each time.
- Closes the real safety gap `INTENT_ENGINE.md`'s architecture already
  intended to close, without touching Legacy's actual `/delete` command
  (out of scope for this migration; Legacy Router is explicitly not
  being modified) — the Offline path becomes safer than Legacy for this
  one operation, opt-in via `OFFLINE_TASKS`.
- Idempotency and post-delete verification make `commit()` safe to call
  more than once for the same pending data, which matters specifically
  because confirmation flows can be retried, double-tapped, or racy in
  ways a single-shot immediate delete never has to consider.

**Negative / accepted tradeoffs:**
- A real, measured equivalence gap: Legacy's `/delete <id>` is a single
  message; Offline `/delete`-equivalent is two (propose, then confirm) —
  the one dimension of this sprint's own "Behavioural Equivalence"
  section this ADR does *not* claim to satisfy, by deliberate design,
  documented here rather than silently.
- Measured overhead: Legacy's bare `delete_task()` averages ~0.45ms;
  Offline's `commit()` (existence check + delete + post-delete verify —
  three queries vs. Legacy's one) averages ~1.20ms — the direct,
  expected cost of the idempotency and verification guarantees, not
  wasted work.
- This ADR's "irreversibility" test is a judgment call, not a mechanical
  rule — a future write operation's Phase 0 review still needs to apply
  it deliberately (as this one did), not treat it as a lookup table.
