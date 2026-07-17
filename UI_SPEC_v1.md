# BAKA UI Specification v1.2 — FINAL (Permanent UI Blueprint)

**Status:** Approved and **FROZEN** by the Architecture Board. This
document is the single source of truth for all UI implementation work.
Any deviation — new pattern, new label, new icon, new screen class —
requires a Board-approved spec revision (v1.3+) *before* code.
**Approved behavior changes ledger (exactly two):** Duplicate Task (§9)
and `/debug` admin-gating (§10). Everything else is presentation-only.

**Ground truth:** `API.md`'s command reference, the `dash:` callback
router, `ui.py`'s card renderers, `fmt.py` (incl. v14.12
blockquotes/spoiler/code-blocks), `debug_system.py`, both `/selftest`
generations, and the admin silent-deny convention.

---

## 1. Design Principles

- **P1 Presentation only, never dispatch** — a button is a shortcut to
  an existing command path; if a button needs new backend logic, the
  design is wrong.
- **P2 Text-first** — every button action stays reachable by typed
  command (slash + slashless). Buttons accelerate; they never gate.
- **P3 Navigation edits, actions append** (lifecycle rules §11).
- **P4 One phone screen per message** (hard rules §6.1).
- **P5 Icons are a closed vocabulary** (§5.5); anything outside it
  fails review.
- **P6 The state machine wins** — no screen paints a button whose
  handler `confirming`/`gathering`/`editing` would intercept (ADR-011
  is a UI law).
- **P7 Never lost, never trapped** — every screen answers *where am I /
  what matters / what next* and always has a working exit (§2.5).

## 2. Navigation Architecture

**2.1 Two tiers.** Reply keyboard: the existing 18-button menu,
byte-identical (regression surface; Phase 9 may *propose* changes
separately). Inline keyboards: all new navigation, edit-in-place via
`safe_edit_message_text`.

**2.2 Hub-and-spoke, max depth 3.** `Home → {Tasks, Habits,
Goals/Projects, AI, Stats, Settings, Developer Center} → detail`.
Deeper content collapses into detail screens via expandable sections.

**2.3 Callback grammar** (≤ 64 bytes): `dash:*` legacy — kept routing
forever · `nav:*` navigation · `act:*` actions calling existing
handlers · `wiz:*` wizard steps over existing states · `dev:*`
admin-gated (silent no-op otherwise) · `pg:*` pagination (8 items/page;
footer `‹ Prev · 2/5 · Next ›`; page index in callback data, never in
conversation state).

**2.4 Breadcrumbs.** Line 2 of every screen except Home, italic,
`›`-separated: `<i>🏠 Dashboard › Tasks › Today</i>`. Max 3 segments;
detail screens end in the entity (`› #17`); wizards use a step counter
(`› Add Task · step 2/3`). Text only (not tappable); rendered
exclusively by `render_header()`; never hand-built.

**2.5 Universal navigation rules.** Canonical nav buttons
`⬅ Back · 🔄 Refresh · 🏠 Home`, always the last row, always that
order, omitting per page class:

| Page class | Nav row | Notes |
|---|---|---|
| Root (Home) | `🔄 Refresh` | no Back/Home |
| Hub | `⬅ Back · 🔄 Refresh · 🏠 Home` | Back = Home, kept for consistency |
| Child list | `⬅ Back · 🔄 Refresh · 🏠 Home` | Back = parent hub |
| Detail | `⬅ Back · 🏠 Home` | no Refresh (re-renders after every action); Back returns to the originating list (origin encoded in callback) |
| Modal (wizard/prompt) | `✕ Cancel` only | must be resolved or cancelled; Cancel = existing `cancel`, clears state |
| Confirmation | `✕ Cancel · confirm` only | nothing may abandon a pending confirm except Cancel |

Anti-trap invariants: typed `cancel` works everywhere in every state;
no keyboard is ever empty; a failed edit (aged message) sends the same
screen fresh rather than failing silently.

## 3. Screen Inventory

