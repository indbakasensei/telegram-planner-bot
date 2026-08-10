# v15.2 — BAKA Brain / AI Worker · M2 & M3: Tool Contract + Real Tool Adapters

> **Status: DORMANT FOUNDATION — no user command routes through it yet.**
> M2 ships the *contract*; M3 ships the *real tool adapters* on top of it.
> There is **no AI Worker**, **no agent loop**, **no GLM tool-calling**, and
> **no main.py routing change** in either milestone. The surface is verified
> by offline tests, self-test probes, and a regression suite — the Worker
> builds on top of it in later milestones (M4+). Version: still
> `v15.1.0-alpha.13` (no bump until a milestone is complete and released).

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

## What M2 did NOT do — and what M3 completed

- **M3 (below)** builds the **tool adapter surface**: each real capability
  (tasks/habits/goals/entities/workspace/memory-recall/Telegram projection) is
  now a concrete `Tool` with honest `RiskLevel`s, registered into the M2
  `ToolRegistry` by `build_tool_registry()`.
- The future Worker routes through `ToolRegistry.execute` / `Tool.execute`
  (the containment + validation layer was already in place in M2).
- Still no Worker, no agent loop, no GLM calls — M3 adds adapters only.

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
- M2 left `open_workspace` declared `READ_ONLY` while actually setting the
  active workspace. **Fixed in M3** (below): both the `/ws` `OpenWorkspaceTool`
  and the adapter's `WsOpenTool` are now honestly `MUTATING`.
- `confirmation_message` / `requires_admin` are **metadata only** in M2; no
  confirmation or permission flow enforces them yet (reserved codes exist).
- `cognition.execute()` still calls `tool.run(...)` directly (not
  `Tool.execute`) — keeping `/ws` behavior identical. M3/M5 will route the
  Worker through `registry.execute`.

---

# v15.2 M3 — Real Tool Adapters

> **Status: DORMANT ADAPTERS — no user command routes through them yet.**
> M3 wraps BAKA's **existing** business logic (Storage facade, EntityEngine,
> WorkspaceGroups, M1 ReferenceResolver/Retriever, TelegramProjection) in 24
> M2-contract `Tool`s, but **nothing in `main.py` calls `build_tool_registry`**
> and no normal message is routed through it. There is **no AI Worker, no
> agent loop, no multi-step reasoning, no worker routing, no automatic worker
> activation, no new LLM orchestration, no `main.py` routing migration**, and
> **no version bump**. The adapters are health-verifiable now via
> `/selftest → AI → 'AI Tool Adapter Registry'` / `'… Round-trip'`. The future
> Worker (M4+) will be the first caller.

## Objective

Every tool is a **thin adapter**: argument translation + validation + one or
more calls into the real services + conversion of the result into a
structured `ToolResult` carrying machine-readable `data` (ids, fields,
workspace, projection status). No rewritten business logic, no raw SQL, no
second registry, no second `ToolResult`, no new tool abstraction — the M2
contract is used as-is. The result: a future Worker can act with **real,
grounded, structured state** behind an honest risk classification, without
the model ever touching the database or inventing facts.

## Tool inventory (24 tools) and their source handler

Every tool is bound to a `user_id` at build time (`user_id` is **never** a
model-facing argument). Registry: `core/ai/tool_adapters.py` →
`build_tool_registry(user_id, storage=None, engine=None, projection=None, ref_ctx=None)`.

