# ADR-007: Offline Engine Stage 1 — Action-Based Architecture, Read-Only First

**Status:** Accepted — Stage 1 (read-only task commands) implemented and
shipped, v14.2 (`core/offline/`, `core/actions/`).
**Part of:** BAKA v14 Autonomous Core (`DESIGN_SPEC_v14_AUTONOMOUS_CORE.md`),
`DRG-001_Intent_Aware_Routing.md`'s Sub-stage C.
**Depends on:** `docs/adr/ADR-002-intent-engine.md` (Intent Engine, Accepted),
`docs/adr/ADR-006-intent-aware-routing.md` (Routing Layer, Accepted),
`OFFLINE_ENGINE.md`, v14.1C's Storage Facade / feature flags.

## Problem

`DRG-001_Intent_Aware_Routing.md`'s Sub-stage C ("Offline") calls for real
routing decisions to start executing, one command group at a time — but
neither `OFFLINE_ENGINE.md` nor any prior sprint specified *how* an
individual command's execution logic should be structured once it's no
longer a `main.py` handler taking `(update, context)` directly. Getting
this wrong at the first real command group would be expensive to unwind
across the ~90 handlers `OFFLINE_ENGINE.md` eventually expects to migrate.

## Alternatives considered

1. **Command-handler architecture, ported as-is.** Each offline-eligible
   command becomes a function with the same shape `main.py`'s handlers
   already use, just relocated and with `database.py` calls replaced by
   Storage Facade calls. Rejected as the long-term pattern: this preserves
   today's Telegram coupling (still takes `update`/`context` PTB objects,
   or a close analog), which is exactly what `COMMAND_PIPELINE.md`'s NFR-6
   ("offline-testable without mocking Telegram") and this project's own
   demonstrated testing discipline (`core/intent/`, `core/routing/`, both
   100%-covered with zero Telegram mocking) argue against repeating.
