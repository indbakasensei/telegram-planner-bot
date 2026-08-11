# v15.2 — BAKA Brain / AI Worker · M2, M3 & M4: Tool Contract + Real Tool Adapters + GLM-5.2 Worker

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

---

# v15.2 M4 — GLM-5.2 Worker (the bounded tool-calling executor)

M4 delivers the Worker itself — **DORMANT** behind `feature_flags.WORKER`
(default OFF) plus the owner-only canary. It replaces NO routing: while OFF,
`handle_message` is byte-identical to pre-M4. When ON, the Worker activates
only for the owner (`OWNER_ID`, the same `is_admin()` gate admin commands
use) and only at the very END of the message cascade — after menu,
confirming/editing/gathering states, NL maps, EntityManager and the task VIEW
quick-match have ALL declined. Anything the Worker declines or that fails
falls through to the legacy path untouched.

## Objective

Convert ONE user message into at most 4 tool calls through a ToolRegistry,
then one final reply — bounded, observable, honest, and never touching a
database, Telegram, or raw handler directly. Architecture: see the M4
Architecture Proposal (Phase0 audit + 18 sections) that preceded this build.

## Modules / files

| File | Responsibility |
|---|---|
| `core/ai/worker_contract.py` | Types: `WorkerRequest`/`WorkerDecision`/`WorkerStep`/`WorkerRunResult`, `WorkerAction`, `TerminationReason`, `MAX_TOOL_CALLS=6` (Python constant — not configurable via any input/env) |
| `core/ai/worker_parser.py` | The robust structured-output parser (fenced/malformed/multi-JSON/missing-fields/injection). Deliberately NOT the greedy `clean_json` `r"{.*}"` extractor (audit F1) — see below |
| `core/ai/worker_prompt.py` | Compact system contract ("Worker Constitution") + per-request data (date block, deterministic parse result, bounded tasks/memory/history, 30-tool catalog). Never a repo dump |
| `core/ai/worker.py` | The bounded loop, mechanical confirmation gate, never-fabricate-success guard, structured logging; injected `model_fn` (tests = fake, production = `baka_brain.call_worker_single`) |
| `baka_brain.py` | `call_worker_single()` — ONE MODEL_MAIN attempt, `temperature=0`, no retry, no MODEL_FAST fallback (the loop owns failure handling; a retry storm is impossible) |
| `core/feature_flags.py` | `WORKER: bool = _flag("WORKER")` — default OFF, same pattern as the other flags |
| `main.py` | Seam A (idle BAKA: `if feature_flags.WORKER and is_admin(user_id)`), Seam B (`worker_confirm` branch in the confirming state), `_worker_engine/_worker_ref_ctx/_worker_request/worker_run` |
| `core/selftest/tests/test_worker_selftest.py` | 2 probes: "AI Worker (dormant)" + "AI Worker Deterministic Round-trip" |
| `core/regression/suites/worker_m4.py` | WKR-001…031 — the user scenarios + safety/observability specs + generic invariants (S1–S30) + topic-lifecycle/workspace-lifecycle/response-format specs (WKR-028/029/031) |

## Request / response contract

```
WorkerRequest(user_id, text, registry, ref_ctx, projection, workspace_id,
              tasks, memory, history, now)   # snapshots are gathered by the
                                             # CALLER; the Worker never opens DB
WorkerDecision(action=TOOL|FINAL|DECLINE, tool_name, arguments, reply, reason)
WorkerStep(number, decision, result, duration_ms)
WorkerRunResult(handled, reply, steps, termination, request_id, total_ms,
                confirmation_data)
```

`handled=True` ⇒ the reply is authoritative; `handled=False` (only DECLINED)
⇒ the caller falls through to legacy. Every run ends in exactly one
`TerminationReason` (see failure policy).

## LLM output contract & parser

Model decisions are exactly one JSON object:
`{"action":"tool","tool":"<name>","arguments":{…}}` |
`{"action":"final","reply":"<HTML>"}` | `{"action":"decline","reason":…}`.

