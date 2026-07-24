# RC v14 — Release Candidate Phase 1: Architecture Validation

**Sprint:** v14.7.1 — review-only, zero code changes (verified: `git diff`
touches only documentation).
**Scope reviewed:** everything shipped v14.0–v14.7 — `core/intent/`,
`core/routing/`, `core/offline/`, `core/actions/`, `core/storage/`,
`core/feature_flags.py`, ADR-001..011, plus their `main.py` integration
points.
**Verdict up front:** the architecture is canary-ready **after two named
blockers** (§11). No architectural defect requiring new code was found.

---

## 1. Architecture Review

**Consistency.** All five `core/` packages follow one idiom, established
in v14.0 and never broken: pure/stateless components, caller-injected
clock (`now` threading, never `datetime.now()` inside `core/`), typed
dataclass results (never dicts), data-driven dispatch tables, graceful
`success=False, warnings=[...]` fallthrough instead of exceptions,
exception containment at exactly one boundary per entry point
(`OfflineEngine`'s methods), and lazy `%`-style debug logging. Verified
mechanically: **pyflakes reports zero findings across all of `core/`**
(vs. 49 in Legacy `main.py`), and every architectural constraint
(no telegram/database/AI imports) is AST-enforced by tests, not just
convention.

**SOLID.** Single responsibility holds cleanly (classify / route /
dispatch / execute / persist are five separate components). Dependency
inversion is honest where it matters (actions depend on the Storage
Facade, injected into `OfflineEngine`; tests exploit this with fakes).
Open/closed holds at the data level (new phrases/actions are table rows
and new files) with one known ceiling: adding a new *intent-gated
operation* still means a new `elif`-shaped branch in
`OfflineEngine.execute()` — acceptable at 4 branches, worth a
registration-table refactor before Habits/Goals/Projects triple it (§6).

**Coupling/cohesion.** Coupling between `core/` packages is one-way and
narrow (`offline` → `intent`'s types + `storage`; `routing` → `intent`'s
types; nothing imports `main.py`). The one deliberate coupling *gap*:
`core/routing/`'s recommendation and `core/offline/`'s actual dispatch
are still disconnected (`OFFLINE_ENGINE_IMPLEMENTED_INTENTS` still an
empty frozenset) — documented since v14.2, now genuinely reconcilable
(§7).

**Unnecessary abstractions.** One candidate: `RoutingError`
(`core/routing/exceptions.py`) — defined, exported, never raised
(verified by grep). Its docstring declared this forward-provisioning at
birth (v14.1B); three sprints later no raise site has materialized.
Recommend: remove or repurpose during the routing-reconciliation work,
not before (review-only sprint).

**Duplicated logic.** The known four-level command-phrase duplication
chain, unchanged: `main.py` tables → `core/intent/rules.py` mirror →
`core/offline/engine.py`'s phrase slices → per-action entry regexes.
Every level individually documented and tested; collectively the
largest single maintenance liability in v14. The fix (structured
action hints in `IntentResult.entities`) has been named since ADR-007
and is now blocking-adjacent: Habits/Goals/Projects would add a fifth,
sixth, seventh copy of the pattern.

**Naming.** Consistent within layers. Two small wrinkles, cosmetic only:
`lifecycle_task.py` exposes `match_entry()` while its siblings expose
`match_entry_command()`; `TaskStorage` mixes verb styles (`get_all` vs
`exists` vs `mark_done` — inherited from `database.py`'s own names,
which the facade deliberately mirrors). Neither is worth churn now.

**Scalability/maintainability.** Per-message overhead of the full v14
stack (classify + route + offline attempt) is ~1–2ms worst case against
measured benchmarks — irrelevant next to Telegram round-trips. Test
architecture (545 tests, ~10s, zero mocking of owned code) is the
strongest maintainability asset; every regression this migration
caught was caught by it.

## 2. ADR Review (Task 1)

- **ADR-001..006** — still accurate. ADR-002's Implementation Note and
  ADR-006's contract match shipped code. DRG-001's Sub-stage B condition
  (comparison logging before real routing) remains satisfied and
  unviolated.
- **ADR-007..009** — correct as shipped; their documented debts (Tier-0
  duplication, `QUERY_TASK` coarseness, update's state-gated dispatch)
  are all still true and still tracked.
- **ADR-010 (destructive-operations policy)** — **validated by
  subsequent use**: v14.6 (Complete) and v14.7 (lifecycle ops) each
  applied its irreversibility test and correctly landed on
  "match Legacy, no confirm," exactly as the ADR predicted. No
  amendment needed. One observation for the future: the policy's
  "irreversible" test worked because every case so far was clear-cut;
  the first genuinely ambiguous case (e.g. a bulk destructive op)
  should be argued in a new ADR, not stretched under this one.
- **ADR-011 (conversation-state priority)** — remains correct and is
  now the **top pre-canary blocker**: Option A (state outranks
  intent-gated dispatch) must be applied before `OFFLINE_TASKS` is
  enabled anywhere, since the divergence it closes is unreachable only
  while the flag stays OFF. Status should move Proposed → Accepted at
  implementation time.

## 3. Technical Debt Report (Task 2)

Verified by grep across all `*.py` (venv excluded):

- **TODO / FIXME / HACK / TEMP / deprecated markers: zero.** (Three
  "XXX" hits are literal redaction-format strings in `log_sanitizer.py`,
  not markers.)
- **Legacy-compatibility debt (all previously documented, re-confirmed):**
  1. Four-level command-phrase duplication chain (§1).
  2. `core/routing/` ↔ `core/offline/` disconnection: empty
     `OFFLINE_ENGINE_IMPLEMENTED_INTENTS`, unconsumed
     `recommended_destination`.
  3. `OFFLINE_HABITS`/`OFFLINE_GOALS`/`OFFLINE_PROJECTS`: defined,
     tested, read by no production code (their domains don't exist yet)
     — correct, by design, re-verified.
  4. `RoutingError`: exported, never raised (§1).
  5. `INTENT_ENGINE.md`'s 0.75-boundary tension (execution threshold vs.
     descriptive band), documented since v14.1B, still unresolved —
     harmless until routing goes live.
  6. `main.py`: 49 pyflakes findings (unused Legacy imports incl. the 6
     dead `baka_brain` imports found in the earlier verification audit,
     one `mark_reminded` double-import). Legacy cleanup, explicitly out
     of scope for every v14 sprint to date.

## 4. Dead Code Report (Task 3) — report only, nothing removed

- **`core/`: no dead code.** Zero pyflakes findings; all 11 `Intent`
  members are consumed by classification rules and/or dispatch;
  `ActionResult.warnings`/`data`/`metadata` all have live consumers.
  Sole exception: `RoutingError` (§1).
- **Repo root (pre-existing, documented in DEBUGGING.md/ROADMAP.md,
  re-confirmed):** `ai_helper.py` and `bot_state.py` (unimported dead
  modules — the former still carrying the flagged hardcoded-key string);
  `database.get_recurring_tasks()` (defined, never called — verified
  again during v14.6); the five never-assembled `analytics` package
  files (unreachable via their intended package imports);
  `database.py`'s unused `shutil` import.
- **Duplicate parsers/regex:** `main.py`'s `parse_time_from_text()`
  overlaps `date_parser.parse_time()` (Legacy-internal, pre-v14);
  the four-level phrase chain (§1). No *new* duplication introduced by
  v14 beyond the documented mirrors.

## 5. Storage Facade Review (Task 4) — recommendations only

Current shape: 5 domains, ~40 one-line delegations, zero SQL, zero
reshaping — the v14.1C Phase 0 contract has held perfectly through five
extension rounds, each extension arriving exactly when an action needed
it (no speculative surface).

- **Missing abstractions:** none blocking. When Habits migrate,
  `HabitStorage` already covers the streak functions; Goals/Projects
  are similarly pre-covered from v14.1C.
- **Duplicated methods:** none (`TaskStorage.mark_done` vs
  `complete_task`'s use of it is layering, not duplication).
- **Overly broad interfaces:** none — the facade deliberately exposes
  less than `database.py`'s ~120 functions ("representative, not
  exhaustive," documented).
- **Inconsistent naming:** the `get_all`/`exists`/`mark_done` verb mix
  mirrors `database.py` intentionally; recommend keeping mirror-naming
  until/unless `database.py` itself is ever renamed — renaming the
  facade alone would *create* a mapping to memorize.

## 6. Offline Engine Review (Task 5)

Dispatch, fallback, error propagation, and logging are consistent and
fully covered by tests (`execute()` 100%, every failure warning
category asserted). **Scaling verdict for Habits/Goals/Projects:
architecture yes, dispatch mechanism needs one refactor first.**
`execute()` is now a ~90-line if/elif ladder over intents with inlined
per-intent match logic; three more domains at Task's pace (~6 actions
each) would make it a god-function — the exact pattern
`ENGINEERING_AUDIT.md` flagged in `handle_message()`. Recommendation
(not implemented — review-only): convert dispatch to a registration
table (`(intent, matcher) → action`) mirroring `routing_matrix.py`'s
data-driven idiom, as the *first* task of any Habits sprint. Feature
flags: per-domain gating slots in cleanly (`OFFLINE_HABITS` gate beside
`OFFLINE_TASKS` in `main.py`), no redesign needed.

## 7. Routing Review (Task 6)

Ordering Intent Engine → Routing Layer → Offline Engine → Legacy
**remains correct** — with ADR-011's amendment that conversation state
must outrank the Offline gate (state → intent → routing → offline →
legacy, matching Legacy's own semantics). What should change *after*
canary data exists: the Routing Layer is still decision-logging-only
(DRG-001 Sub-stage B) while the Offline Engine dispatches independently
via feature flag — two parallel decision systems. That was the designed
transition state, but its end condition ("tune thresholds against real
comparison logs, then wire `recommended_destination` to real dispatch")
requires exactly the canary traffic this RC unblocks. Recommendation:
keep both systems through the canary; reconcile in the sprint after,
using the canary's `[Routing]` vs `[Offline]` log correlation.

## 8. Canary Deployment Plan (Task 7)

- **Precondition:** apply ADR-011 Option A (small change + regression
  test); re-run full suite.
- **Rollout:** single-instance bot → the canary is temporal, not
  cohort-based. Enable `OFFLINE_TASKS=true` in `.env` on the live
  deployment during a low-stakes window; the owner (sole admin) is the
  de-facto canary user. Restart via `run.sh` (instance lock makes
  redundant starts safe).
- **Logging:** `bot.log` already carries the full chain per message —
  `[Intent]`, `[Routing]`, `[Offline]`/`[Offline Commit]`/`[Offline
  Update]` blocks. Set log level DEBUG for the observation window
  (log_sanitizer keeps it safe).
- **Metrics (grep-derived from bot.log, analytics package still broken):**
  offline-handled message count vs. Legacy fallthroughs;
  `unsupported_action`/`unrecognized_change` rates (dispatch coverage);
  `action_exception:*`/`commit_exception:*`/`delete_not_verified`
  (must stay zero); duplicate-completion re-logs; `[Routing]`
  recommended-vs-actual divergence rate (feeds §7).
- **Rollback:** set `OFFLINE_TASKS=false` (or remove), restart —
  byte-identical Legacy behavior; no schema/data migration to reverse.
  Rollback triggers: any `delete_not_verified`, any wrong-task write,
  any exception rate above zero-per-day, any user-visible wrong reply.
- **Success criteria:** 14 days OR ≥200 offline-dispatched messages
  (whichever is later) with zero rollback triggers and equivalence spot
  checks (10 random offline replies diffed against expected Legacy
  wording) all passing.
- **Observation period:** 14 days minimum, matching the bot's
  weekly-cycle features (weekly report, recurring tasks) twice over.

## 9. Legacy Removal Plan (Task 8)

- **Phase 1 — Hybrid (current + canary):** flag ON, Offline handles its
  matched subset, Legacy handles everything else + acts as the error
  fallback. Exit: canary success criteria met.
- **Phase 2 — Offline Preferred:** wire `RoutingDecision.recommended_destination`
  to real dispatch (populate `OFFLINE_ENGINE_IMPLEMENTED_INTENTS`;
  resolve the flags-vs-set reconciliation documented since v14.1C);
  Legacy's matching task handlers become the explicit fallback only
  (reached on offline failure, never first choice). Dependencies:
  canary comparison data for threshold tuning; the dispatch-table
  refactor (§6). Risks: routing misclassification now consequential —
  mitigated by DRG-001's per-write-class confidence gates finally going
  live as designed. Rollback: flag OFF still restores full Legacy.
- **Phase 3 — Legacy Removal (task handlers only):** delete the
  ~15 migrated task handlers from `main.py` + their slashless-table
  entries, per command group, each behind its own commit. Dependencies:
  Phase 2 stable across ≥1 month; AI-dependent flows (free-form
  creation, `/reschedule`) must first be routed through the AI Router
  stage (master-spec Stage 3) since they can never be Offline-only.
  Risks: id-less usage/pick-list replies and reminder callbacks still
  live in those handlers — inventory each handler's full surface before
  deleting (several serve both a migrated text path and an unmigrated
  callback/usage path). Rollback: git revert per command group — after
  Phase 3, flag-OFF no longer restores deleted code, which is why
  Phase 3 is last and gradual.

## 10. Final Engineering Assessment (Task 9)

- **Performance:** all measured (v14.2–v14.7 benchmarks): sub-2ms
  per offline operation, identical query counts to Legacy, ~0.5–1ms
  classification+routing overhead per message. No concerns.
- **Memory:** tracemalloc-bounded in tests; all components stateless;
  no caches, no growth vectors in `core/`.
- **Imports:** `core/` clean (pyflakes 0). Legacy `main.py` carries 49
  stale-import findings — Phase 3 material, not RC-blocking.
- **Architecture:** see §1. Sound, consistent, honestly documented.
- **Logging:** consistent structured DEBUG blocks; sanitizer applies;
  one gap — offline blocks aren't correlated to `[Routing]` trace_ids
  (correlation is by adjacency only). Fine for a single-user canary;
  fix before Phase 2.
- **Scheduler:** untouched by v14 (verified: no `core/` module imports
  scheduler.py; lifecycle ops manipulate scheduler *state* through the
  same columns Legacy does).
- **Database:** untouched schema; all access through the same
  `database.py` functions; WAL/backup/integrity infra from v13.2 intact.
- **Security:** no new secrets, no new input surfaces (all input
  already flowed through handle_message), fmt.esc() applied on all
  user content in offline replies (spot-verified across actions). The
  pre-existing `ai_helper.py` key remains the repo's outstanding
  security item (unchanged, still flagged, still needing rotation).
- **Configuration:** flags are env-read-once — a restart applies
  changes; documented. No config sprawl.
- **Testing:** 545 tests, ~10s, 100% coverage of every `core/` package,
  AST-enforced constraints, equivalence + failure-injection + benchmark
  discipline uniform across stages. The strongest part of the RC.

## 11. Remaining Blockers Before OFFLINE_TASKS

1. **Apply ADR-011 Option A** (move/guard the Offline gate below
   `confirming`/`gathering`; add the mid-confirmation regression test;
   flip ADR-011 to Accepted). Small, well-specified.
2. **Canary logistics** (this document's §8): set DEBUG logging,
   schedule the window, agree the rollback triggers. Operational, not
   code.

Nothing else. Every other known issue (duplication chain, routing
reconciliation, dispatch-table refactor, Legacy import hygiene) is
explicitly post-canary work.
