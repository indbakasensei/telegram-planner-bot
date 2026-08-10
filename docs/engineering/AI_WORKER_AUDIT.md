# AI Worker Audit — BAKA v15.1.0-alpha.11

**Date:** 2026-08-09
**Head:** `d5fe0ef` (v15.1.0-alpha.11)
**Auditor scope:** read-only investigation; **no code modified, nothing committed.** Baseline test suite: **1234 passed in ~63s**.

This document reconstructs the *actual* architecture (as built, not as advertised), traces exactly how a user message travels through the system, answers the 20 architecture questions, maps every observed Telegram failure to a concrete code path (distinguishing symptom from root cause), and proposes a target architecture with a migration strategy. It is the deliverable for the pre-v15.2 audit.

---

## 1. Current architecture (as-built)

BAKA is a **single-process Python Telegram bot** (`python-telegram-bot` 20.7, SQLite, NVIDIA NIM OpenAI-compatible endpoint). The headline v15.1 claim — "AI worker + intent engine + routing layer + offline engine" — describes a set of systems that are largely **shadow-only or flag-gated dormant**. The *live* production path is narrower: **deterministic NL maps → EntityManager → a single-shot LLM classifier**.

### 1.1 Process & entry point

- `main.py` (5,671 lines) is the entire legacy router, handlers, and UI. One `Application.run_polling()` loop.
- Every user message lands in `handle_message` (main.py:702). There is no dispatcher, no queue, no async worker — one blocking turn at a time.

### 1.2 The live message execution path (in exact order)

```
handle_message (main.py:702)
├─ 1. /dev-* test-run commands (development only)
├─ 2. WORKSPACE flag block (main.py:737–756) ............ OFF in .env → skipped
├─ 3. IntentEngine.shadow_classify (main.py:757) ......... logs intent, never routes
├─ 4. RoutingLayer.route (main.py:765) ................... logs decision, ALWAYS destination=LEGACY
├─ 5. Offline Engine gates (main.py:782–893) ............. OFFLINE_* flags all OFF → skipped
├─ 6. Menu / inline-button callbacks
├─ 7. State machine:  confirming / editing / gathering
├─ 8. Time & date answers (state == "gathering" re-prompt etc.)
├─ 9. NL command maps (deterministic):
│     • Phase 1 — starts-with prefix table (main.py:1165–1194)
│     • Phase 2 — exact-match table (main.py:1223–1284)
├─10. EntityManager (main.py:1291–1311) — NL→JSON classifier, may create/update/retrieve workspace entities
├─11. Task VIEW quick-match (main.py:1313–1360)
├─12. Idle BAKA (main.py:1362–1440) — get_baka_response single-shot classifier + intent dispatch
└─13. Fallback chat reply
```

**Critical finding:** steps 3, 4, 5 exist and log, but **none of them influence routing**. `RoutingLayer.route()` *always* resolves to `Destination.LEGACY` (the fallback_reason string says so on every message). The Offline Engine (which holds the ActionRegistry task/habit tools) is entirely flag-gated OFF. So the effective brain is: **deterministic maps → EntityManager → view quick-match → one fast-LLM call**.

### 1.3 Component status table

| Component | Location | Status in production | What it actually does |
|---|---|---|---|
| IntentEngine | core/intent/ | **Shadow only** | Rule+date-parser intent/entity guess, logged, discarded |
| RoutingLayer | core/routing/ | **Shadow only** | Decision logged, always LEGACY |
| Offline Engine | core/offline/ | **Dormant** (all flags OFF) | ActionRegistry task/habit tools — never called |
| Workspace OS orchestrator | core/workspace/app.py | **Dormant** (WORKSPACE flag OFF) | `process_message` never runs in the main path |
| NL command maps | main.py | **Live** | Prefix + exact-match deterministic handlers (create/delete/view tasks, goals, etc.) |
| EntityManager | core/ai/entity_manager.py | **Live** | Fast-LLM single-intent JSON classifier for workspace entities |
| Task VIEW quick-match | main.py:1313 | **Live** | "show/dikhao/list"-prefixed → view_tasks (default period "all") |
| Idle BAKA | main.py:1362 / baka_brain.get_baka_response | **Live** | One-shot llama-3.1-8b classification into TASK/HABIT/EDIT/DELETE/VIEW/GOAL/.../CHAT |
| State machine | conversation_state.py | **Live** | idle / confirming / gathering / editing; MAX_HISTORY=10 |

