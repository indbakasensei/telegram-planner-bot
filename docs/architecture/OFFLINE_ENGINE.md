# Offline Engine — Design Specification

**Part of:** `DESIGN_SPEC_v14_AUTONOMOUS_CORE.md`. Documentation only.
**Replaces/formalizes:** the majority of `main.py`'s ~90 command handlers —
specifically, every one that today already doesn't call `baka_brain.py`
(confirmed against `API.md`'s command reference and the handler-by-handler
review this project's engineering audit performed).

---

## Why this exists

A fact this project already knows but has never architecturally
guaranteed: **most of what BAKA does today never touches AI.** `/list`,
`/done`, `/habits`, `/streak`, `/goals`, `/settings`, every project
command (`/need`, `/got`, `/worklog`, `/project`), every reset/admin
command — none of these call `baka_brain.py`. This is true today only
because each handler happens to have been written that way, not because
anything stops a future handler from reaching for AI unnecessarily. The
Offline Engine makes "this class of command never needs AI" a structural
property, not a habit.

## Which commands require AI

Grounded directly in `baka_brain.py`'s actual call sites (verified during
the v13.3.2 timeout-profile work, which touched every one of them):

| Feature | Why it needs AI |
|---|---|
| Free-text task creation with ambiguous entities | Needs language understanding to extract title/date/time/category from unstructured text beyond what `date_parser.py`'s deterministic rules resolve |
| `/think` | Explicitly open-ended reasoning by design — `think_freely()` has no structured output at all |
| `/plan today`, `/plan week` (generation) | Produces a novel schedule, not a lookup — `generate_structured_plan()`/`generate_daily_plan()`/`generate_weekly_plan()` |
| `/breakdown` | Generates novel subtask suggestions — `generate_task_breakdown()` |
| `/suggest <goal>` | Generates novel task suggestions — `suggest_tasks()` |
| `/analyze` (narrative form) | `analyze_productivity()`'s narrative summary is generated text, though the underlying data it summarizes is a plain query — see "partially offline" note below |
| Photo messages (vision) | Requires `MODEL_VISION` — no deterministic alternative exists for image understanding |
| `/image`, `/video` | Generation, definitionally not deterministic |
| `/reschedule` | `suggest_reschedule_time()` picks a conflict-free time via reasoning, not a fixed rule (though a future deterministic "first free slot" fallback is a plausible Offline Engine extension — not built for v14) |
| Daily AI observations (`observation_engine` scheduled job) | Generates novel behavioral suggestions from the week's data |

## Which commands never require AI

The much larger set — every one of these already works with zero AI calls
today, per `API.md`'s command reference:

**Tasks:** `list`, `today`, `week`, `done`, `delete`, `edit` (structured
field edits), `deadline` (toggle), `tag`/`tagged`, `checktasks`

**Reminders:** `pause`, `resume`, `paused`, `snooze`, `stopreminder`,
`delreminder`

**Deadlines/overdue:** `overdue`, `carryforward`, `deadlines`, `review`

**Habits:** `habits`, `streak`, `habitlog`, `addhabit`, `skiphabit`

**Goals/Projects:** `goals`, `need`/`materials`, `got`/`have`,
`worklog`/`log`, `started`, `finished`, `project`/`projects`, `shopping`

**Memory:** `memory` (list), `forget` — note: *saving* a new memory from
free text needs the Intent Engine to extract a key/value, which is
Tier-1-deterministic for clearly-structured phrasing ("remember X is Y")
and only escalates to AI for genuinely ambiguous phrasing — see
`INTENT_ENGINE.md`.

**Search/tools:** `search`, `template`/`templates`, `savetemplate`,
`export`

**Settings:** `settings`, `quiethours`, `interval`, `wellness`,
`proactive`, `dashboard`/`home`

**Debug:** `debug`, `report`, `bugs`, `resolve`, `trace`, `selftest`

**Admin:** `admin`, `adminmode`, `resettasks`, `resetmemory`,
`resethabits`, `resetlearning`, `resetall`, `sql`, `myid`, `claimadmin`,
`misses`/`reviewed`

**Scheduler-triggered (no user message at all):** `check_reminders`,
`check_followups`, `daily_carry_forward`, `check_did_you_finish`,
`end_of_day_summary`, `wellness_reminder`, `priority_nudge`,
`morning_briefing`, `weekly_report`, `deadline_buffer_check`,
`project_nudge`, `check_deadlines` — all 12 non-AI scheduled jobs
(`docs/scheduler.md`) run entirely through the Offline Engine; only
`observation_engine` needs the AI Router.

