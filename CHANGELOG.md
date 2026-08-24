# BAKA Bot — Changelog

This is the authoritative version history, moved here from the old `VERSION.md`
(now a pointer to this file — see below). Forward-looking / not-yet-built ideas
live in [ROADMAP.md](ROADMAP.md) instead of being mixed into this file.

Each entry lists what was added and which files were touched, so a future
session can find the relevant code quickly.

---
<!-- Markdown header for new version separators -->
---

## v15.6.0 — Phase 4 Characterization Testing Pipeline (2026-08-24)

> **Complete characterization + regression lock + live acceptance testing pipeline.** 135 tests passing across 4 phases.

**What shipped:**

- **Phase 4A — Habit Behavior Characterization** (`tests/behavior/test_habit_behavior.py`, 37 tests)
  Habit CRUD, completion, streaks, reminders, list views — frozen as regression baseline
- **Phase 4B — Snapshot Regression Lock** (`tests/behavior/test_habit_snapshot.py`, 37 tests)
  Golden-file snapshots of habit flows for regression detection
- **Phase 4C — Callback Regression Lock** (`tests/behavior/test_callback_behavior.py`, 58 tests)
  All 20+ callback actions verified: dashboard, task, project, vision, developer, control plane, route dashboard, UI card callbacks, integration snapshots
- **Phase 4D — Live Telegram Acceptance Testing** (`testing/playwright/`, 3 tests)
  Playwright automation against QA bot (`Baka_qa_bot`): `00_bootstrap_login`, `01_start`, `02_commands` with screenshots

**Infrastructure fixes:**
- `instance_lock.py` — Cross-platform singleton lock (fcntl on Linux, CreateMutexW `Global\BAKA_Bot_Lock` on Windows)
- python-telegram-bot 20.7 → 22.8 (fixes `_Updater__polling_cleanup_cb` on Python 3.14.4)
- Playwright config: `workers: 1, fullyParallel: false` + `--no-sandbox --disable-setuid-sandbox` for stable session reuse
- Robust selectors: multiple fallbacks, `waitFor({state: 'visible'})`, crash/close handlers, `domcontentloaded` strategy

**Self-Test Suite**: 38 passed, 0 failed, 1 warning (AI API key not set)  
**Workspace Selftest**: 7 passed (template, engine, groups, cognitive, retrieval)

**Files touched:**
- `tests/behavior/test_habit_behavior.py` (new, 37 tests)
- `tests/behavior/test_habit_snapshot.py` (new, 37 tests)
- `tests/behavior/test_callback_behavior.py` (58 tests, 5 assertions fixed)
- `instance_lock.py` (rewritten cross-platform)
- `testing/playwright/playwright.config.ts` (workers: 1, fullyParallel: false)
- `testing/playwright/tests/00_bootstrap_login.spec.ts` (new)
- `testing/playwright/tests/01_start.spec.ts` (rewritten)
- `testing/playwright/tests/02_commands.spec.ts` (rewritten)
- `start_bot.py`, `run_selftest_all.py` (new)
- `docs/testing/index.md` (new — consolidated testing guide)

---

## v15.5.0-alpha.1+fix1 — Cross-Reference Retrieval (M7)

> **Single retrieval implementation for cross-reference search:** notes + media
> unified via `CrossReferenceService` (M6 NoteStorage/AttachmentStorage through
> EntityEngine). AND/OR filter semantics (entity AND/OR, tag AND/OR, combined),
> free-text, media_type, date range (IST-aware), kind, limit (50/200). Results
> carry `_type` discriminator ("note"|"media"). Active workspace isolation
> mandatory. Three READ_ONLY tools: `search_knowledge` (unified),
> `search_notes_cross`, `search_media_cross`. Control plane (`ctl:search` page
> + 8 gather handlers) uses the SAME service as Worker — **no second logic**.
> Full test matrix A–R (73 tests), regression suite RET-001…038, 4 selftest
> probes, engineering doc. **Version stamped v15.5.0-alpha.1+fix1.**

**fix1 (2026-08-14):** Stateful Search UI Builder — fixed the critical bug where
each gather handler cleared state and passed only its own filter, making compound
searches impossible. Root cause: `_gather_search_*` handlers called `clear_state()`
and passed only their own value to `search_home()`. Fix: all 8 handlers now use
`set_search_state()`/`get_search_state()` to accumulate filters across selections.
Added `_gather_search_entities()` handler, 📦 Entities button, `ctl:search:clear`
callback. Added Matrix Q (UI State Machine, 14 tests) and Matrix R (Control Plane
Integration, 3 tests) to `tests/test_m7_retrieval.py`. Updated engineering doc
(V15_5 §12). Created `docs/RET_LIVE_CHECKLIST.md` for owner-facing live tests.

**What shipped** (user-visible surface):
- **Unified Cross-Reference Search** — `search_knowledge` finds notes and media
  together; `search_notes_cross` / `search_media_cross` for scoped search.
- **Filter semantics** — entity AND/OR (multiple entities, all must match vs any
  matches), tag AND/OR, combined entity+tag filters, free-text across
  title/content/caption/filename/extracted_text, media_type filter, date range
  (created_after/created_before in IST), kind filter (notes only), limit
  (default 50, max 200, honest truncation).
- **Result discriminator** — every result has `_type` field ("note"|"media") so
  callers can branch without type guessing.
- **Workspace isolation** — every query scoped to active workspace; no
  cross-workspace leakage (critical invariant).
- **Control plane** — `/control` → Search page (`ctl:search`) with text query,
  workspace, AND/OR mode, date range, media type, tags, scope gatherers.
- **Worker integration** — 3 M7 tools register in the same `build_tool_registry`,
  classified READ_ONLY; the Worker inherits them automatically.
- **Date boundary fix** — `add_note`/`add_attachment` now write `created_at` in
  IST (matching search boundary logic), fixing the UTC-vs-IST off-by-one-day
  bug in date range filters.

**Implementation** (files touched):
- `core/retrieval/service.py` — NEW: `CrossReferenceService` (single
  implementation), `RetrievalFilters`, `RetrievalResult`; `_search_notes_with_logic`,
  `_search_media_with_logic`, AND/OR set operations, sort by created_at desc.
- `core/ai/tool_adapters.py` — 3 M7 tool adapters (thin wrappers over the
  service); `build_retrieval_service()` factory; all READ_ONLY.
- `core/control/pages.py` — `search_home` page; `core/control/router.py` — 7
  `_gather_search*` handlers (text, workspace, mode, dates, media_type, tags,
  scope); wired into `registry.py` control pages.
- `database.py` — `add_note` and `add_attachment` now explicitly set
  `created_at` via `_now_ist_str()` (IST) instead of relying on UTC
  `DEFAULT CURRENT_TIMESTAMP`; fixes date filter boundary bug.
- Tests: `tests/test_m7_retrieval.py` (57 tests, matrices A–P),
  `core/regression/suites/retrieval_m7.py` (38 tests RET-001…038),
  `core/selftest/tests/test_retrieval_selftest.py` (4 probes).
- Docs: `docs/engineering/V15_5_CROSS_REFERENCE_RETRIEVAL.md`.

---

## v15.4.0-alpha.1 — Knowledge + Media + Tags (M6)

> **BAKA is now a persistent personal knowledge/data-dump system:** notes +
> media metadata + tags, retrievable by entity/topic/tag/workspace/text/
> media-type/date, with Telegram as canonical media storage. Binding layering
> (unchanged from M5): `Worker → Tool Registry → Domain Service → DB /
> Telegram projection`; `Manual Control Plane → Tool Registry → same Domain
> Service`. **No second business-logic path.** Full design:
> [docs/engineering/V15_4_KNOWLEDGE_MEDIA.md](docs/engineering/V15_4_KNOWLEDGE_MEDIA.md).

**What shipped** (user-visible surface):
- **Knowledge (Notes)** — create / update / soft-delete / get / list / search
  (q, entity, tag, date range). Notes have title, content, kind, timestamps,
  entity links (many-to-many via `note_entities`), tag links.
- **Media** — store / update / soft-delete / get / list / search metadata
  records (file_id, media_type, caption, message_id, chat_id, topic_id,
  extracted_text, entity links, tag links). The Telegram file itself is NEVER
  touched; `delete_media` is metadata/links only.
- **Tags** — create / rename / delete (DESTRUCTIVE + confirm, cascades links),
  list per workspace. Tags are workspace-scoped (same name in different
  workspaces = distinct tags; partial unique index on (workspace_id, name)).
  Link tools create unknown tags on-the-fly ("dump under 1v4" contract).
- **Topic integration (DB-first, projection optional)** — notes/media linked
  to an entity can be posted to that entity's topic via
  `TelegramProjection.post_entity_update` (the "Arlecchino build notes" flow).
  A knowledge category never auto-creates a Telegram topic.
- **Media capture** — video/document/audio/voice messages record metadata via
  the domain service (linked to active workspace + active entity). Photos
  stay with `handle_photo` (progress-log/vision priority); photo→media is a
  documented follow-up.
- **Control plane** — `/control` gains Knowledge / Media / Tags sections with
  list/view/add/edit/delete/link pages (same M5-F confirm flow, no second
  logic).
- **Worker** — all 22 M6 tools register in the same `build_tool_registry` →
  the Worker inherits them (catalog renders from `registry.specs()`). Confirm
  gate, never-fabricate-success guard, tool-result-authoritative rules apply
  automatically.

**Implementation** (files touched):
- `database.py` — schema ALTERs (idempotent try/except): `notes` +3 columns,
  `attachments` +8 columns, `tags` +1 column + partial unique index; new
  tables `note_entities` + `attachment_entities` with indexes; corresponding
  storage functions for notes/media/tags/entities/links.
- `core/storage/storage.py` — `NoteStorage` (get/update/soft_delete/search/
  link_entity/unlink_entity/link_tag/unlink_tag), `AttachmentStorage` (new:
  add/get/update/soft_delete/list/search/link_entity/unlink_entity/
  link_tag/unlink_tag), `TagStorage` (new: create/rename/delete/list/for_entity).
- `core/workspace/repository.py` — model-shaped CRUD for all M6 resources
  (notes, media, tags, entity/tag links).
- `core/workspace/engine.py` — `EntityEngine` ownership-checked methods for
  all M6 tools (note CRUD + links, media CRUD + links, tag CRUD). `delete_milestone`
  now cascades to remove note/media entity links (no ghost refs).
- `core/ai/tool_adapters.py` — 22 thin M6 tools (notes 9, media 9, tags 4 —
  catalog 37→59): `create_note`, `update_note`, `delete_note` (DESTRUCTIVE),
  `get_note`, `list_notes`, `link_note_entity`, `unlink_note_entity`,
  `link_note_tag`, `unlink_note_tag`; `store_media`, `update_media`,
  `delete_media` (DESTRUCTIVE), `get_media`, `list_media`,
  `link_media_entity`, `unlink_media_entity`, `link_media_tag`,
  `unlink_media_tag`; `create_tag`, `rename_tag`, `delete_tag` (DESTRUCTIVE),
  `list_tags`. All DESTRUCTIVE tools carry `confirmation_message`.
- `core/control/pages.py` — Knowledge/Media/Tags section renderers (13 new
  pages: list/view/add/edit/del/link-entity/link-tag for each).
- `core/control/router.py` — `ctl:note:*`, `ctl:media:*`, `ctl:tag:*` routes
  + gathering branches.
- `main.py` — `MessageHandler` for video/document/audio/voice capture
  (additive; `handle_photo` unchanged), help entry updates in `ui.help_cards`.
- `tests/test_m6_knowledge.py` — 35 tests: matrix A (note CRUD), B (entity/tag
  links), C (media metadata), D (search + combined filters), E (workspace/entity
  isolation).
- `tests/test_m6_adversarial.py` — 21 tests: matrix F (confirmation gates),
  G (Worker integration), H (manual=Worker path), I (abuse/hostile input).
- `tests/test_tool_adapters.py` — M6 tool surface + risk classification tests
  added.
- `core/selftest/tests/test_knowledge_selftest.py` — 3 probes: M6 registry
  risk/surface, round-trip note+media+tag, control pages render.
- `core/regression/suites/knowledge_m6.py` — KNOW-001…012 (Admin + AI).
- `docs/engineering/V15_4_KNOWLEDGE_MEDIA.md` — schema, layering, topic
  integration A/B/C/D decision, search foundation vs FTS5 future, media
  capture boundary, no-second-logic proof.

**Tests**: `tests/test_m6_knowledge.py` (35), `tests/test_m6_adversarial.py`
(21), M6 tool tests in `tests/test_tool_adapters.py` (updated surface). Full
pytest ≥ 1769 pass with only the 5 known date-flakes. Offline selftest ≥ 30
pass with only the 2 known date-flakes. **`BAKA_VERSION = 15.4.0-alpha.1`.**

**Remaining gate (not claimed offline)**: the owner-run live-Telegram
acceptance matrix `KNOW-001…012` (documented in
`core/regression/suites/knowledge_m6.py` and
`V15_4_KNOWLEDGE_MEDIA.md §Acceptance`).

---

## v15.3.0-alpha.1 — Manual Control Plane + Lifecycle (M5)

> **BAKA can be reliably controlled and repaired manually, using the same
> underlying tool/domain capabilities that AI uses.** Binding layering (never
> a second logic layer): `AI Worker → Manual Dashboard → Telegram commands →
> Tool Registry → domain services → DB / Telegram projection`. The dashboard
> NEVER writes the DB directly — every mutation executes a ToolRegistry tool
> (the identical path `worker_confirm` uses). Admin-only `/control`, silently
> denied to others (CLAUDE.md obscurity rule). Full design:
> [docs/engineering/V15_3_MANUAL_CONTROL_PLANE.md](docs/engineering/V15_3_MANUAL_CONTROL_PLANE.md).

**What shipped** (user-visible surface):
- **`/control`** — the owner's Manual Control Plane: Workspaces · Entities ·
  Topics · Equipment · Identity pages, with an explicit "no workspace active"
  state on every page instead of a crash or a silent empty list.
- **Workspace control (M5-A)** — create / rename / open-switch / close /
  archive. `Close` clears the active context but NEVER deletes the workspace
  row; `Archive` is a soft lifecycle transition (DESTRUCTIVE + confirmation).
- **Entity control (M5-B)** — generic add / view / edit / delete pages per
  kind (Character / Weapon / Artifact) generated from the template's FieldSpecs
  (no Genshin hardcoding; only schema-supported fields are offered). Delete is
  a soft-delete behind confirmation; a topic, if any, stays.
- **Topic Control Center (M5-C)** — ensure / lock / unlock / delete / repair.
  One canonical topic per entity; a LOCKED topic refuses ordinary delete and
  shows `[Unlock] [Force delete] [Back]`; force-delete keeps the entity.
  `Repair` is idempotent and reconciles missing/duplicate topics.
- **Identity Inspector (M5-D)** — exactly 8 rows (Name / Entity ID / Kind /
  Workspace / Topic ID / Topic status / Lock status / Active); never secrets.
- **Equipment (M5-E, minimal)** — equip/unequip a weapon onto a character via
  the existing game-template `weapon` field (no second DB; artifacts and
  non-characters are refused). Richer model (stats/refinement/equipped-to
  linkage) is explicitly deferred to M6+.
- **One shared confirm flow (M5-F)** — every destructive / data-entry action
  uses `begin_confirm`/`confirm_yes`/`confirm_no` with wording from the tool
  spec; Cancel discards and never executes.

**Implementation** (files touched):
- `core/ai/tool_adapters.py` — 7 thin registry tools (catalog 30→37, additive):
  `create_workspace`, `rename_workspace`, `close_workspace`,
  `archive_workspace` (DESTRUCTIVE + confirm), `delete_entity` (DESTRUCTIVE +
  confirm), `repair_topics`, `equip_item`. `_no_projection` moved to the common
  entity-tool base.
- `core/control/` (new) — `registry.py` (`ControlContext`, `build_context`,
  `build_control_registry`, `execute_tool`, `execute_tool_async`; the
  threading-contract projection freeze), `pages.py` (13 pure renderers),
  `actions.py` (the M5-F confirm flow), `router.py` (`ctl:` namespace routing +
  gathering-driven data entry).
- `core/workspace/groups_app.py` — `WorkspaceGroups.close_workspace` (1 line
  over `tg_bindings.clear_active`).
- `main.py` — `ctl` branch in `handle_callback`, `/control` CommandHandler
  (admin-gated), the `_ctl` gathering branch, help entry in `ui.help_cards`.
- Selftest probes — `core/selftest/tests/test_control_panel.py` (2 new), the
  pinned tool surface updated 30→37 in `test_tool_adapters_selftest.py` and
  `test_worker_selftest.py` (both also pin the M5 destructive confirmations).
- Regression spec — `core/regression/suites/control_m5.py` (CTRL-001…010).

**Tests**: `tests/test_control_panel.py` (38: pages, router, M5-F confirm,
gathering, no-second-logic proof), `tests/test_m5_adversarial.py` (41: the
14-scenario M5-H matrix — happy/duplicate/missing/wrong-kind/wrong-workspace/
already-locked/already-unlocked/missing-topic/repeated/cancel-confirm/
invalid-input/stale-identity/cross-workspace/permission-boundary), new tool
tests in `tests/test_tool_adapters.py`, pinned risk/surface checks updated.
Offline selftest: 2 new probes pass (registry + pages/confirm); the two
pre-existing date-of-run flakes (hardcoded `2026-08-11`) are the only
failures. **`BAKA_VERSION = 15.3.0-alpha.1`.**

**Remaining gate (not claimed offline)**: the owner-run live-Telegram
acceptance matrix `CTRL-001…010` (documented in
`core/regression/suites/control_m5.py` and
`V15_3_MANUAL_CONTROL_PLANE.md §Acceptance`).

## v15.2.0-alpha.14 — BAKA Brain · M2: Tool Contract Foundation

> **DORMANT FOUNDATION — not released, no user command routes through it.**
> This milestone builds the *tool contract* the future AI Worker will run on.
> There is **no AI Worker, no agent loop, no GLM tool-calling, and no
> `main.py` routing change** here. When it landed, v15.2 was mid-build and
> the version was NOT bumped then; the M4 remediation (below) is the first
> stamp on the v15.2 line — **`BAKA_VERSION = 15.2.0-alpha.14`** (owner
> decision, M4 patch version, item19). The contract is health-verifiable now
> via `/selftest → AI → 'AI Tool Contract'`. Full design:
> [docs/engineering/V15_2_BAKA_BRAIN.md](docs/engineering/V15_2_BAKA_BRAIN.md).

Extends the existing `core/ai/tools.py` into the single, validated Tool
Contract (one abstraction, no second registry): `RiskLevel`
(READ_ONLY/MUTATING/DESTRUCTIVE/SYSTEM), `ToolSpec` now carries `risk` /
optional `confirmation_message` / optional `requires_admin`, a unified
`ToolResult` (tool, ok, output, optional structured `data`, `warnings`,
stable `error_code`), `ToolError` with stable machine-readable codes
(`ToolErrorCode`), fail-closed argument validation (`validate_spec` /
`validate_args` — invalid args never reach a handler), and a stricter
`ToolRegistry` (spec validation at registration, duplicate-name rejection,
`execute(name, args)` dispatcher). **1380 offline tests passing** (79 new:
`tests/test_tool_contract.py`, A–G + adversarial), self-test probe
"AI Tool Contract" added, regression suite TLC-001…004 added. See
`docs/engineering/V15_2_BAKA_BRAIN.md`. **Next (M3):** the tool adapter
surface — map each real capability (tasks/reminders/habits/goals/entities/
workspace/memory/Telegram projection) to concrete `Tool`s with honest risks,
then route the Worker's planned calls through `ToolRegistry.execute`.

- **`core/ai/tools.py` — the full Tool Contract (single file, single
  abstraction):** `RiskLevel` classifies what a tool may do; `ToolSpec`
  gained `risk` (default `READ_ONLY`), `confirmation_message` (optional) and
  `requires_admin` (optional) beside `name`/`description`/JSON-Schema
  `parameters` (`to_openai()` unchanged); `Tool.execute(**kwargs)` is the one
  sanctioned run path — validate → run → contain, returning a `ToolResult`
  that never raises for ordinary input (`ToolError` keeps its code,
  unexpected exceptions become `error_code='internal'`, `str`/`ToolResult`/
  `None` returns normalized); `ToolRegistry.register` now validates the spec
  and **rejects duplicate names** (replaces pre-M2 idempotent-replace), and
  `ToolRegistry.execute(name, args)` dispatches (unknown tool →
  `unknown_tool`, non-object args → `invalid_args`).
- **`core/ai/tools.py` — validation:** `validate_spec` rejects malformed
  schemas (empty name/description, non-object top-level type, unknown property
  types, empty type lists, undefined `required` refs, non-dict property
  schemas, bad nested objects, non-`RiskLevel` risk, non-string
  `confirmation_message`, non-bool `requires_admin`); `validate_args` enforces
  required args, JSON types (bool ≠ integer; `None` only where `null` is
  declared, e.g. `["string","null"]`), `enum`, `minLength`, nested objects —
  and **rejects unknown arguments for MUTATING/DESTRUCTIVE/SYSTEM tools**
  while **silently dropping them for READ_ONLY** tools. Invalid arguments
  never reach a handler.
- **`core/ai/cognition.py` — ToolResult unification:** removed its **local**
  `ToolResult(tool, output, ok)` and now imports the unified contract
  `ToolResult` from `core.ai.tools` (construction sites converted to keyword
  args; the old positional order would have silently bound the second
  argument to `ok`). `cognition.execute()` itself is **unchanged** — the
  Cognitive Engine's live `/ws` behavior is byte-identical.
- **`core/ai/__init__.py`:** exports `RiskLevel`, `ToolError`,
  `ToolErrorCode`, `ToolRegistryError`, `ToolResult` from `core.ai.tools`;
  `ToolResult` dropped from the cognition re-export (single class now).
- **`tests/test_tool_contract.py` (new, 79 tests):** ToolSchema (A),
  argument validation (B), risk behaviour (C), ToolResult (D), ToolError (E),
  ToolRegistry (F), execution contract (G) + adversarial (malformed JSON
  schemas, junk nested keys, wrong primitive types, empty strings, `None`/
  `null`, duplicate/colliding names, exceptions inside tools, missing tools,
  dangerous metadata, invalid OpenAI function schema).
- **`tests/test_ai_foundation.py`:** `test_registry_register_is_idempotent_by_name`
  → `test_registry_register_rejects_duplicate_name` (contract change).
- **`core/selftest/tests/test_ai.py`:** new offline **"AI Tool Contract"**
  probe (register → validate → execute → contain) so the dormant contract's
  health is verifiable from `/selftest`.
- **`core/regression/suites/tool_contract_m2.py` (new):** TLC-001…004 Quick
  Release Suite specs for the contract checks.

### M3 — Real Tool Adapters

> **DORMANT ADAPTERS — not released, no user command routes through them.**
> This milestone wraps BAKA's **existing** business logic in 24 M2-contract
> `Tool`s, but **nothing in `main.py` calls `build_tool_registry`** and no
> normal message is routed through it. There is **no AI Worker, no agent loop,
> no GLM tool-calling, no worker routing, no automatic worker activation, and
> no `main.py` routing migration** here. Version number is NOT bumped. The
> adapters are health-verifiable now via `/selftest → AI → 'AI Tool Adapter
> Registry'` and `'… Round-trip'`. Full design:
> [docs/engineering/V15_2_BAKA_BRAIN.md](docs/engineering/V15_2_BAKA_BRAIN.md).

New `core/ai/tool_adapters.py`: `build_tool_registry(user_id, …)` returns a
per-user M2 `ToolRegistry` of **24 thin adapters** — tasks (`list_tasks`,
`find_task`, `create_task`, `update_task`, `complete_task`, `delete_task`),
habits (`create_habit`, `list_habits`, `complete_habit`), goals (`create_goal`,
`list_goals`, `update_goal_progress`), entities (`create_entity`,
`get_entity`, `update_entity`, `list_entities`, `find_entity`), workspace
(`list_workspaces`, `get_workspace`, `open_workspace`, `inspect_workspace`),
memory/recall (`get_memories`, `search_memories`, `recall`). Each is argument
translation + validation + calls into the real services (Storage facade,
EntityEngine, WorkspaceGroups, M1 ReferenceResolver/Retriever,
TelegramProjection) + a structured `ToolResult` with machine-readable `data`
(ids, fields, workspace, projection status). Honest risks: every write tool is
MUTATING (including `open_workspace` — persists active state), `delete_task`
is DESTRUCTIVE with a `confirmation_message`, nothing is SYSTEM. Entity
creation/update drive the **same alpha.13 projection contract** `/add` and NL
creation use (create_entity → WorkspaceGroups.create_entity; update_entity →
per-field engine.update_field + append-only post_entity_update). **1423
offline tests passing** (43 new: `tests/test_tool_adapters.py`, incl. Genshin
acceptance fixtures Xiao/Kinich/Xilonen/Nefer/Lauma/Columbina as test data,
adversarial list, and RecorderProj/FakeClient integration proving the
projection is not bypassed), selftest "AI Tool Adapter Registry" + "AI Tool
Adapter Round-trip" added, regression suite TAD-001…005 added. Also: the `/ws`
`OpenWorkspaceTool` is reclassified `READ_ONLY → MUTATING` (honest — behavior
unchanged), and `MemoryStorage` was added to the Storage facade (the recall
tools read through the same facade every domain uses — no raw SQL). Bug fixed
by the suite: `_task_dict` no longer indexes past the 5-column rows
`search_tasks_by_title` returns. **Next (M4):** the AI Worker — agent loop,
GLM tool-calling, worker routing, and `main.py` routing migration. M3 does
not claim any of that exists.

### M4 — GLM-5.2 Worker (bounded, tool-calling executor)

> **DORMANT WORKER — not released, owner-only canary.** The Worker ships
> complete but OFF: `WORKER=0` by default, and even when `WORKER=1` it
> activates ONLY for the owner (`OWNER_ID`, the same `is_admin()` gate admin
> commands use). In the message cascade it runs AFTER the deterministic
> menu/confirming/editing/gathering/NL-map gates but BEFORE the EntityManager
> and the task VIEW quick-match (so real entity/goal/task requests are not
> hijacked by "Tasks for All Pending" — WKR-023…027), falling through to
> EntityManager → VIEW → Legacy when it declines or fails. While OFF,
> `handle_message` is byte-identical to pre-M4. **No live Telegram acceptance
> is claimed** until the manual live matrix (WKR-001…027 in TESTING.md) is
> actually run. Version number is NOT bumped. Full design + architecture
> proposal:
> [docs/engineering/V15_2_BAKA_BRAIN.md](docs/engineering/V15_2_BAKA_BRAIN.md).

New `core/ai/worker.py` (+ `worker_contract.py`, `worker_parser.py`,
`worker_prompt.py`): converts ONE message into **at most 4 tool calls** through
a `ToolRegistry` (`MAX_TOOL_CALLS` is a Python constant — not widenable via
any input/env), then one final reply. Never touches a database, Telegram, or
raw handler directly; `ToolRegistry.execute` is the only run path.
`worker_parser.py` replaces the greedy `clean_json` extractor with a
fail-closed parser (exactly ONE top-level JSON object; multi-object/array/
malformed → `MALFORMED` — the audit's F1 bug class is closed). Mechanical
confirmation gate BEFORE execute: `delete_task` (DESTRUCTIVE, has a
`confirmation_message`) never runs silently — the yes/no flows through the
EXISTING `conversation_state.py` pending-action machine (`worker_confirm`
branch), no second confirmation system. Deterministic never-fabricate-success
guard: a reply can't claim `created/deleted/…` without a backing `ok=True`
tool result. M1 resolver stays authoritative for entity references; the
deterministic `date_parser` result is injected and must be used verbatim
(dates are never LLM-guessed). Model calls go through
`baka_brain.call_worker_single` — ONE `MODEL_MAIN` (GLM-5.2) attempt,
`temperature=0`, no retry, no fallback (no retry storms). One structured log
line per run with request_id/termination/steps/args; **raw user text is never
logged** and secret-keyed args are redacted. **1484 offline tests passing**
(61 new: `tests/test_worker.py` — bounded loop, confirmation gate, failure
taxonomy, honesty guard, M1 references, scenario 14 limitation, scenario 16
reminders, adversarial, structured logging, source guard; plus
`tests/test_worker_parser.py`), selftest "AI Worker (dormant)" + "AI Worker
Deterministic Round-trip" added, regression suite WKR-001…022 added, new
`feature_flags.WORKER` (default OFF). **Known limitation (scenario 14):** task
ordinal resolution ("complete the first task") is NOT implemented — the Worker
honestly asks for the task id/title. **Next (M5):** real-GLM smoke + the live
acceptance matrix, widening the canary, task ordinals.

### M4 orchestration — typed referents, goal-deadline tool, type-aware retrieval, routing order

Generic fixes for the ten live M4 orchestration failures (DEBUGGING.md's
resolved table maps each failure → root cause → fix). All **dormant** (no
user-facing change while `WORKER=0`):

- **Typed referents are first-class context.** New `core/ai/typed_referents.py`
  — a per-user, per-kind, recency-ordered referent store. Every tool adapter
  notes create/update/list results into it (`_note_typed`), the prompt renders
  them as a `REFERENTS` block, and resolution checks the store FIRST: a
  just-created id wins over any stale active entity, and a pronoun pointed at a
  different kind is REFUSED (never reaches across domains). Fixes F1/F2/F5/F6.
- **The goal domain owns deadlines.** New `update_goal_deadline` adapter +
  `database.update_goal_deadline()` + `GoalStorage.update_deadline` — a
  deadline request on a goal can no longer fall through to `update_entity`'s
  forward-compat fields (the target_level corruption). Fixes F6.
- **Deterministic period-end dates.** `date_parser` now resolves "next month
  end" / "end of next month" → last day of next month (crosses years; runs
  before the this-month pattern). Fixes F7.
- **Type-aware entity identity + retrieval.** `milestones.entity_type` column
  (additive, idempotent migration; `Milestone.entity_type` with old-row
  tolerance), threaded through engine/repository/storage/groups_app; duplicate
  detection is `(entity_type, name)`; `create_entity` accepts `entity_type`;
  `list_entities` accepts an `entity_type` filter. Fixes F8/F9/F10.
- **Worker seam ordering (R10).** In `handle_message`, the owner-only Worker
  now runs AFTER the deterministic menu/confirming/NL-map gates but BEFORE the
  EntityManager and the task VIEW quick-match, so compound / typed-retrieve
  requests are never hijacked by "Tasks for All Pending". `WORKER=0` path is
  byte-identical. Fixes F4/F9.
- **Execute every operation.** Worker prompt rule12: a multi-operation message
  ("show X and then update his level") runs EVERY distinct step, one tool per
  step, never skipping a retrieve after a mutation. Fixes F3/F5.
- **Clearing a deadline is a success, not a failure (S30).**
  `database.update_goal_deadline()` returned `None` BOTH when a goal is missing
  AND when a deadline is cleared to `None`, so the `update_goal_deadline`
  adapter reported a false "goal [N] not found" failure for a clear that
  actually succeeded in the DB. It now returns `goal_id` on success (never
  `None` for a legitimate cleared deadline) and the adapter reads the new value
  from its own validated argument. Found by the new S30 invariant test.
- **Generic invariant regression suite (S1–S30, WKR-028…030).** 28 parametrized
  invariant tests in `tests/test_worker_orchestration.py` covering the forensic
  classification of the SECOND live M4 pass: `create(X)→set(X)→show(X)` across
  character/weapon/artifact names, `create(A)→set(A)→show(B)`, `show→update→
  show`, `update→show`, two independent entities, cross-domain same-name
  identity, stale-active + fresh-create pronoun resolution, goal-referent
  domain conflicts, failed-tool recovery, success+failed retrieval traces, the
  never-fabricate-success guard, unknown referents never mutating the active
  entity, max-steps honest summary, typed list filters never returning mixed
  kinds, task/habit domain isolation, and artifact/weapon retrieval after
  create. Every invariant is asserted for MULTIPLE names/kinds — never a
  phrase-specific pin.

**1563 offline tests passing** (+54: the parametrized generic-invariant cases
above, on top of the 1509 suite), selftest 25 PASS / 0 FAIL / 1 WARNING (the
warning is the pre-existing offline "AI Provider" network probe), regression
spec validation 19 passing incl. WKR-028…030. **Forensic note for the second
live pass:** bot.log proved ALL 7 reported failures were LEGACY-path failures
— the Worker never ran (`WORKER=0`, not in `.env`), so every message went
through EntityManager/baka_brain with `meta/llama-3.1-8b-instruct`. Zero
failures are attributable to GLM-5.2, the Worker parser, typed referents, or
Worker composition. Version NOT bumped; live M4 acceptance still NOT claimed
(requires `WORKER=1` + restart + the manual matrix).

### M4 live validation (temporary `meta/llama-3.1-8b-instruct`, 2026-08-11)

