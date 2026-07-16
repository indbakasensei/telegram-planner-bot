# ADR-012: Registry-Based Offline Dispatch Replaces the Intent If/Elif Ladder

**Status:** Accepted — implemented in v14.8.
**Part of:** BAKA v14 Autonomous Core, `DESIGN_SPEC_v14_AUTONOMOUS_CORE.md` §11.
**Depends on:** `docs/adr/ADR-007-offline-engine-stage1.md` (dispatch
coarseness), `ADR-008` (propose/commit pending writes), `ADR-009`
(state-gated `continue_editing()`).
**Anticipated by:** `RC_v14_ARCHITECTURE_VALIDATION.md`'s Offline Engine
Review, which flagged this exact refactor as the precondition for any
Habits sprint.

## Problem

`OfflineEngine.execute()` accreted one `if context.intent is ...` branch
per migration stage across v14.2–v14.7, each containing that stage's
matcher calls, precedence order, argument shapes, and a copy of the same
exception-containment block. At the Task domain's completion the ladder
was ~90 lines with four intent branches and five inline copies of the
containment pattern. Every new action required editing the dispatcher —
an Open/Closed violation the v14.7.1 RC audit named the one remaining
architectural ceiling in `core/`. Habits, Goals, and Projects would each
have added 1–2 more branches plus their own containment copies, recreating
in miniature the `handle_message()` god-function pattern the v14
architecture exists to dismantle.

## Decision

Dispatch through an explicit **ActionRegistry**
(`core/offline/registry.py`, pure mechanism) populated by a single
explicit registration module (`core/offline/registrations.py`, the only
file that changes when an action is added):

```
Intent ──▶ registry.resolve(intent)          O(1) dict lookup →
                 │                            ordered tuple of ActionSpecs
                 ▼
           spec.match(context)               first non-None match wins;
                 │                            registration order IS the
                 ▼                            old ladder's precedence order
           spec.run(context, storage, match) under the engine's single
                 │                            exception-containment block
                 ▼
           ActionResult
```

Key properties, each preserving a load-bearing behavior of the ladder:

- **`resolve()` returns an ordered spec tuple, not one action.** The
  shipped Intent Engine is coarser than the action set (QUERY_TASK spans
  five actions; EDIT_TASK spans complete/lifecycle/update — ADR-007's
  documented under-classification), so a flat `intent → action` map
  cannot express the real dispatch. Registration order within an intent
  is match precedence: behavior, not style.
- **`match` runs outside exception containment, `run` inside** — exactly
  where the ladder's inline matcher calls and action calls sat. Matchers
  are pure inspection; a matcher raise propagates to `main.py`'s
  fall-through-to-Legacy handler, unchanged.
- **The same spec object registers under several intents** (EDIT_TASK and
  UNKNOWN share all three edit-group specs, per ADR-009's "rename task
  5" → UNKNOWN finding).
- **Pending commits register too** (`register_pending()`), replacing
  `execute_pending()`'s inline action_type check — the registry is the
  single source of dispatch for both entry points. `continue_editing()`
  deliberately stays a direct call: state-gated, one possible target,
  nothing to select between (ADR-009).
- **Fallbacks unchanged:** unregistered intent → `unsupported_intent`;
  registered intent, no matcher accepts → `unsupported_action`; unknown
  pending type → `unknown_action_type`. `main.py` needed zero changes.
- **Registration-time validation** (`RegistryError`): duplicate spec name
  within an intent, duplicate pending type, non-callable match/run,
  non-Intent key — all programming errors surfaced at startup, never
  per-message.

## Alternatives considered

- **Decorator/import-side-effect registration** (`@register(Intent.X)` on
  each action module): rejected — registration becomes an invisible
  side effect of import order, the full dispatch table exists nowhere
  readable, and the brief's no-reflection/no-dynamic-import constraint is
  skirted in spirit. One explicit `build_default_registry()` keeps the
  entire dispatch surface diffable in one file and lets tests build
  synthetic registries trivially.
- **Flat `dict[Intent, Callable]`**: cannot express multi-action intents
  or precedence; would have forced the phrase tables back into a
  mini-ladder inside each value. Rejected as a false simplification.
- **Class-based Action interface** (ABC with `matches()`/`execute()`):
  the existing actions are modules with free functions (ADR-007's
  pure-function discipline); wrapping each in a class adds a layer with
  no new capability. `ActionSpec` (a frozen dataclass of two callables
  and a name) is the same idea without the ceremony.

## Consequences

- Adding an Offline action = writing the action module + registering it
  in `registrations.py`. `engine.py` is closed to modification, open to
  extension; Habits/Goals/Projects add registrations (and per-domain
  matchers), not branches.
- `registry.intents()` gives, for the first time, a machine-readable
  answer to "which intents does the Offline Engine implement" — the
  planned source for populating `core/routing/routing_matrix.py`'s
  `OFFLINE_ENGINE_IMPLEMENTED_INTENTS` in Phase 2 of the Legacy Removal
  Plan, replacing hand-maintenance.
- Behavioral equivalence verified three ways (v14.8 sprint report): all
  545 pre-existing tests pass (7 monkeypatch targets and 2
  `_select_action` unit tests mechanically retargeted — documented
  expected maintenance, same class as v14.5's); a 40-case dispatch
  matrix run against the pre-refactor commit in a git worktree produced
  **byte-identical** serialized ActionResults; pyflakes remains at zero
  findings across `core/`.
- Dispatch cost is unchanged in practice: ~0.5 µs registry lookup,
  +~3 µs worst-case on no-match scans (per-matcher function call vs.
  inline checks), ~47 µs one-time registry build at startup, ~728 B
  registry memory. Storage-touching paths are indistinguishable from
  pre-refactor (DB I/O dominates at ~1 ms).
- The phrase tables remain hand-maintained mirrors of
  `core/intent/rules.py` (the four-level duplication chain,
  `DEBUGGING.md`) — this ADR relocates them into `registrations.py` and
  changes who owns dispatch, but the structured-intent-hints fix that
  would eliminate them is still future work, unchanged.
