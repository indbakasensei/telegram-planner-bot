# v15.2 M4 — Final Remediation Report (items 1–20)

**Date:** 2026-08-11
**Version stamped:** `15.2.0-alpha.14` (item19 — owner decision; the first
stamp on the v15.2 line, covering M2+M3+M4)
**Status:** remediation complete; M5 NOT started; nothing committed/pushed
**Scope note:** NVIDIA `z-ai/glm-5.2` serves no output upstream on NIM
(provider hang, 0 bytes at 60–150s probes — same key + auth + request shape
work sub-second with `meta/llama-3.1-8b-instruct`). GLM-5.2 is **not**
deprecated and no timeout/retry/redesign was added around it. All live
validation below ran on `MODEL_MAIN=meta/llama-3.1-8b-instruct` (temporary;
`MODEL_THINK` stays GLM-5.2 for `/think`).

---

## 1. Every live failure — exact root cause, Worker vs legacy path

Three live passes happened. They are NOT three batches of the same class of
failure — the chronology matters.

### Phase 1 — the ten M4 orchestration failures (F1–F10), FIXED generically

These surfaced right after the first M4 build. Root causes were shared
(architecture/contract), so the fixes are generic — no phrase-specific
handlers:

| Live failure | Exact root cause | Generic fix |
|---|---|---|
| F1 "Create Bennet and set him to level 83" updated Hu Tao | Tool results reached the model only as prose step-trace; M1's active-entity-first collapsed every entity to `kind="milestone"` | `TypedReferentStore`: per-kind, recency-ordered referent memory; tools note create/update/list results; resolution checks the typed store FIRST |
| F2 "Create Keqing, set her level to 90, then show her" updated Hu Tao | Same + tool results not fed back; ReferenceContext not updated | Same fix + REFERENTS prompt block renders the current run's ids |
| F3 "Show Xiao and then update his level to 80" skipped the show | Worker stopped early after a mutation; steps collapsed | rule12: execute EVERY distinct operation, one tool per step, never skip |
| F4 "Show Xiao and then show Neuvillette" → "Tasks for All Pending" | Legacy task VIEW quick-match hijacked compound/typed retrieves | Worker seam moved BEFORE EntityManager + VIEW quick-match (still after deterministic NL maps) |
| F5 "Set Xiao's level to 85 and then show Xiao" → no final display | Same early-stop + no retrieve-after-update composition | rule12 + the typed store keeps the created/updated id as a referent |
| F6 "Set its deadline to this month end" corrupted Xiao's target_level | `update_entity` forward-compat accepted `deadline`; M1 pronoun → active character | `update_goal_deadline` tool (goal domain owns deadlines) + typed-store domain-conflict rejection: a pronoun pointed at a different kind is REFUSED |
| F7 "Set Gym deadline to next month end" → 2026-09-30 | `date_parser` returned None for "next month end" | Deterministic period-end: "next month end"/"end of next month" → last day of next month (runs before the this-month pattern) |
| F8 "Create artifact Golden Troupe" → "already a Golden Troupe" | Display-name identity ignored entity type | `milestones.entity_type` column; duplicate check is `(entity_type, name)`; identity is `(workspace, kind, id)` |
| F9 "Show all artifacts" → "Tasks for All Pending" | No structured kind filter; VIEW quick-match hijacked | `list_entities(entity_type=…)` structured filter; Worker seam order |
| F10 "Show all characters" returned mixed kinds | All entities were `kind="milestone"`; no kind column | `entity_type` stored on every entity; typed retrieval filters by it |

**Worker vs legacy:** these ran the Worker seam but the seam was too late and
the tool-feedback contract was prose-only. Fixes are in the Worker/tool
layer, all regression-pinned offline (WKR-023…027, S1–S30).

### Second live pass — 7 reported failures, forensic result: Worker NEVER ran (all LEGACY)

bot.log / debugbot.log forensics are unambiguous: `feature_flags.WORKER`
defaults OFF and was **not** in `.env` (4 lines, no `WORKER` variable). The
seam (`main.py`, owner-only + flag-gated) never executed. Every message was
handled by the LEGACY pipeline — `intent_engine (shadow) → routing_layer
(shadow, ALWAYS→LEGACY) → EntityManager → legacy BAKA`, model
`meta/llama-3.1-8b-instruct`, never GLM-5.2, never the tool contract, never
typed referents. Example root causes: legacy compound reduction collapsed
"create Mizuki…show her" to a single `deterministic update 'Kaeya'`; the
legacy single-object parser discarded a CORRECT two-retrieve Llama answer
("Show Xiao and then show Neuvillette"); goal→active-character cross-domain
collapse. **Zero of the 7 are attributable to the Worker/parser/prompt/typed
referents — none executed.** One reported "no confirmation" was flagged
rather than papered over: the log showed a confirmation WAS sent.

