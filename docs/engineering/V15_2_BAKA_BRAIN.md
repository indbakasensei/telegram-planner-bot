# v15.2 — BAKA Brain / AI Worker · M2: Tool Contract Foundation

> **Status: DORMANT FOUNDATION — no user command routes through it yet.**
> M2 ships the *contract* only. There is **no AI Worker**, **no agent loop**,
> **no GLM tool-calling**, and **no main.py routing change** in this
> milestone. The contract is verified by offline tests, a self-test probe, and
> a regression suite — the Worker builds on top of it in later milestones
> (M3+). Version: still `v15.1.0-alpha.13` (no bump until a milestone is
> complete and released).

## Objective

Extend the **existing** `core/ai/tools.py` (do not build a second registry or
a parallel tool abstraction) into the single, validated **Tool Contract** the
future AI Worker will route through:

1. **RiskLevel** — `READ_ONLY` / `MUTATING` / `DESTRUCTIVE` / `SYSTEM`, the
   class a confirmation/permission gate will key on.
2. **ToolSchema metadata** — `ToolSpec` now carries `risk`,
   `confirmation_message` (optional) and `requires_admin` (optional) beside
   its existing `name` / `description` / JSON-Schema `parameters`.
3. **ToolResult** — `tool`, `ok`, `output`, optional structured `data`,
   `warnings`, and a stable `error_code` on failures.
4. **ToolError** — stable machine-readable `code` + human-readable `message`;
   `ToolErrorCode` constants are contract, not copy.
5. **Schema validation** — fail-closed: required args, JSON types (with
   `bool` ≠ integer, `None` only as declared `null`), enum, `minLength`,
   nested objects; **invalid arguments never reach a handler**.
6. **ToolRegistry** — duplicate-name detection, spec validation at
   registration, `execute(name, args)` dispatcher, OpenAI `tools=[...]`
   generation.

M2 deliberately creates **no** task/entity/reminder tools, wires **nothing**
into `main.py`, keeps the Cognitive Engine's `/ws` path byte-identical, and
does **not** change `database.py`, `EntityManager`, or Telegram topic
projection.

## Files changed

| File | Change |
|---|---|
| `core/ai/tools.py` | The whole contract: `RiskLevel`, `ToolError` (+ `ToolErrorCode`), `ToolRegistryError`, `ToolResult`, extended `ToolSpec`, `Tool.execute`, validated `ToolRegistry` (+ `execute`), `validate_spec` / `validate_args`. |
| `core/ai/cognition.py` | Removed its **local** `ToolResult`; now imports the unified one from `core.ai.tools`. Construction sites converted to keyword args. `execute()` itself is **unchanged** — `/ws` behavior is identical. |
| `core/ai/__init__.py` | Exports `RiskLevel`, `ToolError`, `ToolErrorCode`, `ToolRegistryError`, `ToolResult` from `tools`; `ToolResult` removed from the cognition re-export. |
| `tests/test_ai_foundation.py` | `test_registry_register_is_idempotent_by_name` → `test_registry_register_rejects_duplicate_name` (contract change). |
| `tests/test_tool_contract.py` | **New.** 79 offline tests, A–G + adversarial. |
| `core/selftest/tests/test_ai.py` | **New.** `check_ai_tool_contract` — offline "AI Tool Contract" probe. |
| `core/regression/suites/tool_contract_m2.py` | **New.** TLC-001…004 Quick Release Suite specs. |
| `docs/engineering/V15_2_BAKA_BRAIN.md` | This document. |

**Deliberately untouched:** `main.py` (routing), `database.py`,
`core/ai/entity_manager.py`, topic projection (`projection.py`, `render.py`,
`groups_app.py`), `core/storage/`, `core/feature_flags.py` (no WORKER flag
added), the Offline Engine, Intent/Routing layers, and every existing
command's behavior.

## Contract decisions

### One home, one abstraction

Everything lives in `core/ai/tools.py`. The Cognitive Engine's old local
`ToolResult(tool, output, ok)` was **unified** into the contract's
`ToolResult(tool, ok, output, …)` — there is exactly one `ToolResult` class in
the codebase (verified: `core.ai.tools.ToolResult is core.ai.cognition.ToolResult`).
The old positional order `(tool, output, ok)` would have silently bound the
second argument to the new `ok` field, so all construction sites were
converted to keyword args.

### `Tool.execute(**kwargs) -> ToolResult` is the single run path

`Tool.execute` is a **concrete method on the `Tool` ABC**: it validates
arguments, runs the tool, and contains every failure:

- malformed/invalid args → `ok=False, error_code="invalid_args"`, **handler
  never reached**;