### 1.4 AI model architecture — what model does what

From `baka_brain.py` (MODELS at 77–85, CHAT_MODEL at 95–101) and the request logs:

| Model | Default role | Actually used for |
|---|---|---|
| `z-ai/glm-5.2` (MODEL_MAIN / MODEL_THINK) | deep reasoning (/think, /ws plans) | `LLMPlanner`, `/think` — **rarely reached in normal chat** |
| `meta/llama-3.1-8b-instruct` (MODEL_FAST; **CHAT_MODEL default**) | chat + classification | **Every classification in normal chat**: idle BAKA intent (max_tokens 1024), EntityManager entity intent (max_tokens 256), gathering re-prompts, conversation replies |
| (fallback chain in provider.py) | error fallback | on HTTP/rate failures |

**Conclusion on "one model doing too many jobs":** yes. **llama-3.1-8b is the single classifier for ALL of**: task intent+slot extraction, entity create/update/retrieve classification, confirmation-summary drafting, and chat responses. The traces show it making the same class of error repeatedly (bad date resolution, misclassified intent, ignoring structured output). GLM-5.2, the capable model, is only reached via `/think` and `/ws` — the exact paths the user *isn't* typing. A model split is warranted, but the *bigger* structural problem is that classification is done without tool access, conversation context, or a reference-resolution step (see §3–§4).

### 1.5 The AI/tool architecture today

- **CognitiveEngine** (`core/ai/cognition.py`): `RuleBasedPlanner` (default) → keyword→single tool; `handle` runs plan→registry→execute→compose, **single pass, no iteration, no result inspection, no "continue until done"**.
- **LLMPlanner** (`core/ai/llm_planner.py`): wraps GLM; `KNOWN_TOOLS` = {`list_workspaces`, `workspace_overview`, `list_entities`, `recent_notes`, `open_workspace`, `recall`} — **all read-only**; one tool choice per call.
- **workspace_tools.py** + `WorkspaceRetriever` + `RecallTool`: read-only retrieval over entities/notes.
- **EntityManager**: a *separate*, hand-rolled single-intent JSON contract (create/update/retrieve/none) that bypasses the tool registry entirely — it calls workspace `engine` methods directly. Its tools are *implicit*, not declared.

**Net:** there is **no create/update task tool, no create/update/delete entity tool, no reminder tool, no workspace-creation tool, no goal/habit tool** exposed to *any* AI component. The AI cannot take multi-step action, cannot inspect results, and cannot loop. EntityManager "acts" only via a brittle single-JSON contract, and only for workspace entities.

### 1.6 State & references

- **Conversation state** (`conversation_state.py`): module-level `{user_id: state/context/history}`; states idle/confirming/gathering/editing; **no "current entity" concept**.
- **Active workspace**: `core/storage/storage.py` `TelegramBindingStorage.get_active/set_active` (per user). Set by workspace commands and `WorkspaceGroups`.
- **Active entity: NOT tracked at all by the AI path.** `tg_bindings.set_active(entity_id)` is called **only** by `core/workspace/groups_app.py` (lines 59/76/91/102, via `/add`/`/open`/`/new`), and **never** by `core/ai/entity_manager.py` (which only *reads* `get_active`). Consequence: "Show her", "Can she ascend further?", "Change its owner" have **no referent** when the entity was created via natural language.

---

## 2. Answers to the 20 architecture questions