> **Why Llama, not GLM-5.2 (temporary validation model only).** The NVIDIA
> provider forensic (DEBUGGING.md) proved `z-ai/glm-5.2` currently serves NO
> output on NVIDIA NIM (client-side `APITimeoutError` at 60/90/120/150s
> probes; `models.list()` lists the id, but the model worker hangs upstream).
> Llama-8b answers sub-second. **GLM-5.2 is NOT deprecated and NOT removed**
> — it remains the intended stronger Worker candidate; the provider/model
> abstraction is intact for later Z.ai-native / healthy-NVIDIA testing. The
> Worker was switched to `MODEL_MAIN=meta/llama-3.1-8b-instruct` ONLY for this
> validation pass. No timeout increases, no retries, no silent fallback to
> another Worker model were added.

**Configuration fixes (`.env`):** repaired the malformed `LOG_GROUP_ID=WORKER=1`
line (restored empty `LOG_GROUP_ID`, kept clean `WORKER=1`, added
`MODEL_MAIN=meta/llama-3.1-8b-instruct`). Verified MODEL_MAIN resolved, Worker
logs show Llama, NVIDIA NIM returns minimal Llama responses, and no GLM-5.2
request is made by the Worker (`MODEL_THINK` still GLM-5.2 for the `/think`
path only).

**31-message live matrix (Phases A–F, real Bot, `WORKER=1`).** bot.log line per
message; every scenario judged on the 7-point acceptance rule (Worker executed,
correct tools, correct args, correct ToolResults, DB mutation, Telegram
projection, final reply) — NOT on DB state alone. Result: **11 genuine full
Worker PASSes** (A5, B1, B3, C1, C2, C5, C6, C7, E1a, E2, E3); **4 legacy
fallthroughs** (A1/B2/E1b Worker `declined` → legacy, F2 `tool_failure` after a
Telegram topic-creation ReadTimeout → legacy); the remaining 16 ran the Worker
but did not complete the user's full intent. Failure classification:

- **ARCHITECTURE (tool-contract, FIXED — 3 generic fixes, none phrase-specific):**
  - **C3 — integer workspace ids rejected.** `KNOWN REFERENTS` renders
    workspace ids as ints (`ws=1`) and tells the model to pass exact ids, but
    every workspace spec declared `{"type":"string"}`. All 8 workspace-taking
    tool specs now accept `["string","integer"]`.
  - **C8 — empty optional filters rejected.** `list_entities(status='')` hit the
    `status` enum though `run()` already treats `''` as falsy. `validate_args`
    now normalizes a "leave-it-out" marker (`''`, `omit`, `none`, `all`, `any`)
    on a NON-required argument to `None` (required args keep minLength/type
    enforcement); `list_entities` description reworded from "Omit for all." (the
    wording that invited the literal `'omit'` value) to "Leave a filter out to
    include all."
  - **A2 — unmatched workspace name failed.** `_require_workspace` now falls
    back to the active workspace when a provided name/#id doesn't resolve
    (honoring the documented "defaults to the active one"), while still
    erroring when no active workspace exists.
- **MODEL CAPABILITY (Llama-3.1-8B — documented, NOT architecture, no fix):**
  compound chains abandoned after 1–2 tool calls (A3/A4/D1/D2/D4/D5/F1/F3/F4;
  best run D3 did 3 tools but dropped the last and fabricated "Lauma with level
  80" — the honesty guard catches total fabrication but not overstated partial
  success); "its"-→-goal declines (B2/E1b); `name='artifact'` arg extraction
  (E4); invented `status='done'` filter and `status='omit'` literal on retest.
  The referents block and tool catalog were correct in every one — Llama's
  planning, not the Worker's.
- **DATA/INFRA (documented, not fixed):** typed-identity fragmentation (legacy
  pre-M4 entities are `entity_type='entity'`, invisible to typed lists; F1
  created a second typed `Xiao` beside the legacy one); B2/E1b legacy-path
  active-entity corruption on decline is the pre-existing DEBUGGING.md F6 known
  issue; F2's Telegram ReadTimeout hit the documented topic-failure contract
  (milestone committed, `internal` reported — `test_entity_update_projection_failure`).

**Live retest of the architecture fixes (read-only C8′).** "Show all entities"
first re-failed on the catalog-invited `'omit'` literal → FIX-2b applied →
second live run bot.log-proved Worker→ToolRegistry→`list_entities(status='',
entity_type='', workspace='')`→`ok`→Worker reply listing all entities. A2′
declined (model) → legacy created Mizuki correctly; C3′ returned an honest
empty for the model's invented `status='done'` filter.