## Partially-offline: `/analyze`

Worth calling out explicitly since it's the one command that straddles the
line: `analyze_productivity()`'s *narrative* text generation needs AI, but
every number it summarizes (completion rate, overdue count, category
distribution) comes from `preferences.py`'s `analyze_user()`, which is a
pure, offline function over `database.py` data. v14's Offline Engine
should expose a **structured, offline `/analyze` result** (the raw
numbers, formatted directly without AI) as the default, with the
AI-narrated version as an explicit opt-in ("give me the narrative version")
routed through the AI Router. This is a concrete example of the kind of
AI-dependency reduction the Offline Engine's existence makes visible and
actionable — today this distinction isn't even representable in the code,
since `analyze_productivity()` conflates both.

## Offline capabilities

The Offline Engine owns:

- **All CRUD** against `database.py`'s 13 tables, using the existing
  functions verbatim (`API.md`'s full function inventory) — no
  reimplementation.
- **All scheduler-triggered actions** that don't need AI (11 of 12 jobs,
  per above).
- **Structured entity resolution** for anything the Intent Engine already
  extracted deterministically (Tier 0/Tier 1 matches) — e.g. if the Intent
  Engine resolved a full `TASK` with title/date/time/category at
  confidence 0.9, the Offline Engine saves it directly; no AI is consulted
  even though the *original* message was free-form natural language.
- **Confirmation-flow orchestration** — the "show a summary, wait for
  yes/no" pattern (`fmt.py`'s `confirm_box()`) is unchanged and lives here,
  not in the AI Router, since confirmation is about the write path, not
  about whether AI was involved in deciding what to write.
- **Persisting AI Router results** — when the AI Router returns a
  structured plan/breakdown/suggestion, the Offline Engine is the only
  thing that writes it to `database.py` (see the master spec §7's note on
  why AI Router responses are never self-executing).

## Offline limitations

- **Cannot resolve genuinely ambiguous natural language.** "Remind me
  about the thing" has no deterministic resolution — this is intentional,
  not a gap to close; see `INTENT_ENGINE.md`'s confidence bands.
- **Cannot generate novel content.** No offline substitute for `/think`,
  `/breakdown`'s subtask suggestions, or image/video generation — these
  are inherently generative, not lookups.
- **Cannot learn or adapt beyond `preferences.py`'s existing statistical
  approach.** `preferences.py`'s tone/interval suggestions are pattern
  aggregation over past behavior (already offline, already used today) —
  the Offline Engine does not add any new "intelligence," it just owns
  execution of what's already deterministic.
- **Cannot handle photo/voice input.** Vision requires `MODEL_VISION`
  today; a future local vision model (see below) is the only path to
  closing this without a network call.

## Database interaction

No change from today's pattern: the Offline Engine calls `database.py`'s
existing functions directly, respecting the same `user_id`-scoping
invariant every function already enforces (`docs/database.md`'s "Data
integrity patterns" section). The Offline Engine does **not** get its own
data-access layer — introducing one would violate the master spec's §3
Non-Goals ("not a rewrite of `database.py`'s schema") and would duplicate
logic for no benefit, since `database.py`'s functions are already pure,
already tested (`tests/test_database.py`, 32 tests), and already used
exactly this way by every non-AI handler in `main.py` today.

## Scheduler interaction

Also unchanged: `scheduler.py`'s query functions (`get_due_tasks()`,
`get_tasks_needing_followup()`, `is_quiet_hours()`, etc.,
`docs/scheduler.md`) and the 13 `job_queue`-registered jobs continue to
run exactly as they do today. The Offline Engine is what a scheduled job's
callback *calls into* to do its work (e.g. `check_reminders`'s callback,
after finding due tasks via `scheduler.py`, hands off to the Offline
Engine to actually format and queue the reminder message) — this is a
thin wrapping, not a redesign of the scheduler itself, consistent with the
master spec's constraint that `scheduler.py` is unchanged.

## Future local LLM integration

The Offline Engine is explicitly *not* where a local LLM would plug in —
that's the AI Router's job (`AI_ROUTER.md`'s Ollama/LM Studio adapters).
The distinction matters: a local model is still generative AI, subject to
the same "AI Router returns structured data, Offline Engine persists it"
discipline as any cloud provider. The Offline Engine's only relationship
to a future local model is as the *consumer* of its structured output,
identical to how it would consume NVIDIA's or Anthropic's. This keeps the
architecture's core invariant intact regardless of where inference
actually runs: **the Offline Engine is the only path to `database.py`
writes, whether the data originated from a deterministic rule or a
generative model, local or remote.**
