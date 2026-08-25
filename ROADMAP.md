# BAKA Bot — Roadmap

This consolidates every "not yet built" idea found across the old
`VERSION.md`'s planned-roadmap section, `feature_list.md`'s "Known
Limitations", and gaps found during the 2026-07 documentation pass.

> **v15.0 — Workspace OS**: the next major evolution unifies
> Tasks/Habits/Projects/Goals/Memory under a single **Workspace**
> abstraction (Project/Book/Game/… = same engine, different template),
> with a Milestone hierarchy, an append-only Knowledge Timeline,
> Telegram-Topic sync, and an AI Orchestrator. Full design:
> [docs/v15/](docs/v15/) (WED · TWID · KTD · AWOD · MIGRATION). Built
> additively behind a `WORKSPACE` flag (ships dark, canary-enabled) so no
> existing behaviour regresses — the v14 Autonomous Core playbook.
>
> **Status:** `v15.0-alpha.7` — built in `core/workspace/`, all dormant
> behind `WORKSPACE=off`: the **Workspace Foundation** (alpha.1: schema,
> Storage Facade, Repository, Service, Template registry, migration), the
> reusable **Entity Engine** (alpha.2: ownership + input validation,
> lifecycle state machines, event seam), **Project Integration** (alpha.3:
> `ProjectAdapter` routes v14 Projects through the Workspace layer with
> proven data equivalence — no data moved), **Milestone Management**
> (alpha.4: archive + soft-delete), the append-only **Knowledge Timeline**
> (alpha.5: `TimelineEngine` subscribes to the engine's `EntityEvent`
> hook), the **Synchronization Engine + Telegram Adapter** (alpha.6: TWID
> outbox, idempotent enqueue, retrying drain — Telegram is the first
> `SyncAdapter`, delivering through an injected sender), and the generic
> **AI Workspace Orchestrator** (alpha.7/AWOD: NL → validated engine op via
> interpret → select → resolve → safety gate → apply, with the AI injected
> as an `Interpreter` — no live LLM import, template-agnostic).
>
> **`v15.0-beta.1` — the platform is wired into production** (integration
> only, no architecture change): a flag-gated branch in the free-text
> handler routes to the orchestrator when `WORKSPACE=on` (else Legacy,
> byte-identical); a `SyncWorker` drains the outbox on the existing
> scheduler; the production Telegram sender and the `LLMInterpreter`
> (baka_brain, with a rule-based fallback) are injected. The Workspace OS
> now runs inside the real app behind the flag. **Next:** Workspace
> templates (Game, Books, Research, richer Projects) built on this
> production-ready platform, plus Workspace UI/commands — see
> docs/v15/MIGRATION.md §7.
>
> **`v15.0-beta.2` — Game template (reference implementation):** the first
> new Workspace type added on the production platform, proving a full
> Workspace drops in as one module (`templates/game.py`: schema +
> validation + registration) with **zero OS changes**.
>
> **`v15.0-beta.3` — Knowledge template:** the pattern applied a second
> time, to an educational/knowledge domain
> (`templates/knowledge.py`: 🧠 concepts → milestones, sources/notes →
> notes, mastery% via `PROGRESS_MANUAL`), again with **zero OS changes** and
> coexisting with the Game template.
>
> **`v15.0-beta.4` — Asset template:** the pattern applied a third time and
> at its broadest — **one reusable template for any physical asset**
> (`templates/asset.py`: 📦 vehicle/computer/drone/robot/…, the kind is just
> `metadata['asset_type']`; maintenance → milestones, service records →
> notes, components → tags, ownership/maintenance history → Timeline,
> maintenance completion via `PROGRESS_MILESTONES`), with no per-type logic
> and **zero OS changes**.
>
> **`v15.0-beta.5` — Project template:** the pattern applied a fourth time,
> to an **execution-focused domain** (`templates/project.py`: 🛠 a project
> driven through the Research→Documentation milestone pipeline; phases/tasks
> → milestones, worklog → notes, execution % via `PROGRESS_MILESTONES`).
> This milestone also **took ownership of the `project` template** — moved
> out of `builtin.py` into its own module (as beta.2 did for `game`), shape
> preserved so the alpha.3 `ProjectAdapter` bridge is unaffected. Four
> independent drop-in templates now coexist. **The Workspace OS is frozen.**
>
> **`v15.0-rc.1` — release-candidate hardening:** the final RC before v15
> Stable. A repository-wide cleanup + documentation-quality pass (top-level
> Markdown 27 → 13, v14 docs relocated to `docs/architecture` + `docs/history`,
> tracked runtime artifacts removed, README rewritten for GitHub, help
> polished, hygiene regression tests added) with **zero Workspace-OS behavior
> change**. See [docs/v15/RC1_AUDIT.md](docs/v15/RC1_AUDIT.md).
> **Next:** canary-enable `WORKSPACE` → default-on, user-facing Workspace
> commands/UI, and further templates (Finance, Personal Knowledge, …)
> following this exact pattern.
>
> **`v15.1.0-alpha.1` — Workspace groups (the first usable Workspace
> feature):** mirror a project/game/goal to a **private Telegram forum
> group** — each entity is a topic, photos+notes are a progress journal.
> New commands (`/newproject|newgame|newgoal`, `/linkhere`, `/add`,
> `/open`, `/note`, photo → progress), always available (not tied to the
> `WORKSPACE` flag). The core stays Telegram-agnostic; bindings live in a
> separate **projection adapter** layer. First slice; next: editing/removal,
> richer entities, and per-entity views.
>
> **`v15.1.0-alpha.2` — GLM 5.2 migration & AI foundation:** a reliable,
> cleanly-abstracted AI base in `core/ai/` — provider presets
> (`nvidia-nim`/`glm`/`local`, config-only GLM 5.2 migration), a
> reliability retry/backoff + typed-error taxonomy, and the retrieval + tool
> *interfaces* (foundation only). Byte-identical for NIM. The full **AI
> Intelligence Layer** (planner, tool orchestration, memory, retrieval,
> offline intelligence) builds on this in subsequent milestones.
>
> **`v15.1.0-alpha.3` — Cognitive Engine, Phase 1:** planner + tool
> orchestration over the Workspace OS. `/ws <question>` reasons over real
> Workspace data via grounded tools (`core/ai/workspace_tools.py`,
> `cognition.py`, `llm_planner.py`) — the model routes, the tools ground, so
> answers can't be fabricated; conversation context (active workspace) makes
> follow-ups work without renaming.
>
> **`v15.1.0-alpha.8` — Real retrieval:** the first concrete `Retriever`
> (`workspace_retriever.py`) ranks everything stored in a workspace
> (entities, statuses, notes) by relevance; a `recall` tool lets `/ws`
> answer broad questions ("what do I know about Hu Tao?") grounded in
> retrieved data, no per-question command.
>
> **`v15.1.0-alpha.9` — Structured per-entity fields:** every template
> (`game`/`knowledge`/`asset`/`project`) now declares its own entity-level
> field schema (name, type, validation, defaults) via `FieldSpec` in the
> registry. A `fields TEXT` JSON column on milestones stores per-entity
> data (level, element, materials, effort_hours, etc.) — additive, NULL-safe,
> fully backward compatible. `get_fields()` / `set_fields()` / `update_field()`
> on the Entity Engine validate against the template schema. Scalar field
> values are included in the WorkspaceRetriever's search corpus, making them
> discoverable through the `/ws` recall query.
>
> **`v15.1.0-alpha.10` — Natural Language Entity Management & Release
> Standards:** the alpha.9 entity system is now fully usable through natural
> language. `EntityManager` (`core/ai/entity_manager.py`) translates free text
> like "Create character Furina" or "Hu Tao is level 80" into Entity Engine
> operations using the fast AI call as a lightweight classifier — no commands,
> no JSON, no developer tools. A keyword pre-check avoids useless LLM calls
> on non-entity messages. Also ships `/commands` (a complete reference, not
> the beginner-friendly `/help`), updated `/help` with entity NL examples, a
> Release Checklist standard, and the project's first permanent release
> engineering conventions (version management, documentation, developer
> experience rule).
>
> **`v15.1.0-alpha.11` — Final Stabilization & Production Readiness:**
> fixes routing (EntityManager runs before task VIEW handler), field mapping
> (added `weapon` field vs `weapon_type`), retrieval (entity-aware field search),
> entity display cards, logging, and Telegram UX. 16 new tests, 1234 passing.
>
> **`v15.2 M2` — BAKA Brain · Tool Contract Foundation (dormant, done):**
> the first v15.2 milestone. `core/ai/tools.py` is extended into the single,
> unified tool abstraction the future AI Worker will run on: `RiskLevel`
> (READ_ONLY/MUTATING/DESTRUCTIVE/SYSTEM), validated `ToolSpec` metadata
> (risk / confirmation_message / requires_admin), a unified `ToolResult` +
> stable `ToolError` codes, and fail-closed argument validation —
> `ToolRegistry.register` rejects malformed schemas and duplicate names,
> `ToolRegistry.execute` never lets invalid args reach a handler, and
> `Tool.execute` contains every failure. **1380 offline tests passing** (79
> new in `tests/test_tool_contract.py`), self-test probe "AI Tool Contract",
> regression suite TLC-001…004.
>
> **`v15.2 M3` — BAKA Brain · Real Tool Adapters (dormant, current):**
> `core/ai/tool_adapters.py` maps each real capability to **24 thin
> M2-contract `Tool`s** (`build_tool_registry(user_id, …)`): tasks
> (list/find/create/update/complete/delete), habits (create/list/complete),
> goals (create/list/update-progress), entities (create/get/update/list/find
> — reusing the M1 ReferenceResolver), workspace (list/get/open/inspect) and
> memory/recall (get/search/grounded recall). Every tool is argument
> translation + validation + a call into BAKA's existing services (Storage
> facade, EntityEngine, WorkspaceGroups, TelegramProjection) with a
> structured `ToolResult` (ids, fields, workspace, projection status). Honest
> risks (writes MUTATING incl. `open_workspace`, `delete_task` DESTRUCTIVE
> with a confirmation message, nothing SYSTEM). Entity create/update drive
> the **same alpha.13 projection** `/add` uses — one topic, append-only
> updates, never a second topic mechanism. **1423 offline tests passing** (43
> new in `tests/test_tool_adapters.py`, incl. Genshin acceptance fixtures +
> RecorderProj/FakeClient integration proving the projection is not
> bypassed), selftest "AI Tool Adapter Registry" + "… Round-trip", regression
> suite TAD-001…005. No Worker, no loop, no `main.py` routing change — the
> adapters are dormant and health-verifiable via `/selftest`.
> See `docs/engineering/V15_2_BAKA_BRAIN.md`.
>
> **`v15.2 M4` — GLM-5.2 Worker (dormant, current):** the bounded tool-calling
> executor. `core/ai/worker.py` (+ `worker_contract/parser/prompt`) converts
> ONE message into at most **4 tool calls** through a `ToolRegistry`
> (`MAX_TOOL_CALLS` is a Python constant, not widenable via any input/env),
> then one final reply — never touching a database/Telegram/raw handler
> directly. A fail-closed structured-output parser (replaces the greedy
> `clean_json` `r"{.*}"` extractor; exactly ONE top-level object; multi-object
> → `MALFORMED`). A mechanical confirmation gate BEFORE execute reuses the
> existing `conversation_state.py` pending-action machine (`delete_task` never
> runs silently) — no second confirmation system. A deterministic
> never-fabricate-success guard blocks success claims without a backing
> `ok=True` result. M1 resolver stays authoritative; `date_parser` is
> authoritative for dates. `call_worker_single` = ONE MODEL_MAIN attempt, no
> retry, no fallback. Owner-only canary: `WORKER=1` activates only for the
> owner, running after the deterministic menu/confirming/editing/gathering/
> NL-map gates but BEFORE the EntityManager + task VIEW quick-match, falling
> through to EntityManager → VIEW → Legacy when it declines or fails.
> **1484 offline tests passing** (61 new: `tests/test_worker.py` +
> `test_worker_parser.py`), selftest "AI Worker (dormant)" + "AI Worker
> Deterministic Round-trip", regression WKR-001…022, new `feature_flags.WORKER`
> (OFF). **Known limitation (scenario 14):** task ordinals NOT implemented.
> **No live Telegram acceptance claimed** until the WKR matrix is run.
> See `docs/engineering/V15_2_BAKA_BRAIN.md`. **Next (M5):** real-GLM smoke +
> the live acceptance matrix, widening the canary, task ordinals, any routing
> migration beyond the single dormant seam.
>
> **`v15.2 M4 orchestration` — typed referents, goal-deadline tool, type-aware
> retrieval, routing order (current):** generic fixes for the ten live M4
> orchestration failures (DEBUGGING.md's resolved table maps failure → root
> cause → fix). `core/ai/typed_referents.py` makes tool results first-class
> typed context (per-kind, recency-ordered; a just-created id beats a stale
> active entity; a pronoun pointed at a different kind is refused — never
> reaches across domains). `update_goal_deadline` adapter +
> `database.update_goal_deadline()` make the goal domain OWN its deadlines
> (no more target_level corruption). `date_parser` resolves "next month end" /
> "end of next month" deterministically. `milestones.entity_type` (additive,
> idempotent migration) makes identity (workspace, kind, id) and enables a
> structured `list_entities(entity_type=…)` filter — "show all characters"
> returns ONLY characters. In `handle_message` the owner-only Worker seam now
> runs AFTER the deterministic menu/confirming/NL-map gates but BEFORE the
> EntityManager + task VIEW quick-match, so compound / typed-retrieve requests
> are never hijacked by "Tasks for All Pending" (`WORKER=0` path unchanged).
> **1563 offline tests passing** (+54: the parametrized GENERIC-INVARIANT
> suite S1–S30 / WKR-028…030 added after the second live pass — create→set→show
> across character/weapon/artifact names, show→update→show, two independent
> entities, cross-domain same-name identity, stale-active + fresh-create
> pronouns, goal-referent conflicts, failed-tool recovery, success+failed
> retrieval traces, never-fabricate-success, unknown referents never mutating
> the active entity, max-steps honest summary, typed list filters never mixed
> kinds, task/habit domain isolation, artifact/weapon retrieval after create,
> and deadline-clear S30 — `update_goal_deadline` clearing to `None` is a
> success, not a false "not found"). Selftest 25 PASS / 0 FAIL / 1 WARNING
> (offline AI probe). **Forensic note:** the second live pass's 7 failures were
> ALL legacy-path — bot.log proves the Worker never ran (`WORKER=0`, not in
> `.env`); ZERO failures map to GLM-5.2 / the Worker / typed referents. **No
> live Telegram acceptance claimed** until `WORKER=1` + restart + the manual
> matrix is run.
>
> **`v15.2 M4 live validation` — temporary `meta/llama-3.1-8b-instruct`
> (current, 2026-08-11):** the 31-message live matrix (Phases A–F, real Bot,
> `WORKER=1`) run on Llama because NVIDIA `z-ai/glm-5.2` serves NO output
> upstream (60–150s timeout probes; the id lists on `models.list()` but the
> model worker hangs — a provider problem, NOT a Worker problem; GLM-5.2 is
> NOT deprecated, the provider/model abstraction stays intact for later Z.ai /
> healthy-NVIDIA evaluation). **11 genuine full Worker PASSes**; 4 legacy
> fallthroughs (Worker `declined`/`tool_failure` → legacy, incl. a Telegram
> topic-creation ReadTimeout); the rest ran the Worker but didn't complete
> compound intent (Llama capability, not architecture — the referents block
> and tool catalog were correct in every case). **3 tool-contract ARCHITECTURE
> fixes** (generic, none phrase-specific): workspace specs accept
> `string|integer` (KNOWN REFERENTS renders `ws=1` ints); `validate_args`
> normalizes "leave-it-out" markers (`''`/`omit`/`none`/`all`/`any`) on
> optional args to "no filter"; `_require_workspace` falls back to the active
> workspace on an unmatched name. Live-retest verified the C8 fix end-to-end
> via bot.log (Worker→ToolRegistry→`list_entities(status='',…)`→`ok`→reply).
> **1569 offline tests passing** (+6 new tool-contract regression tests +
> WKR-031), selftest 26 PASS / 0 FAIL / 0 WARNING. **M4 NOT accepted as
> production-ready for compound commands with Llama-8b** — the seam is
> validated (11 genuine successes), but Llama's single-step/decline/
> arg-extraction limits are model capability. **Next:** the M4 remediation
> (below) — per the owner directive, an M4 PATCH version, NOT M5.
>
> **`v15.2 M4 remediation` — the 18-cluster fix list (current, 2026-08-11):**
> **the next release is a v15.2 M4 PATCH, never M5** (owner directive). Every
> fix is generic + regression-tested + documented — none phrase-specific.
> Shipped: item 1/15 `EntityKindResolver` (DB→explicit→hint kind resolution,
> offline-deterministic); item 2 typed `list_entities(kind=…)` invariants;
> item 3 compound execution (MAX_TOOL_CALLS 4→6 with rationale + renderer +
> honest MAX_STEPS budget note); item 4 goal-deadline domain safety via typed
> referents; item 5 `date_parser` relative ranges ("next week", "this/next
> month end", weekends) resolved against the IST app clock + the intent-engine
> QUERY-not-ADD guard; item 6 canonical one-topic-per-entity keyed
> `(workspace_id, entity_id)` + title-normalized dedupe; items 7/8/10 generic
> TopicProjection tools (`get/ensure/set_locked/delete/list` entity topic,
> delete is DESTRUCTIVE + confirmation, locked topics refuse ordinary delete);
> item 9 `/topicrepair` self-heal (duplicates collapse to one topic, kind
> adopted, idempotent); item 11 workspace-lifecycle audit (deletion stays
> DB-only — pinned by an invariant that any future delete/archive workspace
> tool is DESTRUCTIVE + confirmation); items 12/13 response-format restoration
> (`worker_render.py` — Worker decides WHAT, existing BAKA formatter decides
> HOW; cards, escaping, emoji, honesty preserved); matrix E (20 topic tests) +
> matrix H additions; 2 new selftest probes ("Topic Lifecycle Tools", "Topic
> Repair"); `/topicrepair` in `/help`; regression specs WKR-024…031 (incl. the
> renderer-invariant + topic-lifecycle specs); the AI-category selftest probes
> updated to the 30-tool surface + MAX_TOOL_CALLS=6. Full pytest **1631
> passing**, full offline selftest **28 PASS / 0 FAIL / 0 WARNING**. Version
> stamped **15.2.0-alpha.14** (item19); final report written
> ([docs/engineering/V15_2_M4_REPORT.md](docs/engineering/V15_2_M4_REPORT.md)).
> **Remaining before the M4 patch is accepted:** the live revalidation
> matrix only (item17 live portion — owner runs WKR-001…031 with WORKER=1).
> **Next (after M4 is accepted, still not yet):**
> Z.ai-native / healthy-NVIDIA GLM-5.2 smoke + live acceptance on a stronger
> model, then widening the canary and task ordinals — that is M5 territory.
>
> **`v15.3 M5 — Manual Control Plane + Lifecycle (current):** the owner can
> reliably control and repair BAKA manually, through the SAME underlying
> tool/domain capabilities the AI uses (binding layering: AI Worker → Manual
> Dashboard → Telegram commands → Tool Registry → domain services → DB /
> Telegram projection — the dashboard NEVER writes the DB directly, and there
> is no second business-logic layer). Shipped: 7 thin registry tools
> (`create/rename/close/archive workspace`, `delete_entity`, `repair_topics`,
> `equip_item` — catalog 30→37, additive); the `core/control/` module (pages,
> registry, actions, router); admin-only `/control` with `ctl:` callbacks; the
> ONE shared M5-F confirm flow (`begin_confirm`/`confirm_yes`/`confirm_no`,
> wording from the tool spec, cancel never executes); the generic entity pages
> per kind (no Genshin hardcoding); the Topic Control Center (locked topics
> refuse ordinary delete, [Unlock]/[Force delete]/[Back] dialog); the Identity
> Inspector (exactly 8 rows, no secrets); minimal M5-E equipment (character
> `weapon` field only — stats/refinement = M6+); no-active-workspace states
> everywhere. Offline test surface: `tests/test_control_panel.py` (38),
> `tests/test_m5_adversarial.py` (41 — the 14-scenario M5-H matrix), the new
> tool tests in `tests/test_tool_adapters.py`, 2 new selftest probes, and the
> `control_m5.py` regression spec (CTRL-001…010). **Version stamped
> v15.3.0-alpha.1.** Full design + layering + invariants:
> [docs/engineering/V15_3_MANUAL_CONTROL_PLANE.md](docs/engineering/V15_3_MANUAL_CONTROL_PLANE.md).
> **Remaining before M5 is accepted:** live-Telegram acceptance matrix
> (owner-run, CTRL-001…010 — documented, not claimed offline). **Next (M6+, out
> of M5 scope):** richer equipment model (stats/refinement/equipped-to linkage),
> the M6 media vault, M7 cross-topic retrieval, M8 advanced goal logs.
>
> **`v15.4 M6 — Knowledge + Media + Tags (current):** BAKA becomes a
> persistent personal knowledge/data-dump system: notes + media metadata + tags,
> retrievable by entity/topic/tag/workspace/text/media-type/date, with Telegram
> as canonical media storage. Binding layering (unchanged from M5): Worker →
> Tool Registry → Domain Service → DB/Telegram projection; Manual Control Plane
> → Tool Registry → same Domain Service. **No second business-logic path.**
> Shipped: schema extension (notes: title/updated_at/deleted_at; attachments:
> 8 new columns + 2 new junction tables `note_entities`/`attachment_entities`;
> tags: workspace_id + partial unique index); 22 new tools (notes 9, media 9,
> tags 4 — catalog 37→59); `core/control/` Knowledge/Media/Tags pages; media
> capture handler for video/document/audio/voice; full test matrix A-E
> (`tests/test_m6_knowledge.py` 35 tests) + adversarial F-I
> (`tests/test_m6_adversarial.py` 21 tests); selftest probes
> (`test_knowledge_selftest.py` 3 probes); regression suite KNOW-001…012;
> docs/engineering/V15_4_KNOWLEDGE_MEDIA.md. **Version stamped
> v15.4.0-alpha.1.** **Remaining before M6 is accepted:** live-Telegram
> acceptance matrix (owner-run, KNOW-001…012 — documented, not claimed
> offline).
>
> **`v15.5 M7 — Cross-Reference Retrieval (completed 2026-08-14):** single
> retrieval implementation (`core/retrieval/service.py::CrossReferenceService`)
> that composes M6 NoteStorage/AttachmentStorage via EntityEngine with AND/OR
> filter semantics (entity AND/OR, tag AND/OR, combined). Three READ_ONLY
> tools added to the shared registry: `search_knowledge` (unified notes+media),
> `search_notes_cross` (notes only), `search_media_cross` (media only).
> Filters: free-text q (title/content/caption/filename/extracted_text),
> entity list + mode, tag list + mode, media_type, date range
> (created_after/created_before, IST-aware), kind (notes), limit (default 50,
> max 200). Results carry `_type` discriminator ("note"|"media"). Active
> workspace isolation mandatory — never silently searches across workspaces.
> Control plane (`ctl:search` page + 8 gather handlers) uses the SAME service
> as Worker (no second logic). **fix1:** Stateful Search UI Builder — fixed
> the bug where each gather handler cleared state, making compound searches
> impossible. Added `conversation_state.py` search state functions, all 8
> handlers now accumulate filters via `set_search_state`/`get_search_state`.
> Added ��� Entities button, �� Clear callback, entity filter handler.
> Full test matrix A–R (73 tests in `tests/test_m7_retrieval.py`),
> regression suite RET-001…038, selftest probes (`test_retrieval_selftest.py`
> 4 probes), docs/engineering/V15_5_CROSS_REFERENCE_RETRIEVAL.md §12,
> `docs/RET_LIVE_CHECKLIST.md` for owner-facing live tests. **Version stamped
> v15.5.0-alpha.1+fix1.** **Remaining before M7 is accepted:** live-Telegram
> acceptance matrix (owner-run, RET-001…038 — documented, not claimed
> offline).
>
> **`v15.1.0-alpha.13` — Telegram Entity Topic Projection & Backfill (M10,
> current):** closes the topic gap. Every entity-creation path — `/add`,
> natural language ("Create character Arlecchino"), and the new admin-only
> `/topicbackfill` migration op — converges on ONE idempotent entity ⇒
> Telegram topic ⇒ initial-card contract (`WorkspaceGroups.create_entity` +
> `TelegramProjection.ensure_entity_topic`; `EntityManager` composes the same
> primitives through a Telegram-agnostic injected projection seam). NL-created
> entities get topic + binding + initial card automatically; existing entities
> are backfilled generically (soft-deleted excluded, unlinked skipped,
> idempotent re-run, initial cards rendered from live DB state by
> `core/workspace/render.py`). Updates append a minimal message to the topic
> (`post_entity_update`, self-healing). Failure model documented: DB entity
> durable; topic+binding the durable Telegram unit; sends best-effort;
> transient binding-write failures retried once; persistent failure leaves an
> orphan topic recoverable by re-run. **1301 offline tests passing**, Workspace
> self-tests green, regression suite TOP-001…TOP-009. Live-Telegram acceptance
> pending the manual matrix (A–G). See
> `docs/engineering/M13_TOPIC_PROJECTION.md`. **Next:** M2 (robust JSON decode
> + clarification instead of incorrect fall-through), then M3 field-aware
> retrieval, M4 task lookup, M5 reminder/view semantics, M6 confirmation
> truthfulness, M7 deterministic dates, M8 unified tool surface + bounded AI
> worker loop, M9 field semantics/schema validation. v15.1.0-beta.1 and BAKA
> Brain v15.2 follow the milestone sequence, not the other way around.
>
> **`v15.1.0-alpha.12` — Conversational Entity References & Active Entity
> (M1):** the first milestone of the AI-worker roadmap. The bot now
> resolves conversational references deterministically against real context:
> pronouns ("show her/him/it"), ordinals ("show the first one / last one"),
> and bare follow-ups ("what level is she?") — using the DB-backed *active
> entity*, a per-user *recent-mention* stack, and the *last ordered list*
> shown (`core/ai/reference_context.py`, `core/ai/reference_resolver.py`,
> wired into `EntityManager`). Obvious single-field updates ("Sucrose is
> level 70") are applied deterministically, without the LLM. Ambiguous
> references ask for clarification instead of guessing; stale/deleted
> entities are re-validated and never resurrected. 35 new offline tests,
> **1269 passing**, plus M1 regression specs and a self-test probe. The
> `Can she ascend further?` strong-pronoun routing gap is documented as a
> known limitation.

**A note on version numbers:** the original `VERSION.md` roadmap section
labeled ideas `v12.0` (Voice Notes) through `v14.3` (Themes) — written
*before* v12.0 actually shipped as "Project Management" (see
[CHANGELOG.md](CHANGELOG.md)). Those numbers now collide with real
released versions. This file drops fixed version numbers for backlog items
and groups by priority/theme instead. Treat "Next up" as literally next;
everything else is unordered backlog, not a commitment.

---

## v14.0 Autonomous Core migration status

Tracking `DESIGN_SPEC_v14_AUTONOMOUS_CORE.md` §11's 6-stage migration.
**Stage numbers, not version numbers, on purpose** — see the note above
about the old `VERSION.md` roadmap's fixed version labels colliding with
what actually shipped; the authoritative design doc itself uses Stage
0–5 for the same reason.

- ☐ **Stage 0** — AI-call analytics. Reframed by v14.12: the stranded,
  never-importable source files were deleted in the repository cleanup,
  so this is now a **build-from-scratch v15 item** (alongside the AI
  Router, which wants the health data), not a packaging fix.
- ✅ **Stage 1 — Intent Engine (Shadow Mode).** Shipped v14.0
  (`core/intent/`). Classifies every message deterministically via a
  tiered rule set reusing `date_parser.py`; does not yet affect routing.
  See [CHANGELOG.md](CHANGELOG.md).
- ◐ **Stage 2 — Offline Engine** for already-offline commands (in progress).
  The Intent-Aware Routing piece of this stage has an approved design
  ([DRG-001_Intent_Aware_Routing.md](docs/history/DRG-001_Intent_Aware_Routing.md),
  informally "v14.1A"; see [ADR-006](docs/adr/ADR-006-intent-aware-routing.md))
  and its Sub-stage B ("Decision") is now shipped as v14.1B — a real
  Routing Layer (`core/routing/`) runs on every message and logs a
  recommended destination, but always executes via Legacy (hard-coded).
  Sub-stage C (real routing, one command group at a time) and Sub-stage D
  (Legacy removal) are not started — the Offline Engine itself
  (`OFFLINE_ENGINE.md`) does not exist yet, so `core/routing/`'s
  `OFFLINE_ENGINE_IMPLEMENTED_INTENTS` set stays empty until it does.
  v14.1C added the plumbing the Offline Engine needed: a Storage Facade
  (`core/storage/`, thin delegation to `database.py`, no new data-access
  abstraction — see that sprint's Phase 0 review in `CHANGELOG.md`) and
  four gradual-rollout feature flags (`core/feature_flags.py`:
  `OFFLINE_TASKS`/`OFFLINE_HABITS`/`OFFLINE_GOALS`/`OFFLINE_PROJECTS`).
  v14.2 shipped the Offline Engine itself (`core/offline/`, `core/actions/`,
  [ADR-007](docs/adr/ADR-007-offline-engine-stage1.md)) — read-only task
  actions only (list/today/week/search). **v14.3 shipped its first write
  operation, task creation**
  ([ADR-008](docs/adr/ADR-008-offline-write-operations.md)) — a two-phase
  propose/confirm/commit flow reusing `conversation_state.py`'s existing
  machinery so Legacy's "always confirm before writing" property holds
  for the Offline path too. Still gated behind `OFFLINE_TASKS` (still
  OFF — no deployment has enabled it yet). Recognizes exactly four
  explicit verb commands (`add task`/`create task`/`new task`/`todo`);
  free-form natural-language task creation ("remind me to...") remains
  Legacy-only, since title extraction needs the AI this Offline Engine
  explicitly excludes. **v14.4 shipped a second write operation, task
  update** ([ADR-009](docs/adr/ADR-009-offline-task-update.md)) — applies
  directly with no confirm step, genuinely matching Legacy's real update
  behavior (verified: Legacy itself doesn't confirm updates either,
  despite the task brief that requested this sprint assuming it did).
  Supports date/time/priority/category/title changes; recurrence changes
  remain unsupported in *both* paths (verified: `database.update_task()`
  has no recurrence parameters — not an Offline gap, a real Legacy
  limitation). **v14.5 shipped a third write operation, task delete**
  ([ADR-010](docs/adr/ADR-010-destructive-operations-policy.md)) — the
  first (and so far only) case where Offline deliberately does *not*
  match Legacy's real behavior: Legacy's `/delete <id>` deletes
  immediately with zero confirmation (verified), but Offline Delete adds
  one, justified by irreversibility. `ADR-010` generalizes this into a
  reusable policy for future write operations: confirm when irreversible,
  match Legacy otherwise. Idempotent (a repeated confirmation or
  concurrent delete is reported gracefully, never double-executed) and
  self-verifying (re-checks the row is actually gone before reporting
  success). **v14.6 shipped a fourth write operation, task completion** —
  direct apply matching Legacy's real no-confirm behavior, exactly as
  `ADR-010`'s policy predicted for a row-preserving operation.
  Replicates Legacy's learning-log side effects
  (`completions_log`/`interaction_log`, including the exception swallow)
  via a new `LearningStorage` facade domain; habits branch away to
  Legacy's streak logic untouched; no undo exists in either path
  (verified Legacy has none — documented per the Reversibility Review,
  not invented). **v14.7 shipped the final Task-domain stage, task
  lifecycle** — pause/resume/snooze/stop-reminders/carry-forward/
  paused-view, all direct apply matching Legacy's real no-confirm
  behavior, with snooze's learning-log side effects replicated. Verified
  non-existent in Legacy and deliberately not invented: archive/restore/
  hide/unhide/unsnooze. Delreminder needed nothing (a delete alias,
  already covered by v14.5's delete path). Also produced
  [ADR-011](docs/adr/ADR-011-conversation-state-priority.md): the
  conversation-state-ordering question is now a documented architectural
  decision (recommendation: state outranks intent-gated dispatch;
  implementation deliberately deferred — a named pre-enablement
  blocker). Still gated behind `OFFLINE_TASKS` (still OFF — no
  deployment has enabled any stage yet).
  `OFFLINE_HABITS`/`OFFLINE_GOALS`/`OFFLINE_PROJECTS` remain
  unimplemented. **The Task domain is feature-complete under the new
  architecture** — every deterministic, message-path Task operation
  Legacy supports now exists behind the flag. v14.7.1 completed the
  Release Candidate architecture validation
  ([RC_v14_ARCHITECTURE_VALIDATION.md](docs/history/RC_v14_ARCHITECTURE_VALIDATION.md)
  — review only, no defects requiring code found; includes the canary
  deployment plan and the three-phase Legacy removal plan). **v14.8
  executed the RC's required pre-Habits refactor**: `OfflineEngine`'s
  if/elif intent ladder replaced by registry-based dispatch
  ([ADR-012](docs/adr/ADR-012-registry-based-dispatch.md) —
  `core/offline/registry.py` mechanism + `registrations.py` explicit
  build; byte-identical behavior verified against the pre-refactor
  commit; adding an Offline action no longer touches the dispatcher).
  **v14.9 began the second domain — Offline Habits Stage 1** (the three
  read-only views: habits list, streak detail, habit log), the
  registry's proof sprint: shipped with zero engine/registry edits.
  Per-domain flags now gate at registry construction
  ([ADR-013](docs/adr/ADR-013-per-domain-registry-construction.md));
  `OFFLINE_HABITS` is consumed for the first time (still OFF).
  **v14.10 completed Habit Stage 2** — creation and skip migrated
  (both direct-apply/no-confirm, matching Legacy per ADR-010); habit
  "update"/"delete" verified to need no habit code (task edit/delete
  flows already cover habit rows — test-pinned). **v14.11 completed
  the Habit domain** — completion migrated (the habit branch of
  `done_task()`: streak log only, NO learning logs — verified and
  mirrored; v14.6's `habit_not_supported` branch-away retired in every
  Habit-enabled configuration, retained only as the cross-domain guard
  for tasks-without-habits builds). **The Habit domain now has 100%
  deterministic message-path parity with Legacy.** Verified
  non-existent, never to build: habit update/delete/today/search/
  statistics/archive/restore commands. Callback-driven habit surfaces
  (dashboard card, reminder done-buttons) remain Legacy, like all
  callbacks. **v14.12 (Production Readiness) applied ADR-011 Option A**
  — the last architecture blocker — plus rich UI (/help, /selftest),
  the bot-token log-leak fix, provider-agnostic AI config,
  requirements audit, and repository cleanup. **The only step left
  before enabling `OFFLINE_TASKS`/`OFFLINE_HABITS` is running the
  canary per RC_v14_ARCHITECTURE_VALIDATION.md's plan** (plus rotating
  the two exposed credentials — see DEBUGGING.md).

  **UI Overhaul** (Board-approved, spec frozen —
  [UI_SPEC_v1.md](UI_SPEC_v1.md)): Phase 0 shipped in v14.13
  (`ui_components.py` + tests, deliberately unwired). Remaining phases
  per spec §15: 1 (re-express `ui.py` cards) → 2 (Dashboard) → 3–8
  (Tasks+Duplicate, Habits, AI Hub, Developer Center, Statistics,
  Settings) → 9 (Polish); each gates on spec §13.3's review checklist.

  **QA system** (design: [QA_SYSTEM_DESIGN.md](QA_SYSTEM_DESIGN.md)):
  three independent layers — pytest (automated), `core/selftest`
  (runtime health), and `core/regression` (manual behaviour). **Phase 1
  shipped in v14.23**: the regression *specification* foundation
  (`core/regression/` — spec model, registry, categories, version-aware
  history store) + the authored **Quick Release Suite** (28 tests). The
  **Definition of Done** rule (CLAUDE.md) is now permanent: every
  user-visible feature owns its regression tests + docs. Remaining QA
  phases (later milestones, per the design's Q-roadmap): expand toward
  the Major/Full suites, then the Regression Runner, the 🐞 Bugs and
  🧯 Regression Tests Developer Center screens, and Test History/Stats.

  **Self-Test framework** (v14.22, `core/selftest/`): admin-only runtime
  health runner reached from the Debug Menu's 🧪 Self Test button —
  registration-based, so every future feature registers its own live
  checks without editing the runner ([docs/selftest.md](docs/selftest.md)).
  This also delivered the first piece of UI_SPEC §10's Developer Center
  (the admin-only `/debug` menu); the rest of S39–S44 (logs, engines,
  flags panels) can hang off the same `dev:*` namespace when their
  phase runs. Natural next additions: register self-tests for reminders/
  deadlines, projects/materials, and the AI-router health once it lands.

  **Naming note**: task creation/update are sometimes called "Offline
  Engine Stage 2/Stage 3" in their own commit messages and ADR titles
  (`ADR-008`/`ADR-009`) — this is a *different*, nested numbering from
  the master-spec "Stage 3 — AI Router" entry immediately below, which
  hasn't started. Same kind of numbering collision this file's own intro
  note already warns about; flagged explicitly here rather than left to
  cause confusion.
- ☐ **Stage 3 — AI Router**, NVIDIA-only.
- ☐ **Stage 4** — additional AI providers (OpenAI/Anthropic/Gemini adapters).
- ☐ **Stage 5 — Plugin System** (proof of concept via Projects).

**On version labeling:** an earlier task brief for this milestone
suggested fixed version numbers per stage (`v14.1`/`v14.2`/`v14.3`/
`v14.4`/`v15.0`). Deliberately not adopted — it would reintroduce the
exact collision problem this file already moved away from once (see the
note at the top of this file), and it doesn't match
`DESIGN_SPEC_v14_AUTONOMOUS_CORE.md` §11's own Stage-based language.
Flagged here rather than silently diverging without explanation.

---

## ✅ v15.6 Phase 4 — Characterization Testing Pipeline (completed 2026-08-24)

**Full characterization + regression lock + live acceptance testing pipeline.**

| Phase | Description | Tests | Status |
|-------|-------------|-------|--------|
| **4A** | Habit Behavior Characterization — freeze current habit behavior as baseline | 37 | ✅ Done |
| **4B** | Snapshot Regression Lock — golden-file snapshots of habit flows | 37 | ✅ Done |
| **4C** | Callback Regression Lock — all 20+ callback actions verified | 58 | ✅ Done |
| **4D** | Live Telegram Acceptance — Playwright tests against QA bot (`Baka_qa_bot`) | 3 | ✅ Done |

**Total: 135 tests passing**

### Key Deliverables

- **Offline characterization tests** (`tests/behavior/`): 132 tests freeze behavior as regression baseline
  - `test_habit_behavior.py` (37) — habit CRUD, completion, streaks, reminders, list views
  - `test_habit_snapshot.py` (37) — golden snapshots of habit flows
  - `test_callback_behavior.py` (58) — all dashboard/task/project/vision/dev/control-plane/card/integration callbacks
- **Playwright Live Acceptance** (`testing/playwright/`): 3 tests against real Telegram Web
  - `00_bootstrap_login.spec.ts` — QA account login, session persistence
  - `01_start.spec.ts` — `/start` command execution with screenshot
  - `02_commands.spec.ts` — `/help` + `/tasks` commands with screenshots
- **Infrastructure fixes**:
  - `instance_lock.py` — Cross-platform singleton (fcntl on Linux, CreateMutexW on Windows)
  - PTB 20.7 → 22.8 upgrade (Python 3.14.4 compatibility)
  - Playwright config: `workers: 1, fullyParallel: false` + `--no-sandbox --disable-setuid-sandbox`
  - Multiple selector fallbacks, `waitFor({state: 'visible'})`, crash handlers
- **Self-Test Suite**: 38 passed, 0 failed, 1 warning (AI API key not set)
- **Workspace Selftest**: 7 passed (template, engine, groups, cognitive, retrieval)

### Documentation
- Live testing workflow: [docs/testing/index.md](../testing/index.md)
- Playwright QA infrastructure in `testing/playwright/`

---

## ✅ v15.6 Phase 5A — SQLite Infrastructure Stabilization (completed 2026-08-25)

**Resolved persistent "database is locked" error preventing self-tests from running on WSL network share.**

- Root cause: WSL network share (`//wsl.localhost/Ubuntu`) doesn't support proper SQLite file locking — pytest tests passed (using `tmp_path` on local filesystem) but self-tests failed (using real `planner.db` on network share)
- Fix: Modified self-test runner (`core/selftest/runner.py`) to create a temporary database on the local filesystem (Windows `%TEMP%`) and patch `DB_NAME` in `database.py`/`scheduler.py` before test discovery, mirroring the pytest `temp_db` fixture pattern
- Module caching handled by clearing `sys.modules` cache for `database` and `scheduler` before patching
- Self-test `test_database.py` simplified to use runner's temp DB instead of creating its own
- **Validation:** 37 passed, 1 failed (AI Config - expected, no API key), 1 warning (AI Worker - Unicode logging), 0 skipped
- Offline pytest suite fully passes (33 database tests, 40 scheduler tests, 119 habit tests, 115 task tests)

---

## ✅ v15.7 Phase 5B.1C — Analytics Implementation (completed 2026-08-25)

**Restored and modernized the analytics package for NVIDIA NIM architecture.**

### Deliverables
- **analytics/__init__.py** — Public API surface re-exporting 20 symbols (19 functions + `MODEL_COSTS` constant)
- **analytics/usage_logger.py** — Async fire-and-forget logging with background writer thread, WAL mode initialization, `log_ai_request()`/`log_image_request()`/`init_usage_table()`/`shutdown_writer()`, plus `log_ai_request_sync()` for testing
- **analytics/usage_service.py** — Dashboard queries (`get_today_overview`, `get_lifetime_overview`, `get_most_used`, `get_recent_activity`, `get_recent_errors`, `get_error_breakdown`, `get_daily_trend`)
- **analytics/model_metrics.py** — Per-model rollups (`get_model_stats`, `get_fastest_slowest`, `get_most_reliable`, `detect_degraded_models`) with health labels
- **analytics/performance_tracker.py** — Latency percentiles (p50/p95/p99) and trend calculations (`get_trends`)
- **analytics/token_counter.py** — `MODEL_COSTS` dict updated for current production models (z-ai/glm-5.2, meta/llama-3.1-8b-instruct, meta/llama-3.3-70b-instruct, meta/llama-3.2-90b-vision-instruct, black-forest-labs/flux.1-schnell, stabilityai/stable-video-diffusion, deepseek-ai/deepseek-r1) with `estimate_cost()`, `get_provider_for_model()`, `get_model_capabilities()`

### Integration
- **core/selftest/runner.py** — Added analytics modules to `modules_to_patch` list for temp DB isolation
- **core/selftest/tests/test_analytics.py** — Two self-test probes: "Analytics Overview" and "Analytics Table Creation"
- **tests/analytics/test_analytics_infrastructure.py** — 13 integration tests covering write→read roundtrip, image path, multi-user isolation, batch ingestion, schema idempotency, error logging, model stats, percentiles, trends, and pricing

### Validation
- **pytest analytics tests:** 12/12 passed
- **Self-tests (Analytics category):** 2/2 passed (Analytics Overview, Analytics Table Creation)
- **Backward compatibility:** All 13 existing import sites in `database.py`, `baka_brain.py`, `main.py` now resolve without error
- **No OmniRoute/provider abstraction layers** — NVIDIA NIM only as specified

### Documentation Updates
- CHANGELOG.md: Added v15.7 entry
- ROADMAP.md: This entry
- README.md: Updated usage commands status
- ARCHITECTURE.md: Added analytics section
- docs/selftest.md: Added analytics probes

---

## Fix-it list (found during the 2026-07 documentation pass)

These aren't feature requests — they're real gaps between what the code
does and what earlier docs/comments claimed. Tracked here since there was
nowhere else to put them. Full detail in [DEBUGGING.md](DEBUGGING.md#known-issues).

- **Analytics package — RESOLVED differently (v14.12).** The five
  stranded source files (+ `init.py`) were deleted in the repository
  cleanup; `/usage`, `/performance`, `/errors` still return empty data.
  Building analytics is now a clean v15 item (see Stage 0 above).
- **Hardcoded-looking API key in `ai_helper.py:9` — file deleted
  (v14.12).** The key remains in git history; **rotating it is the one
  remaining action**.
- **Dead code — RESOLVED (v14.12):** `ai_helper.py` and `bot_state.py`
  deleted in the repository cleanup.
- **`token_counter.py`'s stale `MODEL_COSTS` table — MOOT (v14.12):**
  the file was deleted with the rest of the never-assembled analytics
  code. A future analytics build should source model costs from
  configuration, not a hardcoded table.
- **`conversation_state.py`'s docstring claims state "survives across
  messages reliably"** via module-level dicts. True within a running
  process, but it does **not** survive a process restart — contrary to
  `feature_list.md`'s claim that state "survive[s] bot restarts". Either
  fix the docs (cheap) or back the state with SQLite (more work, but would
  also fix `/trace` and debug-mode state in `debug_system.py`, which have
  the same in-memory-only limitation).
- **`check_reminders` and `check_followups` jobs don't check quiet hours**,
  unlike every other scheduled job. Confirm whether this is intentional
  (primary reminders should always fire) or a gap.
- **`check_deadlines` job bypasses `database.py`**, opening its own raw
  `sqlite3.connect("planner.db")` — the only place in `main.py` that
  doesn't go through the data-access layer. Worth aligning for consistency.
- **`anthropic` SDK is in `requirements.txt`** but no `import anthropic`
  was found anywhere in the reviewed modules — confirm whether it's a
  leftover dependency or used by code not yet located, and prune if unused.

---

## Next up (from v12.0's own "ideas for next")

- **Project photos via Vision** — send a photo, Llama Vision describes
  progress, auto-adds a worklog entry
- **Cost/budget tracking** — sum material costs, show budget vs. spent per
  project
- **Milestones** — split projects into named stages, each with its own
  progress
- **Template projects** — save a project's material list as a template so
  the next similar build populates instantly

---

## Backlog (from the original roadmap, unordered, numbers dropped)

- **Voice notes** — accept Telegram voice messages, transcribe (Whisper or
  similar), treat transcript as regular text input with a confirm-before-act
  step
- **Task dependencies** — "Task B depends on Task A"; B's reminder only
  fires after A is done. `parent_task_id` column already exists as a
  possible foundation
- **Location-based reminders** — geofence check in the reminder scheduler,
  using Telegram's live-location sharing
- **Personalized briefing times** — use `interaction_log`'s active-hours
  data (already collected since v6.0) instead of a fixed 08:00 morning
  briefing
- **Bulk task import** — paste a numbered/bulleted list, one AI call
  extracts and confirms all of them
- **Named goal milestones + task linking** — `ai_observations`'
  `action_type` hook was built with this in mind
- **GLM 5.2 upgrade** — swap `MODEL_MAIN` once NVIDIA's GLM 5.2 endpoint is
  stable (GLM 5.1 was EOL'd, see [docs/ai_system.md](docs/ai_system.md));
  benchmark both once the analytics pipeline actually works
- **Fast routing enabled** — flip `ENABLE_FAST_ROUTING=True` so Llama 3.1
  8B pre-filters simple intents before escalating to the main model
- **`/replay` command** — full debug timeline for any interaction by
  timestamp, pulling from `ai_usage`, `missed_capabilities`,
  `interaction_log`, and `debug_system.py` — blocked on the analytics
  fix-it item above
- **`/export_usage`** — export `ai_usage` as CSV/JSON — also blocked on the
  analytics fix-it item
- **Multi-user admin mode** — the data model already scopes everything by
  `user_id`; the admin panel itself is currently single-user only
- **Pomodoro mode** — `/pomodoro <task_id>` timer, new `pomodoro_log` table
- **AI weekly insights** — narrative (not just pattern-based) weekly
  productivity summary
- **Themes/personalities** — switchable communication style stored in
  `user_preferences`, applied in `think_freely()`'s system prompt

---

## Future integrations (no timeline)

- Calendar sync (Google Calendar, two-way)
- Email integration (e.g. "did I get a reply from them yet?")
- Notion/Obsidian export
- Music integration (e.g. "play study playlist")
- Streak heatmap (GitHub-style year view of completed tasks)

---

## Known limitations carried over from `feature_list.md`

Reconciled against the current code — some of these are actually already
built; kept here only where still true:

- No web dashboard — all interaction is through Telegram only. **Still
  true.**
- Smart scheduling (`/plan`) creates a schedule and can apply it to the DB
  (v4.0+) — the original "text plan only, no DB tasks" limitation is
  **resolved**.
- Productivity scoring exists via `/analyze` and `/insights` (v6.0+) — the
  original "not yet tracked" limitation is **resolved**.
- Proactive suggestions (stagnation nudges, wellness nudges, priority
  nudges) exist (v8.0, v12.0) — the original "not yet implemented"
  limitation is **resolved**.
- Deployment target: To Be Documented — `README.md` said "hosted locally
  (WSL), not yet deployed to Railway cloud" as of its last update; confirm
  current hosting status before relying on this.