1. **Where Telegram receives the message:** `handle_message` in main.py:702 (polling loop, `Application.run_polling()`).
2. **First routing decision:** the state machine (confirming/editing/gathering) — checked *before* any NL maps or AI. After that, deterministic prefix/exact-match tables.
3. **Deterministic handlers that run before AI:** dev-test-run; WORKSPACE gate (off); offline gates (off); menu buttons; state machine; time/date; NL phase-1 prefix table (incl. `delete/remove/del` → `delete_task_cmd`); phase-2 exact-match table. **All of these short-circuit before EntityManager and before the idle LLM.**
4. **IntentEngine participation:** *shadow only* — its `ADD_TASK, confidence 0.95, date=2026-08-10` parse is logged and **discarded**; it never feeds the legacy path.
5. **RoutingLayer participation:** shadow only — always LEGACY, logged fallback_reason.
6. **CognitiveEngine/LLMPlanner participation:** only via `/ws` and `ask_cmd`; not in normal chat. RuleBasedPlanner default; LLMPlanner unused unless `/ws` mode.
7. **EntityManager participation:** after both NL tables; pre-check keyword/entity mention gate; then fast-LLM classification; acts only on create/update/retrieve for workspace entities.
8. **How tools are represented:** CognitiveEngine/LLMPlanner have a `KNOWN_TOOLS` list (read-only, 6). EntityManager has *implicit* actions (create/update/retrieve) hard-coded into a prompt, not a tool registry. No shared tool abstraction between the two worlds.
9. **Are commands exposed to AI as tools?** **No.** `create_task`, `complete_task`, `delete_task`, `create_reminder`, `create_entity`, etc. are **not** exposed to any AI component. The only tools are read-only workspace retrieval.
10. **Can AI choose multiple tools in sequence?** No — single tool choice, single pass, no loop, no result inspection, no continuation.
11. **Can AI inspect tool results and continue?** No. `CognitiveEngine.handle` composes a final message immediately after one execute pass.
12. **Does AI have conversational memory?** Only a textual "Recent chat" snippet baked into the `get_baka_response` system prompt (last ~10 turns via `get_history`), and a "current tasks/memories" dump. This is **prompt context, not state** — it drifts (as the "NextWeek=2026-08-07" injection proved) and there is no memory of *entities* or *references*.
13. **How are active workspace / current entity / references represented?** Active workspace = `TelegramBindingStorage` per user (works). Current entity = **nonexistent** in the AI path. References/pronouns = **unresolved** (no resolution layer; nothing sets active entity on NL-created entities).
14. **What prevents entity↔task cross-capture?** **Nothing structural.** The gates are heuristic: EntityManager's `_KEYWORDS` pre-check, and the "pre-check miss → falling through" order. A task message that trips a keyword ("show", "create", "update", "remind") gets an entity LLM call (usually harmless → `none`), and an entity message that *doesn't* trip keywords ("Can she ascend further?") falls all the way to the idle LLM and gets misclassified as CHAT/GOAL.
15. **How does confirmation state interact with AI?** Confirming is *before* AI: `state == "confirming"` matches a hard-coded positive/negative word list (yes/save/sure/no/cancel...); the affirmative executes a previously stored `pending_action`. The AI never participates in confirmation; conversely an LLM-written `response` field can **claim success that never happened** (see failure 15) because the two systems don't share state.
16. **How do reminders interact with task creation?** Reminders **are tasks** (same table, `remind_me_cmd` creates a task with a date/time and the reminder scheduler follows up on pending dated tasks). There is **no reminder-specific AI slot type**; "remind me X at T" is classified as TASK, and "show reminders" falls to the VIEW quick-match which mixes dated + undated tasks.
17. **How are Telegram topics created?** Only via `core/workspace/adapters/projection.py` (`create_forum_topic`/`ensure_entity_topic`), invoked by `WorkspaceGroups.add_entity` when the workspace is linked to a linked group. **EntityManager creates entities by calling `engine.add_milestone` directly** (`_handle_create`), bypassing `WorkspaceGroups` → **no topic is created** for NL-created entities.
18. **Which model/provider for which call?** See §1.4. Classification everywhere = llama-3.1-8b (CHAT_MODEL default) on NVIDIA NIM; deep reasoning = GLM-5.2 via /think, /ws, LLMPlanner.
19. **Is one model doing too many jobs?** Yes — see §1.4.
20. **Fallback behavior:** provider.py fallback chain on transport/rate errors; several calls hardcode `max_tokens` low (256 for entity classification) which truncates structured JSON output (a contributor to failure 1).

---

## 3. Observed Telegram failures → code paths (symptom vs root cause)

Evidence source: `debugbot.log` (2026-07-31 manual session, admin=user). Each entry: the user's report, the exact code path that produced it, and the true root cause.

### F1. "Zhongli, show ascension phase and weapon and artifacts" → "No tasks for All Pending!"

