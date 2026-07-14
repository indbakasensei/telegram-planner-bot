# ADR-006: Intent-Aware Routing — A Distinct Routing Layer, Not Folded Into the Intent Engine or Offline Engine

**Status:** Proposed — design only, `DRG-001_Intent_Aware_Routing.md`. No
code changes accompany this ADR.
**Part of:** BAKA v14 Autonomous Core (`DESIGN_SPEC_v14_AUTONOMOUS_CORE.md`)
**Depends on:** ADR-002 (Intent Engine — Accepted, Stage 1 shipped)

## Problem

The Intent Engine (`core/intent/`, Stage 1, Shadow Mode) produces a real
`IntentResult` on every message but nothing consumes it. Three existing
design documents describe the components downstream of it —
`OFFLINE_ENGINE.md` (execution for deterministic commands), `AI_ROUTER.md`
(provider selection for AI-shaped requests), `COMMAND_PIPELINE.md` (the
overall request lifecycle, sketched at a high level) — but none of them
owns the actual decision of *which* of those destinations a given
`IntentResult` should reach. `COMMAND_PIPELINE.md`'s stages 3–5
(Validation/Permission/Execution) gesture at this but were never given a
concrete contract, ownership boundary, or failure-mode analysis of their
own. Building this decision logic without that analysis risks the same
class of bug this project has now hit twice: `date_parser.py`'s
flat-pattern-list fragility (`ADR-002`'s cited precedent) and `core/intent/`'s
own near-miss tier-ordering bug found during Stage 1's testing (`ADR-002`'s
Implementation Note) — both traced back to a priority decision made
implicitly rather than reviewed.

## Alternatives considered

1. **Fold routing logic into the Intent Engine itself** (`classify()`
   returns a destination directly, not just a classification). Rejected:
   this would violate the Intent Engine's own, already-Accepted design
   constraint (`docs/adr/ADR-002-intent-engine.md`, `core/intent/intent_engine.py`'s
   docstring: "MUST NOT ... dispatch commands, execute handlers") and
   conflate two independently-testable concerns — "what does this message
   mean" and "what should happen given what it means" — that Stage 1's own
   test suite benefited from keeping separate (100% coverage of a *pure*
   classifier was achievable specifically because it has no execution
   side-effects to mock).
2. **Fold routing logic into the Offline Engine** (Offline Engine decides
   for itself whether to handle a request or defer to Legacy/AI). Rejected:
   `OFFLINE_ENGINE.md` already scopes itself to "execution for commands that
   don't need AI" — giving it the additional job of deciding whether *AI
   Router or Legacy* should run instead would mean the Offline Engine needs
   knowledge of both the AI Router's capability matrix and Legacy's command
   coverage, expanding its scope well beyond `OFFLINE_ENGINE.md`'s own stated
   boundaries and creating a circular-feeling dependency (Offline Engine
   deciding when to call something that isn't the Offline Engine).
3. **A distinct Routing Layer, consuming `IntentResult`, producing a new
   `RoutingDecision`, owned by neither the Intent Engine nor Offline Engine
   (chosen).** Mirrors this project's existing precedent for exactly this
   kind of decision: `AI_ROUTER.md`'s own provider-selection logic is
   already a distinct component from any individual provider adapter, for
   the identical reason (selection logic shouldn't live inside the thing
   being selected). Applying the same separation one layer up — a component
   that selects *among* Offline Engine / Legacy / AI Router, owned by none
   of them — is structurally consistent with a pattern this architecture
   already uses successfully.

## Decision

Introduce a **Routing Layer** as a new, named architectural component
(`DRG-001_Intent_Aware_Routing.md`), sitting between the Intent Engine and
every execution destination. It consumes `IntentResult` (unmodified — no new
fields added to that already-shipped dataclass) and `ConversationContext`,
and produces a new `RoutingDecision` record (trace ID, the carried
`IntentResult`, a `Destination` enum value, an optional `fallback_reason`,
and its own decision latency). It owns destination selection, trace ID
generation, shallow routing-relevant well-formedness checks, and fail-safe
error containment (any exception anywhere upstream of a successful
destination selection defaults to the `Legacy` destination — the one
destination requiring no `IntentResult` at all, since it's today's
already-working, unmodified `main.py` routing). It does not own execution,
deep validation, permission checks, state transitions, AI provider
selection, or response formatting — each remains exactly where
`COMMAND_PIPELINE.md`/`STATE_MACHINE.md`/`AI_ROUTER.md`/`OFFLINE_ENGINE.md`
already assign it.

The Confidence Policy extends `INTENT_ENGINE.md`'s already-approved
per-intent-class thresholds (read-only 0.6 / reversible-write 0.75 /
destructive-write 0.95) with a fourth destination tier (`Legacy`,
transitional, numerically identical thresholds to `Offline` — the
distinction is implementation status, not trust) and, new to this design,
treats `IntentResult.ambiguity` (computed by Stage 1 since v14.0 but
previously unused) as an independent safety gate, capping any
high-ambiguity result at `Legacy` regardless of raw confidence.

Migration is staged as four sub-stages nested inside the master spec's own
Stage 2 (Shadow → Decision/comparison-logging-only → Offline/real routing,
one command group at a time → Legacy removal, per group, once sustained
confidence exists) — deliberately not given new top-level version or stage
numbers, to avoid the version-numbering collision this project's own
`ROADMAP.md` has already documented once.

## Consequences

**Positive:**
- Keeps the Intent Engine's Stage 1 design (`ADR-002`) and its 100%-covered,
  pure-function testability property completely intact — the Routing
  Layer's own logic can be unit tested the same way, against `IntentResult`
  fixtures with no Telegram/database/AI mocking required, extending rather
  than compromising the precedent Stage 1 set.
- Makes "which command groups are still on Legacy vs. migrated to Offline"
  a data question (the Routing Matrix, `DRG-001` §7) rather than a code
  question — a command group's migration status becomes a table row flip,
  not a structural change to routing logic.
- Ambiguity, computed since Stage 1 but previously inert, becomes load-
  bearing — closing a real gap between what the Intent Engine already
  measures and what the system actually acts on.
- The `Legacy` destination gives the Offline Engine migration (master spec
  Stage 2, `OFFLINE_ENGINE.md`) an incremental, per-command-group path with
  no forced big-bang cutover — a high-confidence classification for a
  not-yet-migrated command routes correctly to the existing, proven handler
  rather than being misrouted to AI or blocked entirely.

**Negative / accepted tradeoffs:**
- One more component in the request path, with its own (small, estimated
  sub-0.1ms, not yet measured) latency contribution and its own failure
  mode to reason about (`DRG-001` §8's "Routing crash") — accepted because
  the alternative (folding this logic into an existing component) was
  rejected above for concrete, structural reasons, not merely to avoid
  adding a component.
- Several real parameters (exact confidence thresholds beyond the approved
  per-class bands, the ambiguity cap's exact value, per-command-group
  Legacy-removal readiness criteria) are explicitly left open
  (`DRG-001` §12) rather than guessed at — meaning this design alone is not
  sufficient to begin Sub-stage C (real routing); Sub-stage B's
  comparison-logging period is a required, not optional, precursor, and the
  approval in `DRG-001` §13 is conditioned on that sequencing being honored.
- `OFFLINE_ENGINE.md` does not yet specify its own exception-handling
  contract in enough detail for this design's "Offline handler crash"
  failure mode to be fully specified — noted as a dependency this ADR's
  Decision does not resolve on its own (`DRG-001`'s Open Question 4).
