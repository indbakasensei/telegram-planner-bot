# BAKA Quality Assurance System — Design Milestone (post-v14.22)

**Status:** Design, audit, and planning milestone. No production code is
modified by this document. It is the referenceable blueprint for BAKA's
long-term manual regression testing system, which will become part of
the Developer Center.

**Grounded in:** the full release history (51 releases, v1.0 → v14.22),
the ~91 registered command handlers, the current `/start` greeting
(pre-overhaul Markdown), and `/help` (v14.12 design). Known defects are
sourced from the v14.20 UI RC audit, the v14.22 runtime log audit, and
DEBUGGING.md.

---

## Refinements (v14.23 architecture review)

The four refinements below were approved after the initial design and
are now normative. Phase 1 of the implementation (`core/regression/`)
is built to them.

**R1 — Feature-driven, growing-forever suite.** The "~315 tests" in
Part 4 is an **estimate, never a target**. Every user-visible feature
permanently *owns* its regression tests; the suite grows with the
project, it is never a fixed size that gets periodically rewritten. The
per-feature authoring model (`core/regression/suites/`) makes this
structural: adding a feature adds a suite module (or extends one);
nothing central is edited.

**R2 — Definition of Done (permanent rule).** A feature is NOT complete
until ALL exist: ✓ production implementation · ✓ regression tests · ✓
Self-Test additions (where applicable) · ✓ updated `/help` · ✓ updated
`/start` (if onboarding changed) · ✓ CHANGELOG · ✓ ROADMAP (if
affected) · ✓ README · ✓ feature documentation. Recorded in CLAUDE.md's
development standards.

**R3 — Three independent QA layers.** Kept completely separate:

| Layer | Purpose | Tech | Runs |
|---|---|---|---|
| **1 — Automated tests** | developer verification | `pytest` | CI / local |
| **2 — Runtime Self-Test** | live health check (DB, scheduler, storage, routing, AI, permissions) | `core/selftest` | in Telegram, admin-only |
| **3 — Manual regression** | human behaviour verification (PASS/FAIL/SKIP; FAIL → auto-bug) | `core/regression` + future runner | human, admin-driven |

Each layer has its own package and lifecycle; they never merge.

**R4 — Version-aware tests.** Every regression test permanently stores
execution history: introduced version (in the spec), plus last
executed / last passed / pass count / fail count / skip count / linked
bug ids (in the persisted history, `store.py`). A test that passed for
many versions and now fails is the regression signal.

---

## Part 1 — Project Feature Inventory

Criticality: **C**ritical (data loss / missed reminders = catastrophic)
· **H**igh · **M**edium · **L**ow. Visibility: **U**ser / **D**eveloper
/ **A**dmin.