- **Path:** EntityManager pre-check (keyword hit) → LLM returned **three concatenated JSON objects** (create + two retrieve clauses) → `_extract_json` used `re.search(r"\{.*\}", text, re.DOTALL)` which greedily matched across all three → `json.loads` raised `Extra data: line 2 column 1 (char 154)` → exception → fall-through → task VIEW quick-match ("show" in `_view_words`) → `view_tasks(period="all")` → "No tasks for All Pending!".
- **Root cause:** (a) **greedy JSON extraction** cannot handle multi-JSON LLM responses (same pattern in `baka_brain.clean_json`); (b) **EntityManager is single-intent by design** — the prompt forces one create/update/retrieve, so a compound request *cannot* be honored; (c) view quick-match hijacks "show" with no awareness that EntityManager just failed.

### F2. "Show her" / "Show him" → contextless

- **Path:** EntityManager pre-check (no keyword, no entity) → miss → idle LLM → CHAT / generic.
- **Root cause:** **no active-entity referent.** `set_active(entity_id)` is only called by `groups_app`; the pronoun is never resolved against any candidate; the LLM has no entity list context in the idle path (the workspace/entity list only exists inside the *EntityManager* prompt, which was skipped).

### F3. "Can she ascend further?" → generic

- **Path:** same as F2. EntityManager pre-check misses ("she" isn't a keyword, no entity name), falls to idle LLM.
- **Root cause:** same as F2 plus **no `_KEYWORDS` entry for "ascension"**, so even the pre-check wouldn't route it; and the EntityManager prompt has no entity-field *semantics* ("ascension_phase 0–6") to answer a question about it.

### F4. "Fleuve Cendre Ferryman" stored under `weapon_type`

- **Path:** EntityManager update classification → `fields={"weapon_type": "Fleuve Cendre Ferryman"}`.
- **Root cause:** the entity prompt is a **flat field list with no per-field semantics**; nothing distinguishes `weapon_type` (class: Sword/Polearm) from `weapon` (specific weapon name). Examples in the prompt even teach "Xiao uses a polearm → weapon_type" and "Furina uses Fleuve Cendre Ferryman → weapon" — the weak model confused the two on a long name.

### F5. "artifact is Golden Troupe" → stored as a character entity

- **Path:** EntityManager retrieve-or-create confusion; "Golden Troupe" (an artifact set) got created as an entity in the Genshin workspace (it appears in the entities list).
- **Root cause:** `_KEYWORDS`/classification has **no artifact-aware semantics** and the template's `materials` (json) / no `artifact` field means there is no slot that fits; the model invents one; `validate_entity_fields` **allows unknown keys** so bogus data persists silently.

### F6. Numeric / semantic filters ("ascension phase 6", "swords", "unfinished")

- **Path:** EntityManager retrieve → `_handle_retrieve` → `_filter_entities_by_query`.
- **Root cause:** `_query_tokens` **drops tokens with `len(t) <= 1`** (so "6" is dropped); strong-match requires `len(fstr) > 1` (so single letters never match); **field NAMES never match** ("ascension phase" isn't a field value); and `_handle_retrieve` **discards the LLM's structured `fields` dict** and re-runs string matching on the raw query — so "level 90" matches nothing unless the value string appears verbatim. "swords" → no `weapon_type` value called "sword" (stored as "Sword") → miss. "unfinished" → no synonym handling.

### F7. "Priority ultra" → GOAL branch

- **Path:** EntityManager pre-check miss → idle LLM classified as GOAL → GOAL branch, wrong.
- **Root cause:** weak classifier + **no enum validation/feedback** ("ultra" isn't a valid priority; the model should ask or map to high) + no conversation context to notice the referent.

### F8. "Ascension phase 20" → CHAT

- **Path:** EntityManager pre-check miss (no keyword/entity mention) → idle LLM → CHAT.
- **Root cause:** same as F3/F7 — pre-check gate too strict, no "ascension" keyword, no field semantics, weak model.

### F9. "Weapon kya hai?" → generic

- **Path:** EntityManager miss → idle LLM → CHAT/generic.
- **Root cause:** pre-check gate has no Hinglish keyword; **no active-entity referent**; idle LLM has no entity schema.

### F10. "Create character Furina" → entity created, **no Telegram topic**

- **Path:** EntityManager `_handle_create` → `engine.add_milestone(...)` directly.
- **Root cause:** bypasses `WorkspaceGroups.add_entity` (which calls `projection.ensure_entity_topic` and `set_active`). **Topic creation and active-entity tracking are only wired to the `/add`-style command path.**

### F11. "Finish Buy milk" → created a *new* task confirm

- **Path:** idle LLM classified as TASK (new) instead of EDIT/complete; title extraction produced "Buy milk".
- **Root cause:** single-shot classifier with **no task lookup** — it cannot match "Buy milk" against existing task [39] Buy milk; the LLM had the task list in its system prompt but is not instructed to *look up* before classifying; and the deterministic maps have no "finish <name>" prefix entry (only `delete/remove/del`).

### F12. "I bought milk" / "Done" → CHAT

- **Path:** idle LLM → CHAT.
- **Root cause:** "Done" as a standalone has **no deterministic complete-handler prefix** (only `/done <id>`), and the classifier has no instruction to treat implicit completion statements as complete-actions; no task matching.

### F13. "Delete the first one" → "Usage: /delete <id>"

- **Path:** deterministic prefix table `["delete ", ...]` → `delete_task_cmd` → `int("the first one")` → ValueError → usage message.
- **Root cause:** **deterministic handler catches it before the AI**, then tries to parse the rest as an integer ID. No resolution of "the first one" to the most recently listed task; no AI fallback for a failed parse.

### F14. "Show reminders" → "📋 Tasks for All Pending" (includes undated tasks)

- **Path:** EntityManager → `intent=none` → task VIEW quick-match ("show") → `view_tasks(period="all")` → prints every pending task, dated or not.
- **Root cause:** no **reminder/task semantic distinction** (same table), and the VIEW quick-match has no awareness of "reminders" (only "show/dikhao/list"); the word "reminder(s)" is not in `_view_words` and not a filter.

### F15. "Remind me next Monday at 8 AM" → *false* "I've added a reminder", then wrong date

Full trace (verified in log):
1. User: "Remind me next Monday at 8 AM."
2. IntentEngine (shadow): `ADD_TASK, date=2026-08-10` (correct) — **discarded**.
3. EntityManager pre-check miss → idle LLM: `TASK, title=None, date=2026-08-07` (**wrong** — anchored on injected "NextWeek=2026-08-07", which is *next Friday*, not next Monday), time=08:00, Missing=[title].
4. Bot replies: **"I've added a reminder for next Monday at 8 AM."** — nothing was saved.
5. User: "okay" → bot: "Got it! What task should I schedule for **2026-08-07** at 08:00?" (enters gathering with the wrong date).
6. User: "Remind me to pay electricity bill tomorrow." → gathering merge `for k,v in entities.items(): if v and not partial.get(k)` keeps the stale `date=2026-08-07`, so **"tomorrow" (08-01) is ignored**.
7. Confirm: "📅 Date: 2026-08-07 ⏰ 08:00" → saved. The follow-up/reminder scheduler later fires on the wrong date.

- **Root causes:** (a) **shadow IntentEngine result discarded** — the one correct parse never used; (b) the LLM's **injected "NextWeek" context hijacks weekday resolution**; (c) the `response` field **falsely claims success** before gathering completes; (d) the **gathering merge never overwrites stale partial values** (`if v and not partial.get(k)`), so newer, correct information is dropped.

### F16. "Change its owner to Neuvillette" → stored bogus `owner=user`

- **Path:** EntityManager update → fields `{"owner": "user"}` (or similar) → `validate_entity_fields` **accepts unknown keys** → stored.
- **Root cause:** no active-entity referent ("its"), **no per-field schema validation** (owner isn't a Genshin template field), unknown keys silently allowed.

### F17. Task confirm/edit (the *working* case) — for contrast

- "Buy milk" → confirm box with category + suggested time → "yes" → saved. **This path works** because it's the deterministic state machine, not the AI. It should be preserved in the target architecture.

### Failure taxonomy (symptom → true root cause)

| # | Observed symptom | System | True root cause |
|---|---|---|---|
| F1 | "No tasks for All Pending!" | Planner | greedy multi-JSON regex + single-intent contract + view quick-match hijack |
| F2,F3,F9,F16 | contextless/CHAT | Reference | **no active-entity state in AI path**; no pronoun resolution |
| F4,F5,F8 | wrong/missing field | Tool-schema | **flat field list, no per-field semantics**; unknown keys allowed |
| F6 | no filtered results | Retrieval | token-drop `len<=1`; no field-name match; **structured fields discarded** |
| F7,F8,F12 | wrong intent | LLM-quality | weak model + no task/entity lookup + no referent |
| F11,F12 | created instead of completed | Intent/task-state | no task-matching before classify; no implicit-complete path |
| F13 | Usage: /delete | Routing | deterministic prefix pre-empts AI; no "first one" resolution |
| F14 | reminders=all pending | Routing | no reminder/task distinction in VIEW |
| F15 | false success + wrong date | Confirmation/task-state/LLM-quality | shadow parse discarded + LLM re-parse wrong + false-success reply + stale-merge |
| F10 | no topic created | Workspace/Telegram | EntityManager bypasses `WorkspaceGroups`/projection |

---

## 4. Proposed target architecture: BAKA as an AI worker with tools

The long-term vision (commands/features become tools an AI worker selects, runs, inspects, and continues) is sound and **reuses almost everything already built**. Do **not** build a new system; expose existing handlers and the workspace engine as a unified tool surface and give the worker a real agent loop.

### 4.1 One tool surface (unified registry)

Wrap **existing** capabilities — never duplicate. Initial catalog (all backed by current code):

- **Task:** `create_task`, `update_task`, `complete_task` (→ `execute_task_action` / done path), `delete_task`, `list_tasks(period, category, search)`, `get_task(id|name)`, `snooze_task`, `remind_me` (creates dated task)
- **Habit/Goal:** `create_habit`, `create_goal`, `list_goals`
- **Workspace entity:** `list_workspaces`, `open_workspace`, `create_entity`, `get_entity`, `update_entity_field`, `list_entities(field_filters)`, `recall(query)`, `create_topic` (via `WorkspaceGroups`/projection so topics + active-entity tracking work)
- **Memory:** `save_memory`, `get_memory`
- Each tool declares: name, description, JSON-schema args, **per-field semantics**, read/write, and confirmation policy (writes require confirm).

### 4.2 Agent loop (replaces single-shot)

Replace `CognitiveEngine.handle`'s single pass with a bounded loop:
1. Build context (active workspace, active entity, recent task/entity mentions, user history).
2. AI worker selects tool + args (GLM-5.2, the reasoning model — not llama).
3. Registry **validates args against schema** (reject `owner` if not a field; clamp `ascension_phase` to 0–6; reject "ultra" priority with a clarifying question).
4. Tool executes the **real handler**; returns structured result.
5. Worker inspects result; loops (bounded, e.g. ≤4 tool calls) until the user's outcome is met or a clarifying question is required.
6. Writes confirm; on "yes", commit.

### 4.3 Reference resolution layer

Add a small, deterministic resolvers **before** the worker:
- **Active entity:** EntityManager `_handle_create`/`_handle_update` must call `tg_bindings.set_active(entity_id)` so "her/it/first one" have a referent.
- **Pronoun resolution:** map he/she/her/him/it/this/that/first one/last one → active entity or most-recently-mentioned entity (keep a per-user mention stack — reuses `conversation_state` pattern).
- **Ordinal resolution:** "the first one" → first row of the last list the user was shown (store last-listed ids per user).
- **Task lookup:** before classify, deterministic fuzzy-name match against open tasks (F11/F12/F13 all benefit).

### 4.4 Model architecture (surgical, not wholesale)

- **GLM-5.2** becomes the **worker/planner** (tool selection, multi-step reasoning) — it already exists as MODEL_MAIN.
- **llama-3.1-8b** stays the **fast classifier** where a single low-risk label is enough (entity pre-class, sentiment) — but **no longer the only decision-maker for writes**.
- Add **deterministic slot extraction** (date_parser already resolves dates correctly — see IntentEngine's correct 2026-08-10) and feed it to the worker instead of letting the LLM re-anchor on injected context.
- **JSON decoding:** replace every greedy `re.search(r"\{.*\}")` (entity_manager `_extract_json`, baka_brain `clean_json`) with a robust extraction (first balanced-brace parse; fallback to json-repair) — or better, move to structured/tool-call output so the model can't concatenate JSON.

### 4.5 Field semantics, not keyword rules

- Per-field descriptors on every template field (what it means, example values, enum, synonyms) — derived from `entity_field_specs`; **no Genshin-specific hard-coding**, generic `(label, semantics, enum, examples)` so any template benefits.
- `validate_entity_fields` should **reject unknown keys for writes** (or explicitly request "add field") rather than silently persisting.
- Semantic matching (field-aware) instead of raw substring/token-overlap for retrieve (F6).

---

## 5. Minimal migration strategy

Ordered so the bot stays healthy (1234 tests green) and the risky rewrites come last. Each milestone is independently shippable and flag-gated where behavior changes.

1. **M0 — Instrument, don't change** (report this). Add nothing; the shadow systems already log. *(done — this audit)*
2. **M1 — Reference resolution + active entity.** `set_active` on NL-created entities; pronoun + ordinal resolution; mention stack. Fixes F2, F3, F9, F13, F16 partially. Small, additive, high value.
3. **M2 — Robust JSON decode + single-intent safety.** Replace greedy regexes; on multi-JSON or parse failure, ask a clarifying question instead of falling through to view/chat. Fixes F1's crash.
4. **M3 — Retrieval upgrade.** Don't discard structured `fields`; field-aware semantic filter; fix token-drop `len<=1`; keep name-match fallback. Fixes F6.
5. **M4 — Task lookup before classify.** Deterministic name→task match (open + recent) so "Finish Buy milk"/"I bought milk"/"Delete the first one" resolve to task ids; implicit-complete handling. Fixes F11, F12, F13.
6. **M5 — Reminder/view semantics.** "reminder(s)" aware VIEW (dated tasks only, upcoming first); distinct reminder rendering. Fixes F14.
7. **M6 — Confirmation truthfulness + gathering merge.** Never claim success before commit; gathering merge must overwrite stale fields when the new message supplies a value (or clear conflicting slots). Fixes F15(c),(d).
8. **M7 — Date resolution from IntentEngine/date_parser, not LLM context.** Use the deterministic parse (which was *already correct*); stop injecting "NextWeek" as a resolved anchor. Fixes F15(b).
9. **M8 — Tool surface + agent loop (the flagship).** Wrap existing handlers as tools; bounded GLM worker loop; confirmation policy. **Behind a flag** (`WORKER=1`) until stable; legacy path remains default. This is where 4.2–4.4 land.
10. **M9 — Field semantics + schema validation.** Per-field descriptors; reject unknown keys. Fixes F4, F5, F16(data side).
11. **M10 — Topic wiring.** Route entity creation through `WorkspaceGroups.add_entity` (when workspace is group-linked) so topics + active-entity tracking are unified. Fixes F10.

---

## 6. Tests that must be added

Each observed failure becomes a regression spec (under `core/regression/suites/` + unit tests, consistent with v15.1 practice). The 1234 existing tests must stay green.

1. **Multi-intent:** LLM returns 2–3 concatenated JSON objects → `_extract_json` must return a clean parse or `None` → system must ask, not view-hijack. (F1)
2. **Pronoun resolution:** "Show her" after "create Furina" → resolves to Furina; "delete the first one" after a list → deletes listed id. (F2, F13)
3. **Active-entity tracking:** `set_active` called after NL entity creation; `get_active` returns it next turn. (F2/F3)
4. **Structured-field retrieval:** "level 90", "ascension phase 6", "swords" → correct filtered results; single-char values work. (F6)
5. **Field semantics:** "Fleuve..." → `weapon`, "polearm" → `weapon_type`; "artifact X" → artifact slot or clarifying question; unknown key rejected. (F4, F5, F16)
6. **Task lookup:** "Finish Buy milk"/"I bought milk"/"Done" → complete task [39]; no new-task creation. (F11, F12)
7. **Reminder/view:** "show reminders" → only dated upcoming; order by date. (F14)
8. **Confirmation truthfulness:** title-missing TASK → bot must not claim "reminder added"; must ask. (F15)
9. **Date resolution:** "next Monday at 8 AM" on a Friday → next Monday (not NextWeek injection); deterministic parse wins over LLM. (F15)
10. **Gathering merge:** partial date must be overwritten when new message says "tomorrow". (F15)
11. **Topic creation:** NL entity creation in a group-linked workspace → topic created + active entity set. (F10)
12. **Agent loop:** worker may call list→get→update in sequence; result inspection; bounded loop; confirm-before-commit. (M8)

---

## 7. Risks & compatibility concerns

1. **Shadow systems are not inert.** IntentEngine/RoutingLayer look like they route; they don't. Do not build the target on the assumption they can be "flipped on" — the Offline Engine still lacks ADD_TASK etc. (`fallback_reason` on every message). Treat them as evidence/logging only.
2. **`validate_entity_fields` forward-compatibility is a liability for writes.** Allowing unknown keys was a deliberate convenience, but it persists garbage (F16). Changing it to reject will **break existing stored rows** with unknown keys — need a data-cleaning pass, not just a validator flip.
3. **Don't touch `check_deadlines` / raw-sqlite exception.** CLAUDE.md forbids adding a second raw-DB path; the worker tools must go through `database.py`.
4. **httpx must stay pinned at 0.25.2** (python-telegram-bot 20.7 compatibility). The worker additions must not drag in dependency bumps.
5. **The 1234-test suite + manual Telegram smoke checklist** must remain the release gate; `--dry-run`/flag-gating every behavior change avoids a big-bang regression.
6. **Model cost/latency.** Moving classification to GLM-5.2 everywhere is expensive and slow for a single-process polling bot (timeouts already seen — alpha.6 "Fix GLM 5.2 chat timeouts"). Keep llama for cheap single-label calls; use GLM for the worker loop and hard decisions only. Bound the agent loop tightly.
7. **Do not hardcode Genshin.** Every new field descriptor, synonym map, and tool must come from template metadata (`entity_field_specs`), generic across `game/asset/knowledge/project` templates.
8. **Do not let the LLM invent tool results.** Every tool result must come from the real handler/repository; the worker only reads what the registry returns (per owner directive).
9. **Telegram topics** are optional/conditional (group-linked workspace + forum). Entity creation must not regress the plain-DM path (no topic needed) — route through `WorkspaceGroups.add_entity` which already handles both.
10. **The `response` field of the classifier is not authoritative.** It already lied (F15). The worker must separate "what I did" from "what the user should see", and confirmation must be grounded in actual tool outcomes.

---

## Appendix A — git history alpha.3 → alpha.11 (file-level evolution)

`git log --oneline 9135ce2..d5fe0ef`:
```
d5fe0ef feat: release v15.1.0-alpha.11 final stabilization
10f7e83 feat: release v15.1.0-alpha.10 natural language entity management
a8ef226 v15.1.0-alpha.9 — Structured per-entity fields
6dac1b2 v15.1.0-alpha.8 Real retrieval: recall across everything stored
ec2bed3 v15.1.0-alpha.7 Responsive chat, GLM 5.2 stays the reasoning brain
55e5522 v15.1.0-alpha.6 Fix GLM 5.2 chat timeouts
002cb66 v15.1.0-alpha.5 Bug-database fixes + manual regression coverage
3c2ddfc v15.1.0-alpha.4 GLM 5.2 is now the default model on NVIDIA NIM
```
41 files, +3705/−138. Highlights: `entity_manager.py` (+660), `ui.py` (+271), `main.py` (+93), `baka_brain.py` (+83), `database.py` (+78), `workspace_retriever.py` (+122), `registry.py` (+101), new templates (asset/game/knowledge/project), new selftest (`test_workspace.py`), new regression suites (`workspace_v151.py`). The alpha series **added capability without adding routing authority**: the new EntityManager/retriever stack is reached only via the fall-through order in §1.2, while the new templates/engine enriched the workspace storage layer that EntityManager writes through directly (hence F10's topic gap).

## Appendix B — evidence log references

All evidence is in `debugbot.log` (2026-07-31 IST session):
- F1 Zhongli multi-JSON: `EntityManager[admin] LLM raw response:` + `Extra data` exception at `_extract_json`.
- F14 show remainders: EntityManager `intent=none` → `📋 Tasks for All Pending` (message 4303).
- F15: message 4316 → IntentEngine `ADD_TASK date=2026-08-10` (shadow) → LLM `TASK date=2026-08-07` → message 4317 "I've added a reminder…" → 4319 "What task should I schedule for 2026-08-07…" → 4320/4321 stale-date confirm `📅 Date: 2026-08-07` → 4323 saved → scheduler follow-up on 2026-08-07.