2. **Action-based architecture: `RequestContext` in, `ActionResult` out,
   zero Telegram/PTB dependency (chosen).** Each action is a small,
   independently testable function with the same input/output contract
   regardless of what will eventually call it — a Telegram message today,
   potentially a future dashboard API or scheduled job later
   (`DESIGN_SPEC_v14_AUTONOMOUS_CORE.md`'s stated extensibility goals).
   Directly extends the precedent `IntentResult`/`RoutingDecision` already
   established: domain-only dataclasses, caller-injected clock, no
   Telegram objects anywhere in the type.
3. **Skip the contract, inline everything in `OfflineEngine.execute()`.**
   Rejected: would make the "Stage" nature of this migration (one command
   group at a time, `OFFLINE_ENGINE.md`'s own migration order) harder to
   scale — every new action would mean editing `execute()`'s own body
   rather than adding a new file to `core/actions/`, repeating the
   god-function growth pattern `ENGINEERING_AUDIT.md` already flagged in
   `main.py` itself (finding J1, `handle_message()` at 841 lines).

## Decision

Adopt the Action-based architecture: `RequestContext` (domain-only input —
`user_id`, `text`, `intent`, `entities`, caller-injected `now`) and
`ActionResult` (`success`, `message`, `data`, `warnings`, `metadata`) as
the fixed contract every action implements, `OfflineEngine.execute()` as
the single dispatcher, and `core/actions/` as the per-action module
directory (one file per action, mirroring `core/intent/rules.py`'s and
`core/routing/routing_matrix.py`'s existing "add a row/file, not a branch"
extensibility pattern).

**Scope for Stage 1: read-only task commands only** (`list`, `today`,
`week`, `search`) — confirmed, not just assumed, to have zero side effects
by reading their underlying `database.py` functions directly before this
decision (`get_tasks`/`get_tasks_by_date`/`get_tasks_by_week`/
`search_tasks_by_title`: `SELECT` + `fetchall()` + close, nothing else).
This is the safest possible starting point for the first sprint where real
user traffic can execute through the new architecture: a bug's worst case
is a wrong or stale display, not data loss or corruption — directly
matching `INTENT_ENGINE.md`'s own risk-tiering ("Read-only... wrong guess
costs nothing").

**A real gap found during this review, not papered over**: `Intent.QUERY_TASK`
(`core/intent/intent_types.py`) is coarser than these four actions — it
also covers `/habits`, `/goals`, `/dashboard`, `/settings`, etc.
(`DRG-001` Section 7's Routing Matrix), none of which Stage 1 implements.
Neither `intent` nor `entities` carries a signal distinguishing "list" from
"today" from "week" from "search" (Tier 0's exact-phrase matches produce
empty `entities`, `core/intent/rules.py`). Rather than modifying the
already-Accepted, tested Intent Engine to add a distinguishing hint —
out of proportion for this sprint, and risky to already-shipped, frozen
Stage 1 code — `OfflineEngine`'s dispatch resolves this with a narrow,
explicitly-documented text-pattern lookup (`core/offline/engine.py`'s
`_select_action()`), a small, hand-maintained mirror of `core/intent/rules.py`'s
own Tier 0 phrase groups for exactly these four actions. Anything
classified `QUERY_TASK` that doesn't match one of the four known patterns
returns a graceful `unsupported_action` result — the caller (`main.py`)
falls through to Legacy exactly as if the Offline Engine had never been
consulted. This is accepted, documented duplication, one level deeper than
`core/intent/rules.py`'s own already-accepted mirroring of `main.py`'s
command tables (`DEBUGGING.md`) — not a design this ADR is satisfied with
long-term; the real fix (a structured action/command hint added to
`IntentResult.entities` at classification time) is named as follow-up
work, not built here.

**Storage access**: `OfflineEngine`/`core/actions/` access data exclusively
through the Storage Facade (`core/storage/`, v14.1C) — never
`import database` directly, enforced both by code review and by an
AST-based test (`tests/test_offline_engine.py`) that fails the build if
any file in `core/offline/`/`core/actions/` ever imports `database`.

**Feature-flag gated**: `core/feature_flags.py`'s `OFFLINE_TASKS` (default
OFF, unset in `.env`) gates the entire path in `main.py`. OFF today means
byte-for-byte identical behavior to v14.1C — verified by all 312
pre-existing tests passing unmodified. No flag is enabled by this ADR.

## Consequences

**Positive:**
- Every action is unit-testable with zero Telegram mocking, extending
  the precedent `core/intent/`/`core/routing/` already set — Stage 1's
  four actions reached 100% coverage without a single mock.
- The dispatch table (`core/actions/__init__.py` + `_select_action()`)
  scales the same way `core/routing/routing_matrix.py` already does:
  adding action five means adding a file and a table entry, not editing
  `OfflineEngine.execute()`'s own logic.
- Real, fixed bug found by this sprint's own tests (not a regression, a
  bug caught before shipping): `_select_action()`'s and
  `search_tasks._extract_keyword()`'s prefix checks both used a full
  `.strip()` before comparing against a prefix that itself ends in a
  space (`"search "`), causing the boundary case of exactly `"search "`
  (no query yet) to miss the match entirely. Fixed by left-stripping
  only before the prefix check — the same category of boundary bug
  `ADR-002`'s Implementation Note and `date_parser.py`'s historical bugs
  already established this project needs to watch for in any tiered/
  prefix-based text matching.

**Negative / accepted tradeoffs:**
- The `Intent.QUERY_TASK` coarseness gap (above) is real, documented
  debt, not resolved by this ADR — `DEBUGGING.md`'s "Offline Engine
  action dispatch is text-pattern-based, not Intent-based" entry tracks
  it for a future sprint.
- `core/routing/routing_matrix.py`'s `OFFLINE_ENGINE_IMPLEMENTED_INTENTS`
  remains an empty `frozenset` — this ADR did *not* populate it with
  `Intent.QUERY_TASK`, specifically because doing so would incorrectly
  imply the Offline Engine covers all of `QUERY_TASK` (it covers four
  specific phrasings within it). The Routing Layer's recommendation and
  the Offline Engine's actual coverage remain two independently-tracked
  signals — `main.py`'s gate checks the feature flag and lets
  `OfflineEngine.execute()`'s own graceful `unsupported_action` result
  handle the rest, rather than trying to encode fine-grained coverage
  into a per-Intent set that isn't granular enough to hold it.