| # | Feature | Introduced | Status | Vis | Crit | Key dependencies |
|---|---|---|---|---|---|---|
| 1 | Task system (create/edit/delete/complete/list) | v1.0→v14.6 | Stable | U | C | database, date_parser, AI |
| 2 | Reminder engine (persist-until-done, escalation) | v2.0 | Stable | U | C | scheduler, notification_service |
| 3 | Snooze / Pause / Resume / Postpone | v1.1 | Stable | U | H | scheduler, callbacks |
| 4 | Overdue + Carry-forward | v1.2 | Stable | U | H | scheduler, database |
| 5 | Deadline mode + pre-deadline buffers (7d/3d/1d/6h/1h) | v1.2, v10.1 | Stable | U | H | scheduler, date_parser |
| 6 | Tags | v1.2 | Stable | U | L | database |
| 7 | Recurring tasks | v3.0 | Stable | U | H | date_parser, scheduler |
| 8 | Quiet hours | v2.0 | Stable | U | M | scheduler, preferences |
| 9 | Habit engine (streaks, 14-day grid, skip) | v5.0 | Stable | U | H | database, date_parser |
| 10 | Goals (progress, deadline, ±) | v4.0/v9.0 | Stable | U | M | database, callbacks |
| 11 | Projects (materials, worklog, shopping) | v12.0 | Stable | U | M | database, goals |
| 12 | Memory (save/get/search/forget) | earlier | Stable (dup-key bug) | U | M | database, AI |
| 13 | Multi-task detection | v3.0/v4.0 | Stable | U | M | AI |
| 14 | Smart planning (`plan`, `breakdown`, `reschedule`) | v4.0 | Stable | U | H | AI |
| 15 | `/think` free reasoning | v10.2 | Degraded (AI timeouts) | U | M | AI |
| 16 | AI chat / advice / clarification | v3.0 | Degraded (fallback storm) | U | H | baka_brain |
| 17 | Multi-model AI + fallback | v11.0 | Stable-but-fragile | U/D | C | NVIDIA NIM |
| 18 | Vision (photo → todos) | v11.0 | Stable | U | L | AI |
| 19 | Image / Video generation | v11.0/v11.2 | Degraded (120s timeouts) | U | L | NIM genai |
| 20 | Search (tasks/memories/habits/goals) | v10.0 | Stable | U | M | database |
| 21 | Templates | v10.0 | Stable | U | L | database |
| 22 | Export | v10.0 | Stable | U | L | database |
| 23 | Dashboard (7 card types, inline nav) | v9.0 | Stable | U | H | ui, callbacks |
| 24 | Proactive (wellness, follow-ups, EOD summary) | v7.0/v8.0 | Stable | U | M | scheduler |
| 25 | Preference learning / insights | v6.0 | Stable | U | M | database |
| 26 | Settings (quiet hours, interval, wellness) | v2.0+ | Stable | U | M | preferences |
| 27 | AI usage analytics (`usage`/`performance`/`errors`) | v11.1 | Broken (never assembled) | U | L | *(removed analytics)* |
| 28 | Intent Engine (deterministic classifier) | v14.0 | Shadow (logs only) | D | M | date_parser |
| 29 | Routing Layer | v14.1 | Decision-logging | D | M | intent |
| 30 | Offline Engine + ActionRegistry (Tasks+Habits) | v14.2–14.11 | Complete, flags OFF | D | H | storage facade |
| 31 | Storage Facade | v14.1C | Stable | D | M | database |
| 32 | Feature flags | v14.1C | Stable | D | M | env |
| 33 | UI component library + overhaul | v14.13–14.20 | Complete | U | H | ui_components |
| 34 | Admin mode + reset tools | v6.1 | Stable | A | C (destructive) | is_admin |
| 35 | Debug system + bug tracking (DBG-ids) | v1.0/v14.21 | Stable | A | M | bugs.db |
| 36 | `/debug` Developer Center menu | v14.22 | New | A | M | callbacks |
| 37 | Self-Test framework | v14.22 | New | A | M | core/selftest |
| 38 | Logging + sanitizer + debugbot.log | v12.1/v14.12/v14.21 | Stable | D | H | log_sanitizer |
| 39 | Infra: WAL, indexes, backups, integrity | v13.2 | Stable | D | C | database |
| 40 | Single-instance lock, safe startup | v13.1 | Stable | D | H | instance_lock |
| 41 | Delivery reliability (rate-limit, retry) | v13.0 | Stable | D | H | notification_service |
| 42 | Async offload (run_blocking) | v12.3 | Stable | D | H | async_bridge |
| 43 | IST timezone handling | v7.0/v12.2/v12.4 | Stable | D | C | zoneinfo |

**Known active defects to guard** (v14.20 / v14.22 audits, DEBUGGING.md):

- Recurring-task detail view renders as "completed" (7-tuple index bug).
- Memory duplicate-key: "remember X is A" then "…is B" kept both when
  the AI varied the key. **Fixed in v14.26** — keys are now matched by a
  normalized form, so separator variants overwrite and existing
  duplicates collapse on the next save.