44 screens, S01–S44 (v1.0/v1.1 inventory carried verbatim — same
routes, same existing-function data sources, same regression notes),
each with a §2.4 breadcrumb and §4 context actions. Highlights: S01
Home · S02–S12 Task screens (hub, today, upcoming, completed, overdue,
search, statistics, details, add wizard, edit, delete confirm) ·
S13–S19 Habit screens (hub, check-in, calendar, streak, stats, details,
add) · S20–S22 Goals/Projects · S23–S28 AI hub screens · S29–S33 Stats
· S34–S38 Settings · S39–S44 Developer Center. Reminder pings: restyled
header only; buttons and callbacks byte-identical.

## 4. Context-Aware Action Buttons

Row 1 = the most likely next action (>50% heuristic; else the screen's
create action; never navigation). Normative table:

| Screen | Row 1 | Rows 2–3 |
|---|---|---|
| Home | `➕ Add Task` | `➕ Add Habit · 🧠 Ask AI` / `⏰ Reminder` + hub rows |
| Task list (any filter) | `➕ Add Task` | `🔍 Search · 📊 Statistics` |
| Task details | `✓ Complete` | `✏️ Edit · ⏰ Reminder` / `⧉ Duplicate · 🗑 Delete` |
| Task created (success) | `✏️ Edit` | `⏰ Reminder · ⧉ Duplicate` / `🏠 Home` |
| Task completed | `📋 Back to list` | `✏️ Edit` (no undo exists — none invented) |
| Delete confirm | — | `✕ Cancel · 🗑 Yes, delete` only |
| Habit hub | `✓ Check In` | `➕ Add Habit · 📆 Calendar` / `📊 Statistics` |
| Habit details | `✓ Check In` | `✏️ Edit · 📆 Calendar` / `📊 Statistics · 🗑 Delete` — **no Duplicate** (§9.4) |
| Habit checked-in | `📆 View streak` | `✓ Check in another` |
| Statistics (any) | `📅 Weekly` | `🗓 Monthly · 📤 Export` (Weekly/Monthly = `analyze_user(days=7/30)`; Export = the existing `export` command — no stats-only export is created) |
| Search results | `🔍 Search` (new query) | per-result open buttons |
| AI hub | `💬 Chat` | `💭 Think · 🗓 Plan` / `📷 Vision · ⚙ Settings` |
| Settings category | `✏️ Edit <setting>` | sibling categories |
| Dev Center | `🧪 Self Test` | subsystem grid (§10) |

Rule for future screens: primary = the action a user takes most often
from that context; if unknowable, the screen's create action; never a
navigation button.

## 5. Rich Text Design System — LOCKED

All output via `fmt.py`; user content always escaped; `escape=False`
only for pre-built component output.

**5.1 Hierarchy.** H1 `ICON <b>TITLE</b>`, one per message, line 1.
H2 `<b>Title Case</b>`, own line, one blank line above. Body plain;
captions `<i>`; ≤ 3 bold spans outside headings. **Never stack two bold
headings.** One blank line between sections; never two; no trailing
blanks; `DIVIDER` only between the H1 block and footer hints.

**5.2 Lists.** `•` unordered / `1.` steps; one line per item; overflow
detail moves to the item's detail screen; ≥ 9 items paginate.

**5.3 Blocks.** `<blockquote>` — summaries, previews, card bodies,
≤ 8 lines. `<blockquote expandable>` — secondary content > 6 lines;
never primary content; never nested. `<code>` — command syntax, IDs,
model/env names. `<pre><code class="language-x">` — Developer Center
only. `<tg-spoiler>` — Dev-page sensitive values only. `<a href>` —
Dev-page doc links only, descriptive text. `<u>` — reserved, unused.

**5.4 Status language.** `✅` success · `⚠️` warning · `❌` error ·
`ℹ️` info — line-start, once; one status level per message (composites
headline the worst level, per-row icons inside a blockquote). **A
status icon never appears without words** (§6.3) — `✅ Saved`, never a
bare `✅`.

**5.5 Icon vocabulary (closed).** Chrome:
`🏠 📌 🌱 🎯 🧠 📊 ⚙️ 🛠 🔍 ➕ ✏️ 🗑 ⬅ 🔄 ⧉ ⏰ 📅 📆 💬 💭 📷 📤 🧪 ✕ ✓`.
Status: §5.4 icons + `🔴🟡🟢` priority, `🟢/⚪` flag, `🔥` streak,
`⏸` paused, `🔁` recurring, `⏳` loading. Density: ≤ 1 icon per line
outside status rows. Anything else in chrome fails review.

