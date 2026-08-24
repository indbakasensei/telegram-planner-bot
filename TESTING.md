# Testing

BAKA has two layers of testing: an automated `pytest` regression suite
(added in this project's first dedicated test-writing pass — see below)
covering deterministic, offline-testable logic, and manual Telegram-driven
testing via `/selftest` for everything that actually requires a live bot
(covered in the rest of this document).

## Automated test suite (`tests/`)

**1700+ tests, all offline** — no Telegram, no NVIDIA API, no network, and
every database test runs against an isolated temporary SQLite file (never
`planner.db`). Run with:

```bash
pip install -r requirements.txt   # includes pytest + pytest-asyncio
pytest                             # ~25 seconds, all 1631 tests
```

| File | Tests | Covers |
|---|---|---|
| `tests/test_date_parser.py` | 111 | Every `date_parser.py` function: relative days, weekdays (including "next X" edge cases), month/day/ISO dates, leap years, year-boundary rollover, vague time phrases, Hindi/Hinglish time words, AM/PM, 24h/military time, ambiguous "X baje", recurrence detection, multi-task detection, priority/deadline inference, and `parse_all()`'s integration of all of the above |
| `tests/test_scheduler.py` | 40 | `is_quiet_hours()` (including the overnight-wraparound boundary logic), `should_remind_again()`, `get_escalated_interval()`, `get_due_tasks()`'s five internal cases (one-time/daily/weekly/monthly/snooze-expiry) including de-duplication and "must not re-fire after clearing snooze", `get_tasks_needing_followup()` (quiet-hours and max-reminders-cap respected), `auto_carry_forward()`, and deadline-buffer round-tripping |
| `tests/test_database.py` | 32 | `init_db()` idempotency and completeness (all 13 tables, all 10 indexes, WAL mode, schema version), `verify_schema_integrity()` correctly detecting a missing table/index, `_safe_add_column()`, `backup_database()` (no-op on fresh, fires on existing, prunes old backups), CRUD across tasks/habits/goals/memories/project materials & worklog, and the Sprint 1C reset-command fix (`/resettasks` excludes habits; a goal reusing a deleted goal's ID inherits zero old project data) |
| `tests/test_notification_service.py` | 16 | `TelegramSender`'s per-chat vs. overall rate-limit buckets (unrelated chats don't serialize against each other), pacing under a burst, `RetryAfter`/`TimedOut`/`NetworkError` retry behavior, retry exhaustion (raises, doesn't loop forever), unrelated exceptions passing through untouched, and `safe_edit_message_text()`/`safe_answer_callback_query()`'s failure-mode handling (not-modified, deleted message, already-answered callback) |
| `tests/test_async_bridge.py` | 12 | `run_blocking()` actually executes off the calling thread, a slow wrapped call doesn't block concurrent fast tasks (with a control-group test proving the unwrapped case *does* block), exception propagation (type preserved, one failure doesn't affect concurrent siblings), and nested synchronous calls within a wrapped function (the exact shape of `generate_video()` calling `generate_image()` internally) all running in the same worker thread |
| `tests/test_intent_engine.py` | 40 | `core/intent/`'s tiered classifier (v14.0 Stage 1): all 10 required categories (add/edit/delete reminder, greeting, help, small talk, random/unknown input, time query, schedule query), ambiguity scoring when tiers disagree, purity (same input → same output, never reads the system clock), entity extraction, and latency (100% coverage of `core/intent/`) |
| `tests/test_routing_layer.py` | 23 | `core/routing/`'s Routing Layer (v14.1B): `destination` is always `LEGACY` regardless of input, every `confidence.evaluate()` branch (AI-shaped intents, unknown, high-confidence-not-yet-offline, below-clarify-band, ambiguous middle band, ambiguity safety cap, the currently-unreachable `OFFLINE` branch via `monkeypatch`), `RoutingDecision` contract (trace ID uniqueness/validity, `clarification_required` derivation, purity), and an end-to-end test against the real `IntentEngine` (100% coverage of `core/routing/`) |
| `tests/test_create_task.py` | 36 | `core/actions/create_task.py`'s two-phase write action (v14.3, Stage 2): verb-prefix/title extraction (all 4 verbs, case-insensitivity, unsupported text), recurrence mapping, `propose()` (validation rejection, duplicate detection, missing-clock handling), `commit()` (mirrors the same checks post-confirmation, deadline-marking with exception containment), `OfflineEngine.execute_pending()` dispatch, and **Behavioral Equivalence tests** that call `database.add_task()` the way Legacy does and `create_task.commit()` the way Offline does for equivalent inputs, then compare the resulting database rows field by field (100% coverage of `core/actions/create_task.py`, `core/offline/engine.py`, `core/storage/storage.py`) |
| `tests/test_update_task.py` | 41 | `core/actions/update_task.py`'s direct-apply write action (v14.4, Stage 3): entry-command recognition (`edit task`/`rename task`, both intent-classification paths), field-change recognition (priority/category/title/date-time/cancel), transaction safety (validate-before-write, per-field-only updates), `OfflineEngine.continue_editing()`/`execute()` dispatch, **Behavioral Equivalence tests** (Legacy's `update_task()` vs. Offline's `apply_change()` compared field by field, including verifying recurrence updates are unsupported in *both* paths), and **Failure Injection tests** (database exception, validation failure, cancel, verified-absent duplicate check, non-existent task) plus a Legacy-vs-Offline latency/memory benchmark (100% coverage of `core/actions/update_task.py`) |
| `tests/test_delete_task.py` | 28 | `core/actions/delete_task.py`'s two-phase destructive write action (v14.5, Stage 4): `propose()`/`commit()` (Locate/Preview/Delete/Verify), idempotency (a repeated confirmation or concurrent delete is reported gracefully, never double-executed), a verify-step test proving a silently-failed delete is never reported as success, **Behavioral Equivalence tests** (Legacy's `delete_task()` vs. Offline's `propose()`+`commit()`, including verifying no cascading cleanup in either path — a plain single-table `DELETE`), and all **8 Failure Injection scenarios** this sprint required (database locked, database exception, task missing, double confirmation, cancel, invalid ID, timeout, concurrent delete) plus a Legacy-vs-Offline latency/memory benchmark (100% coverage of `core/actions/delete_task.py`) |
| `tests/test_complete_task.py` | 38 | `core/actions/complete_task.py`'s direct-apply write action (v14.6, Stage 5): entry-command recognition (all four Legacy prefixes, id-less phrasings correctly rejected to Legacy's pick-list UX), the minutes-late delay computation (late/early/malformed/no-time), learning-log side effects verified by querying `completions_log`/`interaction_log` directly, the Legacy-matching exception swallow (a learning-log failure never un-succeeds the completion), all **8 failure scenarios** this sprint required (already completed, task missing, invalid ID, database exception, database locked, duplicate completion — including the verified Legacy re-log quirk, concurrent completion, invalid state/habit branch-away), engine dispatch (completion-before-edit, no crosstalk), **Behavioral Equivalence tests** comparing final database state field-for-field (task row + both learning-log tables, plus recurring-task completion), the no-undo Reversibility Review, and a Legacy-vs-Offline latency/memory benchmark (100% coverage of `core/actions/complete_task.py`) |
| `tests/test_lifecycle_task.py` | 55 | `core/actions/lifecycle_task.py`'s six lifecycle operations (v14.7, Stage 6): every Legacy entry phrase (pause/resume/snooze/stopreminder variants/carry-forward/paused-view), per-operation happy paths verified against the raw **scheduler-state columns** (`paused`/`snooze_until`/`due_time` — the columns `get_due_tasks()` filters on, so column equality *is* scheduler-state equality), idempotency matching Legacy's guardless UPDATEs, the full failure matrix (missing task, invalid ID, database exception/locked, duplicate, concurrent, wrong intent), a test pinning that archive/restore/hide/unhide/unsnooze **do not exist** in Legacy, Behavioral Equivalence tests per operation (including `snooze_log` rows field-for-field and carry-forward's paused/recurring exclusions), and a benchmark with **query-count instrumentation** (traced `sqlite3.connect`) asserting Legacy and Offline execute identical statement counts (100% coverage of `core/actions/lifecycle_task.py`) |
| `tests/test_offline_engine.py` | 35 | `core/offline/` + `core/actions/`'s Offline Engine (v14.2, Stage 1): `RequestContext`/`ActionResult` contract shape, dispatch (the registry's QUERY_TASK text-pattern matching for all four Stage 1 actions — exercised through `build_default_registry()` since v14.8, unsupported intent, unsupported action, exception containment), each action against real temp-DB data via the Storage Facade (including empty-result and missing-`now` branches), the feature-flag gating condition `main.py` uses, and AST-based checks that `core/offline/`/`core/actions/` never import `database` or `telegram` directly (100% coverage of both packages). *Count was misreported as 34 in this table before v14.8 — it was already 35 at the pre-refactor commit (verified by `pytest --collect-only` on `7ad1a0b`)* |
| `tests/test_action_registry.py` | 28 | `core/offline/registry.py` + `registrations.py`'s registry-based dispatch (v14.8, ADR-012): `ActionRegistry` mechanism with synthetic specs (registration/resolve ordering, duplicate-name and duplicate-pending detection, invalid registrations — non-`ActionSpec`, non-`Intent` key, empty name, non-callable match/run — all raising `RegistryError` at registration time), pending-commit registration/lookup, **default-registry configuration pins** (the exact intent set, spec names, and match-precedence ORDER for QUERY_TASK's search-first rule and EDIT_TASK/UNKNOWN's complete→lifecycle→update chain — reordering fails a test before it changes behavior), and `OfflineEngine` as a thin dispatcher over injected registries (first-match-wins, exception containment producing `action_exception:*`, `unsupported_intent` vs. `unsupported_action` vs. `unknown_action_type` fallbacks, default-registry fallback when none injected) (100% coverage of `core/offline/registry.py` and `core/offline/registrations.py`) |
| `tests/test_habit_views.py` | 43 | `core/actions/habit_views.py`'s three read-only Habit views (v14.9, Habit domain Stage 1) + `build_enabled_registry()` (ADR-013): entry matchers (`streak <id>`/`habitlog <id>`/`habit log <id>`, id-less and write-alias phrasings correctly left to Legacy), each view against real temp-DB data (fire-emoji cap, recurrence labels, conditional lines, HTML escaping of hostile titles, the replicated paused-habit "Habit not found or paused." quirk, 14-day 🟩/⬜ grid, missed-days warning + tip thresholds, empty-log-is-success), engine dispatch through the default registry, the **per-domain flag matrix** (all-off = empty registry; tasks-only has no habit specs; habits-only leaves task messages to Legacy; both-on == full catalog), Failure Injection (exception, locked database), **Behavioral Equivalence** (query-count parity with the exact `database.py` call sequence each Legacy handler makes, plus raw-row invariance proving reads mutate nothing), and latency/memory benchmarks. Seed dates are real-clock-relative, never hard-coded (the v14.1C windowing pitfall) (100% coverage of `core/actions/habit_views.py`) |
| `tests/test_habit_writes.py` | 42 | `core/actions/create_habit.py` + `skip_habit.py`, the v14.10 Habit Stage 2 deterministic writes: entry matchers (3 create prefixes with the args-join whitespace round-trip, 3 skip prefixes incl. `reset streak`, bare/malformed phrasings left to Legacy), creation against real temp-DB data (Health/medium defaults, time+recurrence parsing, the verbatim Legacy title-strip quirk — "every monday at 7 AM" survives into the title — empty-title rejection, **no duplicate detection**, HTML escaping), skip execution (`current_streak` reset with `longest_streak` and `habit_log` untouched, Legacy-matching idempotent repeats, the **self-healing reset** pin: the next completion recomputes and undoes it), engine dispatch with **no ADD_TASK crosstalk** (create_habit vs create_task prefix-gated in one bucket), the update/delete **needs-no-habit-code pins** (v14.4 edit and v14.5 delete flows claim habit rows), Failure Injection (exception, locked DB, no conversation-state markers; cancel documented N/A — nothing pends in a no-confirm flow), **Behavioral Equivalence** (row-for-row vs exact Legacy pipeline replicas across 3 phrasings; skip parity; delete-of-habit orphaning `habit_log` identically in both paths; query-count parity), and latency/memory benchmarks (100% coverage of both modules) |
| `tests/test_complete_habit.py` | 34 | `core/actions/complete_habit.py`, the v14.11 habit completion (Habit domain complete): its own AST-purity check, streak arithmetic against raw rows (extend, reset-after-gap with `longest_streak` preserved, singular "1 day"), the **already-logged-today pin** (success reply, byte-identical rows — the UNIQUE-trip rollback path), paused-habit completion (Legacy has no paused check — replicated), a **facade-spy test** proving the Intent→Registry→Action→Storage-Facade→database.py path, the **completion flag matrix** (both-on = one shared spec with the habit handler injected; tasks-only preserves v14.6's `habit_not_supported` fall-through; habits-only registers its own `complete_habit` spec — EDIT_TASK only — that declines real tasks to Legacy), failure injection (missing/invalid/non-habit id, locked DB, unexpected exception, integrity rollback), **learning-log absence** and **scheduler invariance** (only the three streak columns change; `done` stays 0; `get_due_tasks()` output stable), conversation-state absence, **Behavioral Equivalence** (rows/streaks/timestamps/`habit_log` field-identical across users; **SQL verb order and query count identical** via traced connections; weekly habits; second-completion parity), and latency/memory benchmarks (100% coverage of `core/actions/complete_habit.py`) |
| `tests/test_conversation_state.py` | 13 | `conversation_state.py` (first covered v14.12): the ADR-011 Option A dispatch-priority rule (`claims_messages()` truth table — `idle` allows intent-gated Offline dispatch, `confirming`/`gathering`/`editing` block it; the mid-confirmation/"done 5" regression pin), plus the state-machine contracts every Offline write flow relies on (pending-action, gathering, editing round-trips; clear-state; history cap) |
| `tests/test_fmt.py` | 7 | `fmt.py` (first covered v14.12): the always-escape property for every wrapper (the v7.1 Markdown-corruption lesson), the new rich-UI helpers (spoiler, blockquote, expandable blockquote, language-tagged code blocks), and the explicit `escape=False` opt-in for embedding pre-built HTML |
| `tests/test_log_sanitizer.py` | 10 | `log_sanitizer.py` (first covered v14.12, with the token-leak fix): masking pinned against the EXACT httpx request-line format that leaked the bot token (`/bot<id>:<token>/` — the old regex never matched it), bare-token masking, NVIDIA/OpenAI keys, Bearer/Cookie headers, URL query secrets, user-id redaction (admin vs. others), never-crash and idempotent-install properties |
| `tests/test_ui_cards.py` | 36 | Characterization tests for `ui.py`'s eight dashboard cards (UI Phase 1's mandatory first task — written against the pre-migration output, kept green through it): every field byte-exact (ids, titles, dates, streaks, percentages, insight lines, empty-state copy verbatim), every button label and callback_data byte-exact (reminder-ping buttons regression-critical), progress-bar/priority-dot/recurrence-icon exact formats, strikethrough on completed, dict-and-tuple task inputs, hostile-title escaping across cards; headings pinned case-insensitively (§5.1 uppercase H1 is the one permitted visible delta) |
| `tests/test_ui_utility_cards.py` | 18 | The utility-screen builders (extracted in Phase 5R, redesigned onto the component library in Phase 5 / v14.19 — these pins are the after-picture): settings (quiet-hours variants), debug toggle, bugs (empty/populated, auto-vs-report icons), trace (none/populated), insights (not-enough-data + full render), admin panel (stats + mode states), proactive (wellness toggle), help (structure, version, expandable sections, **admin-only section visibility**, broken-analytics commands unadvertised), AI status (error trio; success fields, escaped errors, quick-vs-full hint, the one extracted keyboard's `dash:home` Re-run callback pinned), models (online/offline/skipped + with/without analytics stats), selftest report (ok/failed verdicts, environment/flag blocks). Handlers are thin wrappers now — their calling lines still need the live smoke checklist |
| `tests/test_ui_components.py` | 38 | `ui_components.py`, the UI Phase 0 component library (UI_SPEC_v1.md §12): HTML generation with hostile input for every builder (headers, breadcrumbs, sections, pages, cards, states, confirmation dialogs), the §14 canonical empty-state copy pinned verbatim, button/keyboard generation, and every mechanical spec enforcement's raise path (closed icon vocabulary §5.5, canonical labels §7, status-never-without-words §6.3, 8-row card cap §5.3, 4,000-char page budget §6.1, 64-byte callbacks §5.7, 3-per-row / 12-per-message button caps §6.2, fixed Back·Refresh·Home nav order and no-empty-keyboard rule §2.5, safe-left confirmations §8, 3-segment breadcrumb depth §2.4), plus `fmt.link()` escaping |
| `tests/test_regression_spec.py` | 15 | `core/regression/`, the manual-regression specification foundation (v14.23, QA Phase 1 — no runner/UI): `RegressionTest`/`RegressionHistory` model (roundtrip, QUICK⊆MAJOR⊆FULL suite nesting), registry validation (bad id/category/empty-steps/no-suite rejected) + dedup + `by_suite`/`by_category`/`by_priority` queries, the version-aware JSON history store (record→persist→reload, pass/fail/skip counters, linked-bug dedup, corrupt-file resilience), and **Quick Release Suite integrity** (28 authored specs: unique ids, valid categories, executable steps, all Phase-2 focus areas covered). Distinct from the runtime frameworks — this is offline pytest over the spec data model |
| `tests/test_selftest_framework.py` | 14 | `core/selftest/`, the admin-only runtime Self-Test framework (v14.22): registration + dedup-by-name, the runner's outcome mapping (PASS/FAIL/WARNING/SKIPPED + uncaught-exception→FAIL with traceback), continue-after-failure aggregation, category include/exclude filters, `SelfTestReport` worst-outcome, real discovery of all 9 categories, a **full integration run under a temp DB** (every real check except the network AI probe passes and leaves zero rows under `SELFTEST_USER_ID`), and the admin-only UI builders' callbacks/shape (`dev_menu_card`, `selftest_screen_card`, `selftest_results_card`). *(This is the offline suite testing the runtime framework; the framework itself is exercised live by admins from the Debug Menu — see [docs/selftest.md](docs/selftest.md).)* |
| `tests/test_debug_ids.py` | 12 | `debug_system`'s independent bug-id presentation (v14.21): `DBG-0018` formatting (zero-padded, grows past 4 digits), tolerant parsing of every display form (`18`/`#18`/`DBG-0018`/`dbg18`/whitespace), rejection of malformed input, and format↔parse round-trip — pure helpers, never touches `bugs.db` |
| `tests/test_storage_facade.py` | 18 | `core/storage/`'s Storage Facade (v14.1C): every `TaskStorage`/`HabitStorage`/`GoalStorage`/`ProjectStorage` method delegates to exactly the `database.py` function it wraps, verified by asserting the facade's return value equals calling `database.py` directly (not just "doesn't crash") — proves pure delegation, zero reshaping (100% coverage of `core/storage/`) |
| `tests/test_feature_flags.py` | 19 | `core/feature_flags.py`'s rollout flags (v14.1C): the `_flag()` helper across truthy/falsy env-var spellings, all four flags defaulting OFF when unset, and — via `importlib.reload()` — that the exported constants actually pick up an environment variable at import time, not just the helper function in isolation (100% coverage of `core/feature_flags.py`) |
| `tests/test_ai_entity_manager.py` | 37 | `core/ai/entity_manager.py` (v15.1.0-alpha.10/11): NL→entity translation — create/update/retrieve routing, JSON extraction, template-agnostic field mapping, entity-by-name and reverse-partial matching, field-value filtering (`_filter_entities_by_query`), entity card/list formatting, query-token stop-word handling, retrieval by name, and the deterministic single-field update extractor (M1, alpha.12). All LLM calls mocked; offline and deterministic |
| `tests/test_reference_resolution.py` | 35 | M1 conversational references (v15.1.0-alpha.12): `core/ai/reference_context.py` + `reference_resolver.py` wired into EntityManager — create-then-pronoun ("create Furina" → "show her"), pronoun variants, ordinal selection (first/second/last), ordered-list persistence across activation, full-sentence pronoun retrieval, ambiguity + clarification, explicit-name-beats-active precedence, stale/deleted-entity self-heal, deterministic field updates, workspace isolation. Resolver is pure and LLM-free; tests assert bare references never reach the LLM |
| `tests/test_topic_projection.py` | 24 | v15.1.0-alpha.13 (M10) topic projection: `ensure_entity_topic` idempotency (no duplicate topic/card), initial card on NEW topics only, card-send failure swallowed, unlinked workspace → no call, `post_entity_update` append-only + self-heal, `backfill_topics` created/existing classification, re-run idempotency, initial cards reflect live DB state, unlinked/soft-deleted/empty-workspace handling, per-entity error collection, partial-then-retry recovery, transient vs persistent binding-write failure, stale bindings, cross-workspace same-name, duplicate create, long/Unicode names, card HTML escaping + sparse/dense fields |
| `tests/test_entity_manager_projection.py` | 8 | v15.1.0-alpha.13 (M10) EntityManager projection seam: NL create projects topic + initial card and activates, create/update without projection makes no call, projection failure keeps the DB op (create warns, update stands), deterministic + LLM update append old→new message with fresh self-heal card, bare reference and retrieve make no projection call |
| `tests/test_tool_contract.py` | 79 | v15.2 M2 Tool Contract Foundation (`core/ai/tools.py`): ToolSchema validation (A — malformed specs, duplicate names), argument validation (B — required, JSON types incl. bool≠integer + declared-null, enum, minLength, nested objects, unknown-arg drop/reject), risk behaviour (C), ToolResult (D — success/failure/structured data/warnings), ToolError stable codes (E), ToolRegistry (F — register/get/has/all/names/specs/openai_tools/execute), execution contract (G — valid executes, invalid never reaches `run()`, ToolError/exception containment, no-escape matrix), plus adversarial inputs (junk nested keys, wrong primitives, empty strings, None, collisions, dangerous metadata, invalid OpenAI schema). Also: `test_ai_foundation.py::test_registry_register_rejects_duplicate_name` pins the new duplicate-detection contract (replaces pre-M2 idempotent-replace) |
| `tests/test_tool_adapters.py` | 48 | v15.2 M3 Real Tool Adapters (`core/ai/tool_adapters.py`): entities (create/duplicate-reject/get by name-#id-workspace/list/status-filter/update/update+topic append-only/create+topic single-contract/creation-failure mirrors `/add`/update-post-failure best-effort/conversational reference via the M1 resolver/find/read-doesn't-move-active), tasks (create+list/reminder surface = due fields/duplicate-reject/invalid-datetime-reject/find/update/complete/delete), habits+goals (create/list/complete/complete-twice-is-not-an-error/`complete_task` takes the habit branch/progress-to-complete), workspace (list/get/open-MUTATING/inspect), memory+recall (get/search/grounded), mixed-capability chaining through ONE registry, adversarial (unknown-arg reject-on-write/drop-on-read, missing targets→invalid_args, no-fields updates, no-active-workspace, forward-compat unknown entity fields, invalid field value names the field, duplicate registration, execute-never-raises matrix, risk classification incl. no SYSTEM + `delete_task` DESTRUCTIVE confirmation), integration — RecorderProj (projection seam called with real card/update text) + FakeClient+TelegramProjection end-to-end (one topic, append-only, no second topic mechanism), **and the v15.2 M4 live-matrix tool-contract regressions (2026-08-11): integer workspace ids accepted by every workspace tool (C3), "leave-it-out" optional-filter markers `''`/`omit`/`none`/`all`/`any` mean "no filter" (C8), unmatched workspace name falls back to the active workspace with no-active still rejected (A2)**. Genshin acceptance fixtures (Xiao/Kinich/Xilonen/Nefer/Lauma/Columbina) are test data only. **Plus the v15.3 M5 lifecycle-tool tests: `create_workspace`/`rename_workspace`/`close_workspace` (MUTATING, close never deletes the row), `archive_workspace`/`delete_entity` (DESTRUCTIVE + confirmation_message, soft lifecycle transitions — never a DB delete, never the topic), `repair_topics` (idempotent report dict), and `equip_item` (equip/unequip via the game `weapon` field; wrong-kind item refused, nothing written)** |
| `tests/test_worker_parser.py` | 26 | v15.2 M4 Worker structured-output parser (`core/ai/worker_parser.py`): the one-object extraction contract (bare / ` ```json ``` `-fenced / prose-wrapped / nested braces / escaped quotes), and the fail-closed rules — zero objects, top-level array, unbalanced, EMPTY, or **multiple objects → error** (the F1 regression class; never "last one wins"), decision shape (missing/non-string/unknown action, non-object arguments, missing tool name, non-string reply, case-insensitive action), and injection resistance (a nested `tool`/`action` inside `arguments` is DATA, never the decision; embedded instruction keys ignored) |
| `tests/test_worker.py` | 36 | v15.2 M4 GLM-5.2 Worker (`core/ai/worker.py` + `worker_contract.py`), driven by a deterministic fake model (no network): decision actions (final/decline→legacy/tool), bounded loop (MAX_TOOL_CALLS=6 hard cap — never a 7th tool; model-call count ≤7; honest summary on budget exhaustion), mechanical confirmation gate (DESTRUCTIVE `delete_task` NEVER executes — CONFIRMATION_NEEDED, DB unchanged, confirmation_data for the existing pending-action machine; MUTATING still executes directly), failure taxonomy (timeout/HTTP/empty/malformed/multi-object/unknown-tool each stop after ONE attempt — no retry storms; invalid-args feed back once then stop; internal tool failure stops), never-fabricate-success guard (claims need a backing ok=True; invented sqlite claims rewritten), M1 references ('her' resolves to the active entity via the shared ReferenceContext), alpha.13 entity projection preserved through the Worker (FakeClient, one topic, no second mechanism), scenario 14 (task ordinals NOT implemented — honest limitation), scenario 16 (reminders ARE task due-times — no separate tool), date_parser injected authoritatively (PARSED block, not LLM-guessed), adversarial (prompt injection, malicious tool-result text as data, forged/forbidden tool names), structured logging (no raw user text, secret-keyed args redacted, request_id/termination present), source guard (worker.py must not import database/sqlite3/Telegram), MAX_TOOL_CALLS=6 constant, **and the v15.2 M4 live-matrix tool-contract regression — the Worker loop executes Llama-shaped args end-to-end: `workspace='default'` (A2), integer workspace id (C3), `'omit'` optional filters (C8) — all steps ok, final reply, DB committed (2026-08-11)**. Genshin acceptance fixtures are test data only |
| `tests/test_worker_orchestration.py` | 75 (21 + 54 parametrized) | v15.2 M4 orchestration acceptance matrix (WKR-023…030): compound create→set→show chains execute EVERY operation in order (F3/F5), typed referents are first-class context — the created entity's exact id appears in the NEXT prompt's REFERENTS block (F1/F2), a run-scoped referent beats a stale active entity (R5), update_goal_deadline registered + sets ONLY the goal's deadline (never Xiao's target_level) with this/next-month-end determinism (F6/F7), goal progress uses the goal domain, cross-domain pronoun conflicts are REFUSED never mutated (R9), same-named entities of different kinds stay distinct, ambiguous referents ask, create_entity duplicates are type-aware + entity_type is stored (F8), list_entities filters by entity_type (F9), typed retrieval excludes other kinds + goals/tasks stay in their own domain (F10), M1 entity-pronoun resolution unchanged (no regression). **Plus 28 parametrized GENERIC-INVARIANT tests (S1–S30, WKR-028…030)** added by the second-live-pass forensic pass: create→set→show across character/weapon/artifact names, create(A)→set(A)→show(B), show→update→show, update→show, two independent entities, cross-domain same-name identity, stale-active + fresh-create pronoun resolution, goal-referent domain conflicts, failed-tool recovery, success+failed retrieval traces, never-fabricate-success guard, unknown referents never mutating the active entity, max-steps honest summary, typed list filters never mixed kinds, task/habit domain isolation, artifact/weapon retrieval after create, and **deadline-clear (S30) — `update_goal_deadline` clearing a deadline to `None` is a success, not a false "goal not found"**. Plus `tests/test_bugfixes.py` gains 4 date_parser period-end cases ("this/next month end", cross-year) |
| `tests/test_worker_render.py` | 18 | v15.2 M4 **response-format restoration** (item12 — the PRODUCT regression): Worker replies are NOT plain prose — `core/ai/worker_render.py` routes each tool result through the existing BAKA formatter (entity/task/goal/habit/workspace cards, topic lifecycle renderers), every list tool accepts the 3-arg `(data, user_id=None, fetcher=None)` dispatch signature (the latent 1-arg `_list_entity_topics` crash — and the same class of crash for every list tool — pinned by `test_render_every_list_tool_accepts_the_3arg_dispatch`), `_TOPIC_REFUSAL_RENDERERS` route ok=False refusals through the data renderer (honest "refused" text, never a generic "failed"), and hostile/empty data never crashes |
| `tests/test_worker_topics.py` | 20 | v15.2 M4 topic lifecycle matrix (items7/8/10 — matrix E): ONE canonical topic per `(workspace_id, entity_id)` via the `_TopicTool` base (`get/ensure/set_locked/delete/list entity topic`), ensure idempotent (initial card only into a NEW topic), lock is durable across a fresh registry, a locked topic REFUSES ordinary deletes (ok=False) unless `force=true`, `delete_entity_topic` is DESTRUCTIVE + carries confirmation_message (the mechanical gate → CONFIRMATION_NEEDED, nothing deleted) and NEVER deletes the DB entity, honest no-projection / no-topic refusals, `repair_topics` collapses logical duplicates (one normalized title → one entity → one topic, kind adopted onto the canonical row, duplicate rows kept-but-skipped — never deleted, locked state preserved), and renderer coverage for every topic op incl. refused deletes |
| `tests/test_control_panel.py` | 38 | v15.3 M5 **Manual Control Plane** (`core/control/`): pages render offline (home/workspace/entity/topic/identity/equip — `(text, keyboard)` from `ui_components`, no Telegram needed), the shared M5-F confirm flow (`begin_confirm` sets a pending action reading `spec.confirmation_message`; `confirm_no`/`cancel_all` clear it and never execute), `execute_tool_async` runs the SAME `ToolRegistry` the Worker executes (no-second-logic proof), new-tool resolution (the 7 M5 tools all present in the control registry; DESTRUCTIVE ones carry confirmation messages), and router dispatch (`ctl:home`/`ctl:ws:*`/`ctl:ent:*`/`ctl:topic:*`/`ctl:ident:*`/`ctl:eq:*`) |
| `tests/test_m5_adversarial.py` | 41 | v15.3 M5 **M5-H adversarial matrix** — 14 scenarios × every feature, fresh names only (`M5_Test_Character_A/B`, `M5_Test_Weapon_A`, `M5_Test_Artifact_A`, `M5_Test_Adopt_A`, `M5_Test_WS_A/B`): workspace lifecycle (create→rename→open→close clears active context, row survives; duplicate titles NOT a false refusal; missing target strict; wrong-kind template rejected; repeated ops noop; cancel confirmation never executes; cross-workspace isolation), entity CRUD per kind (create/get/list kind-filtered; same-kind duplicate rejected; cross-kind on an UNTYPED row adopts; missing targets error; invalid field value → invalid_args, field never written; repeated delete errors cleanly; cancel delete keeps the entity; wrong kind never leaks), topic lifecycle (ensure→lock→unlock→delete; already-locked/unlocked noop; locked refuses ordinary delete, force ok; missing topic/entity contained errors; cancel force-delete keeps topic locked; cross-ws isolation), identity inspector (all 8 rows; missing entity page; stale after delete; cross-ws isolation), equip (equip/unequip via the game `weapon` field; wrong-kind item refused, nothing written; missing targets error; repeated op idempotent; cross-ws isolation), task/goal/habit foundation CRUD (create by id, complete by id; duplicate task same date rejected; missing targets error; invalid input rejected), and cross-user isolation (a second user's active workspace never leaks into the owner's surface) |
| `tests/test_m6_knowledge.py` | 35 | v15.4 M6 **Knowledge matrix A-E** — matrix A: note CRUD (create/retrieve/update/delete/duplicate/empty/long), B: note→1..N entities, note→1..N tags, unlink, deleted entity no ghost link, C: media metadata (photo/video/document, Telegram ids, same media from multiple topics/entities, retrieval by entity/tag/type), D: search (exact/partial + workspace/entity/tag/media/date + combined), E: isolation (ws A≠B, entity A≠B, same name across workspaces distinct) |
| `tests/test_m6_adversarial.py` | 21 | v15.4 M6 **Adversarial matrix F-I** — F: confirmation gates (delete without confirm→gate, cancel, confirm, repeated delete, stale refs), G: Worker integration (registry.execute, tool result authoritative, failed tool never fabricated, zero/multi results, multi-refs), H: manual=Worker path (same domain effects — no-second-logic proof for notes/media/tags), I: abuse/hostile input (prompt injection in stored note, malicious caption, fake tool-result text, unknown entity/tag, wrong workspace, deleted entity, duplicate media ref) |
| `tests/test_m7_retrieval.py` | 73 | v15.5 M7 **Cross-Reference Retrieval matrix A–R** — A: unified mixed-type search (notes+media in one result set, `_type` discriminator), B: entity AND/OR semantics (single+match-all vs match-any, Python-side set ops over multiple searches), C: tag AND/OR semantics, D: combined entity+tag, E: media-type filter, F: free-text query (title/content/caption/filename/extracted_text), G: date-range filters (created_after/created_before, IST), H: workspace isolation (CRITICAL — never cross-workspace), I: kind filter (notes only), J: limit + sorting (newest-first, default 50, max 200, honest truncation), K: empty results (returns `[]`, never fabricates/errors), L: original use cases (Ace/TenZ/1v4 clips, Arlecchino build notes), M: factory `build_retrieval_service`, N: `RetrievalFilters` dataclass, O: `RetrievalResult` dataclass, P: edge cases (duplicate ids, None fields, malformed inputs), Q: UI State Machine (14 tests — filter accumulation, clear, workspace switch, user isolation), R: Control Plane Integration (3 tests — page render, kwargs acceptance, cross-workspace isolation) |
| `tests/test_m7_adversarial.py` | *pending* | v15.5 M7 adversarial matrix — confirmation gates, Worker integration, manual=Worker path (no-second-logic proof), hostile input (prompt injection in stored note, malicious caption, fake tool-result text, unknown entity/tag, wrong workspace, deleted entity, duplicate media ref) |
| `core/selftest/tests/test_retrieval_selftest.py` | 4 | v15.5 M7 **Self-Test probes** (category: **Retrieval**): factory builds a service from a live `EntityEngine`; deterministic round-trip (create note+media+tags, search_knowledge returns mixed `_type`, no second logic); tool registry has all 3 M7 tools (`search_knowledge`, `search_notes_cross`, `search_media_cross`) at `RiskLevel.READ_ONLY`; control plane `search_home`/`search_results` pages render offline |
| `core/regression/suites/retrieval_m7.py` | 38 | v15.5 M7 **Regression suite RET-001…RET-038** (category: **Admin** + **AI**, Quick suite): unified search returns mixed types, entity AND/OR + tag AND/OR semantics, combined filters, media-type filter, free-text, date-range, workspace isolation (CRITICAL), kind filter, limit+sort, empty results, original use cases (Ace/TenZ/1v4 clips), Worker integration (3 M7 tools, READ_ONLY), control plane UI, pagination (50/page, no dups). **Owner-facing live checklist:** `docs/RET_LIVE_CHECKLIST.md` |

## Release Verification Guide (v14.21 — the canonical checklist)

Two layers: **[O] Offline** = covered by the automated pytest suite
(run `pytest`; green = verified). **[L] Requires Live Telegram** = must
be exercised in a real session (handlers, callbacks, rendered HTML,
scheduler pings — the suite deliberately never touches Telegram).
Before ANY release: run the suite, then walk every [L] block below in
one live session. The legacy 72-message parser checklist survives in
`debug_system.SELFTEST_MESSAGES` for deep date-parser regressions.

### Core engines & plumbing
- [O] Intent Engine classification (all tiers) — `test_intent_engine`
- [O] Routing Layer decisions — `test_routing_layer`
- [O] Offline Engine dispatch, registry, all Task+Habit actions —
  `test_offline_engine`, `test_action_registry`, per-action suites
- [O] Storage Facade delegation — `test_storage_facade`
- [O] Conversation state + ADR-011 gate predicate —
  `test_conversation_state`
- [O] Scheduler internals (quiet hours, due/followup/carry-forward) —
  `test_scheduler`
- [O] Database CRUD/migrations/integrity — `test_database`
- [O] Log sanitizer masking — `test_log_sanitizer`
- [O] All UI builders/components — `test_ui_*`
- [L] Offline Engine end-to-end (only with `OFFLINE_TASKS`/`OFFLINE_HABITS`
  ON): task+habit commands answer from the offline path; `debugbot.log`
  shows `[Offline]` blocks; unknown phrases still reach the AI;
  mid-confirmation `done 1` re-prompts (ADR-011) in both flag states.

### Dashboard [L]
`dashboard` → home renders (status card, productivity card) → every
button edits in place: `dash:today`, `dash:tasks` (+ per-task open →
task detail buttons Done/Snooze/Tomorrow/Edit/Delete/Back),
`dash:goals` (➕/➖ adjust progress inline), `dash:habits` (✅ Did
check-in), `dash:stats`, `🔄 Refresh`. Known dead-ends (documented, do
not fail the release on them): `dash:models_view/perf_view/errors_view`
from the `usage` keyboard.

### Tasks [L]
`add task Smoke test tomorrow 6pm` → confirm card → yes · `list` /
`today` / `week` / `overdue` / `search smoke` · `edit <id>` → change
time → applied · `done <id>` · `delete <id>` → confirm · `deadline
<id>` toggle · `snooze/pause/resume/paused/carryforward` · tags:
`tag <id> x` + `tagged x` · hostile title `a<b>&c` renders escaped
everywhere. Recurring-task detail via `dash:task:<id>`: EXPECTED BUG —
renders as completed (documented, v15).

### Habits [L]
`addhabit Smoke habit at 07:00 daily` (HTML card) · `habits` ·
`done <id>` (streak 1) · `done <id>` again (already logged) ·
`streak <id>` (grid) · `habitlog <id>` · `skiphabit <id>` · habit
titled `a*b_c` renders un-corrupted (closed v7.1 bug) · delete the
habit (task-delete path).

### Goals & Projects [L]
Say "I want to read 12 books this year" → goal created · `goals` +
➕/➖ buttons · `need <id> item1,item2` · `got item1` · `started <id>` ·
`worklog <id> note` · `project <id>` · `projects` · `shopping` ·
`finished <id>`.

### Workspaces & Entities [L] (v15.1.0-alpha.10)
Create workspace: `/newproject Drone` · `/newgame Genshin` · `/newgoal Reading`
· `/workspaces` lists them · `/use Genshin` switches active workspace ·
`/add Furina` creates an entity with its own topic · `/open Furina`
focuses it · `/current` shows active workspace/entity · `/note progress text`
logs a note · `/linkhere` (inside the group) links the group.

Natural language entity management (v15.1.0-alpha.10, requires active WS):
"Create character Furina" → entity created · "Hu Tao is level 80" → field
updated · "Hu Tao priority high" → priority field updated · "Show all level
70 characters" → retrieves matching entities · "Create weapon Staff of Homa"
→ entity created. Verify that: unknown entities get offered to create them ·
nonexistent fields get helpful error messages · existing fields update only
the changed value · `/commands` shows the full reference · `/help` workspace
section now includes NL examples.

Topic projection & backfill (v15.1.0-alpha.13): "Create character Arlecchino"
→ entity created AND a "Arlecchino" topic appears in the linked group with an
initial card (status + fields + IST timestamp) · "Arlecchino is level 90" →
the topic gets an append-only "Level: <old> → 90" message (old value only if
real) · `/topicbackfill` (admin) creates exactly one topic per existing
entity that lacks one (never duplicates, skips soft-deleted, re-run is a
no-op) · topic cards match `/show` (never invented) · unlinked workspaces are
reported skipped. Full matrix: `core/regression/suites/topic_projection_m10.py`
(TOP-001…TOP-009).

### Templates, Memory, Search, Export [L]
`savetemplate name <id>` · `template` · `template name` · "Remember my
exam is June 20" → `memory` → ask "when is my exam?" · `forget <key>` ·
`search <keyword>` (tasks+memories+habits+goals) · `export`.

### AI [L]
Free-text chat reply · `think <question>` · `plan today` → Apply
confirm flow · `plan week` · `breakdown <id>` · `reschedule <id>` ·
`analyze` · `insights` (HTML card) · `suggestions`/`approve`/`dismiss` ·
`status` + `status full` (benchmark card, Re-run button → Home) ·
`models` · `image <prompt>` · `video <prompt>` · send a photo.
KNOWN EMPTY (documented): `usage`, `performance`, `errors`.
DORMANT (v15.2 M2–M4, no user command routes through them): the AI Tool
Contract + Adapters + Worker — verify via `/selftest → AI → 'AI Tool
Contract'`, 'AI Tool Adapter Registry', 'AI Tool Adapter Round-trip', 'AI
Worker (dormant)', 'AI Worker Deterministic Round-trip' (all offline probes) +
the offline runs of `tests/test_tool_contract.py`, `tests/test_tool_adapters.py`,
`tests/test_worker.py`, `tests/test_worker_parser.py`,
`tests/test_worker_orchestration.py`, `tests/test_worker_render.py`,
`tests/test_worker_topics.py`. Nothing routes through
the Worker for normal users yet; the owner-only canary (WORKER=1) is NOT
live-accepted until the WKR-001…031 manual matrix (core/regression/suites/
worker_m4.py) is actually run.

### Settings & Utilities [L]
`settings` (HTML card) · `quiethours 22:00 07:00` → re-check settings ·
`interval 15` · `wellness on` / `off` · `proactive` · `help` (2
messages, expandable sections; admin section only for admin) ·
`cancel` escapes any pending state.

### Reminders & notifications [L]
Create a task due in ~2 min → reminder ping arrives with buttons →
test each: ✅ Done · ⏰ 10m · 🕐 1h · 📅 Tomorrow · 🔕 Stop · 🗑 Delete
(re-create between tests) · follow-up prompt after due time passes ·
quiet hours suppress pings · end-of-day summary at 21:00 (or verify
job scheduled in logs).

### Debug & bug reporting [L]
`debug` toggle ON (intent shown after messages) and OFF · `report test
issue` → reply shows `DBG-xxxx` id · `bugs` (DBG-prefixed list) ·
`resolve DBG-xxxx` and `resolve <n>` both work · `trace` (JSON entities
code block) · `selftest` (all checks ✅; version/provider/flags
correct).

### Admin [L] (admin account + one non-admin account)
Non-admin: `admin`, `sql`, `resettasks`, `debug`-era admin cmds →
silent "Unknown command" · `help` shows no admin section. Admin:
`admin` panel (stats card) · `adminmode` toggle · `myid` · destructive
resets ONLY on a disposable database: `resettasks` → YES RESET flow ·
`resolve`/`misses`/`reviewed`.

### Logging & security [L]
After the session: `grep -c 'api.telegram.org/bot' bot.log` → only
`botxxxxxxxxxxxxxxxx` masked forms, zero raw tokens · no httpx
per-request INFO noise · `debugbot.log` exists, contains DEBUG decision
traces, ids/keys sanitized · delete `debugbot.log` → recreated on next
DEBUG record.

**Found and fixed 3 real bugs in `date_parser.py` while writing tests**
(not scope creep — permitted and expected: writing a test against actual
behavior surfaces bugs a checklist-based manual pass had missed):
- "day after tomorrow" was parsed as tomorrow (its regex is a substring of
  the "tomorrow" pattern, checked first)
- "beete kal" (Hindi "yesterday") was also parsed as tomorrow, same
  root cause
- **every mention of "afternoon" was parsed as 12:00 (noon) instead of
  14:00** — "noon" is a literal substring of "afternoon" with no word
  boundary protecting against it

See `CHANGELOG.md`'s test-suite entry for the exact fixes.

### Remaining uncovered components

Deliberately not covered by the automated suite, and why:
- `main.py` — Telegram handlers; requires a live Telegram connection,
  explicitly out of scope for an offline suite. Covered by `/selftest`
  (manual) instead.
- `baka_brain.py` — requires the NVIDIA API; same reasoning.
- `preferences.py`, `ui.py`, `fmt.py`, `debug_system.py`,
  `log_sanitizer.py`, `instance_lock.py` — not covered yet. All are
  reasonably testable offline (most are pure functions or take an
  injectable DB path) and are good candidates for a future pass;
  `instance_lock.py` in particular already has proven test logic from its
  own Sprint 2B validation that was never ported into `tests/`.
- Full end-to-end command flows (e.g. "user sends a message → intent
  detected → task saved → confirmation sent") — this would need mocking
  the entire Telegram + AI + DB chain together; the individual pieces are
  covered, but integration-level testing was explicitly out of scope for
  this pass.

## Manual testing via `/selftest`

Testing is also driven by two overlapping resources that grew
independently — read the "two checklists" section below before using either.

## Quick start

1. Send `debug` (or `/debug`) to turn on verbose mode — every reply gets a
   debug box showing detected intent + extracted entities
2. Work through a section below
3. On any failure, send `report <what went wrong>` (or `/report ...`) —
   this auto-captures your last message, the detected intent, and context
4. After each section, send `bugs` (or `/bugs`) to review what got logged

## Two checklists — read this first

There are **two separate, independently-maintained test lists** that both
happen to use "Section" + letter naming, which collide:

1. **`TEST_CHECKLIST.md`** (this repo, root) — a hand-written manual testing
   guide, Sections A–R, ~189 tests. It predates v6.0+ features: there is
   nothing in it about the dashboard (v9.0), AI analytics (v11.1), multi-model
   AI (v11.0), or Projects (v12.0). Its own "Section P" is **Edge Cases &
   Error Handling** (15 tests).
2. **`debug_system.py`'s `SELFTEST_MESSAGES`** (in code, shown by the
   `/selftest` command) — 72 tests, Sections A–P, kept up to date through
   v12.0 (its "Section P" is 9 **Project Management** tests, added in
   v12.0). This is the more current of the two, since it's version-controlled
   alongside the features it tests.

**These are not the same Section P.** When someone says "run Section P,"
confirm whether they mean the checklist file or `/selftest`'s output.

**Recommendation:** treat `/selftest`'s output as the living source of
truth going forward (it's harder for it to silently drift from the code,
since a maintainer touching a feature is more likely to also be in
`debug_system.py`), and use `TEST_CHECKLIST.md` for its still-valid deep
coverage of parsing/reminder edge cases (Sections A–I, M–O, Q–R) that
`/selftest` covers more thinly. Whether to renumber one of the two to
remove the collision is tracked in [ROADMAP.md](ROADMAP.md).

### M5 selftest probes (v15.3)

The Manual Control Plane adds two offline probes under the **AI** category
(`core/selftest/tests/test_control_panel.py`):
- **"Control Plane (offline registry)"** — builds a control registry via
  `build_context` (no projection, no Telegram) and asserts the 7 M5 tools
  are present, none are READ_ONLY, `archive_workspace`/`delete_entity` are
  DESTRUCTIVE with confirmation messages, and no SYSTEM tool leaked in.
- **"Control Plane (pages + confirm flow)"** — renders the home/workspace/
  topic/equip pages (non-empty text + keyboard), and drives the shared
  M5-F confirm flow: `begin_confirm(..., "archive_workspace", ...)` sets a
  pending action whose question reads the tool spec's
  `confirmation_message`; `cancel_all` clears it without executing.

The two pre-existing "AI Worker" probes were re-pinned 30→37 tools and now
also assert the DESTRUCTIVE confirmation messages on all 4 destructive
tools (deliberate, documented pin update). The M5-H adversarial matrix
(14 scenarios × every feature, fresh names) lives in pytest as
`tests/test_m5_adversarial.py`.

### M6 selftest probes (v15.4)

The Knowledge + Media + Tags system adds three offline probes under the
**AI** category (`core/selftest/tests/test_knowledge_selftest.py`):
- **"M6 Knowledge Tool Registry"** — builds the full tool registry and
  asserts all 22 M6 tools (notes 9, media 9, tags 4) register with honest
  risk classifications: every write tool is MUTATING, the three delete
  tools are DESTRUCTIVE with confirmation messages, no M6 tool is SYSTEM,
  and `post_note` (the 23rd M6-related projection helper) is present.
  Total registry size is pinned at 60 tools.
- **"M6 Knowledge Round-trip"** — a deterministic note+media+tag round-trip
  through ONE registry against the live database with a fake Telegram
  client: create note/media linked to entity + tag, get/list by entity/tag,
  rename tag, soft-delete note — all domain services verified end-to-end
  with cleanup.
- **"M6 Control Pages Render"** — renders the Knowledge/Media/Tags home
  pages via `core/control/pages.py` (note_home, media_home, tag_home)
  against a temp DB with a recording FakeClient; asserts non-empty string
  output for each.

## `TEST_CHECKLIST.md` section map

| Section | Covers | Tests |
|---|---|---|
| A | Debug system (`/debug`, `/report`, `/bugs`, `/resolve`, `/trace`, `/selftest`) | 8 |
| B | Basic task creation | 12 |
| C | Hindi & Hinglish | 12 |
| D | Date & time parsing | 15 |
| E | Vague time phrases | 10 |
| F | Recurring tasks | 8 |
| G | Reminders & inline buttons | 12 |
| H | Overdue & deadlines | 8 |
| I | Passive PA (quiet hours, escalation, batching) | 12 |
| J | Habits | 15 |
| K | Smart planning | 12 |
| L | Memory system | 10 |
| M | Slashless commands | 15 |
| N | Multiple tasks in one message | 5 |
| O | Edit & delete | 8 |
| P | Edge cases & error handling | 15 |
| Q | Stress tests | 10 |
| R | Regression tests (catches previously-fixed bugs) | 12 |

For the exact test messages and expected results, read `TEST_CHECKLIST.md`
directly — reproducing all 189 rows here would just create a third copy to
keep in sync.

**Speed-run:** `TEST_CHECKLIST.md` has a 20-test "Quick Validation" section
near the end for when you don't have time for the full pass.

## `/selftest` (debug_system.py `SELFTEST_MESSAGES`)

Run `selftest` (or `/selftest`) to get the current checklist directly from
the code. Its Section P covers the v12.0 project flow end-to-end (P1–P9):
creating a project goal, adding materials, marking them acquired, logging
worklog entries with auto-detected kind, viewing the project card, and the
shopping-list aggregation. Section Q (v13.2, Sprint 3) covers
infrastructure — unlike every other section, these are verified by
restarting the bot and checking `bot.log`/the filesystem rather than a
Telegram reply, since that's what's actually being tested:
- `bot.log` shows `✅ Schema integrity OK` with a schema version,
  `journal_mode=wal`, and a foreign-keys value — not a warning
- `bot.log` shows `Database journal mode: wal`
- a `backups/` directory exists with a `planner.db.startup_migration.
  <timestamp>.bak` file after a restart on an existing database
- no `Migration failed` or `Unexpected database error` lines in `bot.log`

## Database infrastructure validation (v13.2, Sprint 3)

Not part of `/selftest` (nothing here is reachable via a Telegram
message) — validated instead with standalone scripts run against isolated
temporary databases, never the live `planner.db`, during development:
- `init_db()` is fully idempotent: running it twice on the same database
  (fresh, then again as if restarting) produces no errors and an unchanged
  `verify_schema_integrity()` report
- all 10 new indexes (see `ARCHITECTURE.md`) are actually created and
  present in `sqlite_master`
- `backup_database()` correctly no-ops on a fresh/empty database and
  correctly produces a backup file on an existing one
- ordinary CRUD across every major entity (tasks, habits, goals, memories,
  project materials, preferences) behaves identically to before — no
  command-visible regression
- the Sprint 1C reset-command fix (`/resettasks` excludes habits) still
  holds after Sprint 3's `init_db()` changes
- indexes measured on a synthetic 20,000-row dataset (the real
  `planner.db` is too small today for an index to show a measurable
  difference) — see `CHANGELOG.md`'s v13.2 entry for the numbers

## Regression-testing a change

Minimum bar before considering a change done:
1. The relevant `/selftest` section for the feature you touched
2. `TEST_CHECKLIST.md` Section R (regression tests) — these exist
   specifically because each one caught a real past bug
3. If you touched `date_parser.py` or the intent prompt in `baka_brain.py`,
   also run Sections C, D, and E of `TEST_CHECKLIST.md` — date/time parsing
   is the most bug-prone area in this codebase historically (see how many
   `CHANGELOG.md` entries are parser bugfixes)

## Phase 4 — Live Telegram Acceptance Testing (Playwright) [L]

**Added in v15.6 (2026-08-24)** — Real browser automation against QA bot.

### Prerequisites
- QA Telegram account (NOT personal account — `Baka_qa_bot`)
- Bot running: `python start_bot.py` (or `python main.py`)
- Playwright installed: `cd testing/playwright && npm install`

### Test Suite
```
testing/playwright/
├── playwright.config.ts      # workers: 1, fullyParallel: false
├── tests/
│   ├── 00_bootstrap_login.spec.ts  # Login Telegram Web, save session
│   ├── 01_start.spec.ts          # /start command execution
│   └── 02_commands.spec.ts       # /help, /tasks commands
├── profile/                    # Persistent Chromium profile
├── screenshots/                # Test screenshots
├── traces/                     # Traces on failure
└── reports/html/               # HTML reports
```

### Running Tests
```bash
cd testing/playwright
npx playwright test              # All 3 tests (sequential)
npx playwright test 01_start.spec.ts  # Single test
npx playwright show-report ../reports/html  # View report
```

### Key Configuration
- **Single worker** (`workers: 1, fullyParallel: false`) — prevents profile reuse conflicts
- **Headed mode required** (`headless: false`) — Telegram Web login needs real browser
- **Sandbox disabled** (`--no-sandbox --disable-setuid-sandbox`) — WSL compatibility
- **Multiple selector fallbacks** — Telegram Web UI changes frequently
- **Wait for visibility** — `waitFor({state: 'visible', timeout: 30000})` before interactions
- **Crash/close handlers** — `page.on('crash')`, `page.on('close')` for debugging

### Screenshots Captured
- `screenshots/start-command.png` — `/start` response
- `screenshots/help-command.png` — `/help` response
- `screenshots/tasks-command.png` — `/tasks` response

### Full Documentation
See [docs/testing/index.md](../testing/index.md) for complete testing guide.

---

## Known gaps in test coverage

- No automated tests — every pass above is manual, via live Telegram
  messages to a running bot instance
- No coverage for the AI analytics commands (`/usage`, `/performance`,
  `/errors`) actually returning correct data, only that they don't crash —
  which is moot right now since they're returning empty fallback data
  regardless (see [DEBUGGING.md](DEBUGGING.md#known-issues))
- No coverage for restart behavior of in-memory state
  (`conversation_state.py`, `debug_system.py`'s debug-mode/trace state) —
  see [ROADMAP.md](ROADMAP.md) fix-it list