- `is_deadline` over-triggers on plain time-based meetings.
- `usage`/`performance`/`errors` return empty data; their dashboard
  buttons (`dash:models_view`/`perf_view`/`errors_view`) dead-end.
- 91 Markdown conversational replies remain in `main.py`.
- Bare utility commands (`models`, `usage`, `insights`, `proactive`,
  `performance`, `errors`) fall through to AI instead of executing.
- AI main model (llama-3.3-70b) chronically times out at 8s → fallback
  storm to 8b → non-deterministic classification (session-observed).

---

## Part 2 — Regression Test Inventory (scenario dimensions per feature)

Every feature is tested across nine **scenario classes**: **Normal ·
Boundary · Invalid · Recovery · Failure · Repeated · Multi-step ·
Interrupted · Restart**. Representative expansion (abbreviated — the
full inventory is ~1 scenario-row per applicable feature × class):

- **Tasks** — create (EN/Hindi/Hinglish); vague time (shaam/noon/lunch);
  no-time → gather; invalid time (25 PM) rejected; past-date warning;
  edit time/priority/title; delete + confirm; complete; recurring
  create; duplicate suppression; multi-task ("groceries and call mom");
  **interrupted** (start create, send unrelated command mid-confirm →
  ADR-011 re-prompt); **restart** (create, restart bot, task persists).
- **Reminders** — fires at due time; escalates; each ping button
  (Done/10m/1h/Tomorrow/Stop/Delete); custom snooze; quiet-hours
  suppression; follow-up after due; **repeated** snooze detection.
- **Deadlines** — "by Friday 5pm" arms mode; buffer at 3d/1d/6h/1h;
  "Meeting at 5pm" does NOT arm (boundary / known bug).
- **Habits** — create daily/weekly/monthly; complete → streak +1;
  complete again same day (already-logged); streak grid; skip resets;
  delete.
- **Goals/Projects** — create; ± progress; over-target clamp; add
  materials; got; worklog; shopping list; finish.
- **Memory** — save; get; **overwrite same fact** (known bug); search;
  forget; save-under-varying-key (guard).
- **AI** — chat; think ×N (guard timeout); plan today/week + apply;
  provider **failure** (main down → fallback → still answers);
  **rate-limit** burst (429).
- **Vision/Media** — photo→todos; image/video generate (guard 120s
  timeout / graceful failure).
- **Dashboard** — open; each nav button edits in place; refresh;
  recurring-task detail (known bug); goal ± inline.
- **Search/Templates/Export** — keyword hit/miss; multiline paste
  (known artifact); template save/use; export size.
- **Settings/Proactive** — view; quiethours set + re-check; interval;
  wellness on/off; EOD summary.
- **Developer/Admin/Debug** — `/debug` admin-only (silent deny for
  non-admin); Self-Test run; bug report → DBG-id; resolve; trace;
  selftest report; reset flows on disposable DB only; DBG-id
  independence; debugbot.log rotation.
- **Routing/Offline/Intent** — flag-OFF = Legacy byte-identical; with a
  flag ON, offline path answers + logs `[Offline]`; ADR-011 state
  priority.
- **Cross-cutting** — long conversation (30+ turns); interrupted
  conversation (cancel mid-gather); **restart recovery** (conversation
  state is in-memory → lost on restart: verify graceful degradation);
  IST correctness (log UTC vs bot IST).

---

## Part 3 — Test Specification Format

Standard record (eventually stored as structured data the Developer
Center reads):

```
TEST-ID:            <CAT>-###            (e.g. TASK-014)
Category:           <one of Part 4>
Feature:            <inventory feature #/name>
Version Introduced: <vX.Y>
Priority:           Critical | High | Medium | Low
Scenario Class:     Normal | Boundary | Invalid | Recovery | Failure |
                    Repeated | Multi-step | Interrupted | Restart
Estimated Time:     <mm:ss>
Objective:          <one sentence>
Preconditions:      <state/data required>
Steps:              1. … 2. … 3. …
Expected Result:    <observable outcomes, each verifiable>
Failure Conditions: <what makes this FAIL>
Related Bugs:       <DBG-#### links>
Notes:              <known-issue caveats>
```