`worker_parser` accepts exactly ONE well-formed top-level object. It strips a
``` ```json fence, tolerates surrounding prose, and uses a character-tracking
nesting scanner (no greedy regex). **Zero objects, a top-level array, or MORE
THAN ONE object is `MALFORMED`** — the F1 bug class is closed: a duplicated or
ambiguous decision never executes, never "last one wins". A nested `"tool"` or
`"action"` inside `arguments` is DATA, never the decision (injection-
resistant). Tool membership / argument schema are policy in `worker.py` /
`ToolRegistry`, keeping `UNKNOWN_TOOL` and `INVALID_ARGS` distinct.

## Tool selection & the bounded loop

- Each step = one model call (single attempt, `TIMEOUT_NORMAL_REASONING`,
  no retry, no fallback model) → parse decision → act:
  - `decline` → `handled=False` (legacy answers);
  - `final` → reply through the honesty guard;
  - `tool` → name must be in the registry (else `UNKNOWN_TOOL`, nothing
    executed); risk gate below; then `ToolRegistry.execute` — the ONLY run
    path, fail-closed by M2.
- At most `MAX_TOOL_CALLS=6` tool executions per request; after the 6th, one
  final compose call (≤7 model calls total). `MAX_TOOL_CALLS` is a Python
  constant — not in any prompt, spec, or env flag, so no input can widen it.
  (Raised from 4 during M4 remediation so compound chains — the biggest Llama
  failure class — get honest execution instead of budget exhaustion.)
- Recoverable failures (INVALID_ARGS) feed back into the next step; two
  consecutive ones terminate early. Non-recoverable failures terminate now.

## Safety model

- **Fail-closed execution**: unknown tool / bad args never reach a `run()`.
- **Mechanical confirmation gate, before execute**: a DESTRUCTIVE tool (or any
  tool with a `confirmation_message` — today only `delete_task`) NEVER runs
  silently. The Worker returns `CONFIRMATION_NEEDED` + `confirmation_data`;
  main.py routes yes/no through the **EXISTING** `conversation_state.py`
  pending-action machine (Seam B, `worker_confirm` — same pattern as
  `offline_add_task` / `offline_delete_task`). There is no second confirmation
  system and no "LLM decides whether confirmation is needed".
- **Never-fabricate-success**: a deterministic guard rewrites any final reply
  that claims a success action (`created|deleted|updated|…`) unless an
  `ok=True` ToolResult backs it. The model cannot claim "Xiao created
  successfully" without a create result.

## Reference handling

M1 is authoritative for entity resolution *fallback*; the **typed referent
store is consulted first** (see the M4 orchestration fixes section below).
Entity tools resolve via the shared M1 `ReferenceContext`/`ReferenceResolver`
(active entity from the DB-backed `tg_active_context` + recent-mention stack +
ordered list) only after the typed store misses. The Worker's `ref_ctx` is a
per-process singleton (`_worker_ref_ctx()`) so conversational reference
persists across Worker messages. Ambiguous/stale references → the model asks
for clarification; nothing is guessed or invented.

## Date handling

Deterministic `date_parser` is authoritative. `worker_prompt` injects
`date_parser.parse_all(text, now)` (IST) as a `PARSED` block — date, time,
`time_ambiguous`, recurrence, errors. The contract tells the model to use
those values verbatim or ask the user; it never computes a date. Tools
reject invalid formats themselves, so a guessed date surfaces as a non-ok
`ToolResult`, never silent success.

## Failure policy