### Third live pass — 31 messages, WORKER=1 (Llama): 11 genuine passes, 4 legacy fallthrough, 3 tool-contract fixes

**11 full PASSes** (A5, B1, B3, C1, C2, C5, C6, C7, E1a, E2, E3) were
genuinely `Worker → ToolRegistry → Tool → ToolResult → Worker final`
(proven by bot.log `[worker …]` lines: real tool calls, ok=True, no legacy
fallthrough — a DB mutation alone never counted as a PASS). 4 fell through
to legacy (A1/B2/E1b Worker `declined`; F2 `tool_failure` after a Telegram
topic-creation ReadTimeout).

**3 ARCHITECTURE (tool-contract) failures — fixed generically:**
- **C3** — workspace ids surfaced as integers; workspace tools accepted only
  `string`. Fixed: `string|integer` union across workspace specs.
- **C8** — "leave-it-out" optional-filter markers (`''` and the literal
  `'omit'`/`'none'`/`'all'`/`'any'` the catalog wording invited) were
  rejected. Fixed: `validate_args` normalizes them to "no filter".
- **A2** — unmatched workspace name errored instead of falling back to the
  active workspace per the "(defaults to the active one)" spec. Fixed:
  `_require_workspace` falls back; no-active still rejected.

Each fix has regression tests + WKR-031. The **C8 fix was bot.log-proven
end-to-end live** (Worker→ToolRegistry→`list_entities(status='',…)`→ok→reply).

**The rest were MODEL CAPABILITY (Llama-3.1-8B), not architecture** — the
typed-referents block and tool catalog were correct in every case: compound
chains abandoned after 1–2 tool calls, "its"-→-goal declines, `name=
'artifact'` extraction, and a retest where Llama declined "Create Mizuki"
(legacy then created it correctly) and invented a `status='done'` filter
("Show all artifacts" → honest empty).

### One real code bug found by the forensic pass — deadline-clear (S30)

`database.update_goal_deadline()` returned `None` BOTH when a goal is missing
AND when a deadline is cleared to `None`, so `update_goal_deadline` raised
"goal [N] not found" for a clear that had actually succeeded (deadline was
already `None`) — a MUTATION recorded as failed even though it committed.
Fixed: the function returns `goal_id` on success (never `None` for a
legitimate clear); the adapter reads the new value from its own validated
argument. Pinned by `test_invariant_goal_deadline_clear` (S30).

---

## 2. Topic lifecycle design (items 6/7/8/10)

**Invariant:** ONE canonical topic per `(workspace_id, entity_id)`. Pre-M4 a
topic could be created twice for one entity; now every create flows through
the `_TopicTool` family (`core/ai/tool_adapters.py`), five tools registered
in `build_tool_registry`:

| Tool | Risk | Semantics |
|---|---|---|
| `get_entity_topic` | READ_ONLY | read the canonical binding; ok even when no topic yet |
| `ensure_entity_topic` | MUTATING | idempotent — returns existing (created=False); the initial card goes ONLY into a NEW topic |
| `set_entity_topic_locked` | MUTATING | durable lock (a DB column, survives a fresh registry) |
| `delete_entity_topic` | DESTRUCTIVE + confirmation_message | deletes the TOPIC only — the entity row stays; ordinary deletes of a LOCKED topic are refused (ok=False) unless `force=true` |
| `list_entity_topics` | READ_ONLY | bindings + lock state |

`_TopicTool._resolve_topic_entity()` resolves workspace + entity ref through
the shared M1 reference machinery; every tool returns an honest `not_wired`
result when no projection is wired. The binding is keyed
`(workspace_id, entity_id)` via `tg_get_workspace_entity_topic`, so two
topics for one entity are structurally impossible on the write path.
`DELETE ENTITY ≠ DELETE TOPIC` is pinned by tests.

## 3. Duplicate-topic repair result (item9)