**Worked example:**

```
TEST-ID:            TASK-014
Category:           Tasks     Feature: Recurring tasks (#7)     Version: v3.0
Priority:           Critical  Scenario: Normal                  Est: 00:40
Objective:          Verify recurring task (habit) creation from natural language.
Preconditions:      Idle state; AI reachable.
Steps:              1. Send "Add task Drink Water every day at 8 PM"
                    2. Tap ✅ Yes, save it!
Expected Result:    • Classified HABIT daily 20:00 (NOT GOAL)
                    • Confirmation card shown before save
                    • Exactly one habit row created (no duplicate)
                    • Appears in /habits with streak 0
                    • Reminder recurrence scheduled
Failure Conditions: classified GOAL/TASK; duplicate; no confirm; not in /habits
Related Bugs:       BUG-002 (non-deterministic classification)
Notes:              Under main-model timeout the 8B fallback may misclassify —
                    a FAIL here often = AI degradation, not a code regression.
```

---

## Part 4 — Categories, Counts & Suites

**23 categories** with target manual-regression test counts:

| Category | ~Tests | | Category | ~Tests |
|---|---|---|---|---|
| Core | 8 | | Media | 8 |
| Tasks | 40 | | Search/Files | 10 |
| Reminders | 22 | | Notifications | 12 |
| Scheduler | 12 | | Settings | 12 |
| Dashboard | 18 | | Developer | 12 |
| Habits | 20 | | Admin | 14 |
| Goals | 12 | | Debug | 10 |
| Projects | 16 | | Routing | 8 |
| Memory | 14 | | Offline Engine | 12 |
| AI | 24 | | Intent Engine | 8 |
| Vision | 6 | | Performance | 8 |
| | | | Security | 10 |
| | | | Regression (known-bug guards) | 15 |

**Estimated full suite: ~315 tests — an ESTIMATE, not a target (R1).**
The suite grows as features are added; this table is a planning
snapshot, not a cap.

- **Quick Release Suite (~35 tests, ~25 min)** — Critical-only smoke:
  create/complete/delete task, one reminder fire + Done button, habit
  complete, dashboard open, `/help`, `/debug`→Self-Test all-green, AI
  health, memory save/get, admin silent-deny. Run every release.
- **Major Release Suite (~130 tests, ~2.5 hr)** — all Critical + High
  across every category, plus the 15 known-bug guards. Run on
  minor/feature releases.
- **Full Regression Suite (~315 tests, ~1 day)** — every scenario
  class. Run on major releases and before public launch.

### Quick Release Suite — COMPLETED (v14.23–v14.24)

**The mandatory release gate. Every future BAKA release must pass this
before it is production-ready.** Authored specs live in
`core/regression/suites/`.

- **Size:** **44 tests** · est. runtime **~29 min** · priority mix 9
  Critical / 18 High / 15 Medium / 2 Low.
- **Categories covered (15 of 23):** Core, Tasks, Reminders, Dashboard,
  Habits, Goals, Projects, Memory, AI, Search/Files, Settings, Admin,
  Developer, Debug, Documentation.
- **Workflow coverage:** **100%** of the critical user workflows in the
  Quick-Suite brief — every listed workflow (create/edit/complete/
  delete/recurring/multi-task tasks; reminder fire/done/snooze/tomorrow;
  memory remember/recall/forget; AI chat/planning/clarification/
  fallback; habit create/complete/streak; goal create + progress;
  project create/material/worklog; task+memory search; dashboard
  open/refresh/nav; quiet-hours + interval; admin-only + denial;
  self-test execute; help + onboarding validity) has ≥ 1 spec.
- Includes a handful of high-value edge cases in the gate: invalid time
  (TASK-005), memory overwrite (MEM-002, guards BUG-007), habit
  already-logged (HAB-003), quiet-hours suppression (REM-003), admin
  denial (ADM-001), destructive-reset confirmation (ADM-003).