| Condition | Termination | Behavior |
|---|---|---|
| Model timeout | `MODEL_TIMEOUT` | 1 attempt, graceful fallback, no retry storm |
| HTTP/auth/5xx | `MODEL_ERROR` | same, handled=False (legacy answers) |
| Malformed / multi-object / empty | `MALFORMED` / `EMPTY_REPLY` | graceful |
| Unknown tool | `UNKNOWN_TOOL` | nothing executed |
| Invalid args ×2 | `INVALID_ARGS_RECURRENT` | stop early |
| Tool failure / exception | `TOOL_FAILURE` | honest report |
| DESTRUCTIVE | `CONFIRMATION_NEEDED` | never executes (Seam B) |
| Ambiguous/stale reference | asked | clarification, never a guess |
| Budget exhausted | `MAX_STEPS` | one compose call → honest summary |
| Internal | `INTERNAL` | graceful, run never crashes the bot |

## Observability

One structured INFO line per run:
`request_id, user_id, workspace_id, termination, total_ms, model_calls,
steps=[{step, action, tool, args, ok, error_code, duration_ms}], reply_len`.
**The user message body is never logged** (owner decision: no raw user text in
new Worker logs), and argument keys matching `/token|key|secret|password|…/`
are `[REDACTED]` before logging. Tools never carry secrets; this is
defense-in-depth.

## Cost / latency

≤7 model calls per request (6 tool-decisions + 1 final compose), typically
1–2; ≤6 tool executions; per-call ceiling `TIMEOUT_NORMAL_REASONING` (45s),
one attempt each. Worst-case wall latency ≈6-tool chain (GLM-5.2 first token
>30s on NIM), typical 1-tool ≈20–80s. All calls run off the event loop via
`run_blocking`; the bot stays responsive. Chat-only messages cost one decision
call then hand off to legacy.

## M4 orchestration fixes (v15.2 — typed referents, goal-deadline tool,
type-aware retrieval, routing order)

The M4 Worker's first live pass surfaced ten orchestration failures. They were
fixed **generically** (no phrase-specific rules) — this section records the
four architectural changes and the failure→root-cause→fix mapping.

### Root causes (RC1–RC6)

- **RC1 — tool results were prose, not typed identity.** When a tool ran
  (`create_entity` → `{entity_id, kind, name}`), the follow-up step saw only a
  rendered text block. Nothing told the next tool-call which exact ID it just
  created, so the model fell back to stale active context.
- **RC2 — M1 active-entity-first resolution + all-milestone `kind="milestone"`.**
  `_resolve_entity` reached for the DB "active entity" before anything else, and
  every workspace row reported the same kind — so "its" after a goal was
  created resolved to the active *character* (cross-domain leak), and the
  create→reference→update chain corrupted the wrong row.
- **RC3 — no `entity_type` column.** Duplicate detection keyed on
  `(workspace_id, title)` only, so a character and an artifact with the same
  display name collided ("already a Golden Troupe"), and there was no way to
  filter/list by kind.
- **RC4 — no goal-deadline tool.** "Set its deadline to …" was a goal-domain
  operation with no tool, so the model misrouted it through
  `update_entity`'s forward-compat fallback, which wrote deadline-shaped values
  into a *character's* field map.
- **RC5 — the Worker seam ran *after* EntityManager + the task VIEW
  quick-match.** Compound requests ("Show Xiao and then update his level"),
  typed retrievals ("Show all characters"), and goal operations were hijacked by
  earlier routers before the Worker ever saw them.
- **RC6 — `date_parser` lacked "next month end".** The model had to invent a
  date, which is how a deadline landed as a wrong literal.

### The fixes

1. **`core/ai/typed_referents.py` — `TypedReferentStore`.** Per-kind, recency-
   ordered referent memory. Every tool `note`s its typed outcome
   `(user_id, kind, entity_id, name, workspace_id)`; `resolve` returns
   `ResolveOutcome(referent, conflict, …)`; `snapshot` renders a
   `KNOWN REFERENTS` prompt block that is rebuilt into the message on every
   Worker iteration. **Store-first resolution**: an explicit entity/result from
   the *current* execution is consulted before any stale active context.
2. **Tool results are first-class.** `create_entity` / `create_goal` /
   `create_task` etc. note the returned `entity_id`/kind/name into the typed
   store, so the next step references that exact ID. Compound operations are
   dependency-aware by construction — later tools resolve against the store the
   earlier tools just populated.