`repair_topics` (`core/workspace/groups_app.py`), exposed as the
**`/topicrepair`** admin command + Self-Test "Topic Repair": idempotent,
collapses logical duplicates (one normalized title → ONE entity → ONE topic),
adopts a concrete kind onto the canonical row, reports created/existing/
duplicates/errors, preserves locked state, and **never deletes a DB row**
(duplicate rows are kept-but-skipped — no data loss). Re-running is a no-op.
The orphan-topic known issue (DEBUGGING.md) is now handled in two places:
prevention (canonical binding) + repair (`/topicrepair`).

## 4. Entity-type resolution design (items 1/15)

`core/ai/entity_kinds.py` `EntityKindResolver.resolve_for_create` is
deterministic + offline + generic, priority chain: existing DB row kind →
explicit type in utterance/name → weak generic hints → None (falls back to
the model's `entity_type` arg, default `entity`). `list_entities(kind=…)`
returns exactly that kind; `kind=all` returns every supported type;
mixed entities never leak across typed lists; cross-domain goals/tasks/
habits stay in their own domain. `milestones.entity_type` is stored on every
entity; identity is `(workspace, kind, id)`.

## 5. Goal / date resolution result (items 4/5)

`date_parser` now resolves relative ranges deterministically against the IST
app clock: "next week", "this month end", "next month end" (incl. year
rollover), "this/next weekend". A bare range NEVER falls through unparsed.
The intent engine's unconditional "resolved date → ADD_TASK" was the bug:
schedule-QUERY phrasing now falls through to the tier-4 query fallback
(`_QUERY_KEYWORDS` guard); ADD phrasing keeps the date entity. Goal-deadline
operations resolve through the TYPED referent store (goal domain), never an
active character; cross-domain pronoun → conflict refusal.

## 6. Response-format restoration (items 12/13 — PRODUCT REGRESSION)

`core/ai/worker_render.py` implements the rule "Worker decides WHAT happened;
the existing BAKA formatter decides HOW it is displayed": `render_run_reply`
walks the run's step trace and maps each ok ToolResult onto the same
Telegram-HTML the legacy handlers use (entity cards re-fetched from stored
fields via a `fetcher`; task/goal/habit/workspace lines; escaped; emoji'd).
Failed steps show ⚠️; MAX_STEPS shows only what completed; zero-render falls
back to the worker's own (escaped) text. A latent crash was caught and fixed
generically: the dispatch passes `(data, user_id, fetcher)` to every list
tool, but several list renderers took one argument — any real Worker `list_*`
would have TypeError'd. All list renderers now accept the 3-arg signature,
pinned by `test_render_every_list_tool_accepts_the_3arg_dispatch`. Tool
refusals (locked-topic delete, etc.) render their refusal text through the
data renderer rather than a generic "failed".

## 7. Workspace lifecycle audit (item11)

Deletion exists only at the DB level — not reachable from any user surface
(no command, no Worker tool). The invariant
`test_workspace_lifecycle_has_no_silent_destructive_path` pins the read+open
surface and guards that any future delete/archive workspace tool must be
DESTRUCTIVE + confirmation. RiskLevel audit: `delete_task` and
`delete_entity_topic` are the only DESTRUCTIVE tools; both carry
confirmation_message and are refused by the Worker's mechanical confirmation
gate before execution (CONFIRMATION_NEEDED).

## 8. Automated tests added

| File | Tests | Covers |
|---|---|---|
| `tests/test_worker_orchestration.py` | 75 (21 + 54 parametrized) | WKR-023…030 acceptance + S1–S30 generic invariants (compound chains, typed referents, goal-deadline domain, cross-domain refusal, deadline-clear) |
| `tests/test_worker_render.py` | 18 | response-format restoration (matrix H); the 3-arg list-renderer invariant |
| `tests/test_worker_topics.py` | 20 | topic lifecycle (matrix E): canonical binding, lock, refuse/force delete, repair, renderers |
| `tests/test_worker.py` | 36 | bounded loop (MAX_TOOL_CALLS=6), confirmation gate, failure taxonomy, honesty guard, source guard |
| `tests/test_worker_parser.py` | 26 | one-object extraction contract + fail-closed rules |
| `tests/test_tool_adapters.py` | 48 | 30-tool surface, risk classification, confirmation_message, workspace-lifecycle invariant, live-matrix tool-contract regressions |
| `tests/test_bugfixes.py` | +4 | date_parser period-end cases ("this/next month end", cross-year) |

Plus **2 new selftest probes** ("Topic Lifecycle Tools", "Topic Repair") and
the AI-category probes updated to the 30-tool surface + MAX_TOOL_CALLS=6.

## 9. Gates (verified today, not claimed)

- **Full pytest: 1631 passed** in ~25s (was 1569 before the remediation;
  +62).
- **Full offline selftest: 28 PASS / 0 FAIL / 0 WARNING.**
- **Regression registry: 117 specs, all unique, no duplicates** (16
  categories; worker_m4.py contributes WKR-001…031).
- **py_compile: clean. `git diff --check`: clean.**
- The AI-category selftest probes were themselves brought up to date this
  pass: they still pinned the pre-topic 25-tool registry and MAX_TOOL_CALLS=4
  and would have failed against the final surface — fixed to assert the 30
  tools and the typed-retrieval contract.

## 10. Live matrix PASS/FAIL

- Phase 1: 10 orchestration failures → all fixed generically.
- Second live pass: 7 reported failures → all LEGACY (Worker never ran);
  zero Worker defects.
- Third live pass (31 messages, WORKER=1, Llama): **11 genuine PASS**, 4
  legacy fallthrough, 3 tool-contract fixes (C3/A2/C8, C8 retested live),
  remainder = model capability (compound abandonment, declines, arg
  extraction). Not one remaining failure maps to Worker architecture.
- M4 is NOT accepted as production-ready for compound commands with
  Llama-8b (see acceptance, §12).

## 11. Remaining limitations

- **Task ordinal resolution does NOT exist** (scenario 14) — the Worker
  honestly asks for the id/title, never invents one. M5+ scope.
- **Partial-fabrication honesty (D3):** a reply that OVERSTATES partial
  success ("created Nefer and Lauma" when Lauma's step never executed)
  passes the never-fabricate guard (which only rewrites replies claiming
  success when NO tool succeeded). A deterministic fix needs fragile
  reply-parsing; deferred.
- **Typed-identity data fragmentation (C4/F1):** pre-M4 entities are
  `entity_type='entity'`, so typed lists and type-aware duplicate checks only
  see Worker-created typed entities. Preserved per the typed-identity design;
  a migration of legacy rows is a separate task.
- **NVIDIA `z-ai/glm-5.2` serves no output upstream** — provider hang, not a
  Worker bug; GLM-5.2 not deprecated.
- **Live Telegram acceptance is NOT claimed.** The Worker is dormant
  (`WORKER=0` default, owner-only canary). The owner must flip `WORKER=1`,
  restart, and run the WKR-001…031 manual matrix live before
  "live-accepted" is written anywhere.
- **Secret hygiene:** `.env.bak.pre-retest` and
  `planner.db.pre-retest-092300` were found untracked and un-ignored in the
  working tree (the `.env` backup contains `BOT_TOKEN`/`AI_API_KEY`).
  `.gitignore` was hardened (`.env.*`, `*.db.*`) so a stray `git add .` can
  no longer commit them; **the owner should delete both backup files.** The
  historical `ai_helper.py` key (deleted v14.12) is still in git history and
  still needs rotating (unchanged from DEBUGGING.md).

## 12. M4 acceptance status

**M4 (v15.2.0-alpha.14) is accepted as a dormant, contract-complete,
regression-pinned foundation** — the tool contract, typed retrieval, topic
lifecycle, response-format restoration, and workspace-lifecycle invariants
are all implemented, tested (1631 pytest, 28/0/0 selftest, 117 regression
specs), and documented. **It is NOT accepted as production-ready for
compound commands with Llama-8b** — the seam is validated (11 genuine
successes), but Llama's single-step/decline/arg-extraction limits are model
capability, not Worker architecture.

## 13. Recommended next step

1. **Owner:** delete the two un-ignored backup files; rotate the stale
   `ai_helper.py` key.
2. **Owner:** flip `WORKER=1`, restart, and run the live WKR-001…031 manual
   matrix (the final revalidation gate, item17 live portion).
3. **After the live matrix passes:** stamp M4 accepted; then re-evaluate
   GLM-5.2 on healthy NVIDIA / Z.ai-native for a real-model smoke pass.
4. **Then (and only then): M5 territory** — widen the canary beyond the
   owner, task ordinal resolution, and dashboard metrics. Per the owner
   directive, M5 has NOT been started and this release stays a v15.2 M4
   patch.
