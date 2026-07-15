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

### Hardcoded-looking API key in `ai_helper.py`

Line 9 passes what looks like a real NVIDIA API key as the **argument
name** to `os.getenv(...)` instead of passing `"NVIDIA_API_KEY"` as the
argument and using the key as its value — i.e. it's broken even on its own
terms, but the key string is still sitting in tracked source. The file is
dead code (not imported anywhere), which doesn't change the fact that the
key is committed to git history. **Recommended: rotate that NVIDIA key and
remove the literal from the file**, independent of the rest of this
documentation work.

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
matches produce empty `entities`, `core/intent/rules.py`). `core/offline/engine.py`'s
`_select_action()` resolves this with a narrow, hand-maintained mirror of
`core/intent/rules.py`'s own Tier 0 phrase groups, checked directly
against `RequestContext.text` — a third level of the same accepted
duplication pattern (`main.py`'s tables → `core/intent/rules.py`'s mirror →
`core/offline/engine.py`'s mirror of a slice of that mirror). If any of
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
`core/offline/engine.py`'s `_select_action()` since it matches different
verbs). See `docs/adr/ADR-008-offline-write-operations.md`'s Decision.

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