3. **Typed references carry `(workspace_id, kind, entity_id, display_name)`.**
   Cross-domain safety is enforced at resolve time: resolving a reference whose
   store entry is a different kind raises a refusal ("`X` is a
   `kind`, not a workspace entity"), and a conflict (multiple recent referents
   of the same kind) refuses rather than guesses. **Goal/task/entity domains
   never share unsafe active references.**
4. **`milestones.entity_type`** (`database.py` additive column, default
   `"entity"`). Duplicate detection is now
   `(workspace_id, entity_type, title)`; `ListEntitiesTool` filters by type;
   `_entity_dict` carries `entity_type`.
5. **`update_goal_deadline` tool** (+ `database.update_goal_deadline`). The
   goal domain owns deadlines; the tool resolves strictly within the goal
   domain (`typed store → id → exact-name`, ambiguous names refused) and
   validates `YYYY-MM-DD | null`. Never routes a deadline through an entity
   tool.
6. **`date_parser` "next month end".** A deterministic period-end block runs
   *before* the this-month pattern so "next month end" is always the last day of
   the *next* month, crossing year boundaries correctly.
7. **Routing order in `main.py`.** The Worker seam now sits **before**
   EntityManager and the task-VIEW quick-match. A request already recognized as
   an entity/goal/task operation reaches the Worker first; legacy fallback can
   no longer hijack it. Exactly one seam remains (line ~1335).

### Failure → fix mapping (F1–F10)

| # | Live failure | Root cause | Generic fix |
|---|---|---|---|
| 1 | "Create Bennet … level83" updated Hu Tao, no Bennet | RC1 + RC2 | typed referents, store-first resolve |
| 2 | "Create Keqing, set level90, show her" → Hu Tao | RC1 + RC2 | same + tool-result IDs as first-class context |
| 3 | "Show Xiao then update his level" — show dropped | RC5 | Worker before EntityManager; rule12 executes every operation |
| 4 | "Show Xiao and then show Neuvillette" → task VIEW | RC5 | seam before task VIEW quick-match |
| 5 | "Set Xiao's level85 and then show Xiao" — no display | RC5 | rule12: never collapse distinct operations |
| 6 | Goal deadline → Xiao.target_level=30 | RC2 + RC4 | typed per-kind domains + dedicated deadline tool |
| 7 | "next month end" wrong | RC6 | deterministic `date_parser` block |
| 8 | Artifact dup by display name | RC3 | `(ws, entity_type, title)` identity |
| 9 | "Show all artifacts" → task VIEW | RC5 + RC3 | seam order + type-aware `ListEntitiesTool` |
| 10 | "Show all characters" mixed kinds | RC3 | `entity_type` filter, template-agnostic |

Honesty rules are unchanged: composition never claims created/updated/shown
unless the tool succeeded; `_fabricate_guard` blocks invented tool names;
fail-closed parser and mechanical confirmation gate still apply.

## Tests

- `tests/test_worker_parser.py` (26): extraction one-object contract (bare /
  fenced / prose / multi-object / array / unbalanced / empty), decision shape
  (missing/non-string/unknown action, non-object args), injection resistance.
- `tests/test_worker.py` (36): bounded loop; decision actions; confirmation
  gate; failure policy; honesty guard; M1 references; scenario 14 limitation;
  scenario 16 reminders; date injection; adversarial (prompt injection,
  malicious tool-result text, forged tool name); structured logging (no raw
  text, secrets redacted); source guard (worker.py must not import
  database/sqlite3/reply_text); MAX_TOOL_CALLS=6 (raised from 4 during M4
  so compound chains that were previously abandoned mid-way get honest
  execution instead of budget exhaustion — see the CHANGELOG M4 entry).