**5.6 Timestamps.** `Tue 17 Jun` (current year) / `17 Jun 2027`
(other); `17:00` 24h IST; relative forms (`in 2h`, `3d overdue`) only
in captions, always IST-derived.

**5.7 Telegram constraints.** 4,096 chars (design cap 3,500) ·
callback_data ≤ 64 bytes · ≤ 3 buttons/row, ≤ 12/message · valid entity
nesting (fmt guarantees) · no color/font control · expandable
blockquote = Bot API 7.3+ server-side (`_reply_rich` strip-fallback
shipped) · identical-content edits fail (handled by
`safe_edit_message_text`) · > 48h-old messages can't be edited → send
fresh.

## 6. UI Accessibility & Quality Standards

**6.1 Readability.** Messages fit one mobile screen (~25 lines / 3,500
chars; hard safety cap 4,000). Paragraphs ≤ 3 lines. Whitespace over
decorative separators — `DIVIDER` only in its §5.1 position. The
primary action is never below the fold.

**6.2 Mobile first.** Design reference is Telegram mobile at narrow
width. **Default row width is 2 buttons**; 3 only when all labels are
≤ ~12 chars (the nav row qualifies); 1 for primary and long-label
buttons. Labels ≤ 20 chars, sentence case after the icon; shorten
wording rather than truncate.

**6.3 Accessibility.** Never meaning-by-emoji-alone: every status icon
pairs with text; every icon-led button has a word. One term per concept
project-wide (§7). No all-caps outside H1 titles; no exclamation
stacking. Predictable layouts: Back/Home in the same place on every
screen (§2.5), primary action always row 1 (§4).

**6.4 Performance.** Navigation feels instant: `nav:`/`pg:`/`dev:`
callbacks answer with an edit and no intermediate state (deterministic
reads are sub-ms). Loading states (§11.3) only for AI/network calls
> ~2s, never for DB reads. `safe_answer_callback_query` fires
immediately on every callback. No redundant sends: an action affecting
a visible list edits that list; never two messages where one edit
suffices.

## 7. Naming Conventions — MANDATORY

One canonical label per action, verbatim everywhere. Synonyms are spec
violations. Typed commands are exempt (frozen API: `done`, `stats`,
`addhabit`, …) — this table governs UI chrome.

| Canonical | Banned variants |
|---|---|
| `➕ Add Task` | New Task, Create Task, Add New Task, + Task |
| `➕ Add Habit` | New Habit, Create Habit |
| `🏠 Home` | Dashboard (as button), Main Menu, Start |
| `⬅ Back` | Return, Previous, ‹ |
| `🔄 Refresh` | Reload, Update |
| `🗑 Delete` | Remove, Erase, Discard |
| `✏️ Edit` | Modify, Change, Update |
| `✓ Save` | Confirm (except in confirmation dialogs), Apply, OK |
| `✕ Cancel` | Abort, Dismiss, No |
| `🔍 Search` | Find, Lookup |
| `📊 Statistics` | Stats (as button), Analytics |
| `⚙ Settings` | Preferences, Options, Config |
| `✓ Complete` | Done (as button), Finish, Mark Done |
| `✓ Check In` | Log, Mark, Complete (for habits) |
| `⧉ Duplicate` | Copy, Clone |

The table is closed — new actions add their canonical label via spec
revision (§15).

## 8. Button Design System

```
Row 1   Primary — singular, full row
Row 2   Secondary (2, max 3 short labels)
Row 3   Context / destructive (🗑 never rows 1–2, never adjacent to primary)
Row n-1 Pagination (lists only)
Row n   Navigation per §2.5
```

Confirmations: safe left, destructive right — `✕ Cancel · 🗑 Yes,
delete`. The component library's button builders mechanically enforce
widths, the 64-byte callback limit, nav order, confirmation order, and
§7 labels — violations raise in tests, not in review.

## 9. Duplicate Task — Approved Feature Specification

**9.1 Entry points.** `⧉ Duplicate` on Task Details and Task-Created
card; typed `duplicate <id>` / `/duplicate <id>` (slashless entry
added; nothing renamed).

**9.2 Copies** (normalized to the real schema — `description`/`notes`
do not exist as task fields; this table is authoritative): `title`
verbatim · `category` · `priority` · `tags` ·
`recurrence_type/weekday/day` · `is_deadline` (deadline mode re-arms
for the new date) · subtasks (child rows re-created under the new task:
title/category/priority; **not** their completion state).