**Coverage-review findings (deliberately deferred to the Major Suite):**

- **8 categories not yet in Quick** (dev-facing or non-critical for a
  smoke gate): Scheduler (escalation, carry-forward), Notifications
  (rate-limit/retry), Vision, Media (image/video — degraded/flaky),
  Routing, Offline Engine, Intent Engine (flag-ON paths), Performance,
  Security (beyond the ADM permission tests already in Quick).
- **Scenario classes not yet in Quick:** Interrupted-conversation
  (ADR-011 state priority), Restart recovery (in-memory state loss),
  and deeper Boundary/Invalid/Recovery/Failure/Repeated per feature.
- These are the Major Suite's remit — see below.

### Remaining work for the Major Suite

Expand each Critical/High feature across the full scenario matrix, add
the 8 deferred categories, and add the interrupted/restart cross-cutting
tests. Target ~130 tests (Critical + High everywhere + the 15 known-bug
guards). The Regression Runner is a **separate, later** milestone — the
spec corpus grows first.

---

## Part 5 — Bug Workflow (lifecycle)

```
Run Test (Developer Center → Regression Tests)
        │
   PASS ─┴─ FAIL
   │           │
 log PASS   prompt: Expected / Actual / Steps / Notes  (pre-filled from record)
 + timing        │
              auto-create Bug  ──►  DBG-#### (bugs.db, independent id)
                                    • auto-attaches: test-id, category,
                                      last trace, debugbot.log tail
                                    │
                          Debug Menu → 🐞 Bugs (open list, DBG-prefixed)
                                    │
                          Triage → Resolve (fix ships) → mark resolved
                                    │
                          Retest (re-run the exact TEST-ID)
                                    │
                          PASS → close · FAIL → reopen (increment attempt)
```

Extends the **existing** `debug_system` (report_bug/get_open_bugs/
resolve_bug, DBG-ids from v14.21) — the regression runner becomes a bug
*source* that pre-fills context, closing the loop test → bug → fix →
retest inside the Developer Center.

---

## Part 6 — Developer Center Design (menu tree; design-only)

```
🛠 Developer Center            (/debug, admin-only — v14.22 shell exists)
├── 🧪 Self Test               ✅ built (v14.22) — live health runner
├── 🧯 Regression Tests        ▢ future — browse by category, run suite, PASS/FAIL→bug
│      ├─ Run Quick Suite
│      ├─ Run Major Suite
│      ├─ Run Full Suite
│      └─ By Category → test list → run one → record result
├── 🐞 Bugs                    ◐ backend exists (DBG-ids) — needs a menu screen
│      └─ open list → detail → resolve
├── 📋 Test History            ▢ future — past runs, pass-rate trend, last-fail
├── 📊 Statistics              ▢ future — coverage %, flaky tests, category health
├── 🐞 Toggle Debug            ✅ built (menu button)
├── 📜 Logs                    ◐ debugbot.log exists — needs a tail/download screen
├── 🧠 Engines                 ▢ future — Intent/Routing/Offline registry introspection
└── 🚩 Feature Flags           ▢ future — read-only flag panel (+restart note)
```

All hang off the existing `dev:*` callback namespace (UI_SPEC §10).
Legend: ✅ done · ◐ backend-ready · ▢ design-only.

---

## Part 7 — Living Help System & Documentation Policy

**`/help` audit (against the ~91 handlers):**

- **Missing from help:** `checktasks`, `delreminder`, `suggest` /
  `generate` / `ask` (AI aliases), `myid`, `claimadmin`.
- **Advertised but broken:** `usage`/`performance`/`errors` are
  correctly *un*-advertised (good) — but their dashboard buttons still
  dead-end.
- **Deprecated/hidden:** analytics commands (empty); several admin
  resets (correctly admin-gated).
- **Incorrect examples:** `/start` still uses pre-overhaul phrasing;
  `/help` version string now correct (v14.19+).