- `tests/test_worker_orchestration.py` (75): the M4 acceptance matrix
  (WKR-023…027) PLUS 28 parametrized **generic-invariant** tests (S1–S30,
  WKR-028…030) added by the second-live-pass forensic pass: create→set→show
  across character/weapon/artifact names, create(A)→set(A)→show(B),
  show→update→show, update→show, two independent entities, cross-domain
  same-name identity, stale-active + fresh-create pronoun resolution,
  goal-referent domain conflicts, failed-tool recovery, success+failed
  retrieval traces, never-fabricate-success, unknown referents never mutating
  the active entity, max-steps honest summary, typed list filters never mixed
  kinds, task/habit domain isolation, artifact/weapon retrieval after create,
  and **deadline-clear (S30)** — `update_goal_deadline` clearing to `None` is a
  success, not a false "not found" (the one real code bug found by the
  forensic pass; fixed in `database.py` + `tool_adapters.py`).
- `tests/test_worker_render.py` (18): the **response-format restoration**
  (item12 — the PRODUCT regression). Worker replies are NOT plain prose:
  `core/ai/worker_render.py` routes each tool result through the existing BAKA
  formatter (entity/task/goal/habit/workspace cards, topic lifecycle
  renderers). Pins the latent list-renderer crash (`_list_entity_topics()`
  took 1 arg but the dispatch passes 3) via
  `test_render_every_list_tool_accepts_the_3arg_dispatch` — every list tool
  now accepts `(data, user_id=None, fetcher=None)` — and routes ok=False
  topic refusals through the data renderer (honest "refused" text, never a
  generic "failed"). Hostile/empty data never crashes.
- `tests/test_worker_topics.py` (20): the **topic lifecycle** matrix (items
  7/8/10 — matrix E): ONE canonical topic per `(workspace_id, entity_id)`
  through the `_TopicTool` base; ensure idempotent (card only into a NEW
  topic); lock durable across a fresh registry; locked topics refuse ordinary
  deletes (ok=False) unless `force=true`; `delete_entity_topic` is DESTRUCTIVE
  + confirmation-message (mechanical gate → CONFIRMATION_NEEDED, nothing
  deleted) and NEVER deletes the DB entity; honest no-projection / no-topic
  refusals; `repair_topics` collapses logical duplicates (canonical row + kind
  adoption, duplicate rows kept-but-skipped — never deleted, locked state
  preserved); renderer coverage for every topic op incl. refused deletes.
- Deterministic fake models drive the majority; no test calls the real GLM.
  Real-model smoke is a later live-acceptance pass (never part of pytest).
- Selftest: "AI Worker (dormant)" + "AI Worker Deterministic Round-trip"
  (offline, zero residue), plus "AI Tool Adapter Registry"/"Round-trip",
  "Topic Lifecycle Tools"/"Topic Repair" (Workspace category). Regression:
  WKR-001…031.
- Full suite: **1631 passed** (~25s). Full selftest: **28 PASS / 0 FAIL / 0
  WARNING** (the offline network AI-probe now PASSes — the provider is up on
  `meta/llama-3.1-8b-instruct`).