**9.3 Never copies:** `done` (0) · all reminder/notification state
(`reminder_count`, `last_reminded`, `snooze_until`, `snooze_count`,
`buffer_sent`, follow-up state — fresh defaults) · `paused` (0) ·
`created_at` (fresh) · streak/habit columns · completion history &
analytics rows (they reference the source id and are untouched).

**9.4 Habits are excluded — Board decision, reasoning documented:**
tasks are temporary objects that are frequently reused; habits
represent recurring behaviors — the habit itself already recurs, so
"duplicating" one creates a competing copy with a zeroed streak instead
of continuing the behavior. The correct habit verbs are Edit and Check
In. Consequences: `⧉ Duplicate` is never rendered on any habit surface;
typed `duplicate <habit_id>` replies `❌ Habits can't be duplicated —
edit the habit instead.` and offers `✏️ Edit`; Habit Details' action
set is exactly §4's (Check In · Edit · Calendar · Statistics · Delete).

**9.5 Due-date flow** (source has `due_date`; existing
`confirming`/`gathering` states, no new states): prompt
`📅 Keep <date>` / `🗓 Pick new date` / `∅ No due date` / `✕ Cancel` →
(*Pick new* → gathering prompt parsed by `date_parser`) → standard
create-confirm card → existing create path (same validation; duplicate
titles tolerated, consistent with Legacy). No due date on source →
straight to confirm card.

**9.6 Implementation constraint.** Composed from existing storage calls
(`get_task_by_id`, `get_subtasks`, `add_task`, `add_subtask`,
`set_tags`); no schema change; any facade addition is a
separately-approved one-liner.

## 10. Developer Center — `/debug` Policy FINAL

- Command: **`/debug`** (+ slashless `debug`). Never renamed; `/dev`
  does not exist. Screen title: **Developer Center**.
- Admin → Developer Center (S39). Non-admin → **silent deny** (the
  standard "Unknown command", consistent with every admin command).
  *Recorded consequence:* the pre-v1.2 non-admin `/debug` toggle
  surface folds away — the one Board-approved user-visible change; the
  toggle survives as Dev Center's `🐞 Toggle Debug Mode`.
- Preserved without exception: all existing debug functionality
  (toggle, `report`, `bugs`, `trace` — commands unchanged) · all
  existing callback handlers · `/selftest` (v14.12 diagnostics **and**
  the legacy 72-message checklist via `debug_system.SELFTEST_MESSAGES`,
  both reachable from S40) · backward compatibility of every typed
  path. Contents: Self Test · Legacy checklist · Toggle Debug Mode ·
  Logs & Security · Database (`verify_schema_integrity`) · Scheduler
  probe · Offline/Intent/Router probes
  (+ `build_enabled_registry().intents()`) · AI Diagnostics
  (= `status`/`status full`) · Performance · Feature Flags (read-only +
  restart note) · Tests card. `sql` stays typed-only, admin, unchanged.

## 11. Message Lifecycle

**11.1 Edit** — all `nav:`/`pg:`/`dev:` transitions; post-action list
re-renders; wizard advances; loading→result.
**11.2 Send new** — state-changing action results worth keeping in
scroll history (created/completed/deleted cards); AI outputs; exports;
reminder pings.
**11.3 Loading** — `⏳ <i>Thinking…</i>` sent then **edited** with the
result; only for AI/network > ~2s; deterministic screens never show
loading.
**11.4 Delete/neutralize** — stale interactive keyboards that could
fire against changed state: prefer edit-to-inert (`<i>Resolved.</i>`,
keyboard removed) over deletion; > 48h-old messages get a fresh reply.
**11.5 Keyboards** — re-renders always carry the full fresh keyboard;
success cards get their §4 context keyboard, never the source screen's.

## 12. Component Library (Phase 0 contract)