- **Routing gap:** bare `models` / `usage` / `insights` / `proactive`
  fall through to AI instead of executing (contradicts "slash
  optional").

**Permanent development rule (the "Definition of Done"):**

> No feature is complete until its documentation is synchronized. Any
> change to a **user-facing command or capability** (added / removed /
> renamed / behavior-changed) MUST, in the same change-set, update:
> **`/help` (`ui.help_cards`) · README · CHANGELOG · ROADMAP (if
> roadmap-affecting) · relevant `docs/`**. A future Self-Test check can
> assert every registered `CommandHandler` appears in `help_cards`
> (catches "missing from help" automatically).

---

## Part 8 — First-Run Onboarding Design (design-only)

**Current `/start`:** a single static Markdown block — no personality
arc, no dashboard/AI/help walk-through, doesn't distinguish new vs
returning users, still Markdown (not the HTML component system).

**Proposed (new user) — a 3-message progressive intro, HTML via
components, one CTA per step:**

1. **Meet BAKA** — name + "Behavioral Adaptive Knowledge Assistant,"
   one-line personality ("I nag you until it's done — kindly"), language
   note (EN/Hindi/Hinglish). Button: *Show me →*.
2. **Try it live** — "Type this: *Remind me to call mom tomorrow 5pm*"
   (invites the natural-language thesis by demonstration, not
   description); then explains the reminder-until-done loop + buttons.
   Button: *Reminders & memory →*.
3. **What else** — memory ("*Remember my exam is June 20*"), dashboard
   (`/dashboard`), AI (`/think`), and `/help`. Buttons: `🏠 Dashboard ·
   ❓ Full Help`.

**Returning user:** detect prior data → skip the intro, greet by name
with a live snapshot ("3 due today · 2 habits pending · best streak
🔥12") + dashboard button. A `first_run` flag (or "has any
task/memory") distinguishes them.

*(Realizes the UX-review's Critical onboarding gap and the "NL-first is
invisible" finding — design only; needs Board approval as it is a
§-scope UI addition.)*

---

## Part 9 — Deliverables index

1. Feature inventory → Part 1 (43 features)
2. Regression inventory → Part 2
3. Estimated test count → **~315** (Part 4)
4. Category breakdown → Part 4 (23 categories)
5. Test specification format → Part 3
6. Developer Center design → Part 6
7. Bug workflow → Part 5
8. Documentation-synchronization policy → Part 7
9. First-run onboarding design → Part 8
10. Implementation roadmap → Part 10

---

## Part 10 — Implementation Roadmap (no code now; sequenced to minimize risk)

| Phase | Scope | Depends on | Risk |
|---|---|---|---|
| **Q0** | Adopt the Part 7 doc-sync rule immediately (this file is the artifact) | — | none |
| **Q1** | Encode the ~315 tests as structured records (`docs/regression/` or a `test_specs` table); no UI | Part 3 format | none |
| **Q2** | Author the **Quick Suite** (~35) first — highest value, run manually now | Q1 | none |
| **Q3** | Self-Test checks for automatable guards (help-coverage, DBG-id, schema, flag-honesty) — extends v14.22 framework | v14.22 | low |
| **Q4** | Developer Center **🐞 Bugs** screen (backend exists) | dev:* namespace | low |
| **Q5** | Developer Center **🧯 Regression Tests** runner (browse/run/record → bug) | Q1, Q4 | medium (new callbacks) |
| **Q6** | **📋 Test History + 📊 Statistics** (pass-rate trend, coverage) | Q5 | low |
| **Q7** | **📜 Logs / 🧠 Engines / 🚩 Flags** panels (round out UI_SPEC §10) | dev:* | low |
| **Q8** | First-run onboarding (Part 8) — separate Board approval (UI scope) | UI_SPEC revision | medium |

Nothing above is built in this milestone. Sequencing keeps every step
additive on the existing `dev:*` / `debug_system` / `core/selftest`
foundations.