- **Forensic result for the second live pass:** bot.log proved the Worker
  NEVER ran (`WORKER=0`, not in `.env`) — all 7 reported failures were legacy
  EntityManager/baka_brain with `meta/llama-3.1-8b-instruct`; zero map to
  GLM-5.2 / the Worker parser / typed referents / Worker composition (see
  DEBUGGING.md's "Second live pass" section for the A–G classification).
  Live M4 acceptance is NOT claimed until `WORKER=1` + restart + the manual
  matrix passes.

## M4 live validation (2026-08-11 — temporary `meta/llama-3.1-8b-instruct`)

**Provider forensics:** NVIDIA `z-ai/glm-5.2` currently serves NO output on
NVIDIA NIM. Connectivity/auth/request format are healthy (the same key +
`meta/llama-3.1-8b-instruct` work sub-second), but GLM-5.2 read-times-out at
60–150s probes (0 bytes streamed); the id lists on `models.list()`. This is
an **upstream model-serving hang, not a Worker implementation problem** — no
timeouts/retries/redesign were added around it, and GLM-5.2 was **not**
removed or deprecated. Per the owner directive, the M4 validation matrix ran
on `MODEL_MAIN=meta/llama-3.1-8b-instruct` (temporary; `MODEL_THINK` stays
GLM-5.2 for the `/think` path). Provider/model abstraction is intact for a
later Z.ai-native / healthy-NVIDIA evaluation.

**Live matrix (31 messages, WORKER=1, real Telegram bot):** the Worker ran on
every message. **11 genuine full PASSes** (A5, B1, B3, C1, C2, C5, C6, C7,
E1a, E2, E3) — proven Worker→ToolRegistry→Tool→ToolResult→Worker-final from
bot.log `[worker …]` lines (real tool calls, ok=True, no legacy fallthrough).
4 fell through to legacy (A1/B2/E1b Worker `declined`; F2 `tool_failure`
after a Telegram topic-creation ReadTimeout). 16 ran the Worker but did not
complete the compound intent. The **7-point acceptance rule** was applied per
scenario — a DB mutation alone never counted as a PASS.

**Three ARCHITECTURE (tool-contract) fixes** (generic, with regression tests
+ WKR-031): integer workspace ids accepted (C3); "leave-it-out"
optional-filter markers — `''` and the literal `'omit'`/`'none'`/`'all'`/
`'any'` the catalog wording invited — normalized to no-filter (C8); unmatched
workspace-name falls back to the active workspace per the "(defaults to the
active one)" spec (A2). The C8 fix was bot.log-proven live end-to-end.

**The rest were MODEL CAPABILITY (Llama-3.1-8B)**, not architecture — the
typed-referents block and tool catalog were correct in every case:
compound chains abandoned after 1–2 tool calls, "its"-→-goal declines,
`name='artifact'` extraction, and a retest where Llama declined "Create
Mizuki" (legacy then created it correctly) and invented a `status='done'`
filter for "Show all artifacts" (honest empty). Two documented gaps, **not**
fixed: the never-fabricate guard passes a reply that *overstates partial*
success (D3 — deterministic fix needs fragile reply parsing), and typed
vs legacy entity data fragmentation (pre-M4 rows are `entity_type='entity'`,
so typed lists/dupe-checks only see Worker-created typed entities).

**Acceptance:** **M4 is NOT accepted as production-ready for compound
commands with Llama-8b.** It is accepted as a bounded executor whose
tool-contract and routing are sound and regression-pinned; its ceiling is the
LLM's planning. GLM-5.2 on healthy NVIDIA / Z.ai-native must be re-evaluated
before M5. Full suite at that point: **1569 passed**, selftest **26 PASS /
0 FAIL / 0 WARNING**. (CHANGELOG "M4 live validation" entry; DEBUGGING.md
"Third live pass" section.)

## M4 remediation — the 18-cluster fix list (v15.2, items1–20)

After the first live validation the owner issued the 18–20-cluster
remediation spec: every fix is **generic** (implementation + automated
regression tests + multiple NL variants + live validation + documentation),
none patch only the observed phrases, and M5 is NOT started — this is an M4
**patch** version. The full list is in the CHANGELOG's "M4 remediation"
entry. The clusters that materially changed the Worker surface:

### Topic lifecycle — one canonical topic per `(workspace_id, entity_id)` (items6/7/8/10)

**The invariant (item6, CRITICAL):** an entity has EXACTLY ONE Telegram topic.
Pre-M4 a topic could be created twice for the same entity (different code
paths each called `create_forum_topic`), leaving a shadow topic with no
binding. Now every create flows through the `_TopicTool` family
(`core/ai/tool_adapters.py`, five tools registered in `build_tool_registry`):