**Regression + gates.** 6 new regression tests
(`test_entity_tools_accept_integer_workspace_id`,
`test_list_entities_accepts_integer_workspace`,
`test_list_entities_empty_optional_strings_mean_all`,
`test_create_entity_unmatched_workspace_name_falls_back_to_active`,
`test_create_entity_unmatched_name_no_active_still_rejected`,
`test_worker_accepts_llama_shaped_workspace_args`) + regression spec WKR-031
(+`tests/test_tool_adapters.py` added to the M4 suite's pytest command). Full
pytest **1569 passing**, selftest 26 PASS / 0 FAIL / 0 WARNING (offline,
excluding the network probe), py_compile + `git diff --check` clean.

**M4 is NOT accepted as production-ready for compound commands with Llama-8b.**
The Worker seam, tool contract, typed referents, and projection are validated
end-to-end (11 genuine Worker successes prove the architecture); Llama's
single-step/decline/arg-extraction limits are model capability, not Worker
architecture. **Next evaluation:** Z.ai native GLM-5.2 (and NVIDIA GLM-5.2
when the upstream hang clears), which should handle the compound chains Llama
cannot. Version NOT bumped; live M4 acceptance for a stronger model still
pending.

### M4.x remediation — CURRENT LIVE OBSERVATIONS (2026-08-11, uncommitted)

Follow-up to the 18-cluster remediation: 13 fresh live failures, all traced to
two generic bugs — the Worker *declined* entity/goal messages (so the LEGACY
EntityManager ran) and the legacy path **fell back NOT_FOUND → the active
entity for a mutation** ("Create Citlali and set her level to83" updated the
active Diona; "Set its deadline to this month end" wrote `target_level` on
Wolf's Gravestone). Fixes are generic + regression-tested, no phrase-patches,
version stays `15.2.0-alpha.14`, M5 not started:

- **NOT_FOUND never mutates the active entity.** `EntityManager._handle_update`
  now only falls back to the active referent when the message carried NO
  explicit name; `_try_extract_update` refuses the active-entity fallback on a
  create-intent lead (`create/make/new/add/…`) + fresh name. The legacy
  Citlali→Diona and Noelle→Wolf's-Gravestone corruptions are pinned closed by
  `tests/test_m4x_safety_invariants.py`.
- **Goal-domain deadline guard.** A message with "deadline"/"due date" is a
  GOAL/TASK operation: `EntityManager._goal_deadline_reply` resolves the goal
  deterministically (explicit title wins, else most-recent via "its"/"the
  goal") and parses the date through `date_parser` (this/next month end, ISO,
  "clear"); it NEVER touches a workspace entity. Ambiguous → asks. The Worker
  prompt rule 14 mirrors it (`update_goal_deadline`, never a character field).
- **Active workspace context preserved for the Worker.** `main.py._worker_request`
  now reads `tg_get_active()[0]` (workspace_id) instead of `[1]` (entity_type
  string "milestone"); `validate_args` normalizes an explicit JSON `null` on an
  optional arg to "no value" (so `workspace:null` → active, not "does not
  accept null"); the Worker prompt now includes an authoritative ACTIVE
  WORKSPACE block. 5-rule workspace-context tests (explicit/active/entity-own/
  none-ask/never-ask-with-active).
- **CREATE vs UPDATE semantics.** `create_entity` on an existing name reports
  "already exists — update it instead" (prompt rule 12 tells the Worker to then
  run `update_entity`); compound create→set→show chains are pinned by tool-level
  tests. `update_entity` on a missing name errors — never creates.
- **Topic NL never hits the task-delete gate.** `main._is_topic_operation`
  ("lock/delete/remove/what-is … <X>'s topic") skips the `delete `/`remove `
  NL-map entry, so "Delete Columbina's topic" reaches the Worker's topic tools
  instead of `delete_task_cmd` → "Usage: /delete <id>".
- **Entity-resolution diagnostic + `/diag`.** Every entity resolution (Worker
  tools AND legacy EntityManager) emits a structured non-secret
  `entity_resolution: …` log line and records into an in-memory
  `ResolutionTrace` (`core/ai/resolution_trace.py`); the admin `/diag` command
  renders it ("Requested: Citlali → Resolved: …"). The trace never holds
  secrets, so `/diag` cannot leak one. Two `/selftest` probes + offline tests.
- **Genshin equipment model boundary documented** in
  `docs/engineering/V15_2_BAKA_BRAIN.md` (§M5 scope): the typed
  `entity_type` foundation is correct and unchanged; a richer equipment schema
  (artifact main/sub stats, weapon refinement, set bonuses) is M5, deliberately
  NOT faked now.

### M4 remediation — the 18-cluster fix list (items 1–20, generic fixes only)

> **Version rule: the next release is a v15.2 M4 PATCH, never M5.** Per the
> owner directive, this remediation DOES NOT start M5: every fix below is a
> generic architecture/contract fix with automated regression tests + multiple
> NL variants + documentation. Nothing is phrase-specific.

**Items shipped in this remediation (consolidated):**

- **item 1/15 — entity-kind resolution.** `core/ai/entity_kinds.py`
  `EntityKindResolver.resolve_for_create` (priority: existing DB row kind →
  explicit → weak hints → None) is deterministic + offline + generic; typed
  retrieval (`list_entities(kind=…)`) returns exactly that kind, `kind=all`
  returns every supported type, and mixed entities never leak across typed
  lists (invariants in `tests/test_worker_orchestration.py`).
- **item 2 — typed retrieval contract.** `list_entities(kind=X)` is filtered
  by the resolved kind; list/kinds invariants pinned by tests.
- **item 3 — compound commands actually execute.** `MAX_TOOL_CALLS` raised 4→6
  with an inline rationale (catalog complete, malformed terminates
  immediately, 5-op chains need ≥5); the real compound fix is the renderer
  (item 12) + honest MAX_STEPS budget note. "Do NOT simply raise" honored: the
  renderer + honest failure lines are the completion path.
- **item 4 — active-entity/pronoun domain safety.** Goal-deadline operations
  resolve through the TYPED referent store (goal domain), never an active
  character; cross-domain pronoun → conflict refusal.
- **item 5 — goal deadline date resolution.** `date_parser` now resolves
  relative ranges deterministically against the IST app clock: "next week",
  "this month end", "next month end" (incl. year rollover), "this/next
  weekend". A bare range NEVER falls through unparsed. The intent engine's
  unconditional "resolved date → ADD_TASK" was the bug: schedule QUERY
  phrasing now falls through to the tier-4 query fallback
  (`_QUERY_KEYWORDS` guard), ADD phrasing keeps the date entity.
- **item 6 — canonical one-topic-per-entity.** `tg_entity_topics` is keyed by
  `(workspace_id, entity_id)`; `tg_get_workspace_entity_topic` falls back to
  legacy `(entity_type, entity_id)` rows; title-normalized dedupe in
  `create_entity` collapses same-title rows (same kind → "already exists";
  different kind on an untyped row → adoption; typed+different → DB priority,
  never a silent re-type).
- **items 7/8/10 — generic TopicProjection tool surface.** Five new Worker
  tools in `core/ai/tool_adapters.py`, all thin wrappers over the SAME
  alpha.13 projection the legacy handlers use: `get_entity_topic` (read-only),
  `ensure_entity_topic` (idempotent, one topic per entity, card only into a
  NEW topic), `set_entity_topic_locked` (durable lock), `delete_entity_topic`
  (DESTRUCTIVE + confirmation_message; refuses a LOCKED topic unless
  `force=true`; never touches the DB entity), `list_entity_topics`.
  `DELETE ENTITY ≠ DELETE TOPIC` pinned by tests.
- **item 9 — topic self-heal repair.** `repair_topics` (groups_app) collapses
  logical duplicates (one normalized title → ONE entity → ONE topic), adopts a
  concrete kind onto the canonical row, reports created/existing/duplicates/
  errors, and is idempotent; exposed as the `/topicrepair` admin command.
- **item 11 — workspace lifecycle symmetry audit.** Audit finding: workspace
  deletion exists only at the DB level — it is NOT reachable from any user
  surface (no command, no Worker tool). The invariant
  `test_workspace_lifecycle_has_no_silent_destructive_path` pins the read+open
  surface and guards that any future delete/archive workspace tool must be
  DESTRUCTIVE with confirmation.
- **items 12/13 — response-format restoration (PRODUCT REGRESSION).**
  `core/ai/worker_render.py` implements the rule "Worker decides WHAT
  happened; the existing BAKA formatter decides HOW it is displayed":
  `render_run_reply` walks the run's step trace and maps each ok ToolResult
  onto the same Telegram-HTML the legacy handlers use (entity cards
  re-fetched from stored fields via a `fetcher`, task/goal/habit/workspace
  lines, HTML-escaped, emoji'd). Failed steps show ⚠️, MAX_STEPS shows only
  what completed, zero-render falls back to the worker's own (escaped) text.
  `main.py` routes Worker replies through it (and through the existing
  confirmation branch for CONFIRMATION_NEEDED).
- **matrix E (topic lifecycle, 20 tests) + matrix H additions.** New
  `tests/test_worker_topics.py` (ensure/get/lock/delete/list + repair +
  render cross-check, real registry + real projection over a recording fake
  client) and `tests/test_worker_render.py` extended. Matrix E/H exposed a
  LATENT renderer bug: 1-arg list renderers (`list_tasks/goals/habits/
  workspaces`) were called with the 3-arg dispatch signature and would
  TypeError on a real Worker listing them — all list renderers now accept
  `(data, user_id, fetcher)`; pinned by
  `test_render_every_list_tool_accepts_the_3arg_dispatch`.
- **selftest probes.** `core/selftest/tests/test_workspace.py` gains "Topic
  Lifecycle Tools" and "Topic Repair" live probes (offline, fake client);
  `/topicrepair` added to `/help → Admin`. 2 new regression specs (WKR-028
  renderer invariant, WKR-029 topic lifecycle) + scenarios WKR-024…027;
  `tests/test_worker_render.py` + `tests/test_worker_topics.py` added to the
  M4 suite's pytest command.

- **documentation + quality gates (final M4 pass).** The AI-category selftest
  probes were brought up to the 30-tool surface: "AI Tool Adapter Registry"
  now asserts the full 30-tool registry (was failing — it still pinned the
  pre-topic 25-tool set), "AI Worker (dormant)" now asserts
  `MAX_TOOL_CALLS=6` + the topic-lifecycle family + `delete_entity_topic`
  DESTRUCTIVE (was failing on the raised cap), and the round-trip probe now
  calls the typed-retrieval contract (`list_entities(kind='all')`, was
  crashing on the M4 REQUIRED-kind change). TESTING.md gained the
  `test_worker_render.py` (18) + `test_worker_topics.py` (20) rows and the
  WKR-001…031 reference; DEBUGGING.md's orphan-topic known issue documents
  the two-place fix (canonical binding prevention + `/topicrepair`); the
  adapter count and MAX_TOOL_CALLS references were corrected across
  DEBUGGING.md + docs/engineering/V15_2_BAKA_BRAIN.md.

**Gates.** Full pytest **1631 passing** (was 1569 before this remediation);
full offline selftest **28 PASS / 0 FAIL / 0 WARNING**; regression registry
117 specs valid, no duplicates; py_compile + `git diff --check` clean. The M4
patch version and live-revalidation matrix are tracked in the final M4
report ([docs/engineering/V15_2_M4_REPORT.md](docs/engineering/V15_2_M4_REPORT.md)).
Live M4 acceptance for compound commands with a stronger model remains
pending (Llama's limits are model capability, not Worker architecture).

## v15.1.0-alpha.13 — Telegram Entity Topic Projection & Backfill (M10)

The topic-projection milestone. Every entity-creation path — `/add`,
natural language ("Create character Arlecchino"), and the new `/topicbackfill`
migration op — now converges on ONE idempotent entity ⇒ Telegram topic ⇒
initial-card contract. NL-created entities get their topic, binding, and
initial card automatically (no manual topic/linking steps), and existing
entities can be backfilled generically without being recreated. **1301 offline
tests passing** (24 projection + 8 entity-manager-projection new), Workspace
self-tests green, regression suite TOP-001…TOP-009 added. Live-Telegram
acceptance pending (manual matrix, `TESTING.md`).

- **`core/workspace/render.py` (new) — the single card/update renderer:**
  `format_entity_card(entity, with_timestamp=False)` renders title / status /
  current fields / IST timestamp from live DB state (never invented); `None`,
  dict, and list field values are skipped; all user content HTML-escaped.
  `format_entity_update(entity, changes)` renders the append-only update
  message (old value shown only when it was actually read pre-update). Chat
  replies and topic cards share this one format.
- **`core/workspace/adapters/projection.py` — initial-card + update contracts:**
  `ensure_entity_topic(..., initial_message=None)` now posts the initial card
  into a **newly created** topic only (idempotent; a card-send failure is
  logged, the topic + binding stay the durable unit). New `post_entity_update`
  appends a minimal HTML update message to an entity's topic, self-healing a
  missing topic first (create + current card, then the update). `send_message`
  gained an explicit `parse_mode` so bot-generated content is HTML while
  user notes stay plain. The binding write after topic creation is retried
  once on a transient DB error so a fresh topic is never orphaned.
- **`core/workspace/groups_app.py` — shared contract + backfill:**
  `create_entity(user_id, ws_id, name, projection)` is the explicit
  create + project + activate contract; `add_entity` delegates to it.
  `backfill_topics(user_id, projection)` generically ensures a topic + live-DB
  initial card for every non-deleted entity in every linked workspace
  (idempotent: existing bindings untouched, re-run creates nothing, unlinked
  workspaces skipped with no Telegram call, soft-deleted excluded,
  per-entity errors collected into the report).
- **`core/ai/entity_manager.py` — Telegram-agnostic projection seam:**
  `process(user_id, text, projection=None)` accepts a duck-typed projection
  (main.py injects the live one; tests inject a fake; no Telegram import).
  `_handle_create` projects the new entity's topic + initial card (best-effort,
  failure reported + repairable via `/topicbackfill`); `_handle_update`
  appends a `post_entity_update` message with the old value captured from the
  pre-update DB read and a fresh (never stale) self-heal card. A projection
  failure never fails or rolls back the DB operation. `_format_entity_card`
  now delegates to `render.py`.
- **`main.py` — wiring + `/topicbackfill`:** EntityManager routing now runs
  `_em.process` via `asyncio.to_thread` with the live projection injected
  (the projection's client bridges to the async loop, so it must not run on
  it). New admin-only `/topicbackfill` command runs
  `WorkspaceGroups.backfill_topics` with the live projection and reports
  created / existing / skipped / errors; registered as a CommandHandler.
- **Docs:** `docs/engineering/M10_TOPIC_BACKFILL.md` plan → implemented;
  `docs/engineering/M13_TOPIC_PROJECTION.md` (new) documents the single
  contract, the seam, the renderer, the topic contracts, and the documented
  consistency model (DB entity durable; topic+binding the durable Telegram
  unit; sends best-effort; persistent binding-write failure → orphan topic,
  recoverable by re-run — no fake atomicity).
- **Tests:** `tests/test_topic_projection.py` (24: idempotency, initial cards
  from DB, escaping, soft-deleted, unlinked skip, partial/permission failure,
  transient vs persistent binding-write failure, cross-workspace same-name,
  duplicate create, long/Unicode names, empty workspace, stale bindings) +
  `tests/test_entity_manager_projection.py` (8: NL create/update project,
  projection failure keeps the DB op, bare reference / retrieve make no
  projection call, self-heal card is fresh). Self-test
  `check_topic_backfill` (Workspace category). Regression suite
  `topic_projection_m10.py` TOP-001…TOP-009.

## v15.1.0-alpha.12 — Conversational Entity References & Active Entity (M1)

The first milestone of the AI-worker roadmap (reference resolution +
active-entity context). The bot now resolves conversational references —
pronouns ("show her", "show him", "show it"), ordinals ("show the first
one", "show the last one"), and bare follow-ups ("what level is she?") —
deterministically against real conversation context, instead of letting the
LLM guess or falling through to unrelated handlers. Suite **1269 passing**
(37 entity-manager + 35 reference-resolution tests). No architectural
redesign; the Workspace OS stays dormant behind its flag.

**M1 objective:** when a user creates, views, or updates an entity, that
entity becomes the *active entity*; the last ordered list shown is
remembered; a later reference resolves deterministically against that
context — never a random guess, never an invented entity, never an LLM call
for the resolution itself.

- **`core/ai/reference_context.py` (new) — per-user conversational memory:**
  `ReferenceContext` tracks the recent-mention stack (last 10) and the last
  ordered list per user. `Referent` identity is `(kind, workspace_id, id)` —
  never a display-name substring — so renames/deletes never alias. State is
  in-memory and ephemeral (mirrors `conversation_state.py`); the DB-backed
  active-entity row remains authoritative.
- **`core/ai/reference_resolver.py` (new) — deterministic resolver:**
  Never calls the LLM and never mutates the database. Precedence: ordinal
  phrase → DB active entity → single recent mention → ambiguity
  (multiple candidates → clarified) → `kind="none"` (caller falls through).
  Stale active entities and list entries are re-validated against live DB
  data so deleted entities are never resurrected. Strong pronouns
  (he/him/she/her/they) and deictic phrases ("this one", "the current one")
  are recognised; weak tokens ("it") need an entity-intent signal to avoid
  hijacking unrelated messages.
- **`core/ai/entity_manager.py` — wired the resolver into `process()`:**
  Resolution runs before the keyword pre-check and the LLM. A resolved
  referent or a bare reference forces the gate open; ambiguity produces a
  clarification prompt instead of a guess; a `kind="none"` reference falls
  through to the normal pipeline untouched.
- **`core/ai/entity_manager.py` — active entity + ordered list tracking:**
  `_activate_entity()` persists the resolved entity to `tg_active_context`
  (create/update/retrieve all activate); `_note_list()` records the ordered
  list whenever a retrieve produces one. Activating a single entity no longer
  wipes the ordered list — "show all → first one → last one" works.
- **`core/ai/entity_manager.py` — deterministic single-field update:**
  `_try_extract_update()` recognises "Sucrose is level 70", "Sucrose is
  level70", "Sucrose's level is 70", "Set Sucrose level to 70", and safe
  active/pronoun forms *without the LLM* — a cheap classifier can no longer
  misroute an obvious update to `retrieve`. Field names come from the
  template specs, never hardcoded.
- **`core/ai/entity_manager.py` — bare-reference retrieve:**
  A message that is exactly a pronoun or deictic phrase ("show her") goes
  straight to the active entity / single recent mention without any AI call.
- **`tests/test_reference_resolution.py` (new) — 35 tests:**
  `TestCreateThenPronoun` (create → show her/him), `TestPronounVariants`,
  `TestOrdinalSelection` (first/second/last), `TestOrdinalViaCognitiveList`,
  `TestOrdinalListPersistence` (list survives activation, replaced on new
  list), `TestFullSentencePronoun` (what level is she?), ambiguity and
  clarification, explicit-name-beats-active precedence, stale/deleted entity
  self-heal, deterministic field updates, workspace isolation. All offline,
  LLM mocked, and asserting bare references never reach the LLM.
- **`core/regression/suites/reference_m1.py` (new) — M1 Quick Release
  regression specs:** REF-001…REF-0xx manual Telegram acceptance tests for
  the Xiao/Kinich/Xilonen/Nefer/Lauma/Columbina matrix (see docs/regression.md).
- **`core/selftest/tests/test_workspace.py` — M1 self-test check:**
  A live probe creates an entity, then resolves "show her" and confirms the
  active entity, without touching Telegram.
- **Docs & UI:** README, ROADMAP, TESTING, DEBUGGING, and
  `docs/engineering/M1_REFERENCE_RESOLUTION.md` document the milestone;
  `docs/engineering/M10_TOPIC_BACKFILL.md` scopes the next workspace-topic
  work. `/help` and `/commands` gained concise reference examples. Version
  bumped to `15.1.0-alpha.12`.

**Known limitations (documented, not fixed here):**
- A strong-pronoun query that is *not* a bare reference and carries no entity
  keyword (e.g. "Can she ascend further?") still falls through to the AI
  chat because the pre-check gate requires a keyword or a bare reference.
  The resolver *would* resolve it; routing is deliberately conservative.
- The deterministic extractor handles single-field updates only; multi-field
  updates still go through the LLM classifier.
- References resolve workspace entities only; task-level references
  ("delete the first one") remain legacy-routed (scheduled for M4).
- Natural-language entity creation still bypasses the Telegram topic
  projection (no topic is created for NL entities) — scoped as M10.

**Remaining M2 work (next milestone):** robust JSON decoding with
clarification instead of silent fall-through, so a misclassified intent
never masquerades as success.

## v15.1.0-alpha.11 — Final Stabilization & Production Readiness

Fixes the routing, retrieval understanding, field mapping, display, logging,
and Telegram UX for the Natural Language Entity Management feature. No new
features — only correctness and consistency. Suite **1234 passing** (37
entity manager tests including 16 new; the prior entry's "73" was a count
error). v15.1.0-alpha.10's alpha.9/alpha.8/alpha.7 functionality is fully
preserved.

- **`main.py` — Routing fix: EntityManager runs before task VIEW handler:**
  "Show all level 90 characters" was intercepted by the task quick-match VIEW
  handler (matches on "show"), never reaching EntityManager → returned "No tasks".
  Root cause: EntityManager block at line 1345 ran AFTER the VIEW query at line 1292.
  Fix: moved the EntityManager block to before the VIEW quick-match, so entity
  queries are processed first, falling through to task views when inapplicable.
- **`core/ai/entity_manager.py` — Entity retrieval rewrite:**
  `_handle_retrieve` no longer delegates entirely to CognitiveEngine, which
  couldn't search by field values. Instead: (1) tries to find a specific entity
  by name → full detail card; (2) field-value filtering via `_filter_entities_by_query`;
  (3) CognitiveEngine recall fallback; (4) complete listing as last resort.
  Fixes "Show Furina", "Who is level 90?", "Show Hydro characters",
  "Who uses Fleuve Cendre Ferryman?", "Show everyone using a sword", etc.
- **`core/ai/entity_manager.py` — `_find_entity` reverse partial matching:**
  Added entity-title-in-query check (e.g. "Show Furina" → entity "Furina").
  Previously only checked if query was a substring of title, not vice versa.
- **`core/ai/entity_manager.py` — `_filter_entities_by_query`:**
  New scoring-based field-to-query matcher: verbatim value match, token overlap,
  numeric proximity. Returns filtered list sorted by relevance or None if no
  field-related query detected, so the caller can fall back to other strategies.
- **`core/ai/entity_manager.py` — `_format_entity_card` / `_format_entity_list`:**
  Clean Telegram HTML formatting for single-entity detail views and
  multi-entity listings. No raw dicts, no developer terminology.
- **`core/ai/entity_manager.py` — Set `_SYSTEM_PROMPT` with ~30 examples:**
  Covers creates, single/multi-field updates, weapon/weapon type, retrieve
  by name, retrieve by field value, retrieve by element/weapon/priority,
  view/open/display variants, plural queries, and explicit "none" examples.
- **`core/ai/entity_manager.py` — Better logging:**
  Every handler now logs: incoming text, workspace, entity match, intent,
  field values, DB operation, response, fallback reason.
- **`core/ai/entity_manager.py` — All responses use `esc()` + HTML tags:**
  All user-provided content is HTML-escaped. Responses use `<b>`, `<code>`,
  `<i>` tags via `fmt.py` helpers for consistent Telegram rendering.
- **`core/workspace/templates/game.py` — Added `weapon` field:**
  `FieldSpec("weapon", "str")` for the specific weapon name (e.g. "Fleuve Cendre
  Ferryman"), distinct from `weapon_type` ("Sword"/"Bow"/"Polearm"). Fixes
  "Furina uses Fleuve Cendre Ferryman" incorrectly setting `weapon_type`.
- **`tests/test_ai_entity_manager.py` — 16 new tests:**
  `TestFindEntityReversePartial` (3), `TestFilterEntitiesByQuery` (5),
  `TestFormatEntityCard` (2), `TestQueryTokens` (4), `TestRetrieveByName` (2).
  Entity manager test count: 37 (was 21).
- **`ui.py` — Updated help card** with View/Filter examples for alpha.11.



Makes the structured entity system from alpha.9 fully usable through natural
language. Users can now create, update, and query entities by chatting
naturally — no commands, no JSON, no database knowledge required.
Also establishes release engineering standards and ships a `/commands`
reference command. Suite **1218 passing** (1197 + 21).

- **`core/ai/entity_manager.py` — `EntityManager` (new):**
  Translates conversational free-text into Entity Engine operations (create,
  update, retrieve) using the injected AI call as a lightweight NL classifier.
  Template-agnostic: the prompt includes the active workspace's field specs so
  the model picks the right field names without hardcoding any domain. A
  keyword pre-check (active workspace + entity-related terms) avoids a useless
  LLM call on every message. Returns `(handled, response)`; `handled=False`
  means the caller falls through to the normal AI pipeline.
- **`main.py` — EntityManager integration in `handle_message`:**
  After state-machine checks and the WORKSPACE pipeline, the free-text handler
  now tries the EntityManager. If the user has an active workspace and the
  text looks entity-related, the LLM classifies it and the Entity Engine
  executes; otherwise the text falls through to the regular AI.
- **`/commands` — interactive command reference dashboard:**
  New `commands_cmd` handler plus `ui.commands_dashboard()` and
  `commands_category_page()` — inline-button navigation with category
  pages, back/home buttons, targeting advanced users.
  Registered as `CommandHandler("commands")` in main.py.
- **`/help` — entity management section:**
  The Workspace section of `help_cards()` now includes natural-language
  entity management examples (create, update, find).
- **BAKA_VERSION bumped** from `15.1.0-alpha.8` to `15.1.0-alpha.10`.
- **Self-test: `check_entity_manager`** — verifies the pre-check logic,
  create-intent routing, and non-entity pass-through using a mocked AI call
  (fully offline).
- **21 new offline tests** in `tests/test_ai_entity_manager.py` covering
  `_extract_json`, create/update/retrieve/none routing, duplicate detection,
  no-active-workspace passthrough, AI failure handling, entity name matching,
  and field info generation.
- **Documentation:** CHANGELOG, ROADMAP, TESTING.md, README all updated.

## v15.1.0-alpha.9 — Structured per-entity fields

Adds **structured, template-defined fields on entities (milestones)** — the
schema foundation that lets a game character carry `level`, `element`,
`materials`, and `talent_domain`, a knowledge concept track `review_count`
and `mastery_level`, or a project phase record `effort_hours` and
`dependencies`. The per-entity fields are integrated into the retrieval layer
and exposed via a new Cognitive Engine tool. Suite **1197 passing** (1185 + 12).

- **`core/workspace/templates/registry.py` — `FieldSpec` consolidated:**
  The `FieldSpec` dataclass (previously copy-pasted across game/knowledge/
  asset/project templates) is now the canonical definition living in the
  registry. Templates declare entity-level fields via a new `entity_fields`
  attribute on `WorkspaceTemplate`. Validation helpers (`validate_entity_fields`,
  `normalize_entity_fields`) operate generically on any template's schema,
  keeping the Entity Engine template-agnostic.
- **`database.py` — `fields TEXT` column on milestones:**
  An additive, idempotent ALTER TABLE (same pattern as every prior migration;
  NULL = no structured fields = backward compatible). New `set_milestone_fields()`
  and `get_milestone_fields()` functions handle JSON serialization.
- **`core/workspace/models.py` — `fields: dict` on `Milestone`:**
  The frozen dataclass gains a `fields` attribute with a `{}` default, parsed
  from the JSON column via the existing `_parse_metadata` helper. `from_row()`
  tolerates pre-migration rows without the column.
- **`core/workspace/engine.py` — `get_fields()`, `set_fields()`, `update_field()`:**
  Three new Entity Engine APIs that validate ownership via the shared
  `_owned_milestone` path, validate field values against the template's entity
  schema, normalize (coerce types, fill defaults), and emit an entity-status
  event on mutation. `get_fields()` returns the Milestone model's built-in
  `fields` attribute (no extra DB roundtrip).
- **Template entity fields per domain:**
  - **Game:** `level`, `element`, `weapon_type`, `talent_domain`, `materials`,
    `ascension_phase`, `target_level`, `priority` — the Genshin "who to farm
    today" data model.
  - **Knowledge:** `difficulty`, `review_count`, `mastery_level`, `source_type`,
    `key_concepts`, `next_review`.
  - **Asset:** `component_type`, `specifications`, `install_date`,
    `lifecycle_status`, `maintenance_interval_days`, `last_service_date`.
  - **Project:** `effort_hours`, `priority`, `dependencies`, `phase_status`,
    `assignee`, `target_date`.
- **`core/ai/workspace_retriever.py` — field values in retrieval corpus:**
  `WorkspaceRetriever._candidates()` now appends scalar field values to each
  milestone's searchable text, so querying by element / level / domain finds
  the right entity — no dedicated tool needed.
- **`tests/` — 12 new tests:**
  Engine field API test suite (CRUD, validation, ownership, coercion, defaults,
  model payload) in `test_workspace_engine.py`; field-aware retrieval test in
  `test_ai_retrieval.py`; a self-test for entity fields in
  `core/selftest/tests/test_workspace.py`.

**Files changed:** `database.py`, `core/workspace/models.py`,
`core/workspace/templates/registry.py`, `core/workspace/templates/__init__.py`,
`core/workspace/templates/game.py`, `core/workspace/templates/knowledge.py`,
`core/workspace/templates/asset.py`, `core/workspace/templates/project.py`,
`core/storage/storage.py`, `core/workspace/repository.py`,
`core/workspace/engine.py`, `core/ai/workspace_retriever.py`,
`core/selftest/tests/test_workspace.py`,
`tests/test_workspace_engine.py`, `tests/test_ai_retrieval.py`,
`CHANGELOG.md`, `ROADMAP.md`.

---

## v15.1.0-alpha.8 — Real retrieval: recall across everything you've stored

Implements the `Retriever` interface that alpha.2 only stubbed. The
Cognitive Engine can now **gather related context from across a workspace
before answering** — so broad, natural questions work without a
feature-specific command per question, moving toward "the AI understands
everything I've stored." Suite **1184 passing** (1174 + 10).

- **`core/ai/workspace_retriever.py` — the first real `Retriever`:**
  `WorkspaceRetriever` ranks everything stored in a user's workspaces
  (entity titles + statuses, and every progress note) by keyword relevance
  (token overlap with per-type weights) and returns scored `Document`s.
  Deterministic, offline, no embeddings/network — a vector/FTS backend can
  replace `retrieve()` later without touching callers. Every result is real
  stored data (grounding preserved: nothing invented).
- **`RecallTool`** wraps the retriever as a first-class tool. The planner
  routes broad/open questions to it — "what do I know about Hu Tao?", "tell
  me about the drone build", "anything on exams" — and the answer is grounded
  in the retrieved items; on no match it says so.
- **Planner updates:** `RuleBasedPlanner` recognises recall phrases and, when
  a question matches no precise tool, **falls back to retrieval** instead of
  guessing; `LLMPlanner` gains `recall` in its tool catalogue. Precise
  questions ("which component is blocked", "how far along") still route to
  their exact tools.
- **DoD:** `/help` documents broad recall; `/selftest` → Workspace gains a
  **Workspace Retrieval** probe; README + ROADMAP updated.

**Tests:** `tests/test_ai_retrieval.py` (10) — cross-entity/note retrieval,
relevance ranking, empty-on-unknown, recall grounding, planner routing +
fallback, and end-to-end broad-question answering that still leaves precise
tools intact; `tests/test_workspace_selftest.py` (+1).

> **Toward the vision:** this is Layer 3's retrieval half. Next: structured
> per-entity fields (talent domain, materials, level) + a GLM-powered
> analysis tool that reasons over retrieved context for daily recommendations.

---

## v15.1.0-alpha.7 — Responsive chat while GLM 5.2 stays the reasoning brain

Follow-up to alpha.6: raising the timeout wasn't enough — a **10-token
liveness probe** to `z-ai/glm-5.2` on NVIDIA NIM still exceeded **30s**,
i.e. that endpoint is genuinely degraded (>30s time-to-first-token), which
no client-side timeout can fix. Using a slow reasoning model for *every*
"hey" is also poor UX regardless. So the hot path is now split from the
reasoning path:

- **New `CHAT_MODEL` (baka_brain.py):** the latency-sensitive chat + intent
  path (`get_baka_response`, every plain message) now uses a **fast model**
  by default (`CHAT_MODEL=fast` → `MODEL_FAST`), so replies are snappy even
  when the main model is slow/degraded. **Deep reasoning (`/think`, `/ws`,
  plans, breakdowns) still uses `MODEL_MAIN`/`MODEL_THINK` = GLM 5.2**, so
  GLM 5.2 remains the reasoning brain. Configurable: `CHAT_MODEL=main` (use
  GLM for chat too, only if it's fast) or `CHAT_MODEL=<any model id>`.
- `call_nvidia` gained a `model=` override (defaults to `MODEL_MAIN`); its
  fallback logging now reports the actual model tried.
- **For fast GLM 5.2 everywhere**, use the GLM-native endpoint
  (`AI_PROVIDER=glm` + `GLM_API_KEY`) instead of NVIDIA NIM's degraded
  `z-ai/glm-5.2`, or set `CHAT_MODEL=meta/llama-3.3-70b-instruct` for a
  faster+capable chat model on NIM.
- Test locks that the hot path never defaults to the slow main model.

---

## v15.1.0-alpha.6 — Fix GLM 5.2 chat timeouts

**Fixes GLM 5.2 timing out on every message.** After alpha.4 made
`z-ai/glm-5.2` the default model, ordinary chat began falling back to
Llama-8b on *every* message with `MAIN model ... unavailable (Request timed
out.)`. Root cause: the fast-chat timeout was **8s**, tuned long ago for the
fast Llama-3.3-70b. GLM 5.2 is a **reasoning** model whose first response
routinely takes >8s even for a trivial "hey", so the 8s cap falsely marked
it dead — the core model was never actually used, and every reply stalled
8s before falling back.

- `baka_brain.py` — the per-workload timeouts are resized for a reasoning
  main model and made **env-overridable**: `TIMEOUT_FAST_CHAT` 8 → **30s**,
  `TIMEOUT_NORMAL_REASONING` 15 → **45s**, `TIMEOUT_LONG_REASONING` 25 →
  **90s**, `TIMEOUT_VISION` 30 → **45s**; the shared client ceiling 30 →
  **120s** (`AI_CLIENT_TIMEOUT`). All chat AI runs off the event loop via
  `run_blocking`, so the longer timeouts never block the bot.
- Tune per provider without code changes, e.g. `TIMEOUT_FAST_CHAT=20` in
  `.env`. The Llama-8b fallback still applies if GLM 5.2 genuinely exceeds
  the (now realistic) limit.
- Test: `tests/test_bugfixes.py` locks in the headroom (fast-chat ≥ 20s, and
  the client ceiling ≥ the longest tier).

---

## v15.1.0-alpha.5 — Bug-database fixes + manual regression coverage

Fixes the genuine defects logged in the bug database (`DBG-####`) during the
2026-07-22 regression run, and grows the manual Quick Release Suite to cover
everything through v15.1. Suite **1172 passing** (1164 + 8).

**Fixes (with automated regression tests, `tests/test_bugfixes.py`):**
- **DBG-0004** — a goal phrased "…this year" now gets a **31-Dec deadline**
  instead of "No deadline". Added period-end parsing to
  `date_parser.parse_date` ("this year" → Dec 31, "by month end" → last day
  of month, "next year", "by end of week" → Sunday), and the GOAL handler
  falls back to it when the AI extracts no date.
- **DBG-0006** — a natural question like "When is my exam?" now finds the
  **exam** memory via keyword search (`search_memories_smart` strips question
  words), instead of matching nothing and **dumping every memory**. On no
  match it says so rather than dumping all.
- **DBG-0001 / DBG-0002** — `/think` no longer gives up with "I had trouble
  thinking…" the moment its model returns empty: `call_think` now **falls
  back once to `MODEL_FAST`** (the reliability model), mirroring
  `call_nvidia`'s MAIN→FAST fallback. (The original reports coincided with a
  degraded model; this makes the path resilient.)
- **DBG-0005** — verified already fixed in v14.26 (`_normalize_memory_key`
  collapses "favorite color"/"favorite_color"); added a lock test.
- Marked DBG-0001/0002/0004/0005/0006 **resolved** in the bug tracker.
  DBG-0007–0010 remain **open as feature requests** (NL project creation,
  manual goal milestones/sub-goals, per-user interval by id, multi-task
  split with per-task times) — not defects, tracked for future milestones.

**Manual regression coverage (Quick Release Suite):** new
`core/regression/suites/workspace_v151.py` — **WSG-001…004** (create
workspace, link group, add entity→topic, photo journal), **WSQ-001/002**
(grounded `/ws` answer, conversation context), **AI-011** (GLM 5.2 default);
plus **GOAL-002** (this-year deadline, DBG-0004) and **MEM-004** (keyword
memory question, DBG-0006). New regression category **"Workspace Groups"**.

---

## v15.1.0-alpha.4 — GLM 5.2 is now the default model on NVIDIA NIM

Completes the alpha.2 GLM 5.2 migration: alpha.2 made GLM 5.2 *available*
but left the default as Llama (opt-in via `.env`), so the running bot still
used Llama. This makes **`z-ai/glm-5.2` the default main + reasoning model
on the `nvidia-nim` provider** — no env change needed; the owner's core
model is now active out of the box.

- `core/ai/provider.py` — the `nvidia-nim` preset's `model_main` and
  `model_reasoning` default to `z-ai/glm-5.2`. `model_fast` stays
  `meta/llama-3.1-8b-instruct` (the reliable **auto-fallback** if glm-5.2 is
  briefly degraded), and `model_vision` stays the Llama vision model
  (glm-5.2 is text-only on NIM). Every value remains env-overridable.
- `baka_brain.py` — matching defensive fallback defaults + updated model
  history note.
- Verify: `/selftest → AI → AI Configuration` now shows
  `nvidia-nim · z-ai/glm-5.2 · …` (offline), and `AI Provider` confirms live
  reachability (a WARNING there means glm-5.2 is degraded and the Llama-8b
  fallback is serving — the bot keeps working).

Docs (README AI table + `.env` note + `docs/ai_system.md`) updated; the
provider-config test now asserts the GLM-5.2 default.

---

## v15.1.0-alpha.3 — Cognitive Engine, Phase 1 (planner & tool orchestration)

Turns BAKA into an assistant that **reasons over the existing Workspace OS**
— answering questions about your projects/games/goals **without new
feature-specific commands** — while being structurally unable to make data
up. Built on the alpha.2 `Tool`/`ToolRegistry` foundation. Suite **1164
passing** (1151 + 13).

**Separation of responsibilities (the design principle, enforced by
construction):** the **Planner reasons** (picks which tool answers a
question), the **Executor executes** (runs it against the Workspace APIs),
and the **tools ground** (every fact comes from real Workspace state). The
model only *routes* — it never writes the factual answer — so it **cannot
hallucinate Workspace data**. The Workspace OS stays the source of truth;
the AI is the reasoning layer only, never the database or the business logic.

- **`core/ai/workspace_tools.py`** — grounded, read-mostly tools over the
  Entity Engine: `list_workspaces`, `workspace_overview`, `list_entities`
  (incl. `status=blocked`), `recent_notes`, and `open_workspace` (the
  conversation-context write). A tool never invents data — when nothing
  exists it says so.
- **`core/ai/cognition.py`** — the Cognitive Engine: `Planner` contract +
  a deterministic `RuleBasedPlanner`, an `execute()` step runner, and
  `CognitiveEngine.handle()` which plans → executes → composes the answer
  **only from tool facts** (empty ⇒ "I don't have that information yet",
  PART 8). Uses the active workspace (`tg_active_context`) so follow-ups
  resolve without renaming it (PART 7: "open Drone" → "which component is
  blocked?").
- **`core/ai/llm_planner.py`** — production `LLMPlanner` over baka_brain that
  emits only a `{"tool","args"}` choice (JSON); any AI failure, bad output,
  or unknown tool falls back to `RuleBasedPlanner`. Injected AI ⇒
  offline-testable, no live LLM in tests.
- **New command `/ws` (alias `/query`):** ask a natural-language question
  about your workspaces — e.g. `/ws which component is blocked in Drone?`.
- **DoD:** `/help` documents `/ws`; `/selftest` → Workspace gains a
  **Cognitive Engine** offline probe (grounded answer from seeded data);
  README + ROADMAP updated.

**Tests:** `tests/test_ai_cognition.py` (12) — grounded tool reads,
planner routing, end-to-end grounding, conversation-context inference,
no-fabrication on absent/unknown data, and the LLM planner's route-only +
safe-fallback behavior; `tests/test_workspace_selftest.py` (+1).

> **Still deferred (later phases):** natural-language routing of *all*
> free-text (Phase 1 uses the explicit `/ws`), write-action planning,
> multi-step plans, memory, and real retrieval. This phase is reasoning +
> tool orchestration over reads.

---

## v15.1.0-alpha.2 — GLM 5.2 migration & AI foundation stabilization

Establishes a reliable, cleanly-abstracted **AI foundation** before the AI
Intelligence Layer is built on top of it. **Intentionally limited scope:**
configuration, reliability, and the retrieval + tool *interfaces* — **no
planner, no tool orchestration** (those are later milestones). Byte-identical
for existing NVIDIA-NIM deployments; suite **1151 passing** (1131 + 20).

- **New `core/ai/` package (foundation, pure/offline-testable):**
  - `provider.py` — env → `ProviderConfig` with named **presets**
    (`nvidia-nim`, `glm`, `local`). Centralizes the provider/model config
    that was scattered through `baka_brain.py`. Resolving an empty/NIM env
    returns the historical defaults **byte-for-byte**.
  - `reliability.py` — a typed error taxonomy (`AITimeout`/`AIRateLimited`/
    `AIUnavailable`/`AIBadRequest`), `classify_status()`, and
    `call_with_retry()` with exponential backoff + jitter (injectable
    sleep/rng, no SDK import).
  - `retrieval.py` — `Retriever` interface + `NullRetriever` (foundation for
    future RAG; no implementation yet).
  - `tools.py` — `Tool` + `ToolSpec` (with `to_openai()`) + `ToolRegistry`
    (registration-based, ADR-012 style; contract only, no orchestration).
- **GLM 5.2 migration = configuration, not code.** Two supported paths:
  set `MODEL_MAIN=z-ai/glm-5.2` on NVIDIA NIM, or `AI_PROVIDER=glm`
  (+ `GLM_API_KEY`) for the GLM-native endpoint. `baka_brain.py` now
  resolves provider/model through `core.ai.provider` behind a guard that
  falls back to the historical NIM defaults, so a config problem can never
  block startup.
- **Local provider abstraction:** a `local` preset (Ollama/LM Studio/vLLM at
  `localhost:11434/v1`, key optional) — swap providers with one env var.
- **DoD:** `/selftest` → AI gains an offline **AI Configuration** probe
  (shows the active provider/model/endpoint at a glance — verify a migration
  without a network call) alongside the live **AI Provider** probe; a new
  **AI-010** regression spec walks a provider migration; README + `.env`
  example + `docs/ai_system.md` document GLM 5.2 and the presets.

**Tests:** `tests/test_ai_foundation.py` (20) — provider presets +
byte-identical NIM defaults + env overrides + key priority; the reliability
retry/backoff/taxonomy; and the retrieval + tool interfaces.

> **Deliberately deferred to later milestones:** the AI planner, tool
> orchestration/execution loop, real retrieval (RAG), memory, and offline
> intelligence. This milestone is the stable base they plug into.

---

## v15.1.0-alpha.1 — Workspace groups: Telegram photo-journal

The **first genuinely usable** Workspace feature, and the one the owner
actually asked for: mirror a project / game / goal to a **private Telegram
forum group**, where **each entity is a topic** and the **photos + notes you
send become a scrollable progress journal**. The database stays the source
of truth; Telegram is the human-readable mirror.

**Architecture (owner directive honored):** the Workspace OS stays
**completely Telegram-agnostic** — no chat/topic id is stored on any
workspace or milestone row. All Telegram bindings live in three new
**adapter-owned** tables (`tg_workspace_bindings`, `tg_entity_topics`,
`tg_active_context`), read only by a new **projection adapter**. Topics are
a *visualization of entities*, created by the adapter for whatever entities
exist; a permanent **General topic** (the group's built-in one) holds
workspace-level notes. These commands are **always available** and are
**not** gated by the `WORKSPACE` orchestrator flag — they only act when the
owner invokes them.

- **New commands (`main.py`):** `/newproject`, `/newgame`, `/newgoal`
  (create + make active), `/workspaces` (list), `/use <name>` (switch),
  `/linkhere` (run inside the group to bind it — enable Topics + add the bot
  as admin), `/add <name>` (add an entity → its own topic), `/open <name>`
  (focus an entity), `/current` (show active context), `/note <text>`
  (text-only progress). **Sending a photo + caption** while a workspace is
  active logs progress to the active entity's topic (or General).
- **New layers:** `core/workspace/adapters/projection.py` (the
  `TelegramProjection`, with an **injected** `TelegramClient` so it imports
  no PTB and is offline-testable), `core/workspace/groups_app.py` (the
  use-case service), a `TelegramBindingStorage` facade, and
  `app.make_projection_client()` (bridges the sync projection to the async
  bot via the running loop, like `make_telegram_sender`).
- **Persistence:** `database.add_attachment`/`get_attachments` (Telegram
  photo `file_id` kept against a note); binding CRUD; `delete_workspace`
  now also clears notes/attachments/bindings.
- **Definition of Done, honored this time:** `/help` gains a **PROJECT
  GROUPS** card; `/selftest` gains a **Workspace** → *Workspace Groups*
  live probe (fake client, no Telegram) alongside *Templates* and *Engine*;
  README documents the feature.

**Tests:** `tests/test_workspace_groups.py` (9) — full flow with a fake
Telegram client (create → link → entity→topic → photo/note routing →
General fallback → unlinked-still-persists → topic reuse → cleanup) and
`tests/test_workspace_selftest.py` (+1). Full suite **1131 passing**
(1121 + 10). Live Telegram posting (forum topic create + send) is verified
by `/selftest` + manual use, per the offline-suite convention.

---

## v15.0-rc.2 — Workspace self-test coverage + DoD tightening

Closes a real gap flagged by the owner: the v15 Workspace OS shipped with
pytest coverage but **no live `/selftest` health check**, so there was no
in-bot way to confirm it works as planned. This release adds that, plus a
hard-delete primitive and a tightened Definition of Done.

- **Live Self-Test checks (`core/selftest/tests/test_workspace.py`)** — a new
  **Workspace** category in `/selftest`: *Workspace Templates* (all 8
  built-in + drop-in templates are registered) and *Workspace Engine* (a
  create → milestone → progress-rollup round-trip against the live DB,
  cleaned up after itself). Auto-discovered by the runner; run `/selftest`
  and "Run All" to see them.
- **`database.delete_workspace(workspace_id, user_id)`** — an additive,
  ownership-scoped hard delete (workspace + its milestones + notes), so the
  self-test round-trip leaves no residue. Nothing else calls it and the
  `WORKSPACE` flag stays OFF, so behavior is unchanged.
- **Definition of Done tightened (CLAUDE.md):** an explicit owner directive
  that **every** command/feature must update README + `/help` + a `/selftest`
  check in the same change-set — and that even backend/flag-gated work needs
  a Self-Test probe and a plain statement that it is dormant + how to enable
  it, never implying a dormant feature is usable.

**Status note (important):** the Workspace OS (engine, timeline, sync, and
the Game/Knowledge/Asset/Project templates) remains **backend-only and
dormant behind `WORKSPACE=off`** — there are **no user-facing Workspace
commands yet**, which is why `/help` shows none. Creating/among workspaces
from Telegram, and any multi-account storage, are **not yet built** and are
the next user-facing milestone.

**Tests:** `tests/test_workspace_selftest.py` (4) — `delete_workspace` hard
delete + ownership, and both self-test checks pass and leave no residue.
Full suite **1121 passing** (1117 + 4). Files: `database.py`,
`core/selftest/tests/test_workspace.py`, `CLAUDE.md`, `main.py` (version),
README, new test file.

---

## v15.0-rc.1 — Release-candidate hardening

The final Release Candidate before v15 Stable: a repository-wide cleanup and
documentation-quality pass making BAKA production-ready as an open-source
project. **Zero Workspace-OS behavior changes, no public import-path
changes**; the suite stays green (**1117 passing** — 1115 + 2 hygiene
tests). Full details: [docs/v15/RC1_AUDIT.md](docs/v15/RC1_AUDIT.md).

- **Documentation consolidation & folder org:** top-level Markdown reduced
  **27 → 13** (permanent docs + standard OSS root files kept at root). v14
  subsystem deep-dives moved to `docs/architecture/` (AI_ROUTER,
  COMMAND_PIPELINE, DATA_FLOW, INTENT_ENGINE, OFFLINE_ENGINE, PLUGIN_SYSTEM,
  STATE_MACHINE); point-in-time v14 design/audit records moved to
  `docs/history/` (DESIGN_SPEC_v14_AUTONOMOUS_CORE, DRG-001, ENGINEERING_AUDIT,
  AI_DIAGNOSTIC_REPORT, RC_v14_ARCHITECTURE_VALIDATION, TEST_CHECKLIST,
  feature_list). All `](…)` links to moved targets were rewritten to correct
  relative paths and verified. Deleted two obsolete files: `REPOSITORY_CLEANUP.md`
  (a completed cleanup checklist) and `VERSION.md` (a stub already superseded
  by this CHANGELOG). Historical records were **relocated, not removed**.
- **Repository cleanup:** removed 7 tracked runtime artifacts
  (`planner{1,2,3}.{out,err}`, `planner.lock`) — provably unreferenced — and
  added `.gitignore` patterns so they cannot return.
- **README rewrite:** production-ready for GitHub — added a Supported
  Workspace Templates table, a Feature Flags section, Testing, Roadmap,
  Contributing, and Acknowledgements; fixed the broken screenshot
  placeholders; refreshed the file-structure and version history.
- **Help system:** added a concise Workspace-mode / `WORKSPACE`-flag note to
  the admin-only help card (operator-facing; no end-user Workspace commands
  exist yet).
- **Testing:** new `tests/test_repo_hygiene.py` (2) asserting no broken
  Markdown links and no tracked runtime artifacts — the RC audit encoded as
  a regression.
- **Code quality:** removed genuinely unused imports from files touched this
  cycle. Pre-existing lint in `main.py`/`baka_brain.py` is documented as a
  post-Stable follow-up rather than churning the behavior-critical hot path.

Files touched: doc moves/deletes across the tree, `.gitignore`, `README.md`,
`ui.py` (help card), new `tests/test_repo_hygiene.py`, new
`docs/v15/RC1_AUDIT.md`, `main.py` (version), ROADMAP.

---

## v15.0-beta.5 — Project Workspace Template

Adds the **Project** Workspace template — the fourth application of the
beta.2 drop-in pattern, validating the extension model against an
**execution-focused domain** (a project driven to completion through a
milestone pipeline). Still **zero OS changes**: no edit to the Entity
Engine, Orchestrator, Timeline, Sync Engine, repositories, models, or the
database schema. This milestone also **takes ownership of the `project`
template** — moving it out of `builtin.py` into its own module, exactly as
beta.2 did for `game` — while preserving its shape so the alpha.3
`ProjectAdapter` bridge is unaffected. Full suite: **1115 passing**
(1092 + 23).

- **One drop-in module (`core/workspace/templates/project.py`)**, same
  shape as the other templates: its **entity/metadata schema** (`FieldSpec`
  list — `status` and `priority` enums, optional free-form `target_date`),
  **validation** (`validate_project_metadata` — enum membership, string
  types), **normalization** (`normalize_project_metadata` — fills enum
  defaults, lowercases/trims enums, trims strings), the registered
  `WorkspaceTemplate` (🛠, sections goals/milestones/tasks/materials/worklog/
  files, the Research→Documentation default milestone pipeline,
  `PROGRESS_MILESTONES`), and a validating
  `create_project_workspace(engine, …)` helper that **normalizes then
  validates** (accepts `'Active'` / `' high '`), seeds the default pipeline
  by default (execution focus), and raises the OS's own
  `EntityValidationError` on bad input.
- **Migration (template ownership moved, shape preserved):** the minimal
  `project` entry was removed from `builtin.py` and re-registered from
  `project.py` with an **identical** icon (🛠), sections, default milestones
  (`Research/Design/Prototype/Testing/Documentation`), and progress model —
  so `templates.get("project").default_milestones` and the alpha.3
  `ProjectAdapter` (which creates `template='project'` workspaces for the
  v14 Project↔Workspace bridge) keep working unchanged. Statuses:
  planning/active/on_hold/completed/cancelled; priorities:
  low/medium/high/critical.
- **Maps project concepts onto the generic entities**: phases/tasks →
  milestones, decisions/worklog → notes, categories → tags, history → the
  append-only Timeline, and **execution progress → the generic
  `PROGRESS_MILESTONES` rollup** (% of milestones done). **No new tables, no
  new entity types.**
- **Registration:** `templates/__init__.py` imports `project`
  (self-registers), alongside `game`, `knowledge`, `asset` — four
  independent drop-in templates now coexist.

**Tests:** `tests/test_workspace_project_template.py` (23) — registration,
the **migration-preserved shape** (icon/sections/default pipeline/progress
model unchanged), the "builtins present" guarantee still holds, coexistence
with the other templates, metadata schema/defaults, validation, enum +
string normalization, the create helper (seeds pipeline / no-seed /
mixed-case enums / rejects bad status), execution progress as the milestone
rollup, the **generic AI orchestrator** driving a project workspace, the
**alpha.3 `ProjectAdapter` bridge still creating project workspaces**
post-migration, the full create → Timeline → Sync pipeline, and an AST
purity check. Files touched: new `project.py`, `templates/builtin.py`
(project entry removed), `templates/__init__.py`, new test file, `main.py`
(version), docs.

---

## v15.0-beta.4 — Asset Workspace Template

Adds the **Asset** Workspace — the third and broadest application of the
beta.2 drop-in pattern: **one reusable template for any owned physical
asset** (vehicles, computers, drones, cameras, robots, manufacturing
equipment, electronics, appliances, tools). There is deliberately **no
per-type template and no hardcoded vehicle/drone/laptop logic** — the asset
kind is just `metadata['asset_type']`. Still **zero OS changes**: no edit to
the Entity Engine, Orchestrator, Timeline, Sync Engine, repositories,
models, or the database schema. Full suite: **1092 passing** (1064 + 28).

- **One drop-in module (`core/workspace/templates/asset.py`)**, same shape
  as `game.py`/`knowledge.py`: its **entity/metadata schema** (`FieldSpec`
  list — required `asset_type` enum; `status` and `condition` enums; and
  optional strings manufacturer/model/serial_number/purchase_date/
  warranty_expiry/location), **validation rules** (`validate_asset_metadata`
  — required asset_type, enum membership, string types; dates free-form),
  **normalization** (`normalize_asset_metadata` — fills enum defaults,
  lowercases/trims enums, trims strings), the registered `WorkspaceTemplate`
  (📦, sections maintenance/service_records/notes/components/history,
  `PROGRESS_MILESTONES`), and a validating
  `create_asset_workspace(engine, …)` helper that **normalizes then
  validates** (so `'Vehicle'` / `' active '` are accepted) and raises the
  OS's own `EntityValidationError` on bad input.
- **Maps asset concepts onto the generic entities** the OS already
  provides: maintenance/inspections/repairs/upgrades → milestones,
  service records/observations/issues/config → notes,
  categories/components → tags, ownership + maintenance history → the
  append-only Timeline, and **maintenance/lifecycle completion → the
  generic `PROGRESS_MILESTONES` rollup** (% of maintenance milestones done).
  **No new tables, no new entity types.** Enums: types
  vehicle/computer/drone/robot/equipment/electronics/appliance/tool/other;
  statuses active/maintenance/stored/retired/sold; conditions
  excellent/good/fair/poor.
- **Registration:** `templates/__init__.py` imports `asset`
  (self-registers), alongside `game` and `knowledge` — three independent
  drop-in templates now coexist. The engine/orchestrator/sync/timeline/
  builtin templates are untouched.

**Tests:** `tests/test_workspace_asset_template.py` (28) — registration &
discovery, coexistence with Game + Knowledge, the one-template-covers-all
guarantee, metadata schema/defaults, validation (required/type/enum/string,
free-form dates), normalization (enum lowercasing + string trimming +
defaults), the create helper (valid, mixed-case enums, rejects
missing/unknown asset_type), the generic-engine proof points (maintenance
as milestones, progress as maintenance completion), the **generic AI
orchestrator** driving an asset workspace (add maintenance milestone / add
service note / create), the full create → Timeline → Sync pipeline, and an
AST check that `asset.py` imports only the public registry + error surface.
Files touched: new `asset.py`, `templates/__init__.py`, new test file,
`main.py` (version), docs.

---

## v15.0-beta.3 — Knowledge Workspace Template

Adds the **Knowledge** Workspace — a second application of the beta.2
pattern, this time for an **educational/knowledge domain** ("learn a
subject, capture what you know, track your mastery"). It is the second
proof that a full Workspace drops in as **one module with zero OS
changes**: no edit to the Entity Engine, Orchestrator, Timeline, Sync
Engine, repositories, models, or the database schema. Full suite:
**1064 passing** (1044 + 20).

- **One drop-in module (`core/workspace/templates/knowledge.py`)** with the
  whole template, structurally identical to `game.py`: its
  **entity/metadata schema** (`FieldSpec` list — domain, source, status,
  items_reviewed, mastery `progress`), **validation rules**
  (`validate_knowledge_metadata` — required/type/enum/range),
  `normalize_knowledge_metadata` (defaults + int coercion), the registered
  `WorkspaceTemplate` (🧠, sections concepts/sources/notes/reviews/progress,
  `PROGRESS_MANUAL`), and a validating
  `create_knowledge_workspace(engine, …)` helper that raises the OS's own
  `EntityValidationError` on bad input.
- **Maps knowledge concepts onto the generic entities** the OS already
  provides: concepts/topics → milestones, sources/notes → notes, mastery% →
  the workspace `metadata` (read by the engine's `PROGRESS_MANUAL` model).
  **No new tables, no new entity types.** Learning lifecycle statuses:
  exploring → learning → reviewing → mastered → archived.
- **Registration:** `templates/__init__.py` imports `knowledge`
  (self-registers on import), alongside `game`. The
  engine/orchestrator/sync/timeline/builtin templates are untouched, and
  the two drop-in templates coexist without collision.

**Tests:** `tests/test_workspace_knowledge_template.py` (20) — registration
& discovery (including coexistence with the game template), metadata
schema/defaults, validation (status/items/progress/type/bool/str),
normalization, the validating create helper (valid + rejects bad
metadata), and the proof points: mastery via the generic manual model,
concepts as generic milestones, the full create → Timeline → Sync pipeline
for a knowledge workspace, and an AST check that `knowledge.py` imports
only the public registry + error surface (never the OS internals). Files
touched: new `knowledge.py`, `templates/__init__.py`, new test file,
`main.py` (version), docs.

---

## v15.0-beta.2 — Game Workspace Template (reference implementation)

Adds the **Game** Workspace as the **reference implementation** for new
Workspace types. The point is not a game tracker — it's proof that an
entire new Workspace can be added **without changing the Workspace OS**:
no edit to the Entity Engine, Orchestrator, Timeline, Sync Engine,
repositories, models, or the database schema. It plugs in only through the
existing extension points. Full suite: **1044 passing** (1026 + 18).

- **One drop-in module (`core/workspace/templates/game.py`)** containing
  the whole template: its **entity/metadata schema** (`FieldSpec` list —
  platform, status, hours_played, completion `progress`), **validation
  rules** (`validate_game_metadata` — required/type/enum/range),
  `normalize_game_metadata` (defaults + int coercion), the registered
  `WorkspaceTemplate` (🎮, sections objectives/sessions/notes/progress,
  `PROGRESS_MANUAL`), and a validating `create_game_workspace(engine, …)`
  helper that raises the OS's own `EntityValidationError` on bad input.
- **Maps game concepts onto the generic entities** the OS already
  provides: objectives → milestones, sessions/notes → notes, completion% →
  the workspace `metadata` (read by the engine's `PROGRESS_MANUAL` model).
  **No new tables, no new entity types.**
- **Registration:** `templates/__init__.py` imports `game` (self-registers
  on import); the minimal placeholder `game` entry was removed from
  `builtin.py`. The engine/orchestrator/sync/timeline are untouched.

**Tests:** `tests/test_workspace_game_template.py` (18) — registration &
discovery, metadata schema/defaults, validation (status/hours/progress/
type/bool), normalization, the validating create helper (valid + rejects
bad metadata), and the proof points: game progress via the generic manual
model, objectives as generic milestones, the full
create → Timeline → Sync pipeline for a game workspace, and an AST check
that `game.py` imports only the public registry + error surface (never the
OS internals). Files touched: new `game.py`, `templates/__init__.py`,
`templates/builtin.py` (placeholder removed), new test file, `main.py`
(version), docs.

---

## v15.0-beta.1 — Workspace Activation & Production Wiring

**Integration only** — the completed v15 backend (alpha.1–7) is wired into
the running application, with **no architecture, engine, repository, or
schema changes**. The whole thing stays behind `WORKSPACE`: with the flag
**OFF the bot is byte-identical to v14.26** (the guarded branch is skipped
and no worker is registered), and with it **ON the Workspace OS pipeline
becomes active**. All 1008 prior tests stay green; **1026 passing** total
(+18 integration).

- **Feature-flag activation (main.py):** a single guarded branch in the
  free-text handler — `if feature_flags.WORKSPACE:` route through the
  Workspace OS, else the existing production path. A recognized workspace
  utterance is handled and returns; anything unrecognized falls through to
  Legacy (no duplicate command implementations). A pipeline exception is
  caught and also falls through.
- **Telegram handler integration (`core/workspace/app.py`
  `process_message`):** message → Interpreter → Orchestrator → Entity
  Engine → Timeline (→ Sync). Manages a small confirm flow ("reply yes/no"
  for irreversible actions) and tracks the last-touched workspace so
  follow-ups need no explicit "in <ws>". Returns `(handled, reply)`;
  `handled=False` defers to Legacy.
- **Background worker + scheduler wiring:** `SyncWorker.run_once` drains
  the sync outbox (enqueue backlog + retrying drain) for each user; a
  failed user never aborts the pass and it no-ops once stopped (clean
  shutdown). `register_workers(application)` registers a repeating job on
  the **existing** `job_queue` **only when the flag is ON**; the job drains
  off the event loop (`asyncio.to_thread`) so a slow send never blocks the
  bot.
- **Production Telegram sender (`make_telegram_sender`):** a synchronous
  sender that safely calls the async bot from the worker thread via
  `run_coroutine_threadsafe`, injected into the (unchanged) Telegram
  adapter. The Sync Engine stays Telegram-independent.
- **LLM Interpreter (`core/workspace/llm_interpreter.py`):** the production
  `Interpreter`, using `baka_brain` (imported lazily) to turn an utterance
  into a JSON `Proposal`. It never writes and cannot bypass the engine
  (proposal only), and **falls back cleanly to `RuleBasedInterpreter`** on
  any AI failure (timeout/429/bad JSON/unknown action).
  `RuleBasedInterpreter` remains the default for tests.

**Tests:** `tests/test_workspace_integration.py` (18) — flag OFF/ON
(worker registration), message→proposal→execution (create + active-
workspace follow-up, confirm/cancel), Timeline recording, Sync delivery,
AI fallback (valid JSON / AI error / garbage / unknown action / full
failing-AI pipeline), worker lifecycle + graceful shutdown + per-user
error tolerance, and the sync→async production sender bridge (no live bot).
Files touched: `main.py` (import + guarded handler branch + guarded worker
registration + version), new `core/workspace/{app,llm_interpreter}.py`,
`core/workspace/__init__.py`, new test file, docs.

---

## v15.0-alpha.7 — AI Workspace Orchestrator

The **generic** orchestration layer (docs/v15/AWOD.md) that turns a
natural-language utterance into a validated Entity Engine operation. It
runs the AWOD resolver pipeline — interpret → select workspace → resolve
entity → plan → safety gate → apply — over a fixed set of **generic**
actions mapped to generic engine calls. **No template-specific logic**
(no book/game/project branches), no new Telegram/UI/commands/templates, no
automatic summaries, no conversational-memory changes. Every future
Workspace template reuses this same orchestration unchanged. Gated behind
`WORKSPACE` (default OFF); nothing constructs it, so the bot stays
byte-identical to alpha.6/v14.26. Full suite: **1008 passing** (978 + 30).

- **AI proposes, engine disposes:** the AI model is injected as an
  `Interpreter` (`interpret(utterance, ctx) -> Proposal`); the orchestrator
  **never calls the live LLM/NIM**, so it stays offline-testable. It
  re-resolves and re-validates every proposal against real data and applies
  it through the Entity Engine (which enforces ownership, lifecycle, and
  emits events). A deterministic `RuleBasedInterpreter` ships as the
  default/test interpreter — a generic verb→action parser; an LLM-backed
  interpreter plugs into the same contract in a later, user-facing phase.
- **Resolvers:** workspace selection (explicit title → exact/fuzzy match;
  else the active workspace; else clarify — with options on ambiguity);
  milestone resolution within the workspace (0/many → clarify with
  options).
- **Safety gate (AWOD §4):** irreversible actions (archive workspace,
  archive/delete milestone) return `NEEDS_CONFIRMATION` until `confirm=True`;
  reversible ones (create, rename, add milestone/note, complete milestone)
  apply directly. Low-confidence/unknown proposals return
  `NEEDS_CLARIFICATION` ("rephrase"). Engine refusals surface as
  `REJECTED`/`FAILED`, never a crash.
- **Generic actions:** create/rename/archive/complete workspace;
  add/complete/archive/delete milestone; add note. `OrchestratorResult`
  carries a status (`APPLIED`/`NEEDS_CONFIRMATION`/`NEEDS_CLARIFICATION`/
  `REJECTED`/`FAILED`), a message, and the affected entity.

**Tests:** `tests/test_workspace_orchestrator.py` (30) — rule-based parsing
(incl. the "in <workspace>, …" prefix), create end-to-end, workspace/entity
resolution and clarification (unknown/ambiguous → options), the safety gate
(confirm applies; reversible applies directly), graceful degradation,
AI-proposes/engine-validates (bad proposal → REJECTED), ownership
enforcement, template-agnostic behaviour across generic/project/book/game,
and the full orchestrator → engine → Timeline cascade. Files touched: new
`core/workspace/orchestrator.py`, `core/workspace/__init__.py`, new test
file, `main.py` (version), docs.

---

## v15.0-alpha.6 — Synchronization Engine + Telegram Adapter

Reliable **outbound synchronization** via the TWID outbox pattern
(docs/v15/TWID.md): a durable `sync_outbox`, a pluggable `SyncAdapter`
contract, a `SyncEngine` that drains the outbox with idempotency + bounded
retries + error capture, and **Telegram as the first adapter**. Solely
outbound sync — **no AI Orchestrator, no workspace summaries, no
user-facing controls**, and it is **not wired into the bot's job_queue**.
The Telegram adapter delivers through an *injected sender callable* and
never imports python-telegram-bot, so the offline suite stays
Telegram-free. Gated behind `WORKSPACE` (default OFF); nothing constructs
it, so the bot stays byte-identical to alpha.5/v14.26. Full suite: **978
passing** (961 + 17).

- **Schema (database.py, additive):** `sync_outbox` (id, user_id,
  workspace_id, timeline_event_id, adapter, target_id, payload, status,
  attempts, last_error, created_at, sent_at, ref) + two indexes. Functions:
  `enqueue_sync`, `sync_outbox_exists` (idempotency), `get_pending_sync`
  (oldest-first drain order), `mark_sync_sent`/`mark_sync_retry`/
  `mark_sync_failed`, `sync_remaining_for_event`, `count_sync`. Added to
  `REQUIRED_TABLES`; `reset_everything` clears it.
- **Storage integration:** `SyncStorage` facade domain (`storage.sync`).
- **Repository:** `SyncOutboxRepository` (tuples → `SyncItem`).
- **Sync Engine (`sync.py`):** `SyncAdapter` ABC (`render` + `deliver`),
  `SyncResult`, `SyncItem`. `SyncEngine.enqueue(event)` creates one
  outbox row per registered adapter (idempotent via `sync_outbox_exists`);
  `enqueue_backlog(user_id)` reconciles all unsynced timeline events;
  `drain(user_id)` delivers oldest-first — success → `sent` (+ delivered
  ref) and, once every adapter delivered an event, the timeline event is
  stamped `synced_at`; failure → retry (kept pending) until `max_attempts`
  then `failed`; unexpected adapter exceptions are caught (offline-
  tolerant). `sync()` = enqueue backlog + drain.
- **Telegram Adapter (`adapters/telegram.py`):** renders a timeline event
  to Telegram HTML via `fmt.b` (escaped) and delivers through an injected
  `sender(user_id, text, target_id)`. No sender → clean failure, never a
  crash. Real bot wiring is a later, user-facing step.

**Tests:** `tests/test_workspace_sync.py` (17) — schema, DB layer
(enqueue/pending/mark/idempotency/reset), Telegram adapter (escaping,
no-sender failure, delivery), engine (idempotent enqueue, drain→sent with
timeline synced, retry-then-succeed, give-up-after-max, exception
tolerance, no re-delivery of sent rows), multi-adapter enqueue, and the
full Entity Engine → Timeline → Sync pipeline. Files touched:
`database.py`, `core/storage/storage.py`, new
`core/workspace/{sync,adapters/…}`, `core/workspace/__init__.py`, new test
file, `main.py` (version), docs.

---

## v15.0-alpha.5 — Timeline Engine

The **Knowledge Timeline** (docs/v15/KTD.md): append-only, persistent
event infrastructure that subscribes to the Entity Engine's event hook and
records one immutable row per mutation. **Purely persistence** — **no
Telegram, no AI, and no aggregate/journal summaries** (the per-event
`summary` is a short factual label the schema requires; the AI-written
roll-up reports are out of scope). Telegram Sync (alpha.6) and the AI
Orchestrator (alpha.7) become subscribers later. Gated behind `WORKSPACE`
(default OFF); with no subscriber attached the engine's default hook is a
no-op, so the bot stays byte-identical to alpha.4/v14.26. Full suite:
**961 passing** (948 + 13).

- **Event upgrade (`events.py`):** the engine's `on_event` seam now carries
  a self-contained `EntityEvent` (event_type, entity_type, user_id,
  workspace_id, entity_id, entity, source) instead of three loose args. A
  `Milestone`/`Note` model has no `user_id`, but the engine knows it at
  emit time and stamps it onto the event — so a subscriber can persist a
  user-scoped row without reaching back into the engine. Engine `_emit`
  call sites updated to thread `user_id` (seeded milestones marked
  `source='system'`).
- **Schema (database.py, additive):** `timeline_events` (id, user_id,
  workspace_id, entity_type, entity_id, event_type, summary, payload,
  source, created_at, synced_at) + two indexes. Append-only:
  `add_timeline_event` inserts; `get_timeline`/`get_entity_timeline`/
  `get_unsynced_timeline`/`count_timeline` read; only `mark_timeline_synced`
  updates (a single `synced_at` stamp, for alpha.6). Added to
  `REQUIRED_TABLES`; `reset_everything` clears it.
- **Storage integration:** `TimelineStorage` facade domain (`storage.timeline`).
- **Repository:** `TimelineRepository` (tuples → `TimelineEvent` models).
- **Timeline Engine (`timeline.py`):** `TimelineEngine.record` is the event
  hook — attach as `EntityEngine(on_event=TimelineEngine().record)` and
  every mutation is persisted, with a deterministic per-event summary and a
  small payload snapshot. Reads: `timeline()`, `entity_history()`, `count()`.

**Tests:** `tests/test_workspace_timeline.py` (13) — schema, append-only DB
layer (add/get/entity-history/unsynced/mark-synced), facade delegation,
repository mapping, and the integration proof: Entity Engine + Timeline
subscriber records correct user-scoped rows (incl. a milestone event
carrying user_id/workspace_id/entity_id despite the model lacking user_id),
pre-delete snapshot on delete, `source='system'` for seeded milestones, and
flag-OFF neutrality (default engine records nothing). The alpha.2/alpha.4
engine test helpers were updated for the `EntityEvent` hook. Files touched:
`database.py`, `core/workspace/{events,engine,timeline,__init__}.py`,
`core/storage/storage.py`, new test file, `tests/test_workspace_engine.py`,
`tests/test_workspace_milestone_mgmt.py`, `main.py` (version), docs.

---

## v15.0-alpha.4 — Milestone Management (archive + soft-delete)

Milestone management for the Entity Engine: **archive** and **soft-delete**
(the CRUD + lifecycle already shipped in alpha.2). Backend only — **no
Telegram, no AI**, and **no Timeline consumer**: the operations emit
through the existing Entity Engine event hook (still the default no-op
sink), which the alpha.5 Timeline Engine will subscribe to. Gated behind
`WORKSPACE` (default OFF); the new columns ship empty, so the bot stays
byte-identical to v14.26. Full suite: **948 passing** (934 + 14).

- **Schema (database.py, additive):** `milestones` gains `archived_at`
  and `deleted_at` (nullable). `get_milestone()`/`get_milestones()` now
  exclude soft-deleted rows (and, by default, archived ones —
  `include_archived=True` to see them). `count_milestones()` excludes both
  from the progress denominator (an archived/deleted milestone is no
  longer part of the plan). New `soft_delete_milestone()` stamps
  `deleted_at` and **never DROPs the row** (retained for recovery/audit).
  `update_milestone()` stamps `archived_at` on status→archived.
- **Lifecycle (`lifecycle.py`):** `archived` joins the milestone state
  machine — reachable from any active state, `archived → todo` restores.
  Soft-delete is orthogonal (a `deleted_at` flag), not a lifecycle move.
- **Engine (`engine.py`):** `archive_milestone()` (lifecycle-validated,
  no-op if already archived, emits `milestone.archived`) and
  `delete_milestone()` (ownership-checked soft delete, raises
  `EntityNotFound` on a double delete, emits `milestone.deleted` with the
  pre-delete snapshot). `list_milestones()` gained `include_archived`.
- **Facade / Repository:** `MilestoneStorage.soft_delete` +
  `list_for(include_archived=…)`; matching `WorkspaceRepository` methods.
- **Model:** `Milestone` gains `archived_at`/`deleted_at` + `is_archived`;
  `MS_ARCHIVED` constant. `from_row` tolerates old 9-column rows.

**Tests:** `tests/test_workspace_milestone_mgmt.py` (14) — schema,
archive/restore lifecycle, archive & soft-delete hide from listings and
progress, row retention (soft delete never DROPs), double-delete error,
ownership, event emission, flag-OFF column neutrality. The alpha.2
`test_lifecycle_states_complete` was updated for the new `archived` state.
Files touched: `database.py`, `core/workspace/{models,lifecycle,engine,
repository}.py`, `core/storage/storage.py`, new test file,
`tests/test_workspace_engine.py`, `main.py` (version), docs.

---

## v15.0-alpha.3 — Project Integration

Proves the Workspace architecture can **transparently replace the v14
Project backend**. Backend integration only — **no Milestones, no
Timeline, no Telegram sync, no AI**, and no user-facing wiring: the
production `/projects` handlers are untouched. Still gated behind
`WORKSPACE` (default OFF), so with the flag off the bot is byte-identical
to v14.26. Full suite: **934 passing** (920 + 14 integration tests).

A v14 "project" is a goal with materials/worklog. This milestone routes it
through the Workspace layer by making a `template='project'` workspace its
container, linked to the goal via `goals.workspace_id`. **No project data
is moved** — materials/worklog/progress are read and written through the
existing v14 project functions, keyed by the goal the workspace resolves
to (WED §8, MIGRATION.md §3). Same data, new lens.

- **Bridge (database.py):** `get_workspace_goal_id()` /
  `get_goal_workspace_id()` / `set_goal_workspace()` link a project's goal
  and its workspace both ways; `verify_project_migration()` reports
  unmigrated projects and orphan project-workspaces (`ok` = the
  transparent-replacement proof). All additive, uncalled while the flag is
  OFF.
- **Repository / Facade updates:** `WorkspaceStorage` and
  `WorkspaceRepository` gain the bridge methods (`goal_id_for`,
  `workspace_id_for_goal`, `link_goal`, `verify_migration`).
- **`ProjectAdapter` (`core/workspace/project_adapter.py`):** serves
  project operations (create, list, overview, materials, worklog,
  progress) through the Workspace layer, delegating project data to the
  v14 functions. Creates project workspaces with **`seed_milestones=
  False`** and reports **project progress via the v14 materials/worklog
  computation** (not a milestone rollup) — so a project routed through the
  workspace layer returns identical values to the legacy path.
  `use_workspace_projects()` reflects the flag for the later handler swap.

**Integration tests** (`tests/test_workspace_project_integration.py`, 14):
flag-OFF legacy path unchanged; project-via-workspace == legacy project
(materials/worklog/progress/overview equivalence); ownership scoping;
migration round-trip + `verify_project_migration` correctness &
idempotency; no data moved. Files touched: `database.py`,
`core/storage/storage.py`, `core/workspace/repository.py`, new
`project_adapter.py`, `__init__.py`, the new test file, `main.py`
(version), docs.

---

## v15.0-alpha.2 — Workspace Entity Engine

The reusable **Entity Engine** every future template will depend on.
Backend infrastructure only — as with alpha.1, **no user-facing
functionality: no commands, no Telegram, no UI, no AI.** Still fully
dormant behind `WORKSPACE=off` (nothing in v14 constructs it), so the bot
remains byte-identical to v14.26. Full suite: **920 passing** (892 + 28).

The engine is the single choke-point through which entity mutations flow,
adding the three things the raw Repository (alpha.1) does not:

- **Ownership + input validation** — every operation is scoped to a
  `user_id` and refuses with typed errors (`EntityNotFound` /
  `EntityValidationError`) rather than silently touching another user's
  data or writing junk. Milestone/note ownership is inherited from the
  parent workspace.
- **Lifecycle enforcement** — status changes go through declarative state
  machines (`lifecycle.py`): `InvalidTransition` on an illegal move, a
  silent no-op when already in the target state. Workspaces
  (active↔done, →archived, archived→active) and milestones
  (todo→in_progress→done, blocked, reopen).
- **An event seam** — every mutation calls an `on_event(event_type,
  entity_type, entity)` hook; the default is a no-op. This is where the
  Knowledge Timeline (KTD, a later phase) plugs in, so "if a mutation
  doesn't emit an event, it's a bug" becomes true without the engine
  changing.

Template-agnostic by construction: it reads a workspace's `template` key
and asks the Template registry for defaults + the progress model, so
adding a template never means editing the engine (Open/Closed, like
ADR-012's ActionRegistry).

**New files (`core/workspace/`):** `errors.py` (typed engine exceptions),
`lifecycle.py` (declarative state machines), `engine.py` (`EntityEngine`:
workspace/milestone/note CRUD + transitions + progress rollup).

**Refactor (behaviour-preserving):** `service.py`'s `WorkspaceService` now
composes an `EntityEngine` and delegates create/progress/completion to it
instead of hitting the Repository directly — the engine is wired in, not
dead scaffolding. `complete_milestone(user_id, milestone_id)` gained a
`user_id` (ownership-checked); the one alpha.1 test calling it was updated.

**Tests:** `tests/test_workspace_engine.py` — 28 tests (lifecycle state
machines, validation, ownership scoping across two users, workspace &
milestone transitions incl. illegal/no-op/reopen, notes, event emissions,
progress models). Files touched: new `errors.py`/`lifecycle.py`/
`engine.py`, `service.py`, `__init__.py`, `tests/test_workspace_engine.py`,
`tests/test_workspace_foundation.py` (one call updated), `main.py`
(version), docs.

---

## v15.0-alpha.1 — Workspace Foundation

The first **code** milestone of the Workspace OS (designed in
[docs/v15/](docs/v15/)). Ships the *infrastructure only* that later phases
(Telegram sync, Knowledge Timeline, AI Orchestrator) build upon — **no
user-facing Workspace features, no handlers, no UI, no Telegram/dashboard
changes.** Everything is gated behind the new `WORKSPACE` feature flag
(default **OFF**), so with the flag off the bot behaves **byte-identically
to v14.26**: the full 892-test pytest suite passes, no database needs
manual migration, and the new tables ship empty and unread — exactly how
the v14 Offline-Engine flags/tables shipped ahead of their consumers.

**Schema (database.py, additive & idempotent — MIGRATION.md §4):**
- New tables: `workspaces`, `milestones`, `notes`, `attachments`, `tags`,
  `entity_tags` (via `_init_workspace_tables()`, wired into `init_db()`).
- New nullable FK columns (NULL = Inbox/unassigned): `tasks.workspace_id`,
  `tasks.milestone_id`, `goals.workspace_id`, `memories.workspace_id`.
- `SCHEMA_VERSION` → 2; the six tables added to `REQUIRED_TABLES` so
  `verify_schema_integrity()` covers them.
- Workspace/Milestone/Note CRUD + migration helpers
  (`ensure_default_workspace()`, `migrate_projects_to_workspaces()` —
  backfill-never-move, idempotent).
- `reset_everything()` extended to also wipe workspace data (same
  anti-orphan / ID-reuse guard as project_materials).

**Layers (`core/workspace/`, `core/storage/`):**
- Storage Facade: `WorkspaceStorage` / `MilestoneStorage` / `NoteStorage`
  (thin one-line delegations), wired into `Storage()`.
- `models.py` — frozen `Workspace` / `Milestone` / `Note` dataclasses
  with `from_row()` mappers.
- `repository.py` — `WorkspaceRepository`: typed CRUD over the facade
  (tuples → models), no business logic.
- `service.py` — `WorkspaceService`: template application, progress
  rollup, flag-gated `bootstrap()` (no-op while `WORKSPACE` off).
- `templates/` — `WorkspaceTemplate` registry (composition, not
  inheritance) + 6 built-ins (generic, project, book, course, research,
  game). Adding a template is one `register()` call; the engine never
  changes (Open/Closed) — same pattern as ADR-012's ActionRegistry.

**Feature flag:** `core/feature_flags.py` gains `WORKSPACE` (default OFF).

**Tests:** `tests/test_workspace_foundation.py` — 32 tests covering
schema, CRUD, facade delegation, repository mapping, service (template
seeding, all progress models, flag gating), migration idempotency &
no-data-loss, and the template registry. Files touched: `database.py`,
`core/feature_flags.py`, `core/storage/storage.py`, new `core/workspace/`
package, `tests/test_workspace_foundation.py`, `tests/test_database.py`
(reset test extended), `main.py` (version), docs.

---

## v14.26 — Bug fix: memory duplicate keys

Fixes the one genuine code defect surfaced by the manual regression run
(MEM-002). The other reported items are AI-provider degradation
(AI-001/002 timeouts, TASK-007 multi-task split, MEM-003 recall) or
feature requests (GOAL-001 deadline inference, PROJ-001/003 project
creation & sub-goals, SET-003 per-id intervals) — neither a code bug;
see DEBUGGING/summary.

- **`database.py`** — memory keys are now compared via a normalized
  form (`_normalize_memory_key`: lowercased, `_`/`-`/whitespace →
  single space). `save_memory` matches on it, so "favorite color" and
  "favorite_color" **overwrite instead of duplicating**, and any
  pre-existing duplicate rows collapse on the next save; `get_memory`
  and `delete_memory` match the same way (robust to old spellings). The
  stored key text is unchanged, so existing memories keep working.
- **`tests/test_database.py`** — added a separator-variant test
  (overwrite + one row + delete-either-spelling).

Small and isolated: only the three memory functions changed. Suite:
**860 tests** (859 + 1). `BAKA_VERSION` → 14.26.

---

## v14.25 — Developer Center: Run Tests (manual regression runner)

The one QA feature actually needed to test BAKA today — a simple
interactive runner in the Developer Center. **Reuses everything: the
existing Quick Suite specs (`core/regression`), the `dev:*` menu
(v14.22), and `debug_system.report_bug` for the FAIL→bug step.** No new
architecture, no statistics, no history, no separate runner package.

- **`/debug → 🧯 Run Tests`** (admin-only): walks the Quick Suite (44
  tests) one at a time — each shows objective, steps, expected result
  with **✅ Pass / ❌ Fail / ⏭ Skip**. On **Fail** it prompts for a
  short note and logs a bug (`DBG-####`), then continues. Ends with a
  summary (passed/failed/skipped + the bug ids created).
- **`ui.py`** — 3 pure builders (`dev_run_test_card`,
  `dev_run_fail_prompt`, `dev_run_summary_card`) + a 🧯 Run Tests button
  on the Dev menu.
- **`main.py`** — a small in-memory session (`_test_runs`), a `dev:run:*`
  callback branch, and one early-return in `handle_message` to capture
  the FAIL note (checked before intent routing so it can't be swallowed).
  Two helpers (`_quick_suite_tests`, `_test_run_view`).
- `BAKA_VERSION` 14.19 → 14.25 (keeps `/help` + `/selftest` current,
  which DOC-002 checks).
- **Docs synced (Definition of Done):** `/help` moved `debug` into the
  admin section as the **Developer Center** (Self Test · Run Tests ·
  toggle) — it's admin-only now, so it no longer misleads non-admins in
  the general list — and added `claimadmin`/`myid` (previously
  undocumented); `/start` gained a first-run `/claimadmin` hint; README
  updated (version, a Developer Center section, and a "what's new
  v14.21→v14.25" note). **No new user commands were added in this
  range** — the additions are owner/diagnostic tools.

Tests: **859** (855 + 4 builder tests; the Dev-menu callback-set pin
updated for the new button). pyflakes 0; `core/regression`, database,
scheduler, and the engines untouched.

---

## v14.24 — Quick Release Suite complete (QA Phase 2)

The **mandatory release gate** is now authored. Every future BAKA
release must pass the Quick Release Suite before it is production-ready.
Specification corpus only — still **no runner, no UI, no callbacks**
(those are later milestones, unchanged by this one).

### Added (16 new specs → 44 total)

- **Habits** (`suites/habits.py`): create, complete+streak, already-logged.
- **Goals + Projects** (`suites/goals_projects.py`): goal create; project
  create, materials (need/got), worklog.
- **Search** (`suites/search.py`): task search, memory search.
- **Extended existing modules:** task edit (TASK-006), multi-task
  extraction (TASK-007), reminder Tomorrow button (REM-004), AI planning
  (AI-003), AI clarification (AI-004), reminder interval (SET-003),
  onboarding-reference validity (DOC-003).

### Coverage

- **44 tests · 15 categories · ~29 min · 9 Critical / 18 High / 15
  Medium / 2 Low.** 100% of the Quick-Suite brief's critical workflows
  have ≥ 1 spec; several guard known bugs (BUG-001/002/004/007).
- **Coverage review** performed (QA_SYSTEM_DESIGN.md): deferred to the
  Major Suite — 8 dev-facing/non-smoke categories (Scheduler, Vision,
  Media, Notifications, Routing, Offline Engine, Intent Engine,
  Performance, Security-depth) and the interrupted/restart scenario
  classes.

`tests/test_regression_spec.py` integrity test tightened to assert the
completed gate (≥ 40 tests; Habits/Goals/Projects/Search now required).
Suite: **855 tests** (unchanged count — the regression *specs* are data,
not pytest cases). pyflakes 0; frozen files diff-empty.

---

## v14.23 — Regression Specification Foundation (QA Phase 1)

First implementation milestone of the QA system
([QA_SYSTEM_DESIGN.md](QA_SYSTEM_DESIGN.md)). Foundation only — the
manual-regression **specification** system. **No runner, no UI, no
callbacks, no Developer Center integration** (those are later
milestones, by design).

### Design refinements adopted (QA design R1–R4)

- **R1** feature-driven, growing-forever suite (the "~315" is an
  estimate, never a target); **R2** the **Definition of Done** rule
  (now in CLAUDE.md); **R3** three independent QA layers (pytest /
  `core/selftest` / `core/regression`); **R4** version-aware history.

### Added

- **`core/regression/`** — the spec foundation:
  - `models.py` — `RegressionTest` (immutable authored spec: id, steps,
    expected, priority, scenario class, suite membership, introduced
    version) + `RegressionHistory` (version-aware: last executed/passed,
    pass/fail/skip counts, linked bugs) + `Priority`/`ScenarioClass`/
    `Suite` enums with QUICK ⊆ MAJOR ⊆ FULL nesting.
  - `categories.py` — the 23 canonical categories (one source of truth).
  - `registry.py` — `register()` with validation (id format, known
    category, non-empty steps/expected, suite membership) + dedup by id
    + `by_suite`/`by_category`/`by_priority` queries.
  - `store.py` — JSON-backed history persistence foundation
    (`record()`/`load()`/`get_history()`); gitignored, safe to delete.
    *(No runner writes to it yet — the API is ready for the future
    runner.)*
  - `suites/` — the authored **Quick Release Suite**: **28 tests**
    across Core, Tasks, Reminders, Dashboard, Memory, AI, Settings,
    Admin, Developer/Debug, Documentation. Highest-value behavioural
    tests every release must pass; several guard known bugs
    (BUG-001/002/004/007).
- **`tests/test_regression_spec.py`** — 15 tests: model roundtrip +
  suite nesting, registry validation/dedup/queries, the history store
  (record/persist/reload, skip, bad status, corrupt-file resilience),
  and Quick-Suite integrity (unique ids, valid categories, executable
  steps, focus-area coverage).
- **`docs/regression.md`** — how to author regression specs (the
  feature-owns-its-tests workflow).

### Changed

- **CLAUDE.md** — the permanent Definition of Done (R2).
- **QA_SYSTEM_DESIGN.md** — the R1–R4 refinements section.
- **.gitignore** — `regression_history.json` (runtime state).

Suite: **855 tests** (840 + 15). pyflakes: 0 on `core/regression/` +
the new test. No production behaviour changed (frozen files diff-empty).

---

## v14.22 — Admin-only Self-Test Framework

A permanent, registration-based **runtime regression runner** — verifies
BAKA's major features still work in a live process after an update,
without manual testing. Complements (does not replace) the offline
pytest suite. Foundation for all future in-bot diagnostics.

### Added

- **`core/selftest/`** — the framework:
  - `models.py` — the result contract: `Status`
    (PASS/SKIPPED/WARNING/FAIL), `SelfTestResult`, the signal exceptions
    (`SelfTestFail/Warning/Skip`), and `SELFTEST_USER_ID` (a synthetic
    id far outside Telegram's range for temp write-tests).
  - `registry.py` — decorator registration (`@selftest(name, category)`),
    dedup-by-name; a new test needs no central edit.
  - `runner.py` — auto-discovers `tests/` modules, runs sequentially,
    catches every exception (one failure never stops the run), times
    each test + the run, aggregates. Category `include`/`exclude`
    filters.
  - `results.py` — `SelfTestReport` (counts, duration, worst-outcome).
  - `tests/` — 11 representative checks across 9 categories: Database
    (schema integrity), Memory (write/read + overwrite), Tasks, Goals,
    Habits (create round-trips), Dashboard (render sanity), Routing
    (intent→routing), AI (live provider health), Core (settings load,
    scheduler availability). Write-tests use `SELFTEST_USER_ID` and
    clean up in `finally` — production data untouched.
- **Debug Menu (Developer Center)** — since no menu existed, `/debug`
  now opens an **admin-only** inline menu hosting **🧪 Self Test**; the
  old debug-mode toggle moved into it (🐞 button). Non-admins are
  silently denied (same `is_admin()` gate + message as `@admin_only`).
  Namespace `dev:*` (UI_SPEC §10). New `ui.py` builders: `dev_menu_card`,
  `selftest_screen_card`, `selftest_running_text`, `selftest_results_card`.
- **`tests/test_selftest_framework.py`** — 14 tests: registration/dedup,
  the runner's outcome mapping + continue-after-failure + filters, real
  discovery, a full integration run under a temp DB (all pass, zero
  leftover rows), and the UI builders' callbacks/shape.
- **`docs/selftest.md`** — developer guide (architecture, adding a test,
  best practices, how admins run it).

### Changed

- **`main.py`** — `debug_cmd` → admin-only Debug Menu (was: all-users
  toggle; the toggle is preserved as a menu button); `handle_callback`
  gains an admin-gated `dev:` branch. No other handler, routing,
  storage, scheduler, or business-logic change (frozen files diff-empty).
  `ui.debug_toggle_card` is now unused by the command (the menu
  re-renders instead) but retained and still tested — harmless, flagged
  for a future cleanup.

Suite: **840 tests** (826 + 14). pyflakes: 0 on `core/selftest/`,
`ui.py`, and the new test; `main.py` steady at 40 pre-existing.

---

## v14.21 — Maintenance & Developer Experience

Developer tooling and hygiene only; zero user-feature change; frozen
files (core/, database, scheduler, conversation state, fmt,
ui_components) diff-empty.

- **Independent debug ids (Task 1)**: bug ids now display as
  `DBG-0018` in `/report`, `/bugs`, and `/resolve` replies — they were
  always an independent `bugs.db` AUTOINCREMENT sequence (verified),
  never task ids; the prefix ends the visual confusion.
  `debug_system.format_bug_id()`/`parse_bug_id()` are the single
  owners; `/resolve` accepts `18`, `#18`, or `DBG-0018`. Storage,
  schema, callbacks: untouched.
- **Canonical release-verification guide (Task 2)**: TESTING.md's smoke
  section rebuilt as the full guide — every domain (dashboard, tasks,
  goals/projects, habits, templates/memory/search/export, AI, settings,
  reminders & notification callbacks, debug/bugs, admin incl.
  silent-deny checks, logging/security) with **[O] Offline** vs
  **[L] Requires Live Telegram** markers, expected known-issues called
  out so they don't fail a release by surprise.
- **Repository cleanup audit (Task 3)**: `REPOSITORY_CLEANUP.md` —
  every candidate classified (generated/legacy/historical/unknown) with
  risk + recommendation. **Deletions: none** — nothing met all five
  criteria; regenerable caches are handled by the reset script instead.
- **Debug logging (Task 4)**: new rotating, gitignored, lazily-created
  `debugbot.log` (DEBUG tier — Intent/Routing/Offline decision traces,
  i.e. the canary diagnostics) alongside an UNCHANGED INFO `bot.log`
  (retirement assessed, declined). Sanitizer covers both. Root logger
  DEBUG with production handlers pinned INFO.
- **Developer reset (Task 5)**: `dev_reset.sh` — explicit-execution
  removal of `__pycache__`, `.pytest_cache`, `.coverage`, and
  `debugbot.log*`; never touches source, docs, git, venv, secrets, or
  any user database (test DBs live in system temp and self-clean).

Suite: **826 tests** (814 + 12). pyflakes: 0 on all touched files +
`core/` (`main.py` 40 pre-existing).

---

## v14.20 — UI Overhaul Phase 6: Release Candidate RC1

**The UI overhaul is complete.** Final consistency pass; presentation
only; zero callback/routing/logic/schema change (frozen files verified
diff-empty).

- **The five Legacy habit command surfaces converted to component
  HTML** (`habits_overview_card`, `habit_streak_card`,
  `habit_log_card`, `habit_usage_card`, `habit_created_card`,
  `habit_streak_reset_card` in `ui.py`; handlers now thin wrappers) —
  closing the **documented since-v7.1 Markdown title-corruption bug**
  on the message path, completing the Phase 4 deferral, and making
  Legacy and Offline habit replies format-consistent for the first
  time. Empty state uses §14's canonical habit copy; the streak grid,
  fire caps, and all values render identically in meaning.
- **Consistency audit results**: every primary screen (dashboard,
  tasks, habits, goals, settings, AI, help, selftest, debug/bugs/trace,
  admin, insights, proactive) now uses one header/caption/card/footer
  language, §5.4 status hierarchy, §14 empty states, and component
  keyboards; no manual footers or section separators remain in `ui.py`;
  typography exclusively via `fmt`/component helpers.
- **Honest acceptance-criteria note**: "No Markdown remains" is met for
  every primary screen but NOT globally — **91 Markdown reply sites
  remain** in Legacy conversational/secondary flows (was 99 pre-RC).
  Bulk-converting them without per-flow characterization would be the
  kind of risk a stabilization sprint exists to avoid; inventoried in
  DEBUGGING.md as the UI track's one remaining debt item, ticketed for
  v15. `main.py` pyflakes 43 → 40 (pre-existing category).
- 5 new pins (habit command surfaces incl. hostile-title escaping and
  the streak grid); suite **814 tests**.
- **Live smoke checklist: pending your run** — the RC's only open gate.
  TESTING.md's checklist now covers the RC surfaces; run it in a live
  session before tagging RC1 → release.

Next milestone: **v15** (feature work — analytics rebuild, dashboard
callback completion, richer task details, recurring-detail fix, the 91
Markdown conversions, Duplicate Task).

---

## v14.19 — UI Overhaul Phase 5: Utility Screens

The utility screens redesigned onto the component library
(UI_SPEC_v1.md §15 Phase 5), building directly on 5R's pure builders.
Presentation only; the one keyboard (AI-status Re-run → `dash:home`)
stays byte-identical; no callback/routing/logic change anywhere.

- **Ten builders redesigned** to the §-standard layout (header →
  caption → cards → footer, HTML only): settings (information card +
  quiet-hours caption), debug toggle (status components), bugs (§14 dev
  empty state + per-bug rows + footer), trace (information card +
  `language-json` code block for entities — the first §5.3 dev
  code-block use), insights (§14 statistics empty state for
  not-enough-data + sectioned report), admin panel (statistics card +
  commands section), proactive (feature blocks + footer), AI status
  error trio (render_warning/render_error), AI diagnostics (connection
  info card + benchmark statistics card + worst-wins tests status
  card), models (header/caption/footer treatment). `help_cards` keeps
  its v14.12 design (already spec-styled); `selftest_report` unchanged
  from 5R.
- **Six screens leave Markdown behind** (settings/debug/bugs/trace/
  insights/admin — the last pre-v7.1 Markdown surfaces in the command
  path): handlers now pass `parse_mode=HTML`; hostile content is
  escaped by the components (the old Markdown screens never escaped).
  The bugs/trace empty-variant special-case calls collapsed into the
  single builder call.
- **Latent bug caught in review, fixed before it could fire**: the 5R
  insights wrapper had ended up with an unquoted `parse_mode=Markdown`
  (a NameError on first use) via shell quote-stripping in the splice —
  found while converting to HTML; a reminder of why the live smoke
  checklist matters for wrapper lines.
- `BAKA_VERSION` bumped 14.12 → 14.19 (had drifted; /help and
  /selftest now report the real version).
- The 18 utility characterization tests updated in place to the new
  layouts (fields, variants, admin visibility, callback identity all
  still pinned).

Suite: **809 tests**. pyflakes: 0 on `ui.py`/tests/`core/`; `main.py`
pre-existing findings 44 → 43. Live smoke checklist still required
before the next release (wrapper lines + rendered HTML on a real
client).

---

## v14.18 — UI Overhaul Phase 5R: Presentation Extraction

The Board-approved unblock for Phase 5: every utility screen's
presentation moved **verbatim** out of `main.py` into pure, offline-
testable `ui.py` builders — byte-for-byte output, zero behavior change,
zero callback change.

- **13 builders extracted**: `settings_card`, `debug_toggle_card`,
  `bugs_card`, `trace_card`, `insights_card` (incl. its
  not-enough-data variant), `admin_panel_card`, `proactive_card`,
  `help_cards` (both messages, admin section parameterized),
  `ai_status_error_card`, `ai_status_card` (Re-run keyboard included,
  `dash:home` byte-identical), `models_card`, `selftest_report`
  (live probes stay in the handler — they touch the running process).
- **11 handlers reduced to thin wrappers** (gather → `UI.x_card(...)` →
  reply, same parse_mode/reply_markup/gating): settings, debug, bugs,
  trace, insights, admin, proactive, help, status, models, selftest.
  Bonus: two now-unused `fmt` imports dropped (`main.py` pyflakes
  46 → 44, all remaining pre-existing).
- **Verbatim-move discipline**: builders keep their handlers' original
  markup — six still emit the pre-v7.1 Markdown their handlers always
  used. Converting them to spec HTML is Phase 5 proper, now finally
  possible against pinned output. (`\\u2022`-style source escapes render
  identically; verified.)
- **Brief assumption corrected**: there was no
  `models_view`/`perf_view`/`errors_view` presentation to extract —
  `route_dashboard_callback()` has no branches for them; the three
  buttons dead-end today (new DEBUGGING.md entry, pre-existing since
  v11.1, tied to the removed analytics).
- **`tests/test_ui_utility_cards.py` — 18 characterization tests**:
  every builder, every variant branch (quiet-hours states, empty bugs,
  no trace, not-enough-data, wellness toggle, error-status trio,
  quick-vs-full benchmark hint, no-analytics models view, ok/failed
  selftest verdicts), admin visibility in help, callback identity of
  the one extracted keyboard, HTML escaping.
- Handlers themselves still require the TESTING.md live smoke checklist
  (`main.py` remains unimportable offline) — run it before the next
  release.

Suite: **809 tests** (791 + 18). pyflakes: 0 on `ui.py`/`core/`/tests.

---

## v14.17.1 — UI Overhaul Phase 5: Halted at Engineering Review (documentation only)

Phase 5 (Settings • AI • Developer Center • Help • About • information
screens) **stopped at the mandatory pre-implementation review with zero
code changed** — the same discipline as the v14.7.1 RC and the v14.9
"stop if the review reveals a conflict" rule, applied to the UI track.

Findings (full detail in DEBUGGING.md's new entry):
- Every screen in the Phase 5 inventory renders **inline in
  `main.py`** (11 handlers + the 3 `dash:*_view` dashboard branches,
  line numbers documented); no About screen exists; `ui.py` owns none
  of them. The sprint's own DO-NOT-MODIFY list freezes `main.py`, so
  the touchable-file set ∩ screen inventory = **empty**.
- The characterization-first mandate is equally unsatisfiable offline:
  `main.py` is not importable from the test suite (module-level
  side effects, documented since v14.12).
- Per the sprint's stated priority ("behavior wins — never sacrifice
  compatibility for appearance"), no workaround was attempted: no
  speculative unwired renderers, no handler edits, no test churn.

**Proposal for Phase 5R** (needs Board approval): unfreeze `main.py`'s
presentation statements only; extract each screen's text/keyboard
builder into `ui.py` as a pure characterization-pinned function; swap
handler bodies to one-line card calls; verify live via the TESTING.md
smoke checklist. Suite unchanged: **791 tests**, pyflakes 0, zero
diffs outside CHANGELOG.md/DEBUGGING.md.

---

## v14.17 — UI Overhaul Phase 4: Goals & Habits

Goal and Habit dashboard surfaces on the component library
(UI_SPEC_v1.md §15 Phase 4) — presentation only, `ui.py` alone changed.

- **`goal_card`**: "N active goals" caption; item lines, progress bars,
  and the ➖/title/➕ keyboard byte-identical (existing pins kept, not
  replaced, per the brief). **Empty-state copy kept verbatim** — §14 has
  no approved Goals wording (only Projects) and inventing copy is
  forbidden; adding a Goals entry to §14 is a spec-revision item for the
  Board.
- **`habit_card`**: "N active habits" caption; §14 canonical empty
  state (`empty_habits()` — the approved wording); fire-cap/streak/
  check-in rows byte-identical.
- New pins (extending, not replacing): callback-set equality for both
  cards, input-ordering preservation, over-target progress clamping,
  fire cap at 5, and the 18/20-char button-title truncations.

**Constraint-driven deferrals, documented**: every other surface in the
brief's screen list renders inside frozen files — habit streak/log
views and completion/skip texts live in `main.py` handlers and
`core/actions/habit_views.py`/`complete_habit.py`/`skip_habit.py`
(READ-ONLY / DO-NOT-TOUCH this sprint), and no separate Goal
Detail/Statistics screens exist to migrate. Those surfaces await a
phase whose brief unfreezes their files. The dashboard's Goal/Habit
summary lines were already migrated in Phase 2. No new bugs found (the
Phase 3 recurring-detail quirk remains the only open UI known issue).

Suite: **791 tests** (787 + 4). pyflakes: 0.

---

## v14.16 — UI Overhaul Phase 3: Task Workflow

Task List, Today, and Task Details redesigned on the component library
(UI_SPEC_v1.md §15 Phase 3) — presentation only, `ui.py` alone changed,
every callback_data byte-identical (pinned).

- **Task Details** (`task_card`): `📌 TASK <id>` header + title line
  (priority dot/recurrence preserved) + labeled
  `render_information_card` (Due/Time/Category/Priority). Button grid
  unchanged.
- **Task List**: count caption (`1 task` / `10 of 12 tasks`), §14
  canonical empty state (`empty_tasks()` — the approved wording
  replaces "No tasks here. Add one anytime!"). The 10-item slice is
  preserved; §6.2 pagination *buttons* would need new `pg:` callbacks —
  forbidden this phase, deferred.
- **Today**: grouping/ordering/counters untouched; §14 empty state
  (`empty_today()`).
- **Loading states**: none exist on these screens and none were added —
  §11.3 forbids loading UI for deterministic DB reads (documented, not
  an omission).

**Real bug found during Phase 3, preserved + pinned, NOT fixed**
(DEBUGGING.md): `get_task_by_id()` returns 7 columns but `task_card`
reads `done` at index 6 — production's recurring-task detail view shows
✅ with no action buttons ("daily" is truthy there). Presentation-only
phase replicates it; the one-line fix needs Board sign-off (it is a
behavior change). Same 7-column row is why the brief's richer detail
fields (tags/subtasks/reminder state) are deferred — rendering them
requires a wider database read.

Suite: **787 tests** (785 + 2 net). pyflakes: 0.

---

## v14.15 — UI Overhaul Phase 2: Dashboard Redesign

`ui.dashboard_card()` redesigned as the primary navigation hub
(UI_SPEC_v1.md §15 Phase 2) — presentation only, one function changed,
zero diff everywhere else (`main.py`'s `dashboard_cmd`/
`route_dashboard_callback` untouched; refresh keeps editing in place).

**Layout** (all from `ui_components`, no custom formatting): header
with the "Today's productivity overview · <date>" caption → **status
card** (level = worst-wins: ⚠️ n overdue / ℹ️ n due today / ✅ All
clear; body = the 2×2 counter grid + goals/habits lines, every
pre-redesign field in its exact previous format) → **productivity
card** (`render_statistics_card` with the completion bar + a
deterministic motivational caption in four tiers) → keyboard: Quick
row (📅 Today · 🎯 Goals · 🌱 Habits), Management row (📋 Tasks ·
📊 Statistics — §7 canonical label, was "📊 Stats"), §2.5 root nav
(🔄 Refresh only).

**Constraint resolution, documented**: the Phase 2 brief's prescribed
➕ Add Task / 🤖 AI / ⚙ Settings / ❓ Help / 🏠 Home buttons have **no
existing callbacks** (verified against every `callback_data` in
`main.py`), and the same brief forbids new callbacks and handler
changes — so those slots are deferred to the phases that build their
destinations (3, 5, 8; Home is redundant on the root page per §2.5).
The callback set is **provably identical** to the pre-redesign six
(`test_dashboard_card_callback_set_identical_to_pre_redesign`).

Characterization discipline: the pre-redesign dashboard was already
pinned (v14.14's tests, green before this change); field pins survive
the redesign unmodified, button-grid pins updated to the new layout,
plus new pins for the caption, status tiers, and motivation tiers.
Suite: **785 tests** (781 + 4 net). pyflakes: 0.

---

## v14.14 — UI Overhaul Phase 1: Cards Migrated to the Component Library

`ui.py`'s eight dashboard cards now render through `ui_components.py`
(UI_SPEC_v1.md §15 Phase 1). **Characterization tests were written
first** (`tests/test_ui_cards.py`, 21 tests, green against the
pre-migration code, kept green through it): every field, every button
label, and every callback_data is pinned **byte-exact**; headings are
pinned case-insensitively because the one visible delta is
spec-required typography — §5.1 uppercase H1 card titles
("BAKA Dashboard" → "BAKA DASHBOARD" etc.), which the Phase 1 brief
explicitly permits.

- **Duplicated renderers removed from `ui.py` (4)**: `progress_bar`
  (delegates to `progress_indicator` — byte-identical output),
  `priority_dot` (moved to `ui_components`, single owner),
  `recurrence_icon` (new shared `RECURRENCE_ICONS` map), `section`
  (builds on `subheader`). Headers/pages/captions/keyboards now come
  from `render_header`/`render_page`/`caption`/`action_row`/`nav_row`/
  `keyboard`/`button`.
- **Keyboard cap exemption, documented**: `goal_card`/`habit_card`
  (and the per-task rows of `task_list_card`) grow one row per item
  with no cap — pre-existing behavior, so they use `uic.button()` (the
  64-byte check) with direct `InlineKeyboardMarkup` instead of
  `keyboard()`'s 12-button design cap; §6.2-compliant pagination is
  Phase 3/4's job.
- **ICONS vocabulary completion (needs Board ratification)**: `📋 list`,
  `🔔 bell`, `🗓 recurring_monthly` added — all already in production
  chrome before Phase 0 froze the §5.5 vocabulary (ui.py headers since
  v9.0, fmt.task_line's monthly icon). Documenting reality, not new
  chrome.
- **Duplication found and deferred with reasoning**: `main.py`'s
  `_progress_bar` (project cards) is a *variant*, not a duplicate —
  different glyphs (█), truncation, no % suffix; consolidating it
  changes project-card visuals, which is Phase 3b scope.
  `fmt.task_line`'s inline recurrence-icon copy likewise waits for its
  screens' migration (noted at `RECURRENCE_ICONS`).
- Two double-escape bugs caught by the characterization tests during
  migration (caption() escapes; meta must stay raw) — fixed before
  commit.

Zero handler/callback/routing/storage/scheduler/AI changes (`main.py`,
`core/`, `fmt.py` and every behavior file: zero diff). Suite: **781
tests** (760 + 21). pyflakes: 0 on `ui.py`/`ui_components.py`/`core/`.

---

## v14.13 — UI Overhaul Phase 0: Component Library

First implementation phase of the Board-approved UI overhaul. Two
deliverables, **zero user-visible change** (the library is deliberately
unwired — Shadow-Mode discipline, same as v14.0's Intent Engine):

- **`UI_SPEC_v1.md`** — the approved, frozen v1.2 specification
  committed as the single source of truth (§15 freeze policy: no new UI
  pattern without a Board-approved revision first). Approved behavior
  changes ledger: Duplicate Task (§9, Tasks only — Habits excluded with
  reasoning) and `/debug` admin-gating (§10). Neither is implemented in
  this phase.
- **`ui_components.py`** — the §12 component library: page skeleton
  (`render_page/header/section/footer`), cards (information/status/
  statistics), states (success/warning/error/info/loading + the §14
  canonical empty-state builders, copy pinned verbatim by tests),
  confirmation dialog (wraps existing preview builders unescaped —
  wording byte-preserved), button builders (primary/action/nav/
  confirmation/pagination rows + `keyboard()`), and typography helpers
  (closed §5.5 icon vocabulary, §7 canonical labels, breadcrumbs,
  §5.6 timestamps — clock always caller-supplied, core/ discipline).
  Spec rules are enforced **mechanically**: unknown icons/labels,
  wordless status icons, >8-row cards, >4,000-char pages, >64-byte
  callbacks, >3-button rows, >12-button keyboards, empty nav rows, and
  >3-segment breadcrumbs all raise at build time, so violations die in
  tests instead of review.
- **`fmt.py`** gains `link(text, url)` (escaped hyperlink — the one
  §5.3 primitive it lacked). Only fmt change.
- **`tests/test_ui_components.py`** — 38 tests: HTML generation with
  hostile input for every component, §14 copy pins, and every
  enforcement rule's raise path.

Handlers, callbacks, routing, storage, scheduler, AI, commands:
untouched (verified: zero diff on `main.py`, `ui.py`, `core/`,
`conversation_state.py`, `database.py`, `scheduler.py`,
`baka_brain.py`). Suite: **760 tests, ~11–20 s** (722 + 38). Next: 
Phase 1 re-expresses `ui.py`'s existing cards on these components with
field parity pinned.

---

## v14.12 — Production Readiness & Release Candidate

The final polish sprint before real-world testing. No new features;
twelve workstreams:

### Part 1 — ADR-011 Option A implemented (the last architecture blocker)

Conversation state now outranks intent-gated Offline dispatch:
`main.py`'s gate requires `not conversation_state.claims_messages(state)`
(new helper; dispatch runs only in `idle`). A mid-confirmation
`"done 5"` re-prompts instead of completing — Legacy's exact semantics,
in both flag states. Deliberately stricter than the ADR's illustrative
"idle or editing" (Legacy's editing handler claims all editing-state
messages; the Offline editing path already has its own state-gated
entry, ADR-009). ADR-011 flipped to **Accepted**; regression tests in
`tests/test_conversation_state.py` (13). **With this, both pre-canary
blockers from the RC are down to one: canary logistics.**

### Parts 2–4 — Rich UI, /help, /selftest

- `fmt.py` gains `spoiler()`, `blockquote()`, `expandable_blockquote()`,
  `code_block(lang=)` (all auto-escaping; `tests/test_fmt.py`).
- **/help redesigned**: grouped categories in expandable blockquotes
  (no walls of text), quick examples, syntax shown, admin section
  rendered only for the admin (consistent with silent-deny), stale
  "v11.1 · GLM 5.1" banner replaced by the real version
  (`BAKA_VERSION`, bumped from a stale "13.2" to "14.12");
  known-broken analytics commands no longer advertised.
- **/selftest redesigned** from a manual 72-message checklist (still in
  `debug_system.SELFTEST_MESSAGES`; live steps now in TESTING.md's smoke
  checklist) into a real diagnostics report: live checks (DB read +
  integrity, scheduler, Intent Engine, Routing, Offline registry,
  Storage Facade, conversation state) each with latency, plus
  environment (version/Python/provider/models/DB size/peak RSS) and
  feature-flag panels.
- New `_reply_rich()` fallback: if Telegram ever rejects an entity, the
  message is resent stripped of tags instead of crashing the command.

### Parts 5–6 — Token masking + log hygiene (SECURITY)

**Real leak found and fixed**: `log_sanitizer.py`'s token regex required
`/<digits>:<token>` — but Telegram URLs embed `/bot<digits>:<token>/`,
so the pattern NEVER matched and httpx's per-request INFO lines wrote
the full bot token to `bot.log` on every API call. Now
`/bot…` URLs → `/botxxxxxxxxxxxxxxxx`, bare `<id>:<token>` pairs are
masked, and Bearer headers, cookies, and secret-bearing URL query
params (`?api_key=…`) are scrubbed too (`tests/test_log_sanitizer.py`,
pinned against the exact leaking line format). httpx/httpcore/
apscheduler loggers raised to WARNING (per-poll noise gone; the leaking
lines no longer even print). **Action still pending: rotate the old bot
token** — it's in existing `bot.log` files and the deleted
`ai_helper.py` key is in git history.

### Part 8 — AI provider preparation (pre-v15)

`baka_brain.py`: provider, endpoint, key, and all six model ids are now
env-configurable (`AI_PROVIDER`, `AI_BASE_URL`, `AI_API_KEY` — legacy
`NVIDIA_API_KEY` still works — `MODEL_MAIN/FAST/REASONING/VISION/
IMAGE/VIDEO`), defaults = the previous hardcoded NVIDIA values, so an
unset `.env` is byte-identical. All callers already went through the
one OpenAI-compatible client; none changed. Media generation remains
NVIDIA-specific (documented; v15 AI Router scope).

### Part 9 — Requirements audit

`requirements.txt` rebuilt from a dependency-graph audit (installed
metadata, not guesswork): **25 packages removed**, none reachable from
any direct dependency — `anthropic`, the entire unused Google/gRPC
stack (15 packages), `requests`+`charset-normalizer`+`urllib3`,
`cryptography`+`cffi`+`pycparser`, `tenacity`, `websockets`,
`docstring_parser`. 27 kept (8 direct + pinned transitives), with the
`httpx==0.25.2` pin warning inline.

### Part 10 — Repository cleanup (11 files deleted, each verified)

`ai_helper.py` + `bot_state.py` (zero importers, documented dead code
— removing `ai_helper.py` also removes the hardcoded key from the
working tree), the never-assembled analytics six (`init.py`,
`model_metrics.py`, `performance_tracker.py`, `token_counter.py`,
`usage_logger.py`, `usage_service.py` — relative imports that cannot
resolve at repo root; only imported each other), `main.py.save`
(editor backup), `.env.save` (stale placeholder template),
`"h origin main"` (accidental git-output redirect).

### Parts 7, 11, 12 — README, testing, docs

README rewritten for the v14 reality (offline-first pipeline diagram,
component table, flags, audited install, screenshots placeholders,
provider-agnostic AI section, updated file structure and version
history). Manual smoke checklist added to TESTING.md. CLAUDE.md's
long-stale "no automated tests exist" corrected. Docs synchronized
(ARCHITECTURE step ordering now shows the ADR-011 state gate; DEBUGGING/
ROADMAP/MEMORY entries for the resolved issues updated in place).

Suite: **722 tests, ~20 s** (692 + 30). `core/` pyflakes: 0; `main.py`
pre-existing findings reduced 49 → 47.

---

## v14.11 — Offline Habits Stage 3: Completion (Habit domain complete)

**The Habit domain now has 100% feature parity with Legacy for
deterministic message-path operations.** Zero edits to `OfflineEngine`,
`ActionRegistry` (structural), Storage Facade, Routing, Intent Engine,
`main.py`, scheduler, and schema. Still gated behind `OFFLINE_HABITS`
(default OFF, not enabled).

### Phase 0 — Legacy habit completion, re-verified line by line

Habit completion is the habit branch of `done_task()` (message path;
the reminder-callback `done` path stays Legacy like every callback):
one fetch → `is_habit()` → `log_habit_completion()` — a single
connection that INSERTs the `habit_log` row (UNIQUE per day),
recomputes `current_streak` from log history, and UPDATEs the three
streak columns. **Already-logged-today is a success reply with zero
writes** (the UNIQUE trip returns before any UPDATE). **Legacy
intentionally does NOT**: write `completions_log` or `interaction_log`
(unlike task completion), call `mark_done()` (done stays 0 — scheduler
state untouched), refresh notifications, or check `paused` (a paused
habit completes fine). All mirrored exactly, each pinned by a test.

### Added

- **`core/actions/complete_habit.py`** — `execute(task, ...)` (the
  shared-spec path: `complete_task.execute()` has already fetched the
  row and checked `is_habit()`, exactly as Legacy branches after ONE
  fetch — re-fetching would break query parity) and
  `execute_by_id(...)` (the habits-only-build path: performs
  `done_task()`'s own locate + guard sequence, completes habits,
  declines real tasks to Legacy). 100% coverage.
- **`tests/test_complete_habit.py`** — 34 tests: AST purity, streak
  arithmetic (extend/reset-after-gap/longest-preserved, singular
  "1 day"), already-logged zero-write pin, paused-habit completion,
  facade-spy (the required Intent→Registry→Action→Facade→database.py
  path), the full flag matrix, failure injection (missing/invalid/
  non-habit/locked/unexpected/rollback), learning-log absence,
  scheduler invariance (column equality + `get_due_tasks()` stability),
  conversation-state absence, Behavioral Equivalence (rows, streaks,
  timestamps, `habit_log`, **SQL verb order and query count
  identical** via traced connections), and latency/memory benchmarks.

### Changed

- **`core/actions/complete_task.py`** — the v14.6 habit branch now
  takes an optional `habit_handler`; with one injected it delegates
  (habit completion migrated), with none it preserves the v14.6
  `habit_not_supported` fall-through verbatim. Which one runs is decided
  at registry construction:
- **`core/offline/registrations.py`** (ADR-013, amended for the one
  action two domains share): both-domains builds register ONE
  completion spec — Legacy's own one-handler shape — whose runner
  injects `complete_habit.execute` into the branch point; tasks-only
  builds keep the v14.6 runner (Legacy still owns habits there —
  per-domain flags stay honest); habits-only builds register their own
  `complete_habit` spec (EDIT_TASK only — completion phrasings are
  Tier 0 prefixes, never UNKNOWN).

### Success-criteria note on "habit_not_supported removed"

Removed from every configuration in which the Habit domain is enabled
(the canary-relevant ones). Retained solely as the cross-domain guard
for tasks-without-habits builds and direct calls — deleting it there
would complete habits offline under a flag that promises not to.

Suite: **692 tests, ~18 s** (658 + 34; the brief's 700+ estimate
assumed a larger new-module surface — `complete_habit.py` is 22
statements at 100% coverage). `core/` pyflakes: still 0.

---

## v14.10 — Offline Habits Stage 2: Deterministic Writes

Habit CRUD sprint under a frozen architecture — **zero edits to
`OfflineEngine`, `ActionRegistry`, Storage Facade, Routing, Intent
Engine, and (this time) `main.py`**. Still gated behind
`OFFLINE_HABITS` (default OFF, not enabled).

### Phase 0 — the brief's four CRUD targets vs. verified Legacy reality

Only **two** needed habit code:

- **Add Habit** — `/addhabit` + 3 slashless prefixes → `ADD_TASK`.
  Direct apply, **no confirmation** (only the AI HABIT flow confirms;
  per ADR-010, creation is reversible and Legacy's command path doesn't
  confirm — the opposite answer from task creation, same policy).
  **No duplicate detection** (verified: `addhabit_cmd()` never checks —
  two identical creates yield two habits). **No learning logs, no
  scheduler code** (the row's recurrence columns *are* the scheduler
  integration, identical by construction through `add_habit()`).
- **Skip Habit** — `/skiphabit` + 3 prefixes (incl. `reset streak`) →
  `EDIT_TASK`. Direct apply, no confirmation (the reset is
  self-healing — v14.9's DEBUGGING.md finding, now test-pinned:
  the next completion recomputes the streak from `habit_log` and
  undoes it; `longest_streak` untouched). Guardless UPDATE → idempotent
  repeat replies, replicated.
- **Update Habit** — **does not exist in Legacy** (v14.9 finding,
  re-verified); habits are task rows, so v14.4's edit flow already
  covers them. Documented + dispatch-pinned, not invented.
- **Delete Habit** — **no dedicated Legacy command**; v14.5's task
  delete already covers habit rows, orphaned `habit_log` rows and all
  (equivalence-pinned: Legacy `delete_task()` and Offline
  propose+commit orphan identically).

### Added

- **`core/actions/create_habit.py`** — `addhabit_cmd()`'s exact
  pipeline: `parse_all()` for time/recurrence, Legacy's verbatim
  title-strip regex (quirks replicated and pinned: `at 7 AM` (no colon)
  and `every monday` survive into the title even though the parser
  extracts them), empty-title → Legacy's "Tell me what the habit is."
  via fall-through, `HabitStorage.add()` with Legacy's Health/medium
  defaults.
- **`core/actions/skip_habit.py`** — locate → `is_habit` guard →
  `reset_streak()` → reply; not-a-habit falls through to Legacy's
  identical reply.
- **`tests/test_habit_writes.py`** — 42 tests: matchers, execution,
  no-crosstalk dispatch (create_habit vs create_task in the shared
  ADD_TASK bucket), the update/delete needs-no-habit-code pins,
  Failure Injection (exception, locked DB; "cancel" documented N/A —
  nothing pends in a no-confirm flow), Behavioral Equivalence
  (row-for-row vs Legacy pipeline replicas across 3 phrasings; skip +
  delete-orphan parity; query-count parity), benchmarks.

### Changed

- **`core/actions/create_task.py`** — new public
  `matches_entry_command()`; the registry's ADD_TASK matcher for
  create_task is now **prefix-gated instead of match-everything**
  (`registrations.py`). A catch-all matcher shadows any spec registered
  after it in the bucket, and the bucket now holds `create_habit`. Zero
  behavior change for every input — `propose()` applied the identical
  prefix check internally and returned the same
  `success=False/unsupported_action` for non-matching text (verified
  before changing; the narrowing only moves the check earlier).
- **`core/offline/registrations.py`** — habit domain gains
  `create_habit` (ADD_TASK) and `skip_habit` (EDIT_TASK, never UNKNOWN
  — Tier 0 prefixes).
- **Registry pins updated** (expected maintenance): ADD_TASK bucket
  test now pins two prefix-gated specs; EDIT_TASK order gains
  `skip_habit`; v14.9's "`skiphabit 5` is unclaimed" pin retired (it's
  migrated — the pin did exactly its job).

Suite: **658 tests, ~20 s** (616 + 42). `core/` pyflakes: still 0.
No new ADR — no architectural decision changed (ADR-010/012/013 all
applied as written).

---

## v14.9 — Offline Habits Stage 1: Read-Only Views (second domain)

The first non-Task Offline domain, and the registry architecture's
proof sprint: Habit Stage 1 shipped with **zero edits to
`core/offline/engine.py` and `core/offline/registry.py`** — new actions
arrived purely by registration, exactly as ADR-012 promised. Gated
behind `OFFLINE_HABITS` (defined since v14.1C, consumed for the first
time here; default OFF, not enabled).

### Phase 0 — Legacy Habit audit (verified by reading code, per the brief's "do NOT assume anything")

Habits are **task rows** (`is_habit=1` + `habit_start_date`/
`current_streak`/`longest_streak`/`last_completed` columns) plus a
`habit_log` table (UNIQUE one row per habit per day). **Commands that
exist**: `/habits` (+ 4 slashless exact phrases), `/streak <id>`,
`/habitlog <id>` (2 slashless prefixes), `/addhabit` (3 prefixes,
creates immediately, NO confirmation), `/skiphabit` (3 prefixes,
resets streak, NO confirmation), `/resethabits` (admin), plus habit
completion inside `done_task()`'s habit branch (streak log, **no
learning-log writes** — unlike task completion) and the AI-driven
`HABIT` creation flow (the only confirming habit path). **Verified to
NOT exist** (documented, not invented): habit-specific update, delete,
today view, search, statistics, archive/restore. **Scheduler:** zero
habit involvement — reminders ride the tasks table's recurrence; missed
days never auto-reset a streak (streaks recompute only at the next
completion, which also makes `/skiphabit`'s "reset" self-healing — the
next completion recomputes from the full log). **Rendering:** all five
habit handlers still send Markdown with unescaped titles — never
migrated in v7.1's HTML switch (see DEBUGGING.md).

### Added

- **`core/actions/habit_views.py`** — the three read-only views in one
  module (same shared-skeleton grouping precedent as
  `lifecycle_task.py`): `habits_list` (habits_cmd equivalent — fire-emoji
  cap at 5, recurrence labels, conditional last-done line, paused/done
  excluded by the query), `streak_detail` (streak_cmd equivalent
  including its verified quirks: the double lookup, and "Habit not found
  or paused." for a paused habit; 14-day 🟩/⬜ grid built from
  `context.now`), `habit_log_view` (habitlog_cmd equivalent — empty log
  is a success reply, ✅/❌ rows capped at 30). Entry matchers:
  `HABITS_VIEW_PHRASES` mirror of rules.py's exact group,
  `"streak <id>"`, `"habitlog <id>"/"habit log <id>"` regexes; id-less/
  malformed phrasings fall through to Legacy's usage replies (v14.7
  discipline).
- **`build_enabled_registry()`** (`core/offline/registrations.py`) +
  **[docs/adr/ADR-013-per-domain-registry-construction.md](docs/adr/ADR-013-per-domain-registry-construction.md)**
  — per-domain flags now gate at registry construction:
  `_register_task_domain()` / `_register_habit_domain()` split,
  `build_default_registry()` = full catalog (tests/benchmarks/fallback),
  `build_enabled_registry()` = flag-aware production build injected by
  `main.py`. Resolves the "per-domain gate needs generalizing" bottleneck
  v14.8's Scalability Assessment flagged, without touching engine or
  registry.
- **`tests/test_habit_views.py`** — 43 tests: matchers, every view
  against real temp-DB data (HTML escaping of hostile titles included),
  engine dispatch, the ADR-013 flag-combination matrix (tasks-only has
  no habit specs; habits-only leaves task messages to Legacy; both-on ==
  full catalog), Failure Injection (exception, locked DB), Behavioral
  Equivalence (query-count parity with Legacy's exact per-handler call
  sequences + read-invariance on raw rows), latency/memory benchmarks.
  Seed dates are real-clock-relative, never hard-coded (the v14.1C
  windowing pitfall).

### Changed

- **`main.py`** (3 small edits): import `build_enabled_registry`, inject
  it at engine construction, and widen the offline gate to
  `OFFLINE_TASKS or OFFLINE_HABITS` (a short-circuit only — domain
  membership is decided by what got registered).
- **Registry pins updated** (expected maintenance, same class as
  v14.5's/v14.8's): QUERY_TASK order gains `habits_list`, `streak_view`;
  EDIT_TASK gains `habitlog_view` (EDIT_TASK only — its phrasings are
  Tier 0 prefixes and can never classify UNKNOWN); `"habits"` retired as
  the canonical unmatched-QUERY_TASK example in 3 tests (`"goals"` now
  serves — same promotion that retired DELETE_TASK in v14.5).

### Unavoidable differences (documented, deliberate)

- **Reply markup**: Legacy habit replies are Markdown with unescaped
  titles (a latent corruption bug for titles containing `*`/`_`);
  Offline renders the same content as HTML via `fmt.py` per project
  convention. Content-equivalent, byte-different — and the Offline
  path escapes correctly where Legacy corrupts.
- **Error paths reply via Legacy**: not-a-habit/paused replies return
  `success=False`, so main.py falls through and Legacy produces its
  identical reply — same UX, one path of record (the pattern every
  Task action already follows).

Suite: **616 tests, ~17 s** (573 + 43). `core/` pyflakes: still 0.
`OFFLINE_HABITS` remains OFF; nothing is enabled by this release.

---

## v14.8 — Offline Engine Infrastructure Refactor: Registry-Based Dispatch

Pure infrastructure refactor, zero user-visible behavior change —
executes the dispatch-table refactor the v14.7.1 RC audit required
before any Habits sprint. `OfflineEngine.execute()`'s ~90-line
if/elif intent ladder (grown v14.2–v14.7) is replaced by an explicit
**ActionRegistry**; see
[docs/adr/ADR-012-registry-based-dispatch.md](docs/adr/ADR-012-registry-based-dispatch.md)
for the design and the alternatives rejected (decorator registration,
flat intent→action map, class-based Action interface).

### Added

- **`core/offline/registry.py`** — `ActionRegistry` (pure mechanism:
  ordered per-intent `ActionSpec` tuples, O(1) `resolve()`, pending-commit
  table, `RegistryError` validation at registration time — duplicates,
  non-callables, non-Intent keys all fail at startup, never per-message),
  `ActionSpec` (frozen dataclass: `name`, `match`, `run`; match runs
  outside exception containment exactly where the ladder's inline matcher
  calls sat, run inside it).
- **`core/offline/registrations.py`** — `build_default_registry()`, the
  single file to edit when adding an Offline action. All dispatch
  knowledge moved here verbatim from `engine.py`: the QUERY_TASK phrase
  tables (search-prefix-first precedence preserved), the
  complete→lifecycle→update EDIT_TASK/UNKNOWN chain (same spec objects
  registered under both intents), ADD_TASK's match-everything proposal,
  DELETE_TASK's entities-based matcher, and both ADR-008 pending commits.
- **`tests/test_action_registry.py`** — 28 tests: registry mechanism with
  synthetic specs (ordering, duplicate/invalid registration, unknown
  intent/pending lookups), default-registry configuration pins (intents,
  spec names, and ORDER — registration order is match precedence, so
  reordering fails a test before it changes behavior), and
  OfflineEngine-as-thin-dispatcher (injected registries, exception
  containment, both fallback warnings, pending path).

### Changed

- **`core/offline/engine.py`** — `execute()` is now ~25 lines: resolve →
  first non-None match → run under the single containment block →
  identical `unsupported_intent`/`unsupported_action` fallbacks.
  `execute_pending()` resolves commits through the registry
  (`unknown_action_type` fallback unchanged). `continue_editing()`
  deliberately unchanged — state-gated, one target, nothing to select
  between (ADR-009). Constructor gains an optional `registry` parameter
  (defaults to `build_default_registry()`; tests inject synthetic ones).
- **`core/offline/__init__.py`** — exports `ActionRegistry`, `ActionSpec`,
  `RegistryError`, `build_default_registry` alongside the existing three.
- **`main.py` — zero changes** (same as v14.6/v14.7).

### Behavioral equivalence (verified, not asserted)

- All 545 pre-existing tests pass. Expected maintenance, same class as
  v14.5's: 7 test monkeypatch targets retargeted from
  `core.offline.engine.<module>.<fn>` to `core.actions.<module>.<fn>`
  (same module objects; engine no longer imports what it doesn't call),
  and `test_offline_engine.py`'s 2 `_select_action` unit tests now pin
  the same precedence through `build_default_registry()` — runners call
  through module attributes (late binding) precisely so monkeypatching
  still works.
- A 40-case dispatch matrix (every intent branch, every lifecycle op,
  the two-message update flow, propose→commit for add and delete,
  idempotent re-delete, unknown pending type) was run against the
  pre-refactor commit `7ad1a0b` in a git worktree and against the
  refactored tree: serialized ActionResults **byte-identical** (172/172
  output lines).
- Comment-only edits in 4 `core/actions/` files (stale
  `_select_action` cross-references updated); pyflakes still 0 findings
  across `core/`.

### Performance (measured old vs. new, same harness)

Storage-touching paths unchanged (~1.1–1.6 ms, DB I/O dominates; deltas
within run-to-run noise). Pure-dispatch paths: no-match QUERY_TASK scan
0.0039→0.0075 ms (+~3.6 µs — per-matcher function calls vs. inline
checks), unsupported intent unchanged (0.0034 ms). Registry:
~0.5 µs/lookup, ~47 µs one-time build at startup, ~728 B; cold
`import core.offline` unchanged (~130–180 ms both sides).

Suite: **573 tests, ~16 s** (545 + 28). Also corrects TESTING.md's
`test_offline_engine.py` count from 34 to 35 — stale by one *before*
this sprint (verified by collecting on the pre-refactor commit).

---

## v14.7.1 — Release Candidate Phase 1: Architecture Validation (review only, no code changes)

Review-only sprint validating the entire v14.0–v14.7 architecture before
any canary enablement of `OFFLINE_TASKS`. Zero `.py` files changed.
Full findings, canary deployment plan, and three-phase Legacy removal
plan in [RC_v14_ARCHITECTURE_VALIDATION.md](docs/history/RC_v14_ARCHITECTURE_VALIDATION.md).

Headline results: **no architectural defect requiring code found**;
pyflakes reports zero findings across all of `core/` (vs. 49 stale-import
findings in Legacy `main.py`); zero TODO/FIXME/HACK markers repo-wide;
ADR-010 validated by its two subsequent applications; ADR-011 confirmed
as the top pre-canary blocker. Exactly two blockers remain before
enabling `OFFLINE_TASKS` in a canary: apply ADR-011 Option A (small,
specified), and the canary's operational logistics. Post-canary work
queue (not blockers): dispatch-table refactor before Habits, routing
reconciliation using canary comparison logs, the Intent-Engine
structured-hint fix for the four-level phrase-duplication chain.

---

## v14.7 — Offline Engine Stage 6: Task Lifecycle

**The final Task-domain migration sprint.** Still gated behind
`OFFLINE_TASKS` (default OFF, not enabled by this release; all 490
pre-existing tests pass unmodified). The Task domain is now
feature-complete under the new architecture — see Phase 4's Task Domain
Completion Review in this sprint's report.

### Phase 0 — Engineering Review

Per the brief's "do NOT assume any feature exists," every candidate
lifecycle operation was verified against `main.py`/`database.py` before
any code was written. **Verified to exist and migrated**: Pause
(`paused=1`), Resume (`paused=0`), Paused view, Snooze (`snooze_until`,
1–1440-minute validation, `log_snooze`/`log_interaction("task_snooze")`
side effects — swallow included), Stop-reminders (`due_time=NULL,
snooze_until=NULL`), Carry-forward (bulk; its paused/recurring
exclusions live in `database.py`'s WHERE clause, shared by construction).
**Verified to exist but not migrated, with reasons**: Delreminder (a pure
delete alias — `"delete reminder <id>"` already classifies `DELETE_TASK`,
so v14.5's offline delete path already covers it, confirm step and all);
Postpone (only reachable via reminder callback buttons, not the
text-message path); `clear_snooze()` (internal scheduler plumbing).
**Verified to NOT exist — documented, not invented**: Archive, Restore,
Hide, Unhide, Unsnooze (zero matches in `main.py`; a test pins this
finding). None of the migrated operations confirms before acting in
Legacy, and none is irreversible (pause/resume are inverses; the rest are
correctable) — per `ADR-010`'s policy, all apply directly, no confirm.

### Added

- **`core/actions/lifecycle_task.py`** — one module for six operations,
  deliberately (five share an identical locate→single-UPDATE→reply
  skeleton; the brief's per-file names were examples subordinate to its
  own "Do NOT duplicate logic" instruction). Entry regexes mirror
  `main.py`'s slashless prefix groups verbatim; id-less phrasings
  ("pause", "snooze 5") deliberately fall through to Legacy's
  usage/pick-list replies.
- **Storage Facade extensions** — `TaskStorage.pause/resume/snooze/
  stop_reminders/get_paused/carry_forward_overdue`,
  `LearningStorage.log_snooze` — all thin one-line delegations.
- **`docs/adr/ADR-011-conversation-state-priority.md`** — the
  conversation-state ordering question (surfaced v14.6) promoted from a
  debugging observation to an architectural decision. Recommends
  Option A (state outranks intent-gated dispatch, matching Legacy's real
  semantics and v14.4's own `editing` precedent). **Implementation
  deliberately unchanged** per the brief — document and justify only;
  applying it is a named pre-enablement blocker.
- **`tests/test_lifecycle_task.py`** — 55 new tests: all entry phrases,
  per-operation happy paths verified against raw scheduler-state columns
  (`paused`/`snooze_until` *are* the scheduler state — `get_due_tasks()`
  filters on them, so column equality is scheduler-state equality),
  idempotency (re-pause/re-resume/re-snooze all match Legacy's guardless
  UPDATEs), the full failure matrix (missing task, invalid ID, database
  exception/locked, duplicate, concurrent, wrong intent), a test pinning
  the nonexistence of Archive/Restore/Hide/Unhide/Unsnooze, Behavioral
  Equivalence tests per operation (including `snooze_log` rows
  field-for-field and carry-forward's exclusions), and a benchmark with
  **query-count instrumentation** (a traced `sqlite3.connect` wrapper)
  asserting Legacy and Offline execute identical statement counts. 100%
  coverage. Full suite is now 545 tests (was 490).

### Changed

- `core/offline/engine.py`: the `EDIT_TASK`/`UNKNOWN` branch tries
  lifecycle entry phrases after completion's and before update's (all
  regexes disjoint); `_select_action()`'s `QUERY_TASK` table gains the
  paused-view phrases. **`main.py`: zero changes** for the second sprint
  running — direct-apply results ride the existing generic success path.

### Behavioral Equivalence Results

Verified matches per operation: database state (raw column comparisons),
scheduler state (same columns, by construction — same `database.py`
functions), learning logs (`snooze_log`/`interaction_log` rows
field-for-field), validation (snooze's 1–1440 bound, checked before
locate in the same order as Legacy), responses (same wording, HTML vs.
Markdown markup only), errors (same "not found" text; id-less usage
replies stay Legacy's). **One Legacy wording quirk replicated, not
fixed**: stopreminder's reply says "Use /resume to turn back on," but
`resume_task()` only flips `paused` — it doesn't restore the cleared
`due_time`, so the pings don't actually come back. Misleading text,
faithfully mirrored (a wording quibble is neither a genuine bug nor a
safety issue under the brief's improvement criteria) — tracked in
DEBUGGING.md.

### Performance

Measured at n=500 with query-count instrumentation: pause — Legacy
1.980ms/call vs. Offline 1.978ms/call, **identical 4 traced statements**;
snooze — Legacy 4.901ms vs. Offline 5.167ms (+0.27ms), **identical 16
traced statements**. The facade adds zero queries; latency differences
are within noise. Measurement only.

### Notes

Habits, Goals, Projects, AI Router, Plugin System, UI work, and
repository cleanup remain explicitly out of scope. Legacy Router was not
removed. With this sprint, every deterministic, message-path Task
operation Legacy supports is available behind `OFFLINE_TASKS` — which
has still never been enabled anywhere.

---

## v14.6 — Offline Engine Stage 5: Task Completion

**BAKA's fourth Offline write operation.** Still gated behind
`OFFLINE_TASKS` (default OFF, not enabled by this release; all 452
pre-existing tests pass unmodified).

### Phase 0 — Engineering Review

Reviewed Legacy's real `done_task()` (`main.py:428-482`) before writing
code, per this sprint's "do not assume how completion works" instruction.
Findings, all verified directly: **no confirmation** (`mark_done()` fires
immediately — matched, consistent with `ADR-010`'s policy since
completion preserves the row and doesn't meet Delete's irreversibility
bar); **no undo capability anywhere in Legacy** (zero
undone/uncomplete/undo matches — documented per the Reversibility Review
instruction, not invented); **habits branch away before `mark_done()`**
(Legacy checks `is_habit()` first and routes habits to
`log_habit_completion()` + streak display — habits are out of scope, so
Offline returns `habit_not_supported` and falls through to Legacy's
streak logic untouched); **completion has learning-log side effects**
(`log_completion()` with a computed minutes-late delay, plus
`log_interaction(user_id, "task_done")`, both exception-swallowed —
replicated field-for-field including the swallow); **recurrence handling
is identical by construction** (`mark_done()` is a plain
`UPDATE tasks SET done=1`, no recurrence special-casing, and
`get_recurring_tasks()` turns out to be dead code — defined, never
called); **re-completing an already-done task succeeds silently in
Legacy** (no done-flag filter in `get_task_by_id()`, idempotent UPDATE —
matched and tested, not "fixed").

### Added

- **`core/actions/complete_task.py`** — `match_entry_command()` (mirrors
  Legacy's slashless prefix group verbatim: `done <id>`/`complete task
  <id>`/`finish task <id>`/`mark done <id>`; bare `done` and other
  id-less phrasings stay Legacy-only for its pick-list UX) and
  `execute()` (direct apply: locate → habit branch-away → `mark_done()`
  → learning-log side effects → reply, with Legacy's exact
  minutes-late-delay computation replicated).
- **`LearningStorage`** (`core/storage/storage.py`) — new Storage Facade
  domain with `log_completion()`/`log_interaction()`, thin delegations
  needed to replicate Legacy's completion side effects without importing
  `database.py` from the action.
- **`tests/test_complete_task.py`** — 38 new tests: entry-command
  recognition, delay computation, learning-log side effects (verified by
  querying `completions_log`/`interaction_log` directly), all 8 required
  failure scenarios (already completed, task missing, invalid ID,
  database exception, database locked, duplicate completion, concurrent
  completion, invalid state — a habit), the Legacy-swallow equivalence
  for learning-log failures, Behavioral Equivalence tests comparing final
  database state (task row + both learning-log tables, field by field),
  and a Legacy-vs-Offline latency/memory benchmark. 100% coverage. Full
  suite is now 490 tests (was 452).

### Changed

- `core/offline/engine.py`'s `EDIT_TASK`/`UNKNOWN` branch now tries
  `complete_task.match_entry_command()` before `update_task`'s — the two
  entry regexes are disjoint (completion verbs vs. `edit task`/`rename
  task`), verified by a no-crosstalk test. **`main.py` needed zero
  changes** — completion is a direct-apply action, and the existing
  generic success-reply path in the `OFFLINE_TASKS` gate already covers
  it.

### Behavioral Equivalence Results

Verified matches: `done` flag set identically (same `mark_done()` via
the Storage Facade); learning-log rows identical field-for-field
(scheduled time, completed-at, delay minutes); recurrence handling
identical by construction; already-done re-completion behaves
identically (succeeds, re-logs — Legacy has no guard either, verified
and matched); habit completion untouched in both flag states (Offline
branches away before writing anything). **Documented, unavoidable
difference**: message markup only (Legacy replies in Markdown, Offline in
Telegram HTML — same wording), consistent with every prior stage.

### Performance

Legacy completion sequence: ~1.61ms/call; Offline `execute()`:
~1.96ms/call at n=500. The ~0.35ms gap overstates reality: the benchmark's
Legacy replica omitted the `is_habit()` check real Legacy also makes —
actual per-completion query counts are identical (5 each). Measurement
only, no optimization attempted.

### Notes

Task lifecycle, habits, goals, projects, shopping, AI, UI improvements,
and repository cleanup remain explicitly out of scope. Legacy Router was
not removed. No ADR changes — `ADR-010`'s policy applied exactly as
written (its Decision section explicitly anticipated Complete defaulting
to Legacy's real behavior, the way Update did).

---

## v14.5 — Offline Engine Stage 4: Task Delete

**BAKA's first destructive Offline write operation.** Still gated behind
`OFFLINE_TASKS` (default OFF, not enabled by this release; all 424
pre-existing tests pass, with one expected update to an outdated
assertion — see Changed below).

### Phase 0 — Engineering Review

Reviewed Legacy Delete completely before implementing, per this sprint's
explicit "do not assume confirmation flow" instruction. Found
`main.py`'s real `delete_task_cmd()` (verified directly, lines 483-504)
deletes **immediately with zero confirmation of any kind** — even less
safety than Task Update. Unlike every prior sprint's "match Legacy's
real behavior exactly" resolution, this sprint deliberately diverges:
Offline Delete adds a confirmation step Legacy lacks, because deletion
is irreversible (unlike Update, which is correctable with another edit)
and because this sprint's own explicit safety specification
(Locate→Preview→Confirm→Delete→Verify→Return) is a clear, deliberate
signal, not an assumption to override. This is the first time this
migration has intentionally chosen *not* to match Legacy's real
behavior in full — documented prominently, not silently, in
`docs/adr/ADR-010-destructive-operations-policy.md`, which also
generalizes this into a reusable rule (confirm when irreversible, match
Legacy otherwise) for future write operations.

### Added

- **`core/actions/delete_task.py`** — `propose()` (Locate + Preview,
  never deletes) and `commit()` (Confirm + Delete + Verify + Return,
  idempotent: a repeated confirmation or concurrent delete from another
  path is reported gracefully, never attempted twice or treated as an
  error; re-fetches after deleting to verify the row is actually gone
  before reporting success).
- **`OfflineEngine`** gains `Intent.DELETE_TASK` dispatch in `execute()`
  and `"offline_delete_task"` handling in `execute_pending()`. No
  Intent-Engine-coarseness gap this time (unlike Create/Update) —
  `"delete 5"`/`"delete task 5"`/`"remove task 5"` all classify
  `DELETE_TASK` at confidence 1.0 with `task_id` already extracted into
  `entities`, verified directly.
- **`docs/adr/ADR-010-destructive-operations-policy.md`** — generalizes
  three sprints' worth of per-operation confirm-flow findings
  (`ADR-008`/`ADR-009`/this one) into a reusable policy anchored to
  irreversibility, not to "sounds destructive."
- **`tests/test_delete_task.py`** — 28 new tests: Behavioral Equivalence
  (Legacy's `delete_task()` vs. Offline's `propose()`+`commit()`,
  including verifying no cascading cleanup in either path), idempotency,
  and all 8 Failure Injection scenarios this sprint's brief named
  (database locked, database exception, task missing, double
  confirmation, cancel, invalid ID, timeout, concurrent delete). 100%
  coverage of `core/actions/delete_task.py`. Full suite is now 452 tests
  (was 424).

### Changed

- `main.py`'s `OFFLINE_TASKS`-gated block: the existing `needs_confirmation`
  branch now selects between `"offline_add_task"` and `"offline_delete_task"`
  based on the classified intent (previously hard-coded to creation only,
  since delete didn't exist yet); a new `confirming`-state branch commits
  a confirmed delete via `OfflineEngine.execute_pending()`.
- `tests/test_offline_engine.py`'s `test_non_query_task_intent_is_unsupported`
  — a Stage-1-era test used `Intent.DELETE_TASK` as an example of "not
  yet supported," which stopped being true this sprint. Updated to use
  `Intent.CHAT` (genuinely, permanently unsupported — inherently
  AI-shaped) instead. Expected test maintenance, not a behavior change.

### Behavioral Equivalence Results

Verified matches: the deleted row is identical in both paths (same
underlying `database.delete_task()` call via the Storage Facade); no
cascading cleanup in either path (verified — plain single-table
`DELETE`, confirmed by reading the function and by testing that an
unrelated goal survives a task deletion); no scheduler interaction
needed in either path (the scheduler polls the tasks table; a deleted
row simply stops appearing). **Documented, deliberate divergence**: Legacy
deletes in one message with no confirmation; Offline Delete requires a
second, confirming message — this sprint's one intentional exception to
"match Legacy exactly," justified by irreversibility (`ADR-010`).

### Performance

Legacy's bare `delete_task()`: ~0.45ms/call. Offline's `commit()`
(existence check + delete + post-delete verify — three queries vs.
Legacy's one): ~1.20ms/call. The ~0.75ms difference is the direct,
expected cost of the idempotency and verification guarantees, not
wasted work. Measurement only, no optimization attempted.

### Architecture

Deliberately, verifiably inert today: `OFFLINE_TASKS` defaults OFF and is
not enabled by this release. See `ARCHITECTURE.md` and
`docs/adr/ADR-010-destructive-operations-policy.md`.

### Notes

Task complete, habits, goals, projects, shopping, and AI remain
explicitly out of scope and unimplemented. Legacy Router was not
removed (including Legacy's own `/delete`, which keeps its real,
unconfirmed behavior — only the Offline path gained the confirm step).

---

## v14.4 — Offline Engine Stage 3: Task Update

**BAKA's second Offline write operation.** Still gated behind
`OFFLINE_TASKS` (default OFF, not enabled by this release; all 383
pre-existing tests pass unmodified).

### Phase 0 — Engineering Review

Critically evaluated the migration plan against `main.py`'s real code,
not its description. Found the brief's core assumption was factually
wrong: it asked to "preserve Legacy confirmation flow... using the same
Pending Action system," but Legacy's real editing-state handler
(`main.py:1022-1055`) applies an update **immediately** on the next
message, with no confirm step and no `set_pending_action()` call at all
— confirmed by direct reading, not inference. Implementing the brief's
described confirm step would have been a behavioral *divergence* from
Legacy, contradicting the brief's own higher-priority goal ("preserve
Legacy behaviour"). Also found "change recurrence" — listed as a
SUPPORTED example — isn't actually a real Legacy capability:
`database.update_task()`'s signature has no recurrence parameters, and
Legacy's handler doesn't pass any. Both findings resolved in favor of
verified reality over the brief's assumptions. Full review in
`docs/adr/ADR-009-offline-task-update.md`.

### Added

- **`core/actions/update_task.py`** — `start_editing()` (message 1: "edit
  task <id>" / "rename task <id>", verifies the task exists, never
  writes) and `apply_change()` (message 2: recognizes date/time — reused
  `date_parser.parse_all()` — plus new explicit priority/category/title
  patterns; commits immediately, no confirm step, matching Legacy's real
  behavior). Recognizes "cancel"/"nevermind"/"stop" and clears state
  cleanly — a narrow, documented improvement over Legacy's real behavior
  (which would hand these to the AI as a confusing no-op edit attempt).
- **`OfflineEngine.continue_editing()`** — a third dispatch entry point,
  gated on conversation state (`state == "editing"`) rather than Intent
  Engine classification, since a bare "set time to 6pm" reply carries no
  reliable intent signal on its own.
- **`docs/adr/ADR-009-offline-task-update.md`**.
- **`tests/test_update_task.py`** — 41 new tests: field-recognition,
  transaction safety (validate-before-write), Behavioral Equivalence
  tests (Legacy's `update_task()` vs. Offline's `apply_change()`,
  compared field by field), Failure Injection tests (database exception,
  validation failure, cancel, verified-absent duplicate check,
  non-existent task), and a Legacy-vs-Offline performance benchmark.
  100% coverage of `core/actions/update_task.py`,
  `core/offline/engine.py`. Full suite is now 424 tests (was 383).

### Changed

- `main.py`'s `OFFLINE_TASKS`-gated block now also handles
  `Intent.EDIT_TASK`/`Intent.UNKNOWN` for the entry phrases and, in a new
  check gated on `state == "editing"` (checked before the intent-gated
  block, mirroring Legacy's own state-over-intent prioritization),
  intercepts the change-description message. Both reuse
  `conversation_state.py`'s existing `set_editing()`/`get_editing_id()` —
  the same functions Legacy's `edit_task_cmd()` already uses.

### Behavioral Equivalence Results

Verified matches: stored fields identical for equivalent priority/
category/title/date/time changes; per-field-conditional update semantics
identical (only the changed field is ever written, `storage.tasks.update()`
already supported this from Stage 1, no Storage Facade changes needed);
duplicate detection identically absent in both paths (verified — Legacy's
real handler never calls `task_exists()` for updates, and Offline
doesn't either); recurrence changes unsupported in both paths (verified
Legacy limitation, not an Offline gap). **Documented, accepted
differences**: Offline validates dates before writing where Legacy does
not (Transaction Safety requirement, a safety-only addition); Offline
recognizes "cancel"/"nevermind"/"stop" explicitly where Legacy would
confusingly hand them to the AI (a narrow, one-input-class improvement).

### Performance

Legacy's deterministic-portion equivalent (`parse_all()` + `update_task()`
+ `get_task_by_id()`, excluding the AI call that dominates Legacy's real
production latency and can't be benchmarked offline): ~0.79ms/call.
Offline's `apply_change()` (full validate-then-commit cycle): ~0.95ms/call.
Difference: ~0.16ms, from the added validation call and explicit-pattern
regex checks. Measurement only, no optimization attempted, per this
sprint's explicit instruction.

### Architecture

Deliberately, verifiably inert today: `OFFLINE_TASKS` defaults OFF and is
not enabled by this release. See `ARCHITECTURE.md` and
`docs/adr/ADR-009-offline-task-update.md`.

### Notes

Task delete, complete, habits, goals, projects, shopping, and AI remain
explicitly out of scope and unimplemented. Legacy Router was not
removed. Recurrence changes remain unsupported (verified: Legacy can't
do this either).

---

## v14.3 — Offline Engine Stage 2: Task Creation

**The first write operation handled by the Offline Engine.** Still gated
behind `OFFLINE_TASKS` (default OFF, not enabled by this release; behavior
today remains byte-for-byte identical to v14.2, verified by all 347
pre-existing tests passing unmodified).

### Phase 0 — Engineering Review

Critically evaluated the proposed migration rather than implementing it
as given. Confirmed task creation is the safest first write operation
(can only add data, never corrupt/destroy existing rows) while naming a
real nuance: it's also the highest-frequency write action, so per-incident
safety isn't the same as zero aggregate risk. Found two gaps the brief
didn't address, verified by reading `main.py` directly rather than
assuming: (1) the Intent Engine never extracts a task title, for any
tier — resolved by scoping to four explicit verb commands only, title
taken verbatim (no NLP cleanup); (2) neither `"todo X"` nor `"add task X"`
classifies with sufficient confidence under the shipped Intent Engine to
be safely auto-executed (0.0 and ~0.4 respectively, both below
`INTENT_ENGINE.md`'s approved 0.75 reversible-write threshold) — resolved
with a narrow, documented dispatch-layer stopgap (`ADR-007`'s established
pattern, applied a second time). The biggest finding: reading
`execute_task_action()` directly confirmed Legacy *always* confirms
before saving any task, with no exception — implemented genuine two-turn
confirm-flow equivalence rather than skip it, which required touching
`main.py`'s `confirming`-state branch for the first time (Stage 1 only
touched the top of `handle_message()`). Full review in
`docs/adr/ADR-008-offline-write-operations.md`.

### Added

- **`core/actions/create_task.py`** — the first two-phase Offline Engine
  action: `propose()` (parse, validate, check for a duplicate, never
  writes) and `commit()` (the actual save, called only after user
  confirmation). Mirrors `main.py`'s `execute_task_action()`
  field-for-field: title requirement, `date_parser.validate_datetime()`,
  `database.task_exists()`-based duplicate detection (via the Storage
  Facade), recurrence mapping (including monthly's day-of-month default
  of 1), `mark_as_deadline()`, and a closely-matching success message.
- **`OfflineEngine.execute_pending()`** — a second public entry point
  (alongside Stage 1's `execute()`) for committing a previously-proposed
  write after confirmation; there's no fresh `RequestContext` at confirm
  time, only the `pending_data` a prior `propose()` produced.
- **`TaskStorage.mark_as_deadline()`** (`core/storage/storage.py`) — one
  new thin delegation to `database.mark_as_deadline()`, needed to mirror
  Legacy's deadline-marking step.
- **`docs/adr/ADR-008-offline-write-operations.md`** — records the
  two-phase propose/commit pattern and reuse of `conversation_state.py`'s
  existing confirm machinery.
- **`tests/test_create_task.py`** — 36 new tests, including genuine
  Behavioral Equivalence tests that call `database.add_task()` the way
  Legacy does and `create_task.commit()` the way Offline does for the
  same logical input, then compare the resulting database rows field by
  field. 100% coverage of `core/actions/create_task.py`,
  `core/offline/engine.py`, `core/storage/storage.py`. Full suite is now
  383 tests (was 347).

### Changed

- `main.py`'s `OFFLINE_TASKS`-gated block now also handles `Intent.ADD_TASK`:
  on a recognized create-task phrasing, it stores the proposal via
  `conversation_state.set_pending_action()` (a new `"offline_add_task"`
  action_type) and shows the same yes/no confirmation UX Legacy already
  uses, instead of executing directly.
- `main.py`'s `confirming`-state handler gains one new branch,
  `if action_type == "offline_add_task":`, styled identically to the
  existing `admin_reset_tasks`/`admin_reset_all` branches immediately
  above it — routes a confirmed offline-originated task to
  `OfflineEngine.execute_pending()` instead of Legacy's
  `execute_task_action()`. Every existing action_type's behavior is
  unchanged.

### Behavioral Equivalence Results

Verified matches: stored fields (title/date/time/category/priority/
recurrence) identical for equivalent inputs; timestamps identical by
construction (both paths call the same `database.add_task()`, so any
schema-level default applies identically); reminder eligibility
identical by construction (both produce rows `scheduler.py` polls the
same way); duplicate-detection logic identical, including its inherited
SQL-NULL limitation (verified present in both, not introduced by
Offline). **Documented, accepted difference**: Offline-created titles
retain any trailing date/time phrase verbatim (no AI-mediated cleanup) —
Legacy's AI-assisted title extraction produces cleaner titles for
messages this Stage doesn't even recognize (free-form "remind me to..."
phrasing remains Legacy-only).

### Architecture

Deliberately, verifiably inert today: `OFFLINE_TASKS` defaults OFF and is
not enabled by this release. See `ARCHITECTURE.md` for the updated flow
and `docs/adr/ADR-008-offline-write-operations.md` for the two-phase
pattern's full rationale.

### Notes

Task editing, deletion, completion, habits, goals, projects, shopping,
and AI remain explicitly out of scope and unimplemented. Legacy Router
was not removed. `OFFLINE_HABITS`/`OFFLINE_GOALS`/`OFFLINE_PROJECTS`
remain unconsumed.

---

## v14.2 — Offline Engine Stage 1: Read-Only Task Commands

**The first sprint where real user traffic can execute through the new
v14 architecture** — gated entirely behind `OFFLINE_TASKS` (default OFF,
not enabled by this release; behavior today is byte-for-byte identical to
v14.1C, verified by all 312 pre-existing tests passing unmodified).

### Phase 0 — Engineering Review

Critically evaluated (not rubber-stamped) the proposed action-based
architecture against a command-handler port, confirmed `RequestContext`/
`ActionResult`'s Telegram decoupling is worth its cost at this project's
stated scale (~90 eventual handlers), and verified read-only-first is
genuinely the safest starting point by reading the underlying
`database.py` functions directly (`get_tasks`/`get_tasks_by_date`/
`get_tasks_by_week`/`search_tasks_by_title`: pure `SELECT`, zero side
effects). Found and addressed a real design gap the proposal didn't
account for: `Intent.QUERY_TASK` is coarser than the four actions this
Stage implements (it also covers `/habits`, `/goals`, `/dashboard`,
`/settings`) — resolved with a narrow, documented text-pattern dispatch
stopgap rather than modifying the already-Accepted Intent Engine. Full
review in `docs/adr/ADR-007-offline-engine-stage1.md`.

### Added

- **Offline Engine** (`core/offline/`) — `RequestContext` (domain-only
  input: `user_id`, `text`, `intent`, `entities`, caller-injected `now`;
  no Telegram objects, no PTB imports, enforced by an AST-based test),
  `ActionResult` (`success`/`message`/`data`/`warnings`/`metadata`),
  `OfflineEngine.execute()` (dispatches to read-only task actions only,
  never raises, always falls back gracefully).
- **Four read-only task actions** (`core/actions/`) — `list_tasks`,
  `today_tasks`, `week_tasks`, `search_tasks`. Each accesses data
  exclusively through the Storage Facade (`core/storage/`, v14.1C) —
  never `import database` directly, verified by an AST-based test that
  fails the build on any violation.
- **`tests/test_offline_engine.py`** — 34 new tests, 100% coverage of
  `core/offline/` and `core/actions/`. Full suite is now 347 tests
  (was 312).
- **`docs/adr/ADR-007-offline-engine-stage1.md`** — records the
  action-based architecture decision and the `Intent.QUERY_TASK`
  coarseness gap as tracked debt, not silently resolved.

### Changed

- `main.py`'s `handle_message()` integration point now attempts Offline
  Engine execution (feature-flag gated) immediately after the existing
  Intent Engine / Routing Layer calls. When `OFFLINE_TASKS` is False
  (today's only real state), this block is a complete no-op.

### Fixed

- **Real bug found by this sprint's own tests, before shipping**:
  `core/offline/engine.py`'s `_select_action()` and
  `core/actions/search_tasks.py`'s `_extract_keyword()` both stripped
  trailing whitespace before checking a prefix that itself ends in a
  space (`"search "`), so an input of exactly `"search "` (no query yet)
  missed the prefix match entirely. Fixed by left-stripping only before
  the prefix comparison. See `ADR-007`'s Consequences.

### Architecture

Deliberately, verifiably inert today: `OFFLINE_TASKS` defaults OFF and is
not enabled by this release. See `ARCHITECTURE.md` for the updated flow
diagram and `docs/adr/ADR-007-offline-engine-stage1.md` for why read-only
task commands were chosen as the first real path.

### Notes

`OFFLINE_HABITS`/`OFFLINE_GOALS`/`OFFLINE_PROJECTS` remain unimplemented
and unconsumed (v14.1C). Task creation, editing, deletion, reminders,
scheduler integration, AI, habits, goals, and projects were explicitly
out of scope for this sprint. Legacy Router was not removed and remains
the path for every message this Stage doesn't recognize.

---

## v14.1C — Storage Facade + Feature Flags

Infrastructure only — **no user-visible behavior changed, no Offline Engine,
no routing changes.** Introduces the minimum plumbing the (not yet built)
Offline Engine will need: a Storage Facade over `database.py`, and four
feature flags for its eventual gradual, per-domain rollout. Nothing in the
codebase calls either yet.

### Phase 0 — Engineering Review

Before implementing, critically compared a Storage Facade against a full
Repository Layer (simplicity, testability, scalability, migration cost,
technical debt). Concluded the Facade is correct for this codebase: a
Repository Layer's core benefit — swappable backends and fakes for
isolated testing — isn't a live need here (`database.py`'s 32 tests
already run in a fraction of a second against a real temp SQLite file, no
mocking required, and no design doc anywhere calls for a second storage
backend), and `OFFLINE_ENGINE.md` had already, independently, rejected a
new data-access layer for the same reasons. A Repository's other selling
point (typed domain objects instead of raw tuples) doesn't require the
full pattern — it can be added inside a Facade later without interface
polymorphism, if it's ever actually needed. Full reasoning in
`core/storage/storage.py`'s module docstring.

### Added

- **Storage Facade** (`core/storage/`) — `Storage()` exposes four domain
  objects (`tasks`, `habits`, `goals`, `projects`), each a thin,
  one-line-per-method delegation to an existing `database.py` function.
  Zero SQL, zero business logic, zero return-value reshaping — every
  method's return value is byte-for-byte whatever the delegated-to
  `database.py` function already returns.
- **Feature flags** (`core/feature_flags.py`) — `OFFLINE_TASKS`,
  `OFFLINE_HABITS`, `OFFLINE_GOALS`, `OFFLINE_PROJECTS`, all default OFF,
  read once from environment variables at import time (same `.env`
  convention as `BOT_TOKEN`/`OWNER_ID`). None are enabled by this sprint.
- **`tests/test_storage_facade.py`** (18 tests) and
  **`tests/test_feature_flags.py`** (19 tests) — 100% coverage of both new
  modules. Full suite is now 312 tests (was 274).

### Changed

Nothing. `main.py` was not touched — neither the Storage Facade nor the
feature flags are imported or consumed anywhere yet, by design (see
Architecture below).

### Architecture

Deliberately unconsumed infrastructure, not a stub pretending to be
finished — `core/routing/`'s Routing Layer remains behaviorally identical
regardless of any flag's value, since it doesn't read these flags (it
consults its own, separately-empty `OFFLINE_ENGINE_IMPLEMENTED_INTENTS`
set, unrelated to this sprint). See `ARCHITECTURE.md` and `DEBUGGING.md`.

### Notes

No feature flags were enabled. No Offline Engine logic exists. This sprint
is purely additive plumbing for a future stage.

---

## v14.1B — Routing Layer (Decision Logging Only)

Implements DRG-001_Intent_Aware_Routing.md / docs/adr/ADR-006-intent-aware-routing.md's
Sub-stage B ("Decision"). **No production behavior changed.** Every message
is now also routed through a real Routing Layer that computes a genuine
recommended destination — but `destination` is hard-coded to `LEGACY` on
every single call, unconditionally. Only the recommendation is logged, for
the comparison data DRG-001's own migration strategy requires before any
real routing decision is ever acted on (Sub-stage C, not started).

### Added

- **Routing Layer subsystem** (`core/routing/`) — `router.py`
  (`RoutingLayer.route()`), `routing_types.py` (`Destination` enum,
  `RoutingDecision` dataclass), `routing_matrix.py` (per-intent write-class
  table, confidence thresholds, the currently-empty
  `OFFLINE_ENGINE_IMPLEMENTED_INTENTS` set), `confidence.py` (the pure
  decision function), `exceptions.py` (`RoutingError`, unused this sprint).
  Same architectural constraints as the Intent Engine: no AI, no database,
  no scheduler, no Telegram, no network, no IO beyond a debug log line.
- **`RoutingDecision`** — `trace_id`, `intent_result` (carries the
  `IntentResult` unmodified — that dataclass was not touched), `destination`
  (always `LEGACY` this sprint), `recommended_destination` (what the
  Confidence Policy would actually choose), `clarification_required`,
  `fallback_reason`, `decision_latency_ms`.
- **Structured `[Routing]` debug logs**, additive to v14.0's `[Intent]`
  block — Intent, Confidence, Recommended Destination, Actual Destination,
  Trace ID, Fallback Reason, Clarification Required, Decision Latency.
- **`tests/test_routing_layer.py`** — 23 new tests, 100% coverage of
  `core/routing/`. Full suite is now 274 tests (was 251).

### Changed

- `main.py`'s `handle_message()` Shadow Mode integration point now also
  calls `routing_layer.route(intent)` and logs the result, inside the same
  `try/except` as the Intent Engine call — a Routing Layer failure is
  exactly as non-fatal as an Intent Engine failure was already.

### Architecture

The Routing Layer is real, tested infrastructure — not a stub — but its
one hard-coded property (`destination` is always `Destination.LEGACY`) is
deliberate, not a placeholder to be "finished" quietly later. DRG-001
Section 10 identifies skipping this comparison-logging period as the
migration's dominant risk, and DRG-001 Section 13 conditions its own design
approval on this sub-stage running to completion first. See `ARCHITECTURE.md`
for the updated flow diagram.

### Notes

Routing decisions are logged only; nothing reads `recommended_destination`
to make a real choice. Legacy execution is selected unconditionally, every
time, by design. `IntentResult` was not modified. `Intent-Aware Routing`'s
Offline Engine and AI Router integration remain unbuilt — explicitly out of
this sprint's scope.

---

## DRG-001 — Intent-Aware Routing Design Review (design only, no code changes)

Informally self-designated "v14.1A" by its own task brief — **not a shipped
release**; no `.py` file changed. A Design Review Gate document,
[DRG-001_Intent_Aware_Routing.md](docs/history/DRG-001_Intent_Aware_Routing.md), specifying
how the Intent Engine's (v14.0, Shadow Mode) classification output should
eventually drive real routing decisions among the Offline Engine, a
transitional Legacy Handler path, and the AI Router — without yet building
any of it. Companion [docs/adr/ADR-006-intent-aware-routing.md](docs/adr/ADR-006-intent-aware-routing.md)
records the decision to introduce this as a distinct "Routing Layer"
component, separate from the Intent Engine and Offline Engine.

Key design outputs: a new `RoutingDecision` contract (trace ID, destination,
fallback reason — deliberately not added to the already-shipped
`IntentResult`); a Confidence Policy extending `INTENT_ENGINE.md`'s
approved per-intent-class thresholds with a third "Legacy" destination tier
and, new here, treating `IntentResult.ambiguity` (computed since v14.0 but
previously unused) as an independent safety gate; a routing matrix grounded
in `OFFLINE_ENGINE.md`'s real command inventory; a full failure-mode
analysis (10 scenarios); and a four-sub-stage migration path (Shadow →
Decision/comparison-logging → Offline → Legacy removal) nested inside the
master spec's existing Stage 2, not given new top-level version numbers —
see `ROADMAP.md`'s note on why fixed per-stage version labels are
deliberately avoided.

Approved conditionally (`DRG-001` §13): the Decision sub-stage
(comparison-logging, zero behavior change) must not be skipped before any
real routing decision is acted on.

---

## v14.0 — Intent Engine (Shadow Mode)

Stage 1 of the v14 Autonomous Core architecture (`DESIGN_SPEC_v14_AUTONOMOUS_CORE.md`,
approved v13.4 Architecture Freeze — see the "v14 Architecture Freeze" entry
below). Purely additive and internal: **no user-visible behavior changed.**
Every incoming message is now also classified by a new, deterministic
Intent Engine, but nothing in the bot acts on that classification yet — it
only observes and logs.

### Added

- **Intent Engine subsystem** (`core/intent/`) — a pure, stateless,
  offline classifier with zero Telegram/database/scheduler/AI/network
  dependencies. Six-tier deterministic rule priority: exact/prefix
  commands → anchored greeting/small-talk → date/time parsing → recurrence
  keywords → unanchored help phrasing → weak keyword heuristics → unknown
  fallback. Reuses `date_parser.py`'s `parse_all()`/`detect_recurrence()`
  directly rather than reimplementing date/time logic; Tier 0's
  command-recognition table is a documented, hand-maintained mirror of
  `main.py`'s `_starts_with_handlers`/`_exact_handlers` (those are local
  variables inside `handle_message()`, not importable — see
  [DEBUGGING.md](DEBUGGING.md#known-issues) for why this is accepted debt,
  not an oversight).
- **`Intent` enum** (`core/intent/intent_types.py`) — 11 values
  (`ADD_TASK`, `EDIT_TASK`, `DELETE_TASK`, `QUERY_TASK`, `CHAT`,
  `GREETING`, `HELP`, `MEDIA`, `FILE`, `SETTINGS`, `UNKNOWN`).
- **`IntentResult` dataclass** — `intent`, `confidence`, `entities`,
  `ambiguity`, `reasoning`, plus `tier` and `latency_ms` (justified
  additions beyond the original design sketch's `ClassificationResult` —
  see `INTENT_ENGINE.md`'s implementation-status note).
- **Shadow Mode classification** — `main.py`'s `handle_message()` now
  calls `IntentEngine.classify()` as its very first step (before any
  existing routing branch) and logs the result via `logger.debug()`.
  Wrapped in `try/except` so a classifier exception can never affect
  existing behavior — an explicit backward-compatibility addition beyond
  the base design.
- **Structured debug logging** — a multi-line `[Intent] Input/Intent/
  Confidence/Entities/Ambiguity/Reason/Latency` block per classified
  message, emitted with lazy `%`-formatting so it costs nothing unless
  the debug log level is enabled.
- **Intent Engine tests** (`tests/test_intent_engine.py`) — 40 new tests,
  100% coverage of `core/intent/`. Full suite is now 251 tests (was 211,
  see [TESTING.md](TESTING.md)).

### Changed

- Incoming message flow (`main.py`'s `handle_message()`) now performs
  passive intent classification before legacy routing. The classification
  result is logged only; it is not read by any subsequent branch.
- `conversation_state`'s `get_context` is now also imported in `main.py`
  (needed to build the Intent Engine's `ConversationContext.partial_data`
  — no change to `conversation_state.py` itself).

### Architecture

The Intent Engine currently operates in **observation mode only**. It
classifies every message with a real confidence/ambiguity score and logs
it, but does not affect routing — `handle_message()`'s existing
menu/confirming/editing/gathering/slashless-command/AI-fallback logic is
byte-for-byte unchanged. This is Stage 1 of a 6-stage migration
(`DESIGN_SPEC_v14_AUTONOMOUS_CORE.md` §11); Stage 2 (Offline Engine for
already-offline commands) is next, not yet started. See
[ARCHITECTURE.md](ARCHITECTURE.md) for the updated message-lifecycle
diagram and [docs/adr/ADR-002-intent-engine.md](docs/adr/ADR-002-intent-engine.md)
(status updated to Accepted) for the design rationale.

**Real bug found and fixed during implementation** (not a regression —
found by the new test suite before this shipped): a bare `"good morning"`
was initially misclassified as `ADD_TASK` (confidence 0.95), because
`date_parser.py` resolves the vague-time word "morning" to a default
clock time and then infers a date from it — correct behavior for "remind
me in the morning," wrong for a plain greeting. Fixed entirely within
`core/intent/`'s own tier ordering (anchored whole-message greeting/
small-talk is now checked before the date parser); `date_parser.py`
itself was not touched. Same root-cause class as the "noon"-inside-
"afternoon" bug `tests/test_date_parser.py` found during the v13.3 test
suite sprint (below) — see `docs/adr/ADR-002-intent-engine.md`.

### Notes

Routing decisions remain unchanged. No command, AI, scheduler, database,
or Telegram-interaction behavior differs from v13.3.2. This release exists
so the Intent Engine's real-world classification accuracy can be observed
(via `bot.log`'s debug output) before any future stage lets it influence
what the bot actually does.

---

## v13.4 — Architecture Freeze: v14 Autonomous Core Design (design only, no code changes)

Documentation-only milestone (commit `cf3024e`), previously untracked in
this file — added retroactively while synchronizing the v14.0 entry above,
since several docs (the ADRs, `INTENT_ENGINE.md`, this task's own base
commit references) already called it "v13.4 Architecture Freeze" without
it ever having a CHANGELOG entry of its own.

Produced the approved design for BAKA's next architectural layer —
`DESIGN_SPEC_v14_AUTONOMOUS_CORE.md` (master spec) plus five companion
documents (`INTENT_ENGINE.md`, `OFFLINE_ENGINE.md`, `AI_ROUTER.md`,
`PLUGIN_SYSTEM.md`, `COMMAND_PIPELINE.md`, `STATE_MACHINE.md`,
`DATA_FLOW.md`) and five Architecture Decision Records
(`docs/adr/ADR-001` through `ADR-005`). Zero application code changed —
see `docs/adr/ADR-005-autonomous-core.md` for why "Autonomous Core" means
infrastructure autonomy (deciding which code path to run), not expanded
agentic behavior or reduced user confirmation.

Defines a 6-stage migration (`DESIGN_SPEC_v14_AUTONOMOUS_CORE.md` §11):
Stage 0 (fix the `analytics` package, prerequisite) → **Stage 1 (Intent
Engine, additive — implemented next, see v14.0 above)** → Stage 2 (Offline
Engine) → Stage 3 (AI Router, NVIDIA-only) → Stage 4 (additional AI
providers) → Stage 5 (Plugin System, proof of concept via Projects).

---

## v13.3.2 — Hotfix: Adaptive AI Timeout Profiles

Follow-up to v13.3.1. That hotfix fixed *whether* the bot fails over to
`MODEL_FAST` on a timeout; this one fixes *how long it waits before
trying*. All AI chat-completion calls — from a one-word "Hey" to a full
`/think` reasoning session — shared a single flat 30-second timeout, so
ordinary chat waited exactly as long as deep reasoning before even
attempting fallback.

**Current configuration reviewed** (`baka_brain.py`, `ai_helper.py` per
instruction — the latter confirmed dead code, not part of any live path,
left untouched): a single `OpenAI` client with `timeout=30.0` applied
uniformly to every `chat.completions.create()` call across
`call_nvidia()` (12 call sites) and `_call_model()` (backing
`call_main`/`call_fast`/`call_think`/`call_vision`, 5 call sites) — no
distinction between a quick intent-detection call and a long structured
plan. Retry policy (3 attempts, 2s/1s between) was left exactly as
v13.3.1 set it; only the per-call timeout changed. Image/video generation
were already separate — `generate_image()`/`generate_video()` use their
own `httpx.Client(timeout=120.0)`/`httpx.Client(timeout=300.0)` directly,
never the shared chat client — so they needed no change and weren't
touched.

**New profiles**, passed as a per-call `timeout=` override to individual
`.create()` calls rather than changing the client's own default (kept as
the safety ceiling for anything that doesn't override it):

| Profile | Value | Applied to |
|---|---|---|
| `TIMEOUT_FAST_CHAT` | 8s | `call_nvidia()`'s default (covers `get_baka_response()` — the dominant path, every plain chat message), `call_fast()`, `check_api_status()`, `benchmark_all_models()`'s liveness probes |
| `TIMEOUT_NORMAL_REASONING` | 15s | `_call_model()`'s default (covers `call_main()`), and explicit overrides on `call_nvidia()`'s longer-output callers: `suggest_tasks`, `analyze_productivity`, `generate_structured_plan`, `generate_daily_plan`, `generate_weekly_plan`, `generate_task_breakdown`, `generate_study_plan` |
| `TIMEOUT_LONG_REASONING` | 25s | `call_think()` (`/think`) — deliberately the most tolerant tier, since users invoking a "think it through" feature accept more latency, and a short timeout risks truncating a genuinely long but healthy response |
| `TIMEOUT_VISION` | 30s (unchanged) | `call_vision()` — no evidence vision shares `MODEL_MAIN`'s problem, so its effective timeout is deliberately identical to before this hotfix, not shortened |

Values were chosen relative to the only two real latency data points
available: `MODEL_FAST` responding in 676ms when healthy
(`AI_DIAGNOSTIC_REPORT.md` §8), and the original 30s ceiling. 8s gives
roughly 10x headroom over a healthy fast response while cutting worst-case
failover time dramatically; 15s and 25s scale up for workloads that
legitimately produce longer output, while staying under the original
30s. These are estimates informed by the available evidence, not directly
measured against a healthy `MODEL_MAIN` (which was unavailable for
measurement during this investigation, same as v13.3.1) — flagged as a
remaining unknown, not asserted as precisely tuned.

v13.3.1's fallback behavior is fully preserved: `_is_model_dead()`'s
`isinstance(exc, APITimeoutError)` check doesn't care about the specific
timeout duration, so shortening it only makes a hung `MODEL_MAIN` get
detected — and failed over from — faster.

**Benchmark — real, live measurement against the actually-down
`MODEL_MAIN`** (not simulated): a plain `call_nvidia()` call that took
~31s after v13.3.1 now returns a valid `MODEL_FAST` response in **9.0
seconds**. Mocked scenarios additionally confirmed: a healthy-`MODEL_MAIN`
call makes exactly 1 API call with `timeout=8.0`, unaffected in behavior;
`generate_daily_plan()` (normal-reasoning tier) passes `timeout=15.0`;
`call_think()` passes `timeout=25.0`; `call_vision()` passes `timeout=30.0`
— each tier verified to actually reach the API call, not just declared.

Modified: `baka_brain.py` only. Regression: full 211-test suite re-run
clean; `git status` confirms `main.py`, `scheduler.py`, `database.py`,
and `notification_service.py` are all untouched — scheduler, Telegram,
database, and notification-service behavior are unaffected by
construction, not only by testing.

---

## v13.3.1 — Hotfix: NVIDIA Timeout Failover

Follows directly from `AI_DIAGNOSTIC_REPORT.md`'s investigation, which
found `MODEL_MAIN` (`meta/llama-3.3-70b-instruct`) unresponsive on NVIDIA
NIM (5/5 direct test requests timed out at 30s) while `MODEL_FAST`
responded correctly in 676ms — and that the bot's existing MAIN→FAST
fallback mechanism, built for exactly this scenario, didn't trigger for
this specific failure. Root cause: the fallback condition in
`call_nvidia()` matched error text for `"410"`, `"DEGRADED"`, `"504"`,
`"Gateway Timeout"`, or (`"timeout"` **and** `"Read"`) — but a plain
client-side timeout raises `openai.APITimeoutError` with the message
`"Request timed out."`, which contains none of those (it's "timed out",
not "timeout", and no "Read" at all). The fallback silently never fired;
the bot just retried the same hung model three times before giving up,
producing the reported "~1 minute" delay for a plain chat message.

Fix: added `_is_model_dead()`, which checks `isinstance(exc,
openai.APITimeoutError)` first — preferring exception-type matching over
string matching, per the hotfix's own requirement — before falling back
to the pre-existing string checks (410/DEGRADED/504/Gateway Timeout,
unchanged, not implicated by the investigation). Also restructured
`call_nvidia()`'s control flow: previously, a fallback attempt was made
from *inside* each failed retry attempt, meaning `MODEL_FAST` could be
tried more than once across the 3 attempts, and a failed fallback still
fell through into retrying the already-confirmed-dead `MODEL_MAIN` again.
Now the retry loop stops immediately the moment a failure is identified
as "model dead" (no point retrying a model that just timed out), and
`MODEL_FAST` is tried exactly once, immediately after — not interleaved
with `MODEL_MAIN` retries. Any error that isn't recognized as "model
dead" is retried and eventually raised exactly as before, unsuppressed.

Validated three ways: (1) a real, live call through the actual (still
down) `MODEL_MAIN` — `call_nvidia()` now returns a valid `MODEL_FAST`
response in ~31 seconds, versus a prior worst case of ~94 seconds that
usually didn't even succeed, since fallback never fired; (2) a mocked
healthy-`MODEL_MAIN` scenario — exactly 1 API call, no retry, no
fallback, confirming the normal path is byte-for-byte unaffected; (3) a
mocked timeout scenario — exactly 1 `MODEL_MAIN` attempt then exactly 1
`MODEL_FAST` attempt, confirming the new stop-early-then-fallback-once
behavior.

Scope was deliberately narrow, matching the hotfix's own brief: only
`call_nvidia()` (the path `get_baka_response()` uses for ordinary chat
messages, i.e. the reported symptom) was touched. `_call_model()` — the
separate internal dispatcher behind `call_main()`/`call_think()`/
`call_vision()`, used by `/think`, planning, and vision — has no
fallback logic at all (never did) and was **not** given one here; that's
a distinct, pre-existing gap outside this hotfix's explicit scope
("implement ONLY the timeout failover hotfix," "do not introduce routing
logic"). `/selftest`'s separate, already-diagnosed rate-limiter-pacing
slowdown (see `AI_DIAGNOSTIC_REPORT.md` §9 finding 4) is also untouched —
a different root cause, not addressed by this hotfix.

Modified: `baka_brain.py` only (the `call_nvidia()` restructure + new
`_is_model_dead()` helper + one import line). Full 211-test suite
(`tests/`) re-run clean; `generate_image`/`generate_video`/`call_vision`/
`call_think`/`call_main`/`call_fast`/`_call_model` all confirmed
unchanged, both by `git diff` scope and by direct signature/config
inspection.

---

## v13.3 — First Automated Regression Test Suite

211 `pytest` tests across `tests/`, covering every deterministic,
offline-testable module: `date_parser.py` (111), `scheduler.py` (40),
`database.py` (32), `notification_service.py` (16), `async_bridge.py`
(12). Fully offline — no Telegram, no NVIDIA API, no network, database
tests run against isolated temp SQLite files, never `planner.db`. Runs in
~7 seconds. Added `pytest`/`pytest-asyncio` to `requirements.txt` and a
root `pytest.ini` (`asyncio_mode = auto`, `testpaths = tests`).

**Found and fixed 3 real, previously-undiscovered bugs in `date_parser.py`
while writing tests against actual behavior** (explicitly permitted —
"never change bot behaviour unless a genuine bug is found" — and this is
exactly what a regression suite is for):
- **"day after tomorrow" was parsed as tomorrow.** Its check ran after the
  plain "tomorrow" check, and `\btomorrow\b` matches the word "tomorrow"
  as it appears inside "day after tomorrow". Fixed by moving the more
  specific day-after-tomorrow/yesterday checks before the tomorrow check.
- **"beete kal" (Hindi for "yesterday") was also parsed as tomorrow**,
  same root cause — bare "kal" with nothing after it satisfies the
  tomorrow pattern's `kal(?!\s+tha)` negative lookahead, so it matched
  before ever reaching the yesterday pattern. Fixed by the same reordering.
- **Every mention of "afternoon" was parsed as 12:00 (noon) instead of
  14:00.** The vague-time pattern list checks `noon|dupehr|baarah baje`
  before `afternoon`, and "noon" is a literal substring of "afternoon"
  with no word-boundary protection in the original `re.search(_pat, t)`
  call. Fixed by wrapping every vague-time pattern in `\b(?:...)\b`. This
  bug affected every "afternoon" mention in any message, in any of the
  contexts that reach `parse_time()` — the highest-impact of the three,
  given "afternoon" is a common English word and this parser's output
  deterministically overrides the AI's guess for exactly this kind of
  vague-time phrase.

Two other test failures during development were **test-expectation bugs,
not production bugs** — corrected in the tests, production code left
alone: "next wednesday" said on a Wednesday resolves to 7 days out (not
14) per the actual, reasonable implementation; "0 AM" is accepted as
00:00 rather than rejected (the code only validates the upper bound on
AM/PM hours) — a rare, arguably-fine edge case with no clear "correct"
alternative and no evidence of real-world impact, documented as current
behavior rather than changed.

Modified: `date_parser.py` (the 3 bug fixes only), `requirements.txt`.
New: `tests/` (5 files + `conftest.py`), `pytest.ini`.

---

## v13.2 — Infrastructure Hardening: WAL, Indexes, Backups, Integrity Checks

Sprint 3, addressing `ENGINEERING_AUDIT.md` findings E3 (missing indexes),
E4 (no WAL mode / connection pooling), and E7 (migration exceptions too
broad), plus new infrastructure not previously tracked as findings.
Database/startup-infrastructure only — no AI, reminder, scheduler-timing,
Telegram-UX, or command-handler changes; nothing here is user-visible.

**Task 2 — reviewed every `WHERE`/`ORDER BY`/`GROUP BY` in `database.py`
and `scheduler.py`, added 10 indexes** (full list with the specific query
each one serves is documented inline as `REQUIRED_INDEXES` in
`database.py`): `tasks(user_id, done, paused)` — the single most common
filter in the file; `tasks(due_date, due_time)` — the scheduler's
highest-frequency (every 60s), non-user-scoped due-task scan;
`tasks(recurrence_type, done, paused)` — the scheduler's recurring-task
scans; plus `memories(user_id, key)`, `goals(user_id)`,
`completions_log`/`snooze_log`/`interaction_log` each on `(user_id,
<timestamp column>)`, `ai_observations(user_id, status)`,
`missed_capabilities(user_id, created_at)`. Deliberately **not** indexed,
with reasoning inline: `user_preferences.user_id` is already the table's
`INTEGER PRIMARY KEY` (auto-indexed, a separate index would be pure
duplication) — a real finding from actually checking the schema rather
than assuming.

Benchmarked on a synthetic 20,000-row dataset (50 users × 400 tasks —
large enough for indexes to matter; the real `planner.db` is far smaller
today, which is exactly why a synthetic dataset was needed to measure
anything): the scheduler's due-date scan is **~140x faster** with its
index (1.61ms → 0.01ms per query, run every 60 seconds against every
user's tasks); per-user active-task queries are **~2.2x faster**.

**Task 1 — WAL mode.** `init_db()` now sets `PRAGMA journal_mode=WAL`.
Readers no longer block writers (or vice versa) — matters once the
scheduler and multiple handlers hit the database concurrently. Persisted
in the database file itself; re-asserting it on every `init_db()` call is
harmless.

**Task 3 — migration exceptions.** The `ALTER TABLE ... ADD COLUMN` loops
in `init_db()`/`_init_preferences()` (25 columns total) used to catch bare
`Exception: pass`, unable to tell "column already exists" (expected, what
makes the migration idempotent) apart from a real problem (disk full,
corruption). Added `_safe_add_column()`: catches `sqlite3.OperationalError`
specifically, silently continues only when the message says "duplicate
column name," and now logs anything else. The `analytics`-package
availability check (a different, already-tracked issue — see
`DEBUGGING.md`) was deliberately left as a broad `except`, since that's an
optional-dependency guard, not schema migration.

**Task 4 — connection helper.** Added `get_connection()` (applies WAL
consistently) for *new* infrastructure code (backup, integrity checks) to
use. Did **not** retrofit the ~100 existing `sqlite3.connect(DB_NAME)`
call sites across `database.py` — that would be a much larger, riskier
change than this sprint's "do not change behaviour" brief allows for a
"nice to have" consistency improvement; flagged as a future
`ROADMAP.md`-style item instead of attempted here.

**Task 5 — startup integrity verification.** Added
`verify_schema_integrity()`: confirms all 13 required tables and all 10
new indexes exist, and reports schema version (`PRAGMA user_version`, a
new `SCHEMA_VERSION` constant bumped whenever a migration is added — purely
a diagnostic marker, nothing branches on it), foreign-key enforcement
setting, and journal mode. Runs automatically right after `init_db()` in
`main()`, logged clearly either way; a problem is surfaced loudly but does
not block startup, since `init_db()`'s own migrations are already
additive/idempotent and very likely to have succeeded regardless.

One consequential, deliberate side effect: `init_db()` now eagerly creates
`project_materials`, `project_worklog`, `task_templates`,
`missed_capabilities`, and `ai_observations` at startup — previously these
were created lazily, on first use of the relevant feature. Needed so the
integrity check has a complete, meaningful set of tables to verify right
after startup, and so a fresh install's schema is fully formed before
first use. Still idempotent `CREATE TABLE IF NOT EXISTS`; zero user-visible
effect (the tables would exist by the time any command needing them runs,
either way) — noted explicitly here rather than left as a silent side
effect, given this sprint's "do not change behaviour" brief.

**Task 6 — automatic backup before migrations.** Added
`backup_database()`, using SQLite's own online-backup API (`Connection.
backup()` — safe against a concurrently-open WAL file, unlike a raw file
copy). Called at the very start of `init_db()`, before any migration
statement runs. No-op on a fresh/empty database (nothing to protect yet).
Keeps the 5 most recent backups per reason, pruning older ones, in a new
`backups/` directory. A failed backup is logged, never raised — it must
not block startup. (There are currently no destructive migrations in this
codebase — every existing migration is additive `ALTER TABLE ADD COLUMN`
— so this is deliberately a general safety net for *whenever* one is
introduced, not a response to an existing destructive one.)

**Task 7 — `/selftest` infrastructure checks.** Added Section Q to
`debug_system.py`'s `SELFTEST_MESSAGES` — unlike every other section,
these are verified by restarting the bot and checking `bot.log`/the
filesystem rather than a Telegram reply, since that's what's actually
being tested. No new commands or handler changes.

**Task 9 — logging.** `database.py` had no logging at all before this
sprint; added a module logger, used throughout the changes above. Also
fixed `main()`'s startup log line, which had said "v11.1" since that
version (a known, documented issue — see `DEBUGGING.md`) — now derived
from a new `BAKA_VERSION` constant instead of hardcoded. Deliberately
backend-only: user-facing text like `/help` was not touched (Telegram UX,
out of this sprint's scope).

Modified: `database.py`, `main.py`, `debug_system.py`, `.gitignore`
(`backups/`).

---

## v13.1 — Single-Instance Protection & Safe Startup

Sprint 2B of the post-audit production-hardening effort (see
`ENGINEERING_AUDIT.md`, finding D5/ARCH-6). Startup-safety-only sprint —
no AI, database, Telegram-handler, business-logic, scheduler-timing, or
notification-service changes.

**Root cause:** `run.sh` is a bare crash-loop restarter
(`while true; python3 main.py; sleep 5; done`) with no check for an
already-running instance. Two live processes polling the same bot token
would double-fire every reminder and scheduled job, race on SQLite writes,
and duplicate AI processing.

**Investigated before implementing:** reviewed `run.sh`, `main()`'s
startup sequence, and — critically — verified directly against the
installed `python-telegram-bot` 20.7 source how `Application.run_polling()`
already handles SIGINT/SIGTERM/SIGABRT: it installs its own handlers that
raise `SystemExit`, caught internally to shut down gracefully before
`run_polling()` returns normally. This ruled out installing a second,
competing signal handler for the same signals (would risk breaking PTB's
own graceful shutdown) and pointed at `atexit` instead, which correctly
fires after that graceful return, and after both `sys.exit()` paths
already in `main.py`'s `if __name__ == "__main__":` block.

**Locking strategy:** added `instance_lock.py` — an advisory file lock via
`fcntl.flock(fd, LOCK_EX | LOCK_NB)` on a new `bot.pid` file, held for the
process's entire lifetime and acquired as the very first action in
`main()`, before touching the database or Telegram. Chosen specifically
because it survives crashes correctly with no extra staleness-detection
logic needed: the kernel releases a `flock` the instant the holding
process's file descriptor closes, for *any* reason — clean exit, uncaught
exception, or `kill -9`. A plain "does the PID file exist" check can't
tell a live instance apart from one a crash left behind; `flock` doesn't
have that ambiguity because the OS is the source of truth, not the file's
contents. The file still stores the holding PID as plain text, purely for
the diagnostic messages below — the lock/block decision itself never
depends on that text.

Diagnostics reported clearly at startup: lock acquired (with PID); another
instance already running, blocked (with the holder's PID where known,
exit code 2 — distinct from a real crash's exit code 1); a stale lock
found and reclaimed (meaning the previous run crashed or was killed
without cleaning up — this is necessarily reported retroactively on the
*next* startup, since a truly unexpected termination like `kill -9` can't
run any reporting code at the moment it happens); and clean shutdown
(lock released).

Validated with real subprocesses (not just in-process simulation, to
genuinely exercise cross-process `flock` semantics): normal
acquire/release; a second process correctly blocked while a first holds
the lock; a held lock surviving a real `SIGKILL` to the holding process,
correctly detected and reclaimed by the next `acquire()` call with no
manual intervention; normal operation resuming fully afterward.

Same relative-path convention as the project's other runtime state files
(`planner.db`, `bugs.db`, `admin_id.txt`, `bot.log`) — `bot.pid` is
resolved relative to the working directory, matching (not introducing) the
already-documented cross-process-path limitation in
`ENGINEERING_AUDIT.md` finding A3. Added to `.gitignore`.

`run.sh` itself needed no changes: when a second `run.sh` loop's
`python3 main.py` invocation gets blocked, it fails fast, sleeps 5s, and
retries — which means a redundant `run.sh` loop left running (or started
by mistake) automatically and harmlessly becomes a standby that takes over
if the primary instance ever stops, with no code change required for that
property to hold.

Modified: `main.py` (1 import, 1 call at the top of `main()`, 1 new
`except` clause), `.gitignore`. New: `instance_lock.py`.

---

## v13.0 — Telegram Delivery Reliability

Sprint 2A of the post-audit production-hardening effort (see
`ENGINEERING_AUDIT.md`, finding F1, HIGH). Telegram-delivery-only sprint —
no AI, database, scheduling, or business-logic changes.

**Audit first:** inventoried every outbound Telegram Bot API call in
`main.py` — 386 total across `reply_text` (319), `context.bot.send_message`
(18), `edit_message_text` (34), `send_photo`/`send_video` (2),
`answer_callback_query`/`query.answer` (2), and message deletion (11,
mostly "thinking..." placeholder cleanup for AI/media replies). Classified
by trigger: the vast majority user-initiated (command replies, callback
button taps); 13 sites scheduler-initiated (inside job callbacks, using
`context.bot.send_message` since there's no incoming message to reply to
— `check_reminders`, `observation_engine`, etc.); a handful AI-response
and media (image/video generation results). No `send_chat_action` (typing
indicator) usage was found anywhere — noted, not added (out of scope, no
audit finding calls for it).

**A previously undocumented bug found during this sprint's own audit:**
one dashboard callback branch (marking a goal complete) called
`query.answer()` a *second* time for the same callback query — Telegram
allows exactly one answer per callback query id, so this raised
`BadRequest` on every goal-completion tap. It was silently swallowed by
the global error handler before (logged as a bug report, toast never
shown); now it's caught explicitly and logged as an expected case instead.

**Architecture — one seam, not scattered call-site edits.** Verified
directly against the installed `python-telegram-bot` 20.7 source (not
assumed): `ExtBot._do_post()` is the single low-level transport method
every high-level Bot API call funnels through, and when an `Application`
is built with `.rate_limiter(...)`, every one of those calls automatically
routes through that limiter's `process_request()` — the same "official
extension point, zero call-site changes" pattern used for the scheduler
timezone fix (v12.2) and the async-offload fix (v12.3).

Added `notification_service.py`:
- `TelegramSender` (a `telegram.ext.BaseRateLimiter` subclass, registered
  via `Application.builder().rate_limiter(TelegramSender())`) — a
  dependency-free token-bucket rate limiter with two independent levels
  (overall bot-wide cap, default 28/sec; per-chat cap, default 1/sec,
  keyed by `chat_id` so unrelated chats never share a bucket and can't
  serialize against each other), plus retry handling: `RetryAfter` is
  honored exactly (waits the requested duration, retries), `TimedOut`/
  `NetworkError` get bounded exponential backoff, everything else
  propagates untouched (matches `BaseRateLimiter.process_request()`'s own
  documented contract — it must not swallow arbitrary exceptions).
- `safe_edit_message_text()` / `safe_answer_callback_query()` — small
  helper functions (not part of the rate-limiter seam, since edit/answer
  failures like "message deleted" or "already answered" aren't flood
  control and need call-site-aware fallback behavior). Generalizes a
  pattern that already existed for the dashboard's own `_edit()` helper
  (try the edit, fall back to a fresh send if the target is gone, swallow
  silently if the edit was a no-op) so it applies everywhere instead of
  just one code path.

Deliberately **not** built on PTB's own `AIORateLimiter` — it requires the
`aiolimiter` package, not a current project dependency, and adding a new
dependency for a personal-scale bot wasn't judged worth it. The
implementation here is a small, direct reimplementation of the same idea,
written after reading `AIORateLimiter`'s own source for the reference
pattern (per-chat + overall token buckets, `RetryAfter`-aware retry loop).

All 34 `edit_message_text` call sites and 2 `answer_callback_query` call
sites in `main.py` were updated to route through the new helpers — this
was a mechanical, uniform substitution (`await query.edit_message_text(` →
`await safe_edit_message_text(query, `), not a rewrite of what each branch
sends. No other call site in `main.py` changed — `reply_text`,
`send_message`, `send_photo`, `send_video`, and message deletion all reach
the same `TelegramSender` seam automatically without modification.

Validated with a network-free test suite (fake Bot API callbacks, no real
Telegram calls): 50 concurrent reminders to 50 different chats completed
in under a second; a simulated 100-message burst to a single chat
delivered all 100 in order with zero duplicates and measurably enforced
pacing; 10 different users' messages completed concurrently rather than
serializing behind each other; `RetryAfter` and transient network errors
were retried correctly without double-sending; the edit-safety helpers
correctly swallowed "not modified", fell back to a fresh send on a deleted
message, and swallowed an already-answered callback query without raising.

Modified: `main.py` (1 import line, 1 `Application` builder line, 34 edit
call sites, 2 answer call sites — all mechanical). New:
`notification_service.py`.

---

## v12.4 — Data Integrity: Reset Cleanup & IST Habit Dates (superseded by v13.0 above as current)

Sprint 1C of the post-audit production-hardening effort (see
`ENGINEERING_AUDIT.md`, findings E1 and E2, both HIGH). Data-integrity-only
sprint — no performance, AI, scheduler, or Telegram-handler changes.

**E1 — admin reset commands left orphaned data / allowed ID-reuse
inheritance.** Investigated independently (not assumed from the audit) by
tracing all 5 reset commands end to end:
- `reset_all_tasks()` (`/resettasks`) was deleting **all** of a user's
  tasks including habits (`is_habit=1`) — directly contradicting the
  command's own confirmation text, which promises "habits... are kept."
  Fixed by scoping the delete to non-habit tasks only. This also closes
  the habit_log-orphan risk for this command, since habits (and their
  logs) are now simply untouched by it.
- `reset_everything()` (`/resetall`, the "nuclear" wipe) deleted `goals`
  and reset its ID sequence, but never touched `project_materials` /
  `project_worklog` — both of which reference `goal_id`. A newly created
  goal after a nuke could silently reuse an old goal's ID and inherit its
  entire materials checklist and worklog history. Fixed by adding both
  tables to the cleanup (and sequence-reset) pass. Also added
  `task_templates`, `missed_capabilities`, and `ai_observations` to the
  cleanup — these don't have an ID-reuse hazard (nothing references them
  by a reused id), but were silently surviving a command that explicitly
  promises to delete "EVERYTHING."
- **AUTOINCREMENT reset behavior was deliberately left unchanged.**
  Resetting IDs back to 1 is advertised, user-facing behavior (both
  `/resettasks` and `/resetall`'s confirmation text say so explicitly).
  The actual bug wasn't that IDs get reused — it's that dependent tables
  weren't fully cleaned before that reuse could happen. Fixing cleanup
  completeness closes the hazard without the larger, unnecessary,
  user-visible behavior change that abandoning ID resets would be.

**E2 — naive `datetime.now()` in `database.py` could misdate habit
completions.** Repo-wide search for `datetime.now()`, `.today()`,
`.utcnow()`, and other naive datetime construction found 10 occurrences in
`database.py` (all now fixed, replaced with the project's established
`datetime.now(IST)` pattern — already used correctly 14 times elsewhere in
the same file) plus incidental occurrences in `ai_helper.py` (dead code,
excluded — see below), `baka_brain.py` (excluded, see below), and
`debug_system.py` (cosmetic debug/bug-report timestamps only, not
data-integrity-relevant — left as-is to keep this sprint's diff scoped to
actual data correctness, not a repo-wide style pass).
Deliberately **not** touched, with reasoning:
- `ai_helper.py` — confirmed dead code (not imported anywhere); fixing
  unreachable code has no behavioral effect and falls inside this
  sprint's "do not modify AI system" boundary.
- `baka_brain.py` — explicitly excluded by this sprint's rules ("do NOT
  modify: AI system"); its naive-datetime calls build transient prompt
  context strings for the AI, never stored or compared against
  IST-stamped data, so they carry no data-integrity risk of the kind E2
  describes.

Validated against an isolated temporary SQLite database (never the real
`planner.db`): seeded a regular task, a habit, a goal with materials and
worklog, a template, a missed-capability row, and an observation; ran
`/resettasks`-equivalent then `/resetall`-equivalent; confirmed zero
orphaned rows in all 12 user-scoped tables after the nuclear reset, and
confirmed a brand-new goal created immediately afterward (which reused
`goal_id=1`, proving the ID-reuse scenario actually occurred) found zero
inherited materials or worklog entries. Habit completion dates confirmed
to stamp using IST, not naive local time.

Modified: `database.py` only.

---

## v12.3 — Async Offload for AI/Media Calls

Sprint 1B of the post-audit production-hardening effort (see
`ENGINEERING_AUDIT.md`, finding C1/I1, CRITICAL). Fixes the bot's biggest
scalability bug: every AI call and every image/video generation call ran
synchronously inside `async def` Telegram handlers, blocking the *entire*
bot's event loop for every user for as long as that call took — up to
~96s worst-case for a retried text call, up to 5 minutes for `/video`.

**Analysis first:** inventoried every blocking operation in the request
path. 19 call sites across 15 `baka_brain.py` functions are network-bound
(AI inference, image gen, video gen) — these needed fixing. 252 call sites
into `database.py` (plus 4 raw `sqlite3.connect` sites in `main.py`) are
database-bound; benchmarked directly against the live `planner.db` at
0.3-0.4ms per call (connect+query+close included) — negligible for
event-loop purposes at this bot's scale, so deliberately left unwrapped
this sprint rather than touching 250+ call sites for no measurable benefit.

**Architecture:** added `async_bridge.py`, a single new module with one
function, `run_blocking()`, that offloads a synchronous callable to a
worker thread (`asyncio.to_thread`). Every one of the 19 AI/media call
sites in `main.py` now goes through it (`await run_blocking(fn, ...)`
instead of `fn(...)`). Rejected wrapping `baka_brain.py`'s functions in
place — `generate_video()` calls `generate_image()` internally, by name,
synchronously; independently wrapping both as async functions in place
would have broken that internal call (an unawaited coroutine returned
instead of the actual image). Routing through one boundary-level helper
instead means `baka_brain.py` itself is completely untouched — zero risk
to prompts, business logic, or its internal call graph — and leaves a
single seam to swap in native async clients (`AsyncOpenAI`,
`httpx.AsyncClient`) in a future version without touching call sites again.

Modified: `main.py` (19 call sites + 1 import line). New: `async_bridge.py`.
Untouched: `baka_brain.py` (as designed — see above).

---

## v12.2 — Scheduler Timezone Hardening (superseded by v12.3 above as current)

Sprint 1A of the post-audit production-hardening effort (see
`ENGINEERING_AUDIT.md`, finding D1, CRITICAL). Fixes a bug where every
`run_daily()`-scheduled job (`daily_carry_forward`, `end_of_day_summary`,
`morning_briefing`, `weekly_report`, `observation_engine`, `project_nudge`)
fired 5.5 hours later than intended, because the bot's `Application` never
told `python-telegram-bot`'s `JobQueue` it should run in IST — it silently
defaulted to UTC, and every `run_daily()` call passes a naive (tzinfo-less)
`time` object that inherits whatever timezone the scheduler defaults to.

Fix: `main()` now builds the `Application` with
`Defaults(tzinfo=pytz.timezone("Asia/Kolkata"))`. Must be a `pytz` timezone
object specifically, not `zoneinfo.ZoneInfo` — `JobQueue` internally calls
`.localize()` on the configured tzinfo, a pytz-only method. Verified against
the installed `python-telegram-bot` 20.7 source directly (not assumed):
`JobQueue.set_application()` reads `application.bot.defaults.tzinfo`,
falling back to `pytz.utc` when unset, to configure the underlying
APScheduler's timezone.

No scheduling logic changed — every `run_daily()`/`run_repeating()` call
site is untouched; only the timezone they resolve naive times against
changed from UTC to IST. Verified via a standalone script (no network
calls) confirming all 6 daily jobs now compute the correct IST next-run
time; the 7 `run_repeating` (interval-based) jobs were already unaffected
by this bug and remain unaffected by the fix.

Modified: `main.py` (import block + `Application` construction only).

---

## v12.0 — Project Management

Turn any goal into a project with materials, worklog, progress tracking, and
automatic stagnation reminders. Perfect for real-world things you build over
weeks (drones, renovations, hobby builds, learning tracks).

Example flow — the drone build:
```
1. "goal build drone by 2026-08-15"      → goal saved, id shown
2. "need <id> motor, propeller, battery,
      frame, controller"                 → 5 materials attached
3. "got motor"                           → fuzzy-matched, marked done
4. "started <id>"                        → worklog entry, state=started
5. "worklog <id> frame mounted"          → auto-detected as 'progress'
6. "project <id>"                        → full card: progress bar,
                                            material checklist, worklog
7. "shopping"                            → auto-list of everything still
                                            needed across ALL projects
```

Added:
- 2 new SQLite tables: `project_materials`, `project_worklog` (indexed on `goal_id`)
- 11 new commands: `need`/`materials` (add materials), `got`/`have` (fuzzy-mark
  acquired), `worklog`/`log` (log progress, kind auto-detected), `started`,
  `finished`, `project`/`projects`, `shopping`
- Natural-language routing for every command above (e.g. "got the motor" →
  fuzzy match against a user's materials)
- Smart worklog kind detection: finished/khatam → `finished`; blocked/stuck →
  `blocker`; started/began/shuru → `started`; else → `progress`
- Auto-progress formula: 50% materials-acquired ratio + 50% work-state
  (finished=100%, progress=50%, started=25%), rendered as `██████░░░░ 60%`
- Stagnation nudges (daily 20:00, `project_nudge` job): urgent alert if
  deadline < 3 days and materials still missing; gentle nudge if no worklog
  in 7+ days and deadline < 30 days away. Respects quiet hours.
- Inline callback namespace `proj:*` (`proj:started`, `proj:finished`,
  `proj:got`, `proj:view`, `proj:shopping`)
- Selftest expanded to 72 tests (Section P — 9 project tests). **Note:**
  this "Section P" is unrelated to `TEST_CHECKLIST.md`'s own Section P
  (Edge Cases) — see [TESTING.md](TESTING.md) for the naming collision.

Modified: `main.py`, `database.py`, `debug_system.py`

Ideas for next (not yet built — see [ROADMAP.md](ROADMAP.md)): project
photos via Vision, cost/budget tracking, named milestones, template projects.

> **Known issue at time of writing:** the bot's startup banner and `/help`
> text in a couple of places still said "v11.1" even after this release —
> see [DEBUGGING.md](DEBUGGING.md#known-issues).

---

## v11.2 — NIM-Only Visual Generation + Full Debug Pass

Image and video generation rebuilt against the official NVIDIA API specs
(docs.api.nvidia.com), verified line-by-line. No third-party fallbacks.

**Image — FLUX.1-schnell** (fixed per official "Infer" spec):
- Endpoint: `https://ai.api.nvidia.com/v1/genai/black-forest-labs/flux.1-schnell`
- Root cause of earlier 404/422 errors: body must use a plain `"prompt"`
  string (not the Stable-Diffusion-style `text_prompts` array), `cfg_scale`
  must be exactly `0`, and only 1024x1024 is supported
- Response parsed from `artifacts[0].base64` → sent to Telegram as bytes
- Third-party (Pollinations) fallback removed — FLUX via NIM is the only
  image source

**Video — new `/video` command (Stable Video Diffusion):**
- Cosmos has no hosted NIM endpoint, so SVD is the only hosted video model
- Endpoint: `https://ai.api.nvidia.com/v1/genai/stabilityai/stable-video-diffusion`
- SVD is image-to-video: `/video <prompt>` runs FLUX to generate a frame,
  then SVD animates it (`cfg_scale=1.8`, `motion_bucket=127`)
- Frames auto-downscaled below 200KB (spec limit) via Pillow
- `MODEL_VIDEO` changed: `nvidia/cosmos-1.0-7b-text2world` → `stabilityai/stable-video-diffusion`

Always-on flags as of this version: `ENABLE_IMAGE_GEN=True`,
`ENABLE_VIDEO_GEN=True`, `ENABLE_VISION=True`.

A 65-check self-test pass is recorded as fully green in the original
changelog entry, including an "analytics log→query round trip" check. **This
is worth flagging**: as of the v12.0-era documentation pass, the `analytics`
package this check depended on does not exist as an importable package in
the repository (see [DEBUGGING.md](DEBUGGING.md#known-issues)) — whether
this is a later regression or the original check was never actually
exercising the real import path is unconfirmed.

Modified: `baka_brain.py`, `main.py`, `debug_system.py`, `analytics/token_counter.py` (path as documented at the time; the `analytics/` package does not currently exist at the repo root — see known issues)

---

## v11.1 — AI Usage Analytics & Model Monitoring

Per-call AI telemetry, multi-model dashboards, error tracking — intended to
log every AI request automatically without manual instrumentation or added
latency.

Planned package: `analytics/` (`usage_logger.py`, `usage_service.py`,
`model_metrics.py`, `token_counter.py`, `performance_tracker.py`,
`__init__.py`). **As currently checked into the repo, these five files sit
flat at the project root with no `__init__.py` package wrapper**, and
`usage_logger.py` uses package-relative imports (`from .token_counter import
...`) that only resolve inside an actual `analytics` package — see
[docs/ai_system.md](docs/ai_system.md) and
[DEBUGGING.md](DEBUGGING.md#known-issues) for the full picture.

New table (intended): `ai_usage` (19 columns — timestamp, user/session/
conversation ids, provider, model, request_type, intent, token counts,
estimated cost, latency, status, error, fallback flag, response length,
4 indexes). `database.py`'s `init_db()` attempts `from analytics import
init_usage_table` inside a `try/except: pass` — since the import fails,
**this table is never created** in the current tree.

Intended automatic logging sites: `baka_brain.py`'s `_call_model()`,
`call_nvidia()`, and `generate_image()`.

New commands (intended): `/usage`, `/performance`, `/errors`; `/models`
upgraded to show live ping + real usage. All of these are wired into
`main.py` behind `try/except` guards that fall back to empty stats when
`import analytics` fails — which it currently does.

Modified: `main.py`, `database.py`, `baka_brain.py`. New folder (intended,
not present as a package in the current tree): `analytics/`.

---

## v11.0 — Multi-Model AI System

Added 6 AI models with role-based routing (model IDs below are as of this
release; several have since changed — see
[docs/ai_system.md](docs/ai_system.md) for current values):
- `MODEL_MAIN` = `z-ai/glm-5.1` — main brain
- `MODEL_FAST` = `meta/llama-3.1-8b-instruct` — quick intent/classification
- `MODEL_THINK` = `z-ai/glm-5.1` — deep reasoning (`/think`)
- `MODEL_VISION` = `meta/llama-3.2-90b-vision-instruct` — image understanding
- `MODEL_IMAGE` = `black-forest-labs/flux.1-dev` — image generation
- `MODEL_VIDEO` = `nvidia/cosmos-1.0-7b-text2world` — video generation (opt-in)

New per-model functions in `baka_brain.py`: `call_main()`, `call_fast()`,
`call_think()`, `call_vision()`, `generate_image()`, `_call_model()`
(internal dispatcher with retry + logging), `fast_intent_classify()`,
`benchmark_all_models()`.

**Image understanding (Vision):** send a photo → the bot describes it; add a
caption to ask specific questions; todo-list photos get extracted and offered
as one-tap-save tasks.

**Image generation (opt-in at the time):** `/image <prompt>` or natural
language ("draw ...").

**Autonomous Observation Engine:** daily 22:00 job analyzes the week and
generates 1-3 AI suggestions; `/suggestions`, `/approve <id>`, `/dismiss <id>`.

Feature toggles introduced (values below are as of v11.0; see
[docs/ai_system.md](docs/ai_system.md) for current values):
`ENABLE_FAST_ROUTING=False`, `ENABLE_VISION=True`, `ENABLE_IMAGE_GEN=False`,
`ENABLE_VIDEO_GEN=False`.

New commands: `/image`, `/generate`, `/models`, `/suggestions`, `/approve`,
`/dismiss`. New handler: PHOTO messages route to the vision pipeline. New
table: `ai_observations`. New job: `observation_engine` (daily 22:00).

Modified: `main.py`, `database.py`, `baka_brain.py`

---

## v10.2 — AI Autonomy Foundation

- Rich AI context: every AI call now sees the user's open tasks by category,
  recent completions, overdue count, and active habits + streaks
- `/think` (or `/ask`) — free-form AI reasoning against the user's real data,
  no JSON schema
- Missed-Capability Log: low-confidence or action-verb-but-CHAT-intent
  messages are logged (input, AI intent, AI response, miss type, confidence)
  for later feature-gap review via `/misses` (admin-only)
- Natural-language entry points for think mode ("what should I...", "help me
  decide", ...)

New table: `missed_capabilities`. New functions: `get_user_context_for_ai`,
`log_missed_capability`, `get_missed_capabilities`, `mark_missed_reviewed`,
`think_freely`. New commands: `/think`, `/ask`, `/misses` (admin), `/reviewed`
(admin). Modified: `main.py`, `database.py`, `baka_brain.py`

---

## v10.1 — Pre-Deadline Buffer Reminders

- Auto-detects deadline phrasing (English: "due", "submit by", "deliver by",
  "before deadline", "hand in", "turn in"; Hindi: "tak", "tak karna hai",
  "deadline hai", "submission")
- Staged buffer reminders at 7d / 3d / 1d / 6h / 1h ahead of the deadline,
  each with Done now / Break down / Plan today / Mute buttons
- `/deadline <id> [on|off]` toggles deadline mode manually
- All buffer reminders respect quiet hours; each buffer level fires once
  (tracked in the comma-separated `buffer_sent` column)
- Two-layer detection (parser regex + AI's `is_deadline` entity field) —
  either triggering enables deadline mode

New columns: `is_deadline`, `buffer_sent`. New functions: `mark_as_deadline`,
`get_pending_deadlines`, `mark_buffer_sent`, `parse_buffer_sent`. New job:
`deadline_buffer_check` (every 30 min). New callback: `unflagdeadline`.
Modified: `main.py`, `database.py`, `date_parser.py`, `baka_brain.py`

---

## v10.0 — Search, Reports & Templates

- `/search <keyword>` — universal search across tasks, memories, habits, goals
- Task Templates: `/savetemplate`, `/template`, `/templates`
- `/export` — full data backup as plain text
- Weekly Report: automated Sunday 20:00 digest (completed/created/pending/
  overdue, completion rate, top habit streaks)
- Smart time suggestions using learned completion patterns (v6.0) when no
  time is set on a new task

New table: `task_templates`. New functions: `search_all`, template CRUD,
`get_weekly_report_data`, `export_user_data`. New job: `weekly_report`
(Sunday 20:00). Modified: `main.py`, `database.py`

---

## v9.1 — GLM 5.1 AI Upgrade + Enhanced Diagnostics

- Model swap: `meta/llama-3.1-8b-instruct` → `z-ai/glm-5.1`; `MODEL_MAIN`
  constant introduced ahead of v11.0's multi-model swap
- Bulletproof `.env` loading (manual fallback if `dotenv` fails)
- `/status` upgraded: quick (3-test) or `status full` (6-test) benchmark,
  graded A+ to F
- v9.0.1 hotfix: goals table migration for legacy DBs, using
  `PRAGMA table_info` for column detection so it never crashes on an
  old schema

Modified: `baka_brain.py`, `main.py`, `database.py`

---

## v9.0 — Dashboard & Rich UX Integration

Purely additive — every prior feature preserved. New `ui.py` module keeps
presentation separate from business logic.

- Unified Dashboard (`/dashboard`, `/home`, menu button): today/overdue/
  pending counts, goals, habits, completion bar
- New `ui.py` components: `dashboard_card`, `task_card`, `today_card`,
  `goal_card`, `habit_card`, `stat_card`, `reminder_card`, `progress_bar`
- Today View grouped into Overdue / High-priority / Upcoming / Completed
- Goal Dashboard with progress bars + inline +/- buttons (new `goals.target`
  column)
- Morning Briefing job (08:00); Evening Review (upgraded end-of-day summary)
- Centralized dashboard callback router (`dash:` namespace) that edits
  messages in place instead of sending new ones
- Hardened `handle_callback`: task IDs parsed with try/except so malformed
  callbacks can't crash the bot

New file: `ui.py`. New DB: `goals.target` column;
`get_goals_full`/`update_goal_progress`/`get_done_today_count`. New jobs:
`morning_briefing` (08:00). Modified: `main.py`, `database.py`

---

## v8.0 — Proactive Suggestions

- Wellness reminders (opt-in, default off): water/break/eye-rest/posture —
  `/wellness on|off`, `/wellness interval 60`, per-type toggles
- `/proactive` — control panel for every proactive feature
- Slot-crowding hint when creating a task at a time that already has 2+ tasks
- One-time high-priority-due-within-3h nudge (Done / Break-down buttons)
- Messages switched to clean HTML formatting (`fmt.py`)

New columns: `wellness_on`, `wellness_interval`, `wellness_types`,
`last_wellness` (on `user_preferences`). New jobs: `wellness_reminder`
(every 15m, interval-gated), `priority_nudge` (every 30m). Fixed:
`init_db()` now runs preference/learning migrations at startup, not lazily.
Modified: `main.py`, `database.py`

---

## v7.1 — Log-Driven Bug Fixes + Rich HTML Formatting

Bugs fixed from real test-log analysis:
- Recurring-task phrasing ("every Monday", "har Sunday", "daily at 9") was
  misclassified as GOAL — now correctly HABIT
- "evening"/"shaam" returned 15:00 instead of 18:00 (AI overrode the
  parser) — parser's vague-time mapping now always wins over the AI guess
- Invalid times ("25 PM", "13 AM", "25:99") were silently accepted — now
  rejected with a clear message
- Date + action verb messages were sometimes classified as MEMORY_SAVE —
  now correctly TASK
- "Remind me yesterday" now warns about the past date

New file: `fmt.py` (HTML helpers: `b()`, `i()`, `code()`, `esc()`,
`task_line()`, `confirm_box()`). Modified: `baka_brain.py` (intent prompt),
`main.py` (merge logic + HTML)

---

## v7.0 — Follow-up Intelligence

- "Did you finish?" check-ins 15 min after a task's time passes
- Repeated-snooze detection (3+ snoozes triggers a learned-time nudge)
- `/review` — lists stale tasks (3+ days overdue)
- End-of-day summary at 21:00
- All follow-ups respect quiet hours

New columns: `followup_sent`, `followup_count`, `snooze_count`,
`stale_flagged`. New jobs: `check_did_you_finish` (every 15 min),
`end_of_day_summary` (21:00). New callbacks: `finish_yes`, `finish_no`,
`dobreak`. Fixed: timezone bug — v7.0 DB functions now use IST, not naive
UTC. Modified: `main.py`, `database.py`

---

## v6.1 — Admin Mode + Reset Tools (owner-only)

- `/myid`, `/claimadmin` (first caller becomes the permanent sole admin —
  meant to be run once right after deploying)
- `/admin` control panel, `/adminmode` verbose debug toggle
- `/resettasks`, `/resetmemory`, `/resethabits`, `/resetlearning`,
  `/resetall` (nuclear, requires typed confirmation)
- `/sql <SELECT query>` — read-only SQL debugging
- Admin commands are invisible to non-admins ("Unknown command" response)
- `admin_id.txt` persists the lock across restarts (gitignored)

New DB functions: `reset_all_tasks` (also resets autoincrement),
`reset_all_memories`, `reset_all_habits`, `reset_learning_data`,
`reset_everything`, `get_data_stats`. Modified: `main.py`, `database.py`

---

## v6.0 — Preference Learning

- Every completion/snooze/interaction is logged
- `/insights` — tone classification (gentle/strict/balanced), active hours,
  snooze patterns, top categories, completion rate
- `suggest_time_for_task()`, `suggest_interval_for_task()` — used when
  creating new tasks

New tables: `completions_log`, `snooze_log`, `interaction_log`. New module:
`preferences.py`. Modified: `main.py`, `database.py`

---

## v5.0 — Habit Engine

- Habits tracked via `is_habit` flag + `habit_log` table
- `/habits`, `/streak <id>` (14-day grid), `/habitlog <id>` (30-day log),
  `/addhabit`, `/skiphabit`
- Longest-streak tracking, missed-day detection with adjustment tips

New table: `habit_log`. New columns: `is_habit`, `habit_start_date`,
`current_streak`, `longest_streak`, `last_completed`. Modified: `main.py`,
`database.py`

---

## v4.0 — Smart Planning + Task Breakdown

- `/plan [today|week]`, `/breakdown <id>`, `/reschedule <id>`, `/overload`
- Subtask support via new `parent_task_id` column

New DB column: `parent_task_id`. Modified: `main.py`, `database.py`,
`baka_brain.py`

---

## v3.0 — Vague Time Understanding + Smarter Clarification + Habits

- Vague-time defaults ("later"→+2h, "soon"→+30m, "evening/shaam"→18:00,
  "morning/subah"→08:00, "tonight"→21:00, "midnight"→00:00, "lunch"→13:00,
  "noon"→12:00, "end of week"→next Friday)
- Urgency detection → priority=high; "whenever/no rush" → priority=low
- HABIT intent for recurring natural-language phrasing

Modified: `date_parser.py`, `main.py`

---

## v2.0 — Passive PA: Remind Until Done + Escalation + Quiet Hours

- Remind-until-done with escalating frequency near deadline
- Batched follow-ups for 3+ overdue tasks
- Quiet hours (default 23:00–07:00), auto carry-forward at midnight
- Max reminders cap (default 5)

New table: `user_preferences`. New column: `tasks.reminder_count`. New jobs:
`check_followups` (every 5 min), `daily_carry_forward` (midnight). Modified:
`main.py`, `database.py`, `scheduler.py`

---

## v1.2 — Overdue Task Handling + Deadline Warnings + Tags

`/overdue`, `/deadlines`, `/carryforward`, `/tag`, `/tagged`. New column:
`tags`. Modified: `main.py`, `database.py`, `scheduler.py`

---

## v1.1 — Snooze / Postpone / Pause + Persistent Reminder Buttons

Inline buttons on every reminder (Done/Snooze 10m/Snooze 1h/Tomorrow).
`/pause`, `/resume`, `/paused`. New columns: `paused`, `snooze_until`,
`last_reminded`. Modified: `main.py`, `scheduler.py`, `database.py`

---

## v1.0 — Debug & Bug-Tracking System

Built first, deliberately, so every later feature would be easier to test:
`/debug`, `/report`, `/bugs`, `/resolve`, `/trace`, `/selftest`, automatic
exception logging to a separate `bugs.db`.

New file: `debug_system.py`. Modified: `main.py`
