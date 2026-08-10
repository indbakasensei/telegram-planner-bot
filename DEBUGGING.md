# Debugging

## Built-in tooling

| Tool | What it does |
|---|---|
| `debug` / `/debug` | Toggles per-user verbose mode — every bot reply gets an appended debug box showing detected intent, extracted entities, and parsed date/time. State is in-memory only (see [Known Issues](#known-issues)) |
| `report <text>` / `/report` | Files a bug into `bugs.db`, auto-capturing the user's last message, detected intent, entities, and (for auto-caught exceptions) a full traceback |
| `bugs` / `/bugs` | Lists open bug reports |
| `resolve <id>` / `/resolve` | Marks a bug resolved |
| `trace` / `/trace` | Shows the last AI interaction in detail: input, intent, entities, reply. Backed by an in-memory rolling log of the last 50 interactions per user (`debug_system.py`) — also does not survive a restart |
| `selftest` / `/selftest` | Prints the current 72-test manual checklist from `debug_system.py`'s `SELFTEST_MESSAGES` — see [TESTING.md](TESTING.md) |
| `sql <SELECT ...>` (admin only) | Read-only SQL console against `planner.db`, capped at 30 rows |
| `bot.log` | Full activity log — messages, intents, entities, API errors, reminder fires, exceptions with stack traces. Passes through `log_sanitizer.py`, which redacts bot tokens, `nvapi-...`/`sk-...` keys, and Telegram user IDs before they hit the log file |

`error_handler` in `main.py` catches every unhandled exception in any
handler, auto-logs it to `bugs.db` via `debug_system.log_exception()`, and
replies to the user rather than crashing the process.

## Where to look for a given kind of bug

| Symptom | Likely cause / where to look |
|---|---|
| Wrong date/time extracted | `date_parser.py` regex patterns, or the AI overriding a value it shouldn't — check `get_baka_response()`'s disambiguation rules in [PROMPTS.md](PROMPTS.md) |
| Task misclassified (e.g. TASK vs HABIT vs GOAL) | `get_baka_response()`'s intent taxonomy/disambiguation rules, `baka_brain.py` ~L220-302 |
| Reminder fires at the wrong time, twice, or not at all | `scheduler.py`'s `get_due_tasks()` — five separate query cases (one-time, daily/weekly/monthly recurring, expired-snooze) each with their own dedup logic; see [docs/scheduler.md](docs/scheduler.md) |
| A dashboard button/callback does nothing or errors | `main.py`'s `handle_callback` router — check the callback's namespace prefix (`dash:`, `proj:`, plain) routes to the right sub-handler |
| `/usage`, `/performance`, `/errors` show nothing | Expected right now — see [Known Issues](#known-issues) below |
| State seems to "forget" what the user was doing | Check whether the bot process restarted — `conversation_state.py` and `debug_system.py`'s trace/debug state are in-memory only |
| Admin commands not responding | Confirm `/claimadmin` was run and `admin_id.txt` contains the right ID; admin denial is silent by design ("Unknown command"), not an error |

## Known issues

Found during the 2026-07 documentation pass. These are real, current gaps
between behavior and what earlier comments/docs claimed — not hypothetical.
Tracked with more remediation detail in [ROADMAP.md](ROADMAP.md#fix-it-list-found-during-the-2026-07-documentation-pass).

### Topic/binding writes are not atomic — orphan topic on persistent DB failure (v15.1.0-alpha.13, M10)

The entity-topic projection is **not** distributed-atomic (documented in
`docs/engineering/M13_TOPIC_PROJECTION.md`). A transient DB-write failure on
the binding right after `create_forum_topic` is retried once and normally
recovers; a **persistent** failure (disk full, schema error) leaves the
Telegram topic created but **unbound** — an orphan. `/topicbackfill` reports
it in `errors[]`, and a later re-run creates a fresh topic + binding; the
orphan is unreachable (we don't enumerate Telegram topics), so the duplicate
is accepted and documented rather than silently recovered. Rare, and only
under a genuinely broken DB writer.

### Strong-pronoun routing gap in EntityManager (v15.1.0-alpha.12, M1)

A message that is a *strong pronoun reference but not a bare reference* and
carries **no entity keyword** still falls through to the AI chat even when an
active entity exists — e.g. **"Can she ascend further?"**. The M1 resolver
(`core/ai/reference_resolver.py`) *would* resolve "she" to the active entity,
but `EntityManager.process()`'s pre-check gate requires a keyword match **or**
a bare reference to proceed (`core/ai/entity_manager.py`). The gate is
deliberately conservative (avoid hijacking unrelated messages), and widening
it risks false positives, so this was documented rather than fixed in M1.
Mitigation today: phrase entity questions with a keyword ("What level is she?",
"Show her weapon") — those route correctly. Tracked for a later milestone
(field-aware retrieval, M3; the AI-worker routing, M8).

### AI Tool Contract + Tool Adapters are dormant — not a bug, a state (v15.2 M2/M3)

`core/ai/tools.py` ships the full Tool Contract (RiskLevel, validated
`ToolSpec`, unified `ToolResult`/`ToolError`, fail-closed `validate_args`,
strict `ToolRegistry` with duplicate detection + `execute`), and
`core/ai/tool_adapters.py` (M3) adds **24 thin adapters** built on it via
`build_tool_registry(user_id, …)` — tasks, habits, goals, entities,
workspace, memory/recall. **No user command routes through any of it yet** —
there is no AI Worker, no agent loop, and no `main.py` routing change. If you
see the adapters "doing nothing," that is correct; their health is verifiable
via `/selftest → AI → 'AI Tool Contract'`, 'AI Tool Adapter Registry', and
'AI Tool Adapter Round-trip', plus the offline `tests/test_tool_contract.py`
and `tests/test_tool_adapters.py`. Documented limitations to know before
building on it:
- **`open_workspace` is now honestly `MUTATING`** (M3 fixed the M2-era
  READ_ONLY misclassification) in BOTH the `/ws` tool and the adapter —
  behavior unchanged because `/ws` calls `run()` directly.
- **`confirmation_message` / `requires_admin` are metadata only** — no
  confirmation/permission flow enforces them yet (the stable error codes
  `confirmation_required` / `permission_denied` are reserved for that
  milestone).
- **The adapters are create-only where the underlying API is create-only**
  (no `update_habit` — database.py has none); reminders are task due-times,
  not a separate tool.

### The `analytics` package doesn't exist — AI analytics commands are silently broken

`usage_logger.py`, `usage_service.py`, `model_metrics.py`,
`token_counter.py`, `performance_tracker.py` are written as if they belong
to an `analytics/` package (`usage_logger.py` uses `from .token_counter
import ...`, a package-relative import; `init.py` reads like that
package's `__init__.py`). **They currently sit flat at the repo root with
no such package.**

Effects, all currently live:
- `database.py`'s `init_db()` does `from analytics import init_usage_table`
  inside `try/except: pass` — the import fails, so the `ai_usage` table is
  **never created**
- `baka_brain.py` does `from analytics import log_ai_request` /
  `log_image_request` at 5 call sites, each wrapped in
  `try/except Exception: pass` — every AI call's attempt to log usage
  silently no-ops
- `main.py` does `import analytics` at the handlers for `/models`,
  `/usage`, `/performance`, `/errors`, each wrapped in try/except that
  falls back to empty stats or an error message

**Fix shape** (not applied — docs-only pass, see
[ROADMAP.md](ROADMAP.md)): create an `analytics/` package directory,
move the five files into it plus an `__init__.py` that re-exports the
names `main.py`/`baka_brain.py`/`database.py` expect
(`init_usage_table`, `log_ai_request`, `log_image_request`, plus whatever
`usage_service.py`/`model_metrics.py`/`performance_tracker.py` expose for
the query side). No schema or business-logic changes needed — this is
purely a packaging fix.

### Hardcoded-looking API key in `ai_helper.py` — file removed (v14.12), key rotation still pending

`ai_helper.py` (dead code) contained what looked like a real NVIDIA API
key passed as the argument name to `os.getenv(...)`. **v14.12 deleted
the file** in the repository cleanup, so the literal is gone from the
working tree — but it remains in git history, so **the key must still be
rotated** before treating this as closed.

### In-memory-only state doesn't survive a restart

`conversation_state.py`'s own docstring says its module-level dicts
"survive across messages reliably" — true within one running process, but
they're wiped on every restart. `feature_list.md` (now superseded) went
further and claimed this meant state "survive[s] bot restarts," which is
incorrect. Same limitation applies to `debug_system.py`'s per-user
debug-mode flag and last-trace log. Practical effect: if the bot crashes or
is redeployed while a user is mid-conversation (e.g. in `gathering` or
`editing` state), that user's in-progress action is silently lost and they
return to `idle`.

### `check_reminders` and `check_followups` don't check quiet hours

Every other scheduled job in `main.py` calls `is_quiet_hours(uid)` before
acting; these two primary reminder jobs don't. Unconfirmed whether this is
intentional (arguably you always want the *first* reminder to fire, only
follow-ups should respect quiet hours) — flagged here rather than assumed.

### `check_deadlines` bypasses the data-access layer

This one job opens its own `sqlite3.connect("planner.db")` directly instead
of going through `database.py`, the only place in `main.py` that does so.
Not a correctness bug, but an inconsistency worth fixing for
maintainability.

### Stale model references outside `baka_brain.py`

`token_counter.py`'s `MODEL_COSTS` table still lists `z-ai/glm-5.1`,
`flux.1-dev`, and `cosmos-1.0-7b-text2world`, none of which are the
models actually in use anymore (see [docs/ai_system.md](docs/ai_system.md)).
Cost/provider lookups for current models fall through to a fuzzy-match
fallback or return `$0.00`/`"Unknown"`. This will self-resolve once the
analytics package fix above lands and someone updates the cost table
alongside it — until then, don't trust any cost figures the analytics
commands would show even after the import is fixed.

### Version banner lag — partially resolved (v13.2)

The startup **log line** now derives from a `BAKA_VERSION` constant near
the top of `main.py` instead of a hardcoded string, fixed in Sprint 3 as
part of that sprint's "improve logging around startup" task. **Still
open**: user-facing text (e.g. `/help`) may still reference an older
version — deliberately not touched, since that's Telegram UX, out of
Sprint 3's infrastructure-only scope. Worth a grep for stale version
literals in `main.py`'s user-facing strings next time that area is
touched.

### Intent Engine (v14.0 Stage 1) — known architectural debt, not bugs

Found during Stage 1 implementation. All four are deliberate, documented
tradeoffs (see `core/intent/rules.py`'s module docstring and
`docs/adr/ADR-002-intent-engine.md`'s "Implementation Note"), not
oversights — listed here per this project's convention of tracking real
gaps even when they're accepted rather than fixed.

- **Duplicated command tables.** `core/intent/rules.py`'s Tier 0
  `_PREFIX_COMMANDS`/`_EXACT_COMMANDS` are a hand-maintained mirror of
  `main.py`'s `_starts_with_handlers`/`_exact_handlers`. True reuse isn't
  possible without a `main.py` refactor (those are local variables inside
  `handle_message()`, and `core/intent` importing `main.py` would be
  circular, since `main.py` imports `core.intent` for Shadow Mode). If
  `main.py`'s command tables change, `rules.py`'s copy will silently drift
  out of sync — there is no automated check for this yet.
- **Representative, not exhaustive, command coverage.** Tier 0 covers the
  most common command groups verified against `main.py` at implementation
  time, not all ~90 commands. Uncovered commands still work exactly as
  before (Shadow Mode doesn't affect routing) — they just fall through to
  a weaker tier (or `UNKNOWN`) in the *classification log only*.
- **Shadow-mode exception handling.** `main.py`'s integration point wraps
  the `classify()` call (and, since v14.1B, the Routing Layer's `route()`
  call — same `try` block) in `try/except Exception: logger.exception(...)`
  — broader than this project's usual `except sqlite3.OperationalError`-style
  specificity (`CLAUDE.md`'s migration-exception convention). Deliberate:
  the backward-compatibility requirement ("users should notice absolutely
  no behavioural difference") means a bug in brand-new, unproven
  classification or routing code must never be able to break the message
  handler it's observing, at the cost of a broad except swallowing a real
  bug if one occurs. Check `bot.log` for `"Intent Engine / Routing Layer
  failed"` if you suspect this is masking something.
- **Future routing integration — partially resolved (v14.1B).** The
  Intent Engine's output was logged but unread through v14.0. As of
  v14.1B, `core/routing/`'s Routing Layer *does* compute and log a real
  `recommended_destination` for every message — the comparison mechanism
  this bullet originally called for now exists. **Still open**: nothing
  compares that recommendation against what `handle_message()`'s Legacy
  path *actually did* for the same message (the Routing Layer computes a
  recommendation but has no visibility into Legacy's own outcome) — that
  correlation would need a second log line from the Legacy side, keyed by
  `RoutingDecision.trace_id`, not yet built. See the Routing Layer's own
  debt entry below for what v14.1B does and doesn't close.

### Routing Layer (v14.1B) — known architectural debt, not bugs

Found during Sub-stage B implementation
(`DRG-001_Intent_Aware_Routing.md`, `docs/adr/ADR-006-intent-aware-routing.md`).
All deliberate, documented tradeoffs, not oversights.

- **`recommended_destination` can never actually equal `OFFLINE` today.**
  `core/routing/routing_matrix.py`'s `OFFLINE_ENGINE_IMPLEMENTED_INTENTS`
  is an empty `frozenset` — the Offline Engine doesn't exist yet
  (`OFFLINE_ENGINE.md`, Stage 2 not started). Every currently-reachable
  recommendation is `LEGACY`, `AI_ROUTER`, or `CLARIFY`. This is by
  design, not a bug — `tests/test_routing_layer.py`'s
  `test_offline_recommendation_once_a_future_stage_implements_an_intent`
  verifies the `OFFLINE` branch's logic directly (via `monkeypatch`) since
  production traffic can't reach it yet.
- **"Execution duration" is the Routing Layer's own decision latency, not
  the downstream Legacy handler's wall-clock time.** The v14.1B task brief's
  Logging section asked for both, implicitly assuming they're one
  measurement. They aren't: `RoutingDecision.decision_latency_ms` is
  measured entirely inside `RoutingLayer.route()`, before
  `handle_message()`'s Legacy routing even begins. Measuring the Legacy
  handler's own execution time would require wrapping the *rest* of
  `handle_message()`'s body (hundreds of lines, dozens of early `return`
  statements across the menu/confirming/editing/gathering/slashless-command
  branches) in a `try/finally` — judged too invasive for an
  "infrastructure only" integration sprint. Deferred; see Roadmap.
- **A confidence-boundary tension inherited from `INTENT_ENGINE.md`.**
  That document's per-intent-class execution thresholds (reversible-write:
  0.75) and its separate confidence-band table (0.6–0.84 described as
  "ambiguous, missing field") don't perfectly align at the boundary: a
  confidence of exactly 0.75 *clears* `core/routing/confidence.py`'s
  reversible-write threshold (routing recommends `LEGACY`, not `CLARIFY`),
  even though the band table would describe 0.75 as still "ambiguous."
  This is a pre-existing tension in the already-approved design, not
  something v14.1B introduced — `date_parser.py`'s Tier 1 partial match
  (date resolved, no time) lands exactly on this boundary at confidence
  0.75, so it's a real, reachable case, not a theoretical edge. Worth
  resolving explicitly (which table wins at the boundary) before Sub-stage
  C makes the distinction consequential.
- **`main.py`'s Legacy Router has no visibility into the Routing Layer's
  recommendation.** By design, this sprint (v14.1B) never lets Legacy read
  `recommended_destination` — but that also means there's no way yet to
  tell, from logs alone, whether Legacy's *actual* behavior for a given
  message agrees with what the Routing Layer would have chosen. Closing
  this gap (Legacy-side outcome logging, correlated by `trace_id`) is
  necessary before Sub-stage C's real routing decisions can be validated
  against real Legacy behavior as a baseline.

### Storage Facade and feature flags (v14.1C) — partially resolved (v14.2)

Found during v14.1C implementation.

- **`core/storage/` and `core/feature_flags.OFFLINE_TASKS` are now
  consumed — resolved (v14.2).** `core/offline/`/`core/actions/` use the
  Storage Facade exclusively (AST-enforced by
  `tests/test_offline_engine.py`), and `main.py` reads `OFFLINE_TASKS`
  to gate the entire Offline Engine integration point. Still unconsumed:
  `OFFLINE_HABITS`/`OFFLINE_GOALS`/`OFFLINE_PROJECTS` (no corresponding
  Offline Engine domain exists yet).
- **The two "is this feature offline yet" signals are still not fully
  reconciled — deliberately, not by oversight (v14.2).**
  `core/feature_flags.OFFLINE_TASKS` and `core/routing/routing_matrix.py`'s
  `OFFLINE_ENGINE_IMPLEMENTED_INTENTS` (still an empty `frozenset`) remain
  separate. This was considered directly during v14.2
  (`docs/adr/ADR-007-offline-engine-stage1.md`'s Consequences) and kept
  separate on purpose: `Intent.QUERY_TASK` is coarser than what the
  Offline Engine actually implements (four specific phrasings, not all of
  `QUERY_TASK` — see the next entry), so populating
  `OFFLINE_ENGINE_IMPLEMENTED_INTENTS` with `Intent.QUERY_TASK` would
  incorrectly imply full coverage. `main.py`'s actual gate is
  `feature_flags.OFFLINE_TASKS` plus `OfflineEngine.execute()`'s own
  graceful `unsupported_action` fallback — `core/routing/`'s
  recommendation is informational only for now, not wired to real
  dispatch. Revisit once the Offline Engine covers whole intent classes,
  not fragments of one.
- **Storage Facade coverage is representative of four domains, not
  exhaustive of `database.py`'s ~120 functions.** `TaskStorage`/
  `HabitStorage`/`GoalStorage`/`ProjectStorage` cover the core CRUD each
  domain's feature flag implies, not every `database.py` function in that
  domain's neighborhood (e.g. memory/settings/template/analytics functions
  have no facade wrapper at all yet). Extending coverage as the Offline
  Engine actually needs more functions is expected, low-risk, incremental
  work — the same "representative, not exhaustive" pattern already
  accepted for `core/intent/rules.py`'s Tier 0 command table.

### Offline Engine action dispatch is text-pattern-based, not Intent-based (v14.2, v14.3)

`Intent.QUERY_TASK` (`core/intent/intent_types.py`) is deliberately
coarser than the four read-only task actions Stage 1 implements — it also
covers `/habits`, `/goals`, `/dashboard`, `/settings`, and more
(`DRG-001_Intent_Aware_Routing.md` Section 7's Routing Matrix). Neither
`IntentResult.intent` nor `.entities` carries a signal distinguishing
"list" from "today" from "week" from "search" (Tier 0's exact-phrase
matches produce empty `entities`, `core/intent/rules.py`). The
QUERY_TASK matchers in `core/offline/registrations.py` (v14.8; lived
inline in `engine.py`'s `_select_action()` v14.2–v14.7) resolve this
with a narrow, hand-maintained mirror of `core/intent/rules.py`'s own
Tier 0 phrase groups, checked directly against `RequestContext.text` — a
third level of the same accepted duplication pattern (`main.py`'s tables
→ `core/intent/rules.py`'s mirror →
`core/offline/registrations.py`'s mirror of a slice of that mirror). If any of
these three drift out of sync, the symptom is a message that Legacy would
handle one way but the Offline Engine (once its flag is enabled) would
either handle differently or not recognize at all — check all three
before assuming a routing bug is anywhere else. The real fix — a
structured action/command hint added to `IntentResult.entities` at
classification time — is deliberately not built yet
(`docs/adr/ADR-007-offline-engine-stage1.md`'s Decision explains why
modifying the already-Accepted Intent Engine wasn't done for this sprint).

**v14.3 has a second, more severe instance of the same problem**:
`Intent.ADD_TASK` doesn't reliably classify the four create-task verbs at
all — verified directly: `"todo buy milk"` classifies `UNKNOWN` (no rule
matches it), `"add task buy milk"` classifies at confidence ~0.4 (Tier 4,
weak keyword), both below `INTENT_ENGINE.md`'s approved 0.75
reversible-write threshold. `core/actions/create_task.py`'s
`_match_prefix_and_title()` is its own independent prefix table (a
*fourth* level of the same duplication chain, not reusing
`core/offline/registrations.py`'s search matcher since it matches
different verbs). See `docs/adr/ADR-008-offline-write-operations.md`'s
Decision.

**v14.4 has a third instance**: `"edit task 5"` correctly classifies
`Intent.EDIT_TASK` at confidence 1.0 (Tier 0's existing `"edit "` prefix
already covers it), but `"rename task 5"` classifies `Intent.UNKNOWN` —
there is no `"rename "` Tier 0 prefix at all. `OfflineEngine.execute()`
gates entry-command recognition on `context.intent in (Intent.EDIT_TASK,
Intent.UNKNOWN)` to compensate, relying on
`core/actions/update_task.py`'s own specific `_ENTRY_RE` regex for
correctness rather than the coarse intent check. A *separate* dispatch
problem also appears here for the first time: message 2 of the update
flow (the change description, e.g. "set time to 6pm") cannot be
Intent-Engine-gated at all, reliably or otherwise — a bare reply like
that carries no EDIT_TASK signal on its own, since `core/intent/rules.py`
has no notion of conversation state. `core/offline/engine.py`'s
`continue_editing()` is gated on `conversation_state`'s `"editing"` state
directly instead, checked by `main.py` before any intent-based dispatch —
see `docs/adr/ADR-009-offline-task-update.md`.

### Offline task creation: known limitations, verified inherited from Legacy, not introduced (v14.3)

Found while writing Behavioral Equivalence tests. Both confirmed present
in Legacy too (via direct code reading / testing), not Offline-only
regressions:

- **Duplicate detection silently fails for tasks with no due date.**
  `database.task_exists()`'s `WHERE due_date=?` never matches when
  `due_date` is `NULL` — standard SQL semantics (`NULL = NULL` is not
  `TRUE`), not a bug in the query. Since Offline's `create_task.propose()`/
  `commit()` call this function verbatim via the Storage Facade, this
  limitation is inherited exactly, not introduced. `tests/test_create_task.py`'s
  `test_equivalence_duplicate_detection_matches_legacy_exactly` verifies
  the two paths behave identically, including this quirk.
- **`commit()` re-validates against the real system clock, not the
  original message's time.** `date_parser.validate_datetime()` defaults
  to `_now()` (the real clock) when no `now` is passed, and neither
  `commit()` nor Legacy's `execute_task_action()` passes one — verified
  by reading `execute_task_action()` directly. This means a task proposed
  as valid can be rejected at confirm time if enough wall-clock time
  passes and the date becomes stale — correct, intentional behavior in
  both paths, not a bug. Caught during this sprint's own manual testing
  when a test used a fixed simulated `now` for `propose()` and the real
  clock for `commit()`'s validation disagreed — a test-writing pitfall
  worth knowing about, not a code defect: always use a consistent `now`
  (or the real clock throughout) when testing propose-then-commit flows.
- **Titles retain trailing date/time phrases verbatim.** Documented as a
  deliberate, accepted limitation (not attempted to fix with fragile
  regex stripping) in `docs/adr/ADR-008-offline-write-operations.md`'s
  Decision — not a bug report, listed here for discoverability.

### Offline task update: known limitations, verified inherited from Legacy, not introduced (v14.4)

Found while writing Behavioral Equivalence tests, same discipline as the
v14.3 entry above.

- **Legacy's real update flow has no confirm step, contrary to what an
  earlier reading of the task brief for this sprint assumed.** Verified
  by reading `main.py:1022-1055` directly: `update_task()` is called
  immediately on the next message after `/edit <id>`, with no yes/no
  step and no `set_pending_action()` call. Offline Update matches this
  real behavior (`apply_change()` commits immediately) rather than the
  brief's assumed confirm-flow — implementing the brief's described step
  would have been a behavioral *divergence* from Legacy. See
  `docs/adr/ADR-009-offline-task-update.md`.
- **Recurrence cannot be updated in either path.** `database.update_task()`'s
  real signature has no recurrence parameters at all, despite "change
  recurrence" appearing as a SUPPORTED example in an earlier reading of
  this sprint's task brief. Not an Offline gap — Legacy genuinely cannot
  do this today. `tests/test_update_task.py`'s
  `test_equivalence_recurrence_cannot_be_changed_in_either_path` verifies
  this directly.
- **Legacy's update flow never validates dates or checks duplicates.**
  Verified by reading the handler: no `validate_datetime()` call, no
  `task_exists()` call. Offline Update deliberately adds date/time
  validation (this sprint's own Transaction Safety requirement justifies
  it — a safety-only addition, no user-visible flow change) but
  deliberately does *not* add duplicate-checking (no such requirement
  existed, and adding one would be an unequivalent enhancement, not a
  safety net). Two different divergences from Legacy, two different
  justifications — not treated the same way by default.

### Offline task completion: known behaviors, verified inherited from Legacy (v14.6)

Same discipline as the v14.3/v14.4 entries — verified against Legacy's
real code, matched rather than "fixed":

- **No undo exists in either path.** Zero undone/uncomplete/undo matches
  anywhere in `main.py` (verified by grep). A completed task's row
  survives (`done=1`) but no user-facing command flips it back. Per the
  v14.6 sprint's own Reversibility Review instruction: documented, not
  invented — Offline adds no undo either.
- **Re-completing an already-done task succeeds silently and re-logs, in
  both paths.** `get_task_by_id()` has no done-flag filter, `mark_done()`'s
  UPDATE is idempotent, and Legacy's `done_task()` has no already-done
  guard around `log_completion()` — so a duplicate completion adds a
  *second* `completions_log` row in Legacy today, and Offline matches
  exactly (tested). If `preferences.py`'s learning stats ever look
  inflated, duplicate completions are a plausible cause in either path —
  a pre-existing Legacy quirk, not an Offline regression.
- **Habits never reach the Offline path.** Legacy's `done_task()` checks
  `is_habit()` before `mark_done()` and routes habits to streak logic
  instead; Offline's `complete_task.execute()` replicates the check and
  returns `habit_not_supported`, falling through to Legacy untouched. If
  a habit's streak behaves oddly, the Offline Engine is not a suspect —
  it never writes anything for habits, in either flag state.

### Offline task lifecycle: verified findings (v14.7)

Same discipline as the v14.3–v14.6 entries:

- **Archive, Restore, Hide, Unhide, and Unsnooze do not exist in
  Legacy** — zero matches in all of `main.py`, verified during v14.7's
  Phase 0. Not invented; a test
  (`test_archive_restore_hide_unhide_do_not_exist`) pins the finding so
  a future sprint doesn't accidentally "restore" a feature that never
  was. If a user asks for these, it's a feature request, not a
  regression.
- **stopreminder's reply text is misleading — in both paths, on
  purpose.** It says "Use /resume <id> to turn back on", but
  `resume_task()` only flips `paused`; it does not restore the
  `due_time` that `stop_reminders()` cleared, so resuming after
  stopreminder does *not* bring the pings back. A Legacy wording quirk,
  faithfully mirrored per behavioral equivalence (a wording quibble is
  neither a genuine bug nor a safety issue under v14.7's improvement
  criteria). If a user reports "resume didn't restart my reminders,"
  this is why — in Legacy and Offline alike.
- **Delreminder needed no migration** — it's a pure delete alias
  (`delreminder_cmd` calls `delete_task()`), and `"delete reminder <id>"`
  already classifies `DELETE_TASK`, so v14.5's offline delete path
  (including its deliberate confirm step, `ADR-010`) already covers it.
- **Postpone is callback-only** — `postpone_task()` is reachable only
  via reminder buttons (`handle_callback`), not the text-message path
  the Offline Engine integrates with. Out of scope, unchanged.

### Legacy habit surfaces: verified findings (v14.9)

Same discipline as the v14.3–v14.7 entries, from v14.9's Phase 0 audit
of every habit code path:

- **All five habit handlers replied in Markdown with unescaped
  titles — RESOLVED in v14.20 (UI RC1)**: `habits_cmd`, `streak_cmd`,
  `habitlog_cmd`, `addhabit_cmd`, `skiphabit_cmd` now render HTML via
  `ui.py` builders (`habits_overview_card` etc.) with component
  escaping — a hostile habit title no longer corrupts the reply, and
  Legacy/Offline replies are format-consistent for the first time.
  (Historically: never migrated in v7.1's HTML switch; the Offline
  habit views were HTML from birth in v14.9.)
- **Habit-specific update, delete, today view, search, statistics, and
  archive/restore do not exist in Legacy** — verified; not invented.
  "Deleting a habit" is just `delete task <id>` on the habit's task
  row, which **orphans its `habit_log` rows** (no cascading cleanup —
  consistent with v14.5's verified single-table DELETE).
- **Missed days never auto-reset a streak.** No scheduler involvement
  in habits at all (zero habit references in `scheduler.py`); a streak
  only changes when `log_habit_completion()` recomputes it from the log
  at the next completion. Corollary: `/skiphabit`'s `reset_streak()`
  (sets `current_streak=0`) is **self-healing** — the next completion
  recomputes the streak from the full log history, overwriting the
  reset. It is therefore *not* irreversible under `ADR-010`'s test, and
  Legacy's no-confirm behavior is the right thing to match when a later
  stage migrates it.
- **`streak_cmd`'s paused-habit quirk, replicated**: it locates via
  `get_task_by_id` + `is_habit`, then re-fetches through `get_habits()`
  (which filters `paused=0`) — so a paused habit passes the first check
  and dies at the second with "Habit not found or paused."
  `streak_detail()` mirrors this exactly (warning:
  `habit_not_visible`).
- **Habit completion writes no learning logs.** `done_task()`'s habit
  branch calls `log_habit_completion()` and replies — no
  `completions_log`, no `interaction_log` (unlike the task branch).
  v14.11 migrated it exactly so (`core/actions/complete_habit.py`,
  learning-log absence test-pinned). Two more verified-and-replicated
  details from that migration: **already-logged-today is a success
  reply with zero writes** (the UNIQUE trip returns before any streak
  UPDATE — "✅ Habit completed!" + "(already logged today)", in both
  paths), and **a paused habit completes fine** (no paused check
  anywhere in the pipeline). The v14.6 `habit_not_supported`
  branch-away survives ONLY in tasks-without-habits builds, where
  Legacy still owns habit completion (per-domain flags, ADR-013).
- **`/addhabit` creates immediately with no confirmation** — only the
  AI-driven `HABIT` flow confirms. v14.10 migrated it exactly so
  (direct apply, per `ADR-010`: creation is reversible by delete).
- **(v14.10) `addhabit`'s title stripping is quirky — replicated
  verbatim, not fixed.** The strip regex removes only `at HH:MM`
  (colon form) and the literal words daily/every day/every week/
  weekly/monthly. So "gym every monday at 7 AM" produces a **weekly,
  weekday-0, 07:00 habit titled "gym every monday at 7 AM"** — the
  parser extracts what the title keeps. Both paths behave identically
  (`test_create_weekly_habit_title_quirk_replicated`); if a user
  reports redundant words in habit titles, this is Legacy-inherited,
  not an Offline regression.
- **(v14.10) `addhabit` has no duplicate detection** — verified, no
  `task_exists()` or equivalent anywhere in the pipeline; two identical
  creates yield two habits in both paths (test-pinned). Contrast with
  task creation, which duplicate-checks in both paths.

### UI Phase 5 architectural limitation — utility screens render inline in `main.py` (found during the Phase 5 review, v14.17.1)

Phase 5's entire scope (Settings • AI • Developer Center • Help • About
• information screens) has **no presentation surface outside
`main.py`**: `help_command` (271), `status_cmd` (550), `debug_cmd`
(1829), `bugs_cmd` (1857), `trace_cmd` (1886), `selftest_cmd` (1903),
`settings_cmd` (2466), `insights_cmd` (3083), `admin_cmd` (3179),
`proactive_cmd` (3410), `models_cmd` (4091), plus the
`dash:models_view/perf_view/errors_view` branches inside
`route_dashboard_callback` — all build their reply text inline. No
About/credits screen exists at all. `ui.py` holds none of these
(Phases 1–4 already migrated everything it owns), and the sprint froze
`main.py` outright — so the migration's touchable-file set intersected
with its screen inventory is **empty**. Compounding it, `main.py` is
not importable from the offline suite (module-level Telegram/
instance-lock side effects — see `tests/test_conversation_state.py`'s
header), so the mandated characterization-first step can't be satisfied
for these screens either.

**What Phase 5R needs from the Board**: unfreeze `main.py`'s
*presentation statements only* — the plan that keeps risk near zero is
the Phases 1–4 pattern inverted: extract each screen's text/keyboard
builder into `ui.py` as a pure function (offline-testable,
characterization-pinned), swap each handler body to a one-line
`UI.<x>_card(...)` call, and verify the swapped handlers via the
TESTING.md live smoke checklist (offline tests cannot cover the calling
line itself). Until then, per the sprint rule "never sacrifice
compatibility for appearance," these screens keep their v14.12
formatting (help/selftest are already rich-HTML; the older ones —
settings, models, insights, proactive, admin, the three dash views —
remain pre-overhaul).

### Self-Test framework — admin-only runtime diagnostics (v14.22)

`core/selftest/` is a **registration-based runtime regression runner**
accessed from the Debug Menu's 🧪 Self Test button (admins only). It
runs live checks against the running process (DB, scheduler, engines,
AI provider) and reports PASS/WARNING/FAIL/SKIPPED per test plus a
summary — the fast "is the bot healthy after this update?" check.

- **Not** a replacement for the offline pytest suite: pytest proves
  logic in isolation; the self-test framework proves the *live wiring*
  (real DB, real AI provider). Both matter.
- **Adding a test:** drop a module in `core/selftest/tests/` with a
  `@selftest(name=, category=)` function — no central edit. Full guide:
  [docs/selftest.md](docs/selftest.md).
- **Production-safe:** write-tests use `SELFTEST_USER_ID` (a synthetic
  id outside Telegram's range) and clean up in `finally`; the
  integration test asserts zero leftover rows.
- **AI test does a network call** — it's the only one; the offline
  pytest integration run excludes the `AI` category.
- **`/debug` changed (v14.22):** it now opens the admin-only Developer
  Center menu (was an all-users debug toggle). Non-admins get the
  standard silent "Unknown command"; the toggle lives on as the menu's
  🐞 button. If a tester reports "`/debug` stopped toggling for me,"
  this is why — it's admin-only by design now (UI_SPEC §10).

### Debug logging workflow (v14.21)

Two log files, two jobs:

- **`bot.log`** — the production record, unchanged: INFO-level, sanitized
  (`log_sanitizer.py`), the file to read for incidents. **Retirement
  assessed and declined** (v14.21 Task 4): it stays the operational
  diagnostic record; `debugbot.log` supplements, never replaces it.
- **`debugbot.log`** — developer debugging only (v14.21): a rotating
  (2 MB × 3), gitignored, lazily-created DEBUG-level file that
  additionally captures everything the DEBUG tier emits — the Intent
  Engine classifications, RoutingDecisions, `[Offline]`/`[Offline
  Commit]`/`[Offline Update]` blocks — i.e. exactly the canary
  diagnostics, without flipping production to DEBUG. Same sanitizer
  applies (the handler registers before `install_log_sanitizer()`).
  Delete it any time; `./dev_reset.sh` does. Implementation: root
  logger at DEBUG, the bot.log/console handlers pinned to INFO, the
  rotating handler at DEBUG (`main.py`, logging block).

Also v14.21: bug ids display as `DBG-0018` everywhere (`/report`
confirmation, `/bugs`, `/resolve` replies) — they were always a
separate `bugs.db` sequence, never task ids; the prefix makes that
visible. `/resolve` accepts `18`, `#18`, or `DBG-0018`
(`debug_system.parse_bug_id`).

### Remaining Markdown reply sites in main.py — presentation debt inventory (UI RC1, v14.20)

After RC1, **91 `parse_mode="Markdown"` sites remain in `main.py`** —
all in Legacy conversational and secondary flows (AI-mediated replies,
task-creation dialog turns, memory/goals/wellness/template/project
responses, admin reset prompts, misc one-liners). Every *primary
screen* (dashboard, tasks, habits incl. the five command surfaces,
goals cards, settings, AI, help, selftest, debug/bugs/trace, admin
panel, insights, proactive) is HTML via the component library. The 91
were deliberately **not** converted in the RC: they sit inside complex
handlers (many mid-conversation-state), have no offline
characterization possible, and per-flow live verification would be
required for each — bulk-converting them in a stabilization sprint is
exactly the kind of risk RC1 exists to avoid. This is the UI track's
one remaining debt item, ticketed for **v15** alongside the other
approved architectural work. Grep to re-audit:
`grep -c 'parse_mode="Markdown"' main.py`.

### `dash:models_view` / `dash:perf_view` / `dash:errors_view` buttons dead-end (v11.1, confirmed during Phase 5R)

`usage_cmd`'s keyboard offers 🤖 Models / ⚡ Performance / ❌ Errors
buttons, but `route_dashboard_callback()` has **no branches for those
pages** — they fall into the unknown-page `else`. Part of the same
never-assembled-analytics story as the empty `/usage`-family commands
(the files were removed in v14.12; the buttons remained). Pre-existing;
Phase 5R (extraction-only) documents rather than touches it — there was
no models_view/perf_view/errors_view *presentation* to extract, contrary
to the Phase 5/5R briefs' assumption. Fix belongs with the v15
analytics rebuild (or remove the three buttons — a callback change
needing Board approval either way).

### Recurring tasks render as "completed" in the dashboard task-detail view (v9.0, found during UI Phase 3)

`get_task_by_id()` returns a **7-column** row ending in
`recurrence_type`, but `ui.task_card()` reads `done = task[6]` (its
documented 8-tuple shape puts `done` there). For the real
`dash:task:<id>` caller this means **a recurring task's detail screen
shows ✅ and no action buttons** — `"daily"` at index 6 is truthy — and
its recurrence icon is missing (read from absent index 7). Non-recurring
tasks are unaffected (index 6 is `None`). Pre-existing since v9.0;
UI Phase 3 (presentation-only) **replicates and pins it**
(`test_task_detail_seven_tuple_recurring_quirk_preserved`) rather than
fixing it — the fix (widen `get_task_by_id`'s SELECT or reindex the
card) is a small behavior change needing Board sign-off. Also blocks
richer detail fields (tags/subtasks/deadline state): they aren't in the
7-column row, so rendering them awaits the same widened read.

### Offline Engine gate runs before the confirming/gathering state branches — RESOLVED in v14.12 (ADR-011 Option A applied)

**Resolution (v14.12):** `main.py`'s intent-gated Offline dispatch now
requires `not conversation_state.claims_messages(state)` — it runs only
in `idle`, so `confirming`/`gathering`/`editing` messages reach the
state machine first, exactly like Legacy. Regression tests:
`tests/test_conversation_state.py`. The historical entry below is kept
for context.

Found during v14.6's Phase 0 conversation-state verification; applies to
**every** intent-gated Offline action since v14.2, not just completion.
`main.py`'s `OFFLINE_TASKS` `execute()` gate sits *above* the
`confirming`/`gathering` state branches in `handle_message()` (only
`editing` is explicitly checked first, for the v14.4 update flow). With
the flag ON, a message like `"done 5"` typed *while mid-conversation in
`confirming` state* would be intercepted and executed as a completion,
whereas Legacy's confirming handler would have re-prompted ("say yes to
save..."). With the flag OFF (today, always) this is unreachable.
Assessment: arguably the interception is what the user actually meant,
but it is a real behavioral difference in mid-conversation states.
**Update (v14.7): this is now a documented architectural decision** —
[docs/adr/ADR-011-conversation-state-priority.md](docs/adr/ADR-011-conversation-state-priority.md)
recommends Option A (state outranks intent-gated dispatch, matching
Legacy's real semantics), with implementation deliberately deferred per
that sprint's own instructions. Applying ADR-011 is a named blocker
before `OFFLINE_TASKS` is ever enabled in production.

### Offline task delete: intentional divergence from Legacy, not a bug (v14.5)

Different in kind from the v14.3/v14.4 entries above — those documented
*accidental* gaps found and matched or fixed. This one documents a
*deliberate* choice, so it isn't mistaken for one later.

- **Offline Delete requires a confirmation Legacy's real `/delete`
  doesn't have.** Verified directly (`main.py:483-504`):
  `delete_task_cmd()` deletes immediately, no confirm step, no exception.
  `core/actions/delete_task.py`'s `propose()`/`commit()` split adds one,
  on purpose — see `docs/adr/ADR-010-destructive-operations-policy.md`
  for the full reasoning (irreversibility, not "sounds destructive").
  This is the *only* place in the v14.2-v14.5 Offline Engine work where
  Offline intentionally does not match Legacy's real behavior in full.
  If you're auditing for equivalence bugs, don't flag this one — it's
  the one accepted exception, not an oversight.
- **No dispatch-coarseness gap for `Intent.DELETE_TASK`** — worth noting
  precisely because Create/Update/QUERY_TASK all had one. `"delete 5"`/
  `"delete task 5"`/`"remove task 5"` all classify `DELETE_TASK` at
  confidence 1.0 with `task_id` already in `entities` (Tier 0's
  `extract_numeric_id()`, `core/intent/rules.py`, verified directly). No
  narrow dispatch-layer regex was needed for entry recognition — the
  first Offline write/read action where the shipped Intent Engine's
  classification was sufficient on its own.

### Migration exception handling — resolved (v13.2)

`init_db()`'s `ALTER TABLE ... ADD COLUMN` loops used to catch bare
`Exception: pass`, unable to distinguish "column already exists"
(expected) from a real failure (disk full, corruption, permissions). Now
uses `_safe_add_column()`, which catches `sqlite3.OperationalError`
specifically and only silently continues for the "duplicate column name"
case — anything else is logged. The separate `analytics`-package
availability check above is intentionally still a broad `except` — that's
a different problem (an optional dependency that doesn't exist as a
package yet), not migration handling.

### Database infrastructure (v13.2)

As of Sprint 3, `database.py` also: runs in WAL journal mode (check via
`PRAGMA journal_mode` — should report `wal`); creates a timestamped backup
in `backups/` at the start of every `init_db()` call on an existing
database (keeps the 5 most recent per reason); and runs
`verify_schema_integrity()` right after `init_db()` at startup, logging
either `✅ Schema integrity OK` or a `⚠️` line listing exactly what's
missing. If the bot appears to start normally but something feels
schema-related, checking that log line first is faster than querying
`sqlite_master` by hand. A failed backup is logged and does not block
startup — check `bot.log` for `Database backup failed` if `backups/`
looks empty or stale.
