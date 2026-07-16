# ADR-011: Conversation State Priority — State Should Outrank Intent-Gated Dispatch

**Status:** Accepted — implemented in v14.12. `main.py`'s intent-gated
Offline dispatch now requires `not conversation_state.claims_messages(state)`
(i.e. runs only in `idle`); `confirming`/`gathering`/`editing` messages
belong to the state machine, exactly like Legacy. Implementation note:
this is deliberately *stricter* than this ADR's illustrative
parenthetical ("`state == "idle" or state == "editing"`") — Legacy's
editing handler claims ALL editing-state messages, and the Offline
editing path already has its own state-gated entry
(`continue_editing()`, ADR-009) that runs before Legacy's, so
intent-gated dispatch has no business in `editing` either. Regression
tests: `tests/test_conversation_state.py`.
*(Original status: Proposed — decision documented, implementation
deliberately NOT changed by the sprint that produced this ADR (v14.7),
per that sprint's explicit "do not silently change implementation"
instruction.)*
**Part of:** BAKA v14 Autonomous Core, `DRG-001_Intent_Aware_Routing.md`'s
Sub-stage C.
**Depends on:** `docs/adr/ADR-009-offline-task-update.md`, `STATE_MACHINE.md`.

## Problem

First surfaced during v14.6's Phase 0 conversation-state review
(`DEBUGGING.md`'s "Offline Engine gate runs before the confirming/gathering
state branches" entry), now promoted from a debugging observation to an
architectural decision: `main.py`'s `OFFLINE_TASKS`-gated
`OfflineEngine.execute()` call sits *above* the `confirming` and
`gathering` conversation-state branches in `handle_message()`. Only the
`editing` state is checked before intent-gated dispatch (added for
v14.4's update flow).

Concrete consequence, unreachable today (flag OFF everywhere) but real
the moment `OFFLINE_TASKS` is enabled: a user mid-confirmation (BAKA has
just asked "Shall I save this?") who types `"done 5"` would have task 5
completed by the Offline Engine — whereas Legacy's confirming handler
would have re-prompted ("Say yes to save, no to cancel..."). The same
applies to `"pause 3"`, `"list"`, `"delete 2"`, and every other
intent-gated Offline phrase, in both `confirming` and `gathering` states.
Legacy's own ordering is unambiguous: state branches run before the
slashless command table — state outranks command recognition everywhere
in the pre-v14 architecture.

## Alternatives considered

### Option A — Conversation State → Intent Engine → Offline Engine (chosen)

The state machine is consulted first; only a message that the current
state doesn't claim proceeds to intent-gated Offline dispatch.

- **Matches Legacy's real semantics exactly.** Every equivalence review
  since v14.2 has treated "what would Legacy do" as the ground truth;
  Legacy runs its state branches before its command table, so this is
  the only ordering under which "flag ON changes nothing except which
  code executes" stays true in mid-conversation states.
- **Matches the approved architecture's own design.** `STATE_MACHINE.md`
  specifies the Intent Engine *consults* conversation state as context,
  and `INTENT_ENGINE.md`'s `ConversationContext` carries `state` for
  exactly that reason — the architecture always assumed state-awareness,
  the integration point just doesn't implement it for two of the four
  states yet.
- **Precedent already exists in the codebase.** v14.4's update flow
  checks `state == "editing"` *before* intent-gated dispatch — Option A
  simply extends the same treatment to `confirming` and `gathering`.
- Cost: a user genuinely stuck in a conversation state can't escape it
  with a direct command — but Legacy already has this property, and both
  paths already honor "cancel"/"no" as the escape hatch, so nothing is
  lost relative to today.

### Option B — Intent Engine → Conversation State → Offline Engine (current implementation)

High-confidence command recognition outranks the conversation state.

- **Arguably closer to what the user meant**: someone who types
  `"done 5"` mid-confirmation probably does want task 5 completed, not a
  re-prompt about an unrelated pending save.
- **Simpler integration point** — the current code exists because each
  sprint added its gate at the top of `handle_message()`, above the
  state machinery it never needed to touch.
- Cost: a real, silent behavioral divergence from Legacy in every
  mid-conversation state, of exactly the kind every sprint's equivalence
  review exists to prevent — and one that would ship implicitly, having
  never been chosen on purpose (the current ordering is an accident of
  where the Shadow Mode hook was placed in v14.0, inherited by every
  stage since).

## Decision (recommendation — not yet implemented)

**Option A.** The deciding argument: Option B's benefit ("the user
probably meant the command") is a *product* judgment that would change
Legacy-vs-Offline behavior silently, while Option A preserves the
equivalence discipline this entire migration has treated as its prime
directive — including three sprints (`ADR-008`/`ADR-009`/`ADR-010`) that
each explicitly verified Legacy's real behavior rather than assume it.
If "commands should interrupt conversations" is ever wanted, it should
be a deliberate product decision applied to *both* paths, not an
accident of integration-point placement in one of them.

Implementation shape when picked up (small, not done here): move the
`OFFLINE_TASKS` `execute()` gate below the `confirming`/`gathering`
branches in `handle_message()` — or equivalently, guard it with
`state == "idle" or state == "editing"` — and add a regression test
asserting a mid-`confirming` `"done <id>"` re-prompts rather than
completes, in both flag states.

## Consequences

**Positive:**
- Closes the last known flag-ON behavioral divergence *before* any
  deployment enables `OFFLINE_TASKS` — every stage's Migration Review
  has named canary enablement as the next step; this decision is a
  pre-enablement blocker resolved on paper, cheap to implement.
- Keeps the equivalence ground rules consistent: Legacy's semantics are
  the specification, including its state-over-command priority.

**Negative / accepted tradeoffs:**
- Implementation is deferred — the divergence remains latent in the code
  until a future sprint applies this ADR. Accepted because the v14.7
  brief explicitly ordered "document and justify, do NOT silently change
  implementation," and because the flag remains OFF everywhere, making
  the divergence unreachable in the interim.
- Option A means the Offline Engine processes strictly fewer messages
  than the current ordering would allow (none in `confirming`/`gathering`)
  — a marginal reduction in Offline coverage, correct by design.
