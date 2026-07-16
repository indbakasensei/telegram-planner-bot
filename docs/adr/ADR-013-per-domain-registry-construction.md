# ADR-013: Per-Domain Feature-Flag Gating via Registry Construction

**Status:** Accepted — implemented in v14.9 (Habit domain Stage 1, the
first second-domain registration).
**Part of:** BAKA v14 Autonomous Core.
**Depends on:** `docs/adr/ADR-012-registry-based-dispatch.md` (the
registry this gates), `core/feature_flags.py` (v14.1C's four env-read-once
per-domain flags).

## Problem

v14.1C defined four per-domain flags (`OFFLINE_TASKS`, `OFFLINE_HABITS`,
`OFFLINE_GOALS`, `OFFLINE_PROJECTS`), but until v14.9 only
`OFFLINE_TASKS` was consumed, as a single gate in `main.py` in front of
`OfflineEngine.execute()`. The moment a second domain registers actions,
that design breaks: the registry contains both domains' specs, so any
one flag being ON would activate *every* domain's actions —
per-domain flags in name only. v14.8's Scalability Assessment flagged
exactly this ("main.py's per-domain flag gate will need generalizing
when a second domain flag goes live").

The fix had to respect v14.9's constraints: **no OfflineEngine changes,
no ActionRegistry changes** — the sprint exists to prove the
architecture extends without touching either.

## Decision

Gate domains at **registry construction time**, in
`core/offline/registrations.py`:

- Registration is split into per-domain functions
  (`_register_task_domain()`, `_register_habit_domain()`).
- `build_default_registry()` — the **full catalog**, every domain,
  flag-independent. Used by tests, benchmarks, and as
  `OfflineEngine.__init__`'s no-argument fallback.
- `build_enabled_registry()` — the **production build**: registers each
  domain only if its feature flag is ON. `main.py` injects it via the
  `registry=` parameter v14.8 already provided:
  `OfflineEngine(storage, registry=build_enabled_registry())`.
- `main.py`'s message gate widens to a flag-OR
  (`OFFLINE_TASKS or OFFLINE_HABITS`) — purely a short-circuit so the
  all-flags-off configuration never even calls the engine, byte-identical
  to today. *Which* domain is live inside the engine is decided solely
  by what got registered.

A domain whose flag is OFF has no specs at all, so its messages resolve
to `unsupported_intent`/`unsupported_action` and fall through to Legacy
exactly as if the domain had never been migrated. Flag semantics are
unchanged: env-read-once at import (v14.1C), registry built once at
startup — a flag flip still requires the same restart it always did.

## Alternatives considered

- **Flag checks inside `OfflineEngine.execute()`** (map intent/spec →
  domain → flag per message): forbidden by the sprint (engine is closed
  to modification, ADR-012's whole point), adds a per-message cost, and
  teaches the engine about domains it deliberately knows nothing about.
- **Flag checks inside each matcher**: scatters the gate across every
  spec, makes matchers configuration-dependent (they are pure text/entity
  inspection today), and a forgotten check silently activates an action.
- **One global `OFFLINE` flag**: wrong granularity — the staged-rollout
  plan (canary Tasks first, Habits later) requires enabling domains
  independently.
- **Registry-level `register(intent, spec, flag=...)`**: pushes flag
  knowledge into the mechanism layer that ADR-012 deliberately kept
  domain-agnostic, and would have required modifying `registry.py`
  (also forbidden this sprint).

## Consequences

- Adding a domain = a `_register_<domain>_domain()` function + two
  lines in the builders + its flag consumption. Engine, registry, and
  dispatch flow untouched — verified by v14.9 shipping Habits Stage 1
  with zero edits to `engine.py`/`registry.py`.
- Tests exercise domain combinations by monkeypatching flag attributes
  and rebuilding — no environment manipulation, no reloads
  (`tests/test_habit_views.py`'s ADR-013 section).
- `OfflineEngine()` with no registry argument now means "full catalog,
  ignore flags" — correct for tests and benchmarks, and never what
  production does (`main.py` always injects). Documented in
  `build_default_registry()`'s docstring.
- The flag-OR in `main.py` grows by one term per domain (`OFFLINE_GOALS`
  next). If that ever feels wrong, the natural evolution is a
  `feature_flags.any_offline_domain()` helper — deliberately not built
  for one term.

## Amendment (v14.11): actions two domains share

Habit completion exposed a case the original decision didn't cover: an
entry phrase set (`done <id>` etc.) that serves **two** domains, because
Legacy's `done_task()` is one handler branching on `is_habit()`. A flat
per-domain spec split can't express this — a second spec under the same
matcher would be shadowed by the first (first-match-wins), and matchers
cannot consult storage to tell a habit id from a task id.

Resolution, still entirely at construction time: the registration
functions take cross-domain hints (`_register_task_domain(...,
habit_completion=)`, `_register_habit_domain(..., tasks_enabled=)`).
Both-domains builds register **one** completion spec — Legacy's own
one-handler shape — whose runner injects `complete_habit.execute` into
`complete_task.execute()`'s branch point; tasks-only builds keep the
v14.6 runner (habits branch away to Legacy, `habit_not_supported`);
habits-only builds register the domain's own `complete_habit` spec,
which declines real tasks to Legacy. The engine and registry mechanism
remain untouched; the composition knowledge lives where all
registration knowledge lives.