| Tool | Risk | Source handler / service (NOT bypassed) |
|---|---|---|
| `list_tasks` | READ_ONLY | `TaskStorage.get_all` (`done` filter) |
| `find_task` | READ_ONLY | `TaskStorage.search_by_title` (same search `/search` uses) |
| `create_task` | MUTATING | `date_parser.validate_datetime` + `TaskStorage.exists` (duplicate guard) + `TaskStorage.add` |
| `update_task` | MUTATING | `TaskStorage.get_by_id` (existence) + `validate_datetime` + `TaskStorage.update` |
| `complete_task` | MUTATING | `TaskStorage.get_by_id`; habit branch → `HabitStorage.is_habit` + `log_completion` (same branch `/done` takes) |
| `delete_task` | DESTRUCTIVE | `TaskStorage.get_by_id` + `TaskStorage.delete` (hard delete; `confirmation_message` set) |
| `create_habit` | MUTATING | `HabitStorage.add` |
| `list_habits` | READ_ONLY | `HabitStorage.get_all` (streaks included) |
| `complete_habit` | MUTATING | `HabitStorage.is_habit` + `log_completion` (re-log same day is not an error) |
| `create_goal` | MUTATING | `GoalStorage.add` |
| `list_goals` | READ_ONLY | `GoalStorage.get_all_full` (progress/target) |
| `update_goal_progress` | MUTATING | `GoalStorage.update_progress` (clamps, reports completion) |
| `create_entity` | MUTATING | `_require_workspace` (active/name/#id) + duplicate guard + `WorkspaceGroups.create_entity` — the **alpha.13 single entity+topic contract** |
| `get_entity` | READ_ONLY | `_require_workspace` + M1 `ReferenceResolver` / name match; `_note_mention` only (never moves the active entity) |
| `update_entity` | MUTATING | per-field `EntityEngine.update_field` (template validation) + `_activate` + `TelegramProjection.post_entity_update` (append-only) |
| `list_entities` | READ_ONLY | `EntityEngine.list_milestones` (status filter) |
| `find_entity` | READ_ONLY | deterministic token-overlap over title + stored field values |
| `list_workspaces` | READ_ONLY | `EntityEngine.list_workspaces` |
| `get_workspace` | READ_ONLY | `EntityEngine.get_workspace_or_none` (active/name/#id) |
| `open_workspace` | MUTATING | `TelegramBindingStorage.set_active` — persists the active workspace (same side effect `/use` has) |
| `inspect_workspace` | READ_ONLY | `EntityEngine.workspace_progress` + `list_milestones` + `list_notes(kind="progress")` |
| `get_memories` | READ_ONLY | `MemoryStorage.get_all` |
| `search_memories` | READ_ONLY | `MemoryStorage.search_smart` (question-word fallback) |
| `recall` | READ_ONLY | `WorkspaceRetriever.retrieve(query, k=6)` — the **exact M1 retrieval**, returned as structured `data` |

Reminders are **not** a separate tool: a reminder IS a task's `due_date` +
`due_time`, exposed as structured fields on `list_tasks`/`find_task`/`create_task`
(see Known limitations). There is **no `update_habit`** (database.py has no
such function) — only the ops that really exist are exposed.

## Risk classification (the honest ones)

| Class | Tools | Rationale |
|---|---|---|
| READ_ONLY | all list/find/get + `recall` | pure reads; unknown args silently dropped |
| MUTATING | all create/update/complete + `open_workspace` | write/persist state |
| DESTRUCTIVE | `delete_task` | hard delete, `confirmation_message` set |
| SYSTEM | — (none) | M3 exposes no admin/system surface |

Non-obvious calls: **`open_workspace` is MUTATING** (it persists the active
workspace — the same side effect `/use` has; the M2-era READ_ONLY default was
dishonest and is corrected here in BOTH the adapter and the `/ws` tool);
**`get_entity` is READ_ONLY** (it updates only in-memory M1 reference memory,
never the persisted active entity — verified by a test).

## Structured result contract

Every tool returns a `ToolResult` with JSON-compatible `data`, never just a
formatted string. Examples:

```python
# create_task
ToolResult(tool="create_task", ok=True, output="Created task [7] Farm Xiao ascension.",
           data={"task_id": 7, "title": "Farm Xiao ascension",
                 "due_date": "2026-08-11", "due_time": None,
                 "category": "General", "priority": "medium"})

# create_entity (projection wired)
ToolResult(tool="create_entity", ok=True, output="Created entity 'Xiao' (id 12) in #3 · Telegram topic created.",
           data={"entity_id": 12, "title": "Xiao", "workspace_id": 3,
                 "workspace_title": "Genshin", "status": "todo",
                 "topic_id": 4242, "topic_created": True})

# update_entity (projection wired)
ToolResult(tool="update_entity", ok=True, output="Updated entity 'Xiao': level=90; element=Anemo.",
           data={"entity_id": 12, "title": "Xiao", "workspace_id": 3,
                 "applied": {"level": 90, "element": "Anemo"},
                 "changes": {"level": (None, 90), "element": (None, "Anemo")},
                 "topic_posted": True, "warnings": ()})
```

Failure contract: targeted operations on a missing target → `ok=False,
error_code="invalid_args"` with a message naming exactly what is missing (M2's
code set has no separate `not_found` yet); a projection **post** failure on an
entity update is best-effort (`topic_posted=False`, warning appended, DB
write stands); a projection **create** failure is reported (mirrors `/add`'s
"Couldn't create the topic").

## Projection preservation (alpha.13 intact)

Entity creation goes through **`WorkspaceGroups.create_entity`** — the exact
contract `/add` and NL creation use — so the entity, its Telegram topic, the
initial card, and the active-entity write are one sequence, never duplicated.
Entity updates go through `EntityEngine.update_field` + the **same**
`post_entity_update` path the EntityManager uses (append-only, self-healing).
No second Telegram-topic mechanism exists; the M3 integration test
(`test_end_to_end_projection_with_real_client`) proves it end-to-end with a
fake client: create_entity → **one** topic + initial card; update_entity →
**one** append-only message on that same topic (no second topic).

## Tests (tests/test_tool_adapters.py — 43 tests)

The M3 acceptance scenarios use **Genshin fixtures** (Xiao, Kinich, Xilonen,
Nefer, Lauma, Columbina) as **test data only** — nothing in production code
knows any of them.

- **Entities** — create / duplicate-reject / get by name-#id-workspace / list
  / status filter / update fields / update+topic (append-only) / create+topic
  (single contract) / create-topic-failure mirrors `/add` / update-post-failure
  is best-effort / conversational reference ("her" → active entity via the M1
  resolver) / find by keyword / read-doesn't-move-active.
- **Tasks** — create+list / reminder surface (due fields in structured data) /
  duplicate-reject / invalid-datetime reject / find / update / complete /
  delete.
- **Habits / goals** — create+list+complete / complete-twice-is-not-an-error /
  `complete_task` on a habit id takes the habit branch / goal create+list /
  progress-to-complete.
- **Workspace** — list / get / open (MUTATING) / inspect (counts + notes).
- **Memory / recall** — get / search / grounded recall; a miss returns empty,
  not an error.
- **Mixed-capability chaining** — entities + tasks + workspace through ONE
  registry.
- **Adversarial** — unknown args rejected on writes / dropped on reads;
  missing targets → invalid_args; update with no fields; create_entity with no
  active workspace; unknown entity field allowed (forward-compat); invalid
  field value rejected (names the field); duplicate registration rejected;
  `execute`-never-raises matrix; risk classification incl. no SYSTEM and
  `delete_task` DESTRUCTIVE with a confirmation message.
- **Integration** — `RecorderProj` (projection seam is called with real
  card/update text) + `FakeClient`+`TelegramProjection` end-to-end (topics +
  messages produced offline, no second topic mechanism).

Also: regression suite **TAD-001…005** (Quick Release Suite) and selftest
**"AI Tool Adapter Registry"** + **"AI Tool Adapter Round-trip"** (deterministic,
self-cleaning). Full offline suite: **1423 passing** (baseline 1380 + 43).

## Adversarial findings

1. **`_task_dict` shape bug (found by the test suite, fixed):**
   `search_tasks_by_title` returns 5 columns (no priority/recurrence) while
   `get_tasks` returns 7; the shared row→dict mapper indexed `row[5]`
   unconditionally, which would have been an `IndexError` on every `find_task`
   hit. Now guarded by row length.
2. **Create-vs-update projection failure semantics (pinned by a test):** a
   topic **create** failure is NOT a silent best-effort — it is reported,
   exactly like `/add` (an infrastructure problem must reach the user); a
   topic **update/post** failure IS best-effort (DB stands). The tests encode
   both honestly.
3. **`open_workspace` READ_ONLY was dishonest** (M2-era); reclassified MUTATING
   in both the adapter and the `/ws` tool — behavior unchanged because `/ws`
   calls `run()` directly, never `Tool.execute`.

## Known limitations

- **Dormant:** nothing calls `build_tool_registry` in production; no routing
  change. `main.py` is byte-identical for normal messages.
- **No reminders tool:** reminders ARE task due-times (structured on
  task results). A dedicated reminder tool would duplicate a real surface
  that does not exist separately.
- **No `update_habit`:** database.py has no such function; only real ops are
  exposed (create/list/complete).
- **`complete_task` skips the preference-learning side-channel** that
  `done_task` also writes (`LearningStorage.log_completion`) — documented
  divergence; the adapter stays thin and does not replay every side effect.
- **`create_entity` is create-only** (no `fields` param): set fields with
  `update_entity` afterwards — keeps the create path the single alpha.13
  contract and avoids double-projection weirdness.
- **Memory tools are read-only** (`get_memories`, `search_memories`, `recall`);
  no memory-write tool yet (M3 brief allowed only reliable reads).
- **Not-found on a targeted op = `invalid_args`** (M2 has no `not_found` code);
  a future milestone may add one.
- **No Worker, no multi-step reasoning, no GLM tool-calling** — M3 ships the
  adapters only.

## M4 scope (NOT done here)

- The **AI Worker**: the agent loop that calls `ToolRegistry.execute` (and
  confirmation gating on MUTATING/DESTRUCTIVE/SYSTEM), automatic worker
  activation, GLM tool-calling, worker routing, and `main.py` routing
  migration. M3 does not claim any of this exists.