- `ToolError` raised by the tool → `ok=False` with its `code`/`message`;
- any other exception → `ok=False, error_code="internal"`;
- `run()` may return a `str`, a `ToolResult` (passed through untouched), or
  `None` (→ empty output).

`ToolRegistry.execute(name, args)` is the dispatcher: unknown tool →
`error_code="unknown_tool"`; non-object args → `"invalid_args"`. Both
**never raise for ordinary input** — a future Worker can call them safely.

### Fail-closed argument validation

`validate_args(spec, args)` raises `ToolError("invalid_args", …)` on any
violation and returns the (possibly filtered) args. Rules:

- `required` args must be present;
- JSON types enforced: `string`, `integer` (bool rejected), `number`
  (bool rejected), `boolean`, `object`, `array`, `null` (only when declared,
  e.g. `"type": ["string", "null"]`);
- `enum` allowed-values; `minLength` for strings;
- nested objects validated recursively (nested `required`, nested types);
- **unknown arguments are REJECTED for MUTATING/DESTRUCTIVE/SYSTEM tools**
  and **silently dropped for READ_ONLY** tools (a read may be asked for more
  than it knows; a write must never be fed a key it doesn't declare).

### Registration is strict

`ToolRegistry.register` calls `validate_spec` (rejects malformed schemas —
bad names/descriptions, non-object top-level type, unknown property types,
undefined `required` refs, non-`RiskLevel` risk, non-string
`confirmation_message`, non-bool `requires_admin`) and **rejects duplicate
names** with `ToolRegistryError`. This replaces the pre-M2 idempotent-replace
semantics: a duplicate would silently mask an intended tool collision for the
Worker.

### Stable error codes

`ToolErrorCode.INVALID_ARGS / UNKNOWN_TOOL / INTERNAL` are the codes the
contract emits today. `CONFIRMATION_REQUIRED` and `PERMISSION_DENIED` are
**reserved** (fixed now, raised in a later milestone's confirmation flow) so
nothing changes shape later.

## Risk levels

| Level | Meaning | Unknown-arg handling |
|---|---|---|
| `READ_ONLY` | reads state, no side effects (default) | dropped |
| `MUTATING` | writes/creates/updates state | rejected |
| `DESTRUCTIVE` | deletes/destroys state | rejected |
| `SYSTEM` | admin/owner/system surface | rejected |

Existing workspace tools default to `READ_ONLY` (their `open_workspace`
actually sets the active workspace — a **known pre-existing gap**: M3's
adapter pass will assign proper risks per tool, the mechanism ships in M2).

## What M3 will do (NOT done here)

- Build the **tool adapter surface**: map each real capability
  (tasks/reminders/habits/goals/entities/workspace/memory-recall/Telegram
  projection) to a concrete `Tool`, assigning honest `RiskLevel`s.
- Route the Worker's planned tool calls through
  `ToolRegistry.execute` / `Tool.execute` (the containment + validation layer
  is already in place).
- No Worker, no agent loop, no GLM calls yet.

## Testing

- **79 new offline tests** in `tests/test_tool_contract.py` covering
  ToolSchema (A), argument validation (B), risk behaviour (C), ToolResult (D),
  ToolError (E), Registry (F), execution contract (G) — plus adversarial
  inputs (malformed JSON schemas, junk nested keys, wrong primitive types,
  empty strings, `None`/`null`, duplicate/colliding names, exceptions inside
  tools, missing tools, dangerous metadata, invalid OpenAI function schema).
- **Contract-change regression:** `test_registry_register_rejects_duplicate_name`
  pins the new duplicate-detection semantics.
- **Self-test:** `/selftest → AI → 'AI Tool Contract'` — an offline probe
  (register → validate → execute → contain) so the contract's health is
  verifiable live.
- **Regression suite:** TLC-001…004 (Quick Release Suite) describe the
  contract checks the manual walk re-verifies.
- Full offline suite: **1380 passing** (baseline 1301 + 79).

## Known limitations

- No tools are registered in production yet (only the workspace-tools
  registry built by `/ws`, which continues to work and defaults to
  `READ_ONLY`).
- `open_workspace` remains declared `READ_ONLY` while actually setting the
  active workspace — corrected in M3's adapter pass.
- `confirmation_message` / `requires_admin` are **metadata only** in M2; no
  confirmation or permission flow enforces them yet (reserved codes exist).
- `cognition.execute()` still calls `tool.run(...)` directly (not
  `Tool.execute`) — keeping `/ws` behavior identical. M3/M5 will route the
  Worker through `registry.execute`.