`render_page(header, content, footer)` composed of
`render_header(icon, title, crumb)` · `render_section` · cards
(`render_information_card`, `render_status_card`,
`render_statistics_card`) · states (`render_success`, `render_warning`,
`render_error`, `render_info`, `render_loading`, `render_empty_state`
plus the canonical §14 empty-state builders) · `render_confirmation`
(wraps existing preview builders verbatim) · button builders
(`nav_row`, `primary_row`, `action_row`, `confirmation_row`,
`pagination_row`, `keyboard`) · `render_footer`. Helpers: `icon(name)`
(closed-vocabulary lookup, unknown raises) · spacing/separator ·
timestamp formatters (IST, §5.6) · progress indicator · status
indicator (icon+text pairs, §6.3). **Every future screen is built from
these components — hand-assembled messages fail review.**

## 13. Governance

**13.1 Implementation governance — every phase must satisfy all of:**
✓ UI changes only ✓ no backend behavior changes ✓ no routing changes
✓ no storage changes ✓ no scheduler changes ✓ no AI-routing changes
✓ no callback removals ✓ no command removals ✓ no diagnostic removals
✓ no admin-capability removals. **Every PR ships with the completed
§13.3 checklist before review begins.**

**13.2 Documentation governance.** This specification is the single
source of truth. All UI work references its section numbers. The
component library (§12), button system (§8), typography (§5), naming
(§7), and navigation (§2) rules are mandatory. **New UI patterns are
not invented in implementation — the specification is amended first
(§15), then implemented.**

**13.3 Engineering review checklist (end of every phase):**
- *Functionality:* existing features work · every command dispatches
  (slash + slashless, verified against `API.md`) · every callback
  routes (incl. all `dash:*`)
- *Visual:* rich text per §5 · buttons per §7/§8 · navigation per §2 ·
  icons within §5.5
- *Performance:* edits behave (no duplicate sends, no stale keyboards)
  · loading states per §11.3 · callbacks answered immediately (§6.4) ·
  no message spam
- *Regression:* selftest unchanged except presentation (both
  generations reachable) · debug unchanged except presentation ·
  scheduler unaffected · AI unaffected · database unaffected · `core/`
  diff empty · full pytest suite green unmodified (additive tests only)
  · `pyflakes core/` = 0 · TESTING.md live smoke checklist run,
  extended with the phase's screens

## 14. Empty States (mandatory copy)

Template: icon + `<b>headline</b>` + one helpful line + example
blockquote where useful + CTA + nav.

| Context | Copy | CTA |
|---|---|---|
| Tasks | `📌 No tasks — you're all caught up.` + example `add task Read chapter 4 tomorrow 6pm` | `➕ Add Task` |
| Today | `📌 Nothing due today.` + `<i>due-this-week pointer</i>` | `➕ Add Task` |
| Overdue | `✅ Nothing overdue. Keep it that way!` | `📋 All tasks` |
| Habits | `🌱 No habits yet — start one small daily win.` + example `addhabit Drink water at 09:00 daily` | `➕ Add Habit` |
| Statistics | `📊 Not enough data yet — complete a few tasks and check back.` | `📋 Tasks` |
| Search | `🔍 No matches for "<q>".` + `<i>Try fewer words — search covers tasks, memories, habits, goals.</i>` | `🔍 Search` |
| AI history | `🧠 No AI activity logged. Usage history arrives with v15 analytics.` | `💬 Chat` |
| Projects | `🎯 No active projects — attach materials to any goal to start one.` | `🎯 Goals` |
| Dev pages | `ℹ️ No entries.` + subsystem-specific hint | contextual |

## 15. Roadmap & Freeze Policy

**Phases** (each ends at the §13.3 gate; independently testable):
**0** Component library + tests (zero handler changes) → **1** existing
cards re-expressed on components (field parity pinned) → **2**
Dashboard → **3** Tasks + 3b Goals/Projects + Duplicate → **4** Habits
→ **5** AI Hub → **6** Developer Center → **7** Statistics → **8**
Settings → **9** Polish (+ *separate proposal:* reply-keyboard
slimming). Dependencies: 0 → 1 → 2 → (3–8 any order) → 9.

**Freeze policy.** This document is frozen. Implementation phases
reference it; they never redefine UI behavior. Deviations require a
Board-approved revision (v1.3+) before code.

## Appendix A — Future Enhancements (explicitly out of scope)

Adaptive Quick Actions · Recently Used Actions · AI Suggestions on Home
· Pinned Actions · Personalized Dashboard · Keyboard Personalization ·
Context-Aware AI Recommendations — documented for the roadmap, all
gated on v15 (analytics rebuild, AI Router), none implementable without
a new Board approval.