| Tool | Risk | Semantics |
|---|---|---|
| `get_entity_topic` | READ_ONLY | read the canonical binding; ok even when no topic yet |
| `ensure_entity_topic` | MUTATING | idempotent — returns the existing topic (created=False), the initial card goes ONLY into a NEW topic |
| `set_entity_topic_locked` | MUTATING | durable lock (a DB column, survives a fresh registry) |
| `delete_entity_topic` | DESTRUCTIVE + confirmation_message | deletes the TOPIC only — the entity row stays; ordinary deletes of a LOCKED topic are refused (ok=False) unless `force=true` |
| `list_entity_topics` | READ_ONLY | bindings + lock state |

The `_TopicTool._resolve_topic_entity()` resolves a workspace + entity ref
through the shared M1 reference machinery, and every tool returns an honest
result when no projection is wired (`not_wired`, nothing to do). The binding
is keyed `(workspace_id, entity_id)` via `tg_get_workspace_entity_topic`, so
two topics for one entity are structurally impossible on the write path.

**Repair — `/topicrepair` (admin):** `repair_topics` in
`core/workspace/groups_app.py` is idempotent and self-healing: it collapses
logical duplicates (one normalized title → ONE entity → ONE topic), adopts the
entity kind onto the canonical row, reports created/existing/duplicates/errors,
**never deletes a DB row** (duplicate rows are kept-but-skipped, so no data
loss), and preserves locked state. Registered in the Admin help cards and
pinned by a Self-Test ("Topic Repair").

### Workspace lifecycle symmetry audit (item11)

Every destructive workspace operation now carries `RiskLevel.DESTRUCTIVE` +
`confirmation_message` (the Worker's mechanical confirmation gate refuses to
execute them before confirmation). Workspace deletion itself is DB-only —
never reachable from NL — and any future delete/archive *workspace* tool must
follow the same DESTRUCTIVE + confirmation pattern. Pinned by
`test_workspace_lifecycle_has_no_silent_destructive_path` and regression
WKR-026/S23.

### Response-format restoration — Worker decides WHAT happened, BAKA decides HOW it is displayed (item12)

**The PRODUCT regression:** pre-fix the Worker replied in plain prose,
bypassing the bot's established card/formatting language. Post-fix every
Worker tool result is rendered through the existing formatter
(`core/ai/worker_render.py` → the same builders the deterministic commands
use). A latent crash was caught and fixed generically: the dispatch passes
`(data, user_id, fetcher)` to every list tool, but several list renderers
took one argument — any real Worker `list_*` would have crashed. All list
renderers now accept the 3-arg signature, pinned by
`test_render_every_list_tool_accepts_the_3arg_dispatch`. Tool refusals
(locked-topic delete, etc.) render their refusal text through the data
renderer rather than a generic "failed".

**Automated coverage added:** `tests/test_worker_render.py` (18, matrix H) +
`tests/test_worker_topics.py` (20, matrix E) bring the full suite to **1631
passed**; selftest **28 PASS / 0 FAIL / 0 WARNING** (the AI-category
registry/round-trip/worker-dormant probes were updated for the 30-tool
surface and MAX_TOOL_CALLS=6, and "Topic Lifecycle Tools" + "Topic Repair"
added to the Workspace category).

## Known limitations

- **Task ordinal resolution does NOT exist** (scenario 14): "complete the
  first task" has no deterministic mapping to a task_id. The Worker honestly
  asks for the id/title — it does not invent one. Task ordinals are M5+
  scope.
- The Worker's in-memory recent-mention/ordered-list context is Worker-scoped
  (`_worker_ref_ctx`); the DB-backed active entity is shared with the rest of
  the app. Entity-heavy NL is normally handled by EntityManager before the
  Worker anyway.
- **No live Telegram acceptance is claimed.** The Worker is dormant; the
  owner must flip WORKER=1 and run the manual live matrix (WKR-001…031 in
  TESTING.md) before "live-accepted" is written anywhere.
- WORKER applies to the owner only (canary). A future milestone widens it.

## M5 scope (NOT done here)

Widening the canary beyond the owner, real-GLM smoke + the live acceptance
matrix, task ordinal resolution, decline-fast classification if latency
demands, worker metrics surfaced in the dashboard, and any routing migration
beyond the current single dormant seam.
