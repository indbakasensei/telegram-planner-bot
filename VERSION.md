# BAKA Bot — Version History

## v12.0 — Project Management (current)
Turn any goal into a project with materials, worklog, progress tracking, and
automatic stagnation reminders. Perfect for real-world things you build over
weeks (drones, renovations, hobby builds, learning tracks).

Example flow — the drone build:
  1. "goal build drone by 2026-08-15"        → goal saved, id shown
  2. "need <id> motor, propeller, battery,   → 5 materials attached
        frame, controller"
  3. "got motor"                              → fuzzy-matched, marked ✅
  4. "started <id>"                           → worklog entry, state=started
  5. "worklog <id> frame mounted"             → auto-detected as 'progress'
  6. "project <id>"                           → full card w/ progress bar,
                                                material checklist, worklog
  7. "shopping"                               → auto-list of everything
                                                still needed across ALL projects

Added:
- 2 new SQLite tables: project_materials, project_worklog (indexed on goal_id)
- 11 new commands:
    need <id> <items>       add comma-separated materials
    materials <id> <items>  same as /need (alias)
    got <name>              fuzzy-mark acquired across all projects
    have <name>             same as /got (alias)
    worklog <id> <text>     log project progress (kind auto-detected)
    log <id> <text>         same as /worklog (alias)
    started <id>            log 'work started' entry
    finished <id>           log 'finished' entry + mark done
    project <id>            full dashboard card (progress bar, materials
                            checklist, recent worklog, action buttons)
    projects                list all active projects with progress bars
    shopping                auto-shopping list — everything unacquired
                            across all projects, grouped by project

- Natural language routing for every command:
    "I need motor and battery for drone"    → need_cmd
    "got the motor"                         → got_cmd (fuzzy match)
    "started work on drone"                 → started_cmd
    "how is my drone project"               → project_cmd
    "shopping list"                         → shopping_cmd

- Smart worklog kind detection:
    "finished/done/khatam"    → kind=finished
    "blocked/stuck/issue"     → kind=blocker
    "started/began/shuru"     → kind=started
    everything else           → kind=progress

- Auto-progress formula:
    materials 50% weight (acquired/total ratio)
    work_state 50% weight (finished=100%, progress=50%, started=25%)
    Progress % shown as inline bar: ██████░░░░ 60%

- Stagnation nudges (daily 20:00):
    Case A: deadline < 3 days AND materials still missing
            → urgent alert with pending list + shopping button
    Case B: no worklog in 7+ days AND deadline < 30 days away
            → gentle nudge with 'log progress' button
    Respects quiet hours.

- Inline callback router: proj:started, proj:finished, proj:got, proj:view,
  proj:shopping — every project card comes with tap-to-act buttons.

Debug pass:
- 9-step drone scenario end-to-end verified (P1-P9)
- All 11 commands registered
- Selftest expanded to 72 tests (added Section P with 9 project tests)
- Zero regressions across parser, database, analytics, models

Modified: main.py, database.py, debug_system.py

Ideas for next (not yet built):
- v12.1 — project photos via Vision: send a photo, Llama Vision describes
  progress, auto-adds a worklog entry
- v12.2 — cost/budget: sum material costs, show budget vs spent per project
- v12.3 — milestones: split projects into named stages, each with its own
  progress
- v12.4 — template projects: save a project's material list as a template so
  next similar build populates instantly ("build drone" → same 5 materials)

---

## v11.2 — NIM-Only Visual Generation + Full Debug Pass (current)
Image and video generation rebuilt against the OFFICIAL NVIDIA API specs
(docs.api.nvidia.com), verified line-by-line. No third-party fallbacks.

IMAGE — FLUX.1-schnell (fixed per official "Infer" spec):
- Endpoint: https://ai.api.nvidia.com/v1/genai/black-forest-labs/flux.1-schnell
- ROOT CAUSE of the 404/422 chain: body must use a PLAIN "prompt" STRING
  (previous fix wrongly used the Stable-Diffusion-style text_prompts array),
  cfg_scale must be exactly 0, and only 1024x1024 is supported
- Response parsed from artifacts[0].base64 → sent to Telegram as bytes
- Pollinations fallback REMOVED — FLUX via NIM is the only image source
- Clear error messages per status: 404 (no Visual GenAI access on key),
  401/403 (bad key), 422 (invalid body), 429 (rate limit), timeout

VIDEO — NEW /video command (Stable Video Diffusion):
- Cosmos has NO hosted endpoint on NIM — SVD is the only hosted video model
- Endpoint: https://ai.api.nvidia.com/v1/genai/stabilityai/stable-video-diffusion
- SVD is image-to-video, so "/video <prompt>" runs a 100% NIM pipeline:
  FLUX generates the frame → SVD animates it (cfg_scale 1.8, motion_bucket 127)
- Auto-downscales frames >200KB (spec limit) via Pillow
- MODEL_VIDEO changed: nvidia/cosmos-1.0-7b-text2world → stabilityai/stable-video-diffusion
- Natural language: "video waves on a beach", "make a video of..."

ALWAYS-ON: ENABLE_IMAGE_GEN=True, ENABLE_VIDEO_GEN=True, ENABLE_VISION=True

FULL SELF-TEST DEBUG PASS (65 automated checks):
- Parser: all date/time/Hindi/deadline/recurrence/priority tests PASS
- Database: all 13-table CRUD, dedup, case-insensitivity, context PASS
- Analytics: log→query round trip, SVD pricing PASS
- 65/65 commands registered
- 2 "failures" root-caused as doc/test-data errors, NOT code bugs:
  1. Selftest doc said dopahar→14:00; parser has correctly mapped
     lunch/dopahar→13:00 since v3.0. Doc corrected.
  2. Deadline-fetch test used a same-day 20:00 task at 21:28 IST — the
     query CORRECTLY excludes past-due deadlines. Test data corrected.
- Selftest expanded: image + video tests added to Section L (63 tests total)

Modified: baka_brain.py, main.py, debug_system.py, analytics/token_counter.py

---

## v11.1 — AI Usage Analytics & Model Monitoring
Per-call AI telemetry, multi-model dashboards, error tracking.
Every AI request that flows through the system is now logged automatically
without manual instrumentation and without slowing down any AI response.

NEW PACKAGE: analytics/ (kept separate from business logic per spec)
- usage_logger.py — async-queue logger, ZERO-impact on AI latency
- usage_service.py — query functions for the dashboard
- model_metrics.py — per-model rollups + health detection
- token_counter.py — cost estimation (15 models priced)
- performance_tracker.py — latency percentiles + trends
- __init__.py — clean public API

NEW TABLE: ai_usage (19 columns per spec)
- timestamp, user_id, session_id, conversation_id
- provider, model_name, request_type, intent
- prompt_tokens, completion_tokens, total_tokens
- estimated_cost (USD), latency_ms, status, error_message
- fallback_used, response_length, created_at
- 4 indexes for fast queries

AUTOMATIC LOGGING — captures every AI call:
- baka_brain.py _call_model() — every multi-model call
- baka_brain.py call_nvidia() — legacy intent detection path
- baka_brain.py generate_image() — image gen
- Token usage extracted from response.usage (works for any OpenAI-compatible provider)
- Failed calls also logged (status='error' with error_message)
- Fallback activations tracked (fallback_used=1)

NEW COMMANDS:
- /usage — today + lifetime overview, top models/providers/types, recent activity
- /performance — p50/p95/p99 latency, fastest/slowest/most reliable, trends
- /errors — total errors, top errors, models causing them, fallback count, timeline
- /models — UPGRADED: shows live ping + real usage (today/total/avg/success per model)

PROVIDER-INDEPENDENT design:
- Provider stored as separate column (NVIDIA NIM, OpenAI, Anthropic, Google, Ollama)
- 15 model price points pre-loaded (token_counter.py MODEL_COSTS)
- Adding a new provider = adding entries to MODEL_COSTS, no code changes

PERFORMANCE:
- Async background-thread writer queue (0.017ms per call overhead)
- WAL mode + synchronous=NORMAL for concurrent reader/writer safety
- Sub-microsecond impact on AI response path

BACKWARD COMPATIBILITY:
- Every existing call signature unchanged (request_type/user_id are optional kwargs)
- Existing AI flows untouched
- ai_usage table independent — no FK to existing data
- Analytics failure NEVER blocks an AI call (all wrapped in try/except)

Modified: main.py, database.py, baka_brain.py
New folder: analytics/ (6 files)

---

## v11.0 — Multi-Model AI System
The full multi-model AI infrastructure. BAKA can now think, see, and create.

Added 6 AI models with smart routing:
- MODEL_MAIN    = z-ai/glm-5.1                — main brain (will become 5.2)
- MODEL_FAST    = meta/llama-3.1-8b-instruct  — quick intent / classification
- MODEL_THINK   = z-ai/glm-5.1                — deep reasoning (/think)
- MODEL_VISION  = meta/llama-3.2-90b-vision   — understands images
- MODEL_IMAGE   = black-forest-labs/flux.1-dev — generates images
- MODEL_VIDEO   = nvidia/cosmos-1.0-7b        — video generation (opt-in)

New per-model functions in baka_brain.py:
- call_main(), call_fast(), call_think(), call_vision(), generate_image()
- _call_model() — internal dispatcher with retry + logging
- fast_intent_classify() — pre-filter for cheap intent guesses
- benchmark_all_models() — shows status of every model

Image Understanding (Llama 3.2 Vision):
- Send any photo to the bot → it describes the image
- Add a caption to ask specific questions ("translate this", "what brand?")
- If the image contains a todo list, BAKA extracts the items and offers
  to save them as tasks with one button tap
- Use cases: handwritten todos, whiteboards, screenshots, schedules

Image Generation (FLUX.1-dev, opt-in):
- /image <prompt> or "image <prompt>" or "draw <prompt>"
- Returns the generated image inline
- Off by default to save credits — enable in baka_brain.py (ENABLE_IMAGE_GEN)

Autonomous Observation Engine:
- Daily 22:00 job analyzes your week and generates 1-3 AI suggestions
- /suggestions to review pending suggestions
- /approve <id> applies the suggestion (e.g. auto-creates a habit)
- /dismiss <id> rejects it
- Suggestions are JSON-structured so they can be auto-applied safely

Feature toggles (all in baka_brain.py top section):
- ENABLE_FAST_ROUTING = False (escalates to MAIN by default for safety)
- ENABLE_VISION       = True
- ENABLE_IMAGE_GEN    = False (toggle to enable image gen)
- ENABLE_VIDEO_GEN    = False (video is expensive — opt-in only)

New commands: /image, /generate, /models, /suggestions, /approve, /dismiss
New handlers: PHOTO message handler routes to vision pipeline
New callbacks: vision_save_tasks, vision_ask_again
New tables: ai_observations (observation, suggestion, action_type, status)
New jobs: observation_engine (daily 22:00)
Modified: main.py, database.py, baka_brain.py

---

## v10.2 — AI Autonomy Foundation
Three pieces that move BAKA from "scripted bot" toward "real assistant",
laying the groundwork for full v11.0 multi-model autonomy.

Added:
- Rich AI context: every AI call now sees the user's open tasks by category,
  recent completions, overdue count, and active habits + streaks.
  The AI can now reason WITH your actual data, not in a vacuum.
- /think (or /ask) — free-form AI reasoning, no JSON schema, no constraints.
  GLM 5.1 sees your full profile + open tasks + memories and answers
  conversationally. Examples:
    "think what should I focus on today?"
    "ask am I taking on too much?"
    "what should I prioritize this week?"
- Missed-Capability Log: every time the AI fails to handle something well
  (low confidence OR chat-fallback when there were action verbs), we log:
    user input, AI's intent, AI's response, miss type, confidence
  Review them with /misses (admin-only) to pick which features to build next.
  This is the "log it for later" infrastructure for choosing real-world
  feature priorities instead of guessing.
- Natural-language entry for think mode: "what should I...", "should I...",
  "help me decide", "what do you think", "your opinion"

New table: missed_capabilities (input, intent, response, miss_type, confidence, reviewed)
New functions: get_user_context_for_ai, log_missed_capability, get_missed_capabilities,
               mark_missed_reviewed, think_freely
New commands: /think, /ask, /misses (admin), /reviewed (admin)
Modified: main.py, database.py, baka_brain.py

---

## v10.1 — Pre-Deadline Buffer Reminders
A new way to handle "due by" tasks — warn AHEAD so you can plan, not panic.

Added:
- Auto-detect deadline phrasing in natural language:
  English: "due", "deadline", "submit by", "deliver by", "finish by",
           "complete by", "done by", "before deadline", "hand in", "turn in"
  Hindi: "tak", "tak karna hai", "deadline hai", "submission"
- Smart buffer reminders at 7d / 3d / 1d / 6h / 1h ahead of the deadline
- Each warning shows time remaining + inline buttons:
  ✅ Done now · 🔨 Break down · 📅 Plan today · 🔕 Mute buffers
- /deadline <id> [on|off] — manually toggle deadline mode for any task
- All buffer reminders respect quiet hours
- Once a buffer level is sent, it's recorded (comma-separated 'buffer_sent' column)
  so the same warning never fires twice for the same task

Detection works in TWO layers (defense in depth):
- Parser regex (deterministic) detects deadline phrasing first
- AI also has is_deadline as a new entity field
- Either layer triggering enables deadline mode

New columns: is_deadline, buffer_sent (in tasks table, migrated safely)
New functions: mark_as_deadline, get_pending_deadlines, mark_buffer_sent, parse_buffer_sent
New job: deadline_buffer_check (every 30 min)
New callback: unflagdeadline (mute buffers for a task)
New command: /deadline + "deadlines"/"deadline mode" natural lang
Modified: main.py, database.py, date_parser.py, baka_brain.py

---

## v10.0 — Search, Reports & Templates
Phase 10 — power-user features that make BAKA faster to use daily.

Added:
- /search <keyword> — universal search across tasks, memories, habits, goals.
  Searches titles, categories, tags, memory keys+values. Slashless: "search exam"
- Task Templates — save & reuse common task patterns:
  /savetemplate <name> <task_id> — save any task as a template
  /template <name> — create a task from a saved template (pre-fills everything)
  /templates — list all saved templates
  "template gym" / "my templates" / "save template study 5" all work without slash
- /export — full data backup as plain text (tasks, memories, goals)
  Slashless: "export" / "backup" / "export my data"
- Weekly Report — automated Sunday 20:00 digest:
  Tasks completed/created this week, pending, overdue, completion rate,
  top habit streaks. Sent with Dashboard+Stats buttons.
- Smart time suggestions in task creation:
  When no time is set, BAKA checks your learned completion patterns (from v6.0)
  and suggests: "You usually do Study tasks around 20:00. Want me to set that?"

New table: task_templates (name, title, category, priority, recurrence, default_time)
New functions: search_all, save/get/delete_template, get_weekly_report_data, export_user_data
New job: weekly_report (Sunday 20:00)
Modified: main.py, database.py

---

## v9.1 — GLM 5.1 AI Upgrade + Enhanced Diagnostics
Switched AI model from Llama 3.1 8B to GLM 5.1 (much more capable).

Added:
- Model swap: meta/llama-3.1-8b-instruct → z-ai/glm-5.1
- MODEL_MAIN constant for easy v11.0 multi-model swap
- Bulletproof .env loading (manual fallback if dotenv fails)
- top_p parameter support per NVIDIA NIM spec
- /status upgraded to full AI benchmark:
  Quick mode (3 tests): connectivity, JSON compliance, intent detection
  Full mode (6 tests): adds Hindi understanding, task extraction, instruction following
  Shows: per-test pass/fail + latency, overall grade (A+ to F), avg response time
  Run: `status` (quick) or `status full` (deep benchmark)
- v9.0.1 hotfix: goals table migration for legacy DBs (missing 'done'/'progress'/'target')
  All goal queries now use PRAGMA table_info for column detection — never crashes

Modified: baka_brain.py (model + benchmark), main.py (status cmd), database.py (goals migration)

---

## v9.0 — Dashboard & Rich UX Integration
Phase 9 — transforms BAKA from chat-centric to dashboard-centric. Purely additive;
every prior feature preserved. New ui.py component module keeps UI separate from logic.

Added:
- 🏠 Unified Dashboard (/dashboard, /home, menu button, "dashboard"/"home" NL)
  Adaptive home hub: today/overdue/pending counts, goals, habits, completion bar
- New ui.py module — reusable HTML cards: dashboard_card, task_card, today_card,
  goal_card, habit_card, stat_card, reminder_card, progress_bar
- Rich Task Cards with inline action rows: Done · Edit · Snooze · Postpone · Delete
- Today View grouped into Overdue / High-priority / Upcoming / Completed
- 🎯 Goal Dashboard with progress bars + inline ➕/➖ progress buttons (/goals)
  New goals.target column for milestone tracking
- 🌱 Habit Dashboard card (wraps existing v5.0 habit engine — not rebuilt)
- 📊 Productivity/Stats dashboard (wraps v6.0 analyze_user) with completion bars
- ☀️ Morning Briefing job (08:00): today's priorities, deadlines, overdue, goals
- 🌙 Evening Review (upgraded end-of-day): done count, pending, tomorrow preview
- Centralized dashboard callback router ("dash:" namespace) — edits messages
  IN PLACE to reduce chat clutter (spec #11)
- Callback logger + dashboard render logger (debug infra)

Safety / compatibility:
- HARDENED handle_callback: task_id now parsed safely (try/except) so dashboard
  callbacks never crash the old int() conversion — makes ALL callbacks more robust
- "dash:" callback namespace is fully separate — zero collision with existing actions
- Every existing command (25), callback (10), and scheduler job preserved
- 1 safe migration: ALTER TABLE goals ADD COLUMN target (no data touched)

New file: ui.py
New DB: goals.target column; get_goals_full, update_goal_progress, get_done_today_count
New jobs: morning_briefing (08:00); end_of_day_summary upgraded to Evening Review
Modified: main.py (router, dashboard handlers, menu, GOAL intent), database.py

---

## v8.0 — Proactive Suggestions
Phase 8 — BAKA offers help on its own, but every proactive feature is opt-in
or respectful of quiet hours so it never becomes annoying.

Added:
- Wellness reminders (OPT-IN, default OFF): 💧 water, 🧘 break, 👀 eye-rest, 🪑 posture
  - /wellness on|off, /wellness interval 60, /wellness water|break|eyes|all
  - Only sent during awake hours, never during quiet hours
  - Per-user interval gate (default 90 min) prevents spam
- /proactive — control panel showing every proactive feature + its status
- Smart task-creation hint: if you already have 2+ tasks at the exact same time,
  the confirmation shows "you already have N tasks at that time"
- Proactive high-priority nudge: a high-priority task due within 3 hours gets ONE
  heads-up with Done / Break-down buttons (never repeated)
- All new messages use clean HTML formatting (fmt.py)

New columns: wellness_on, wellness_interval, wellness_types, last_wellness (user_preferences)
New functions: get_wellness_prefs, set_wellness, mark_wellness_sent,
  get_wellness_enabled_users, count_tasks_at_time, get_high_priority_soon
New jobs: wellness_reminder (every 15m, interval-gated), priority_nudge (every 30m)
Fixed: init_db now runs preference + learning migrations at startup, not lazily
Modified: main.py, database.py

---

## v7.1 — Log-Driven Bug Fixes + Rich HTML Formatting
Fixed bugs found in real test logs + switched messages to clean HTML formatting.

Bugs fixed (from test log analysis):
- BUG: Recurring tasks ("every Monday", "har Sunday", "daily at 9") were
  misclassified as GOAL and did nothing. Now correctly detected as HABIT.
  Updated the AI prompt: ANY phrase with every/har/daily/weekly/monthly = HABIT.
- BUG: "evening"/"shaam" returned 15:00 instead of 18:00 (AI overrode parser).
  Now the parser's exact vague-time mapping ALWAYS wins over the AI guess.
- BUG: Invalid times ("25 PM", "13 AM", "25:99") were silently accepted.
  Now rejected with a friendly "that time doesn't look valid" message.
- BUG: "Remind me on 25 December" and "Submit on 2026-12-25" were classified
  as MEMORY_SAVE. Now a date + action verb = TASK.
- BUG: "Remind me yesterday" → now warns about the past date.
- Parser merge logic now handles HABIT intent and validates time/date before saving.

Rich HTML formatting (new fmt.py module):
- Switched core messages (task list, confirmation card, reminders, save success)
  from Markdown to Telegram HTML parse mode
- HTML is robust: titles with dots, dashes, parentheses, +, & no longer break
  message rendering (Markdown would corrupt on these)
- New helpers: b() bold, i() italic, code() monospace, esc() escaping,
  task_line(), confirm_box() for consistent clean cards
- Task lists now use clean "· " separators and proper recurrence icons

New file: fmt.py
Modified: baka_brain.py (intent prompt), main.py (merge logic + HTML), 

---

## v7.0 — Follow-up Intelligence
Phase 7 — BAKA stops being reactive and starts following up proactively.

Added:
- "Did you finish?" check-ins: 15 min after a task's time passes, BAKA asks
  if you completed it, with buttons: ✅ Yes done / ❌ Not yet / ⏰ Snooze 1h / 📅 Tomorrow
- If "Not yet" → offers to Reschedule, Break it down, or Stop asking
- Repeated-snooze detection: snooze a task 3+ times and BAKA notices —
  "You've snoozed this 3 times. You usually get things done around 19:00 — want to move it?"
  (uses v6.0 learned completion times)
- /review — lists stale tasks (3+ days overdue) with days-overdue + snooze count,
  so you can bulk carryforward/delete/reschedule
- End-of-day summary at 21:00: "You have 3 tasks still pending today: ..."
- All follow-ups respect quiet hours — no nagging while you sleep
- Natural language: "review", "stale tasks", "old tasks", "what needs review"

New columns: followup_sent, followup_count, snooze_count, stale_flagged
New jobs: check_did_you_finish (every 15 min), end_of_day_summary (21:00 daily)
New callbacks: finish_yes, finish_no, dobreak
New functions: get_tasks_for_followup, mark_followup_sent, increment_snooze_count,
  get_snooze_count, get_stale_tasks, get_unresolved_today, get_all_active_user_ids
Fixed: timezone bug — v7.0 db functions now use IST not naive UTC
Modified: main.py, database.py

---

## v6.1 — Admin Mode + Reset Tools (owner-only)
A private control panel locked to YOUR Telegram ID alone.

Added:
- /myid — shows your Telegram ID and admin status
- /claimadmin — first user to run this becomes the permanent sole admin
  (run this ONCE right after deploying — it locks the bot's admin to you)
- /admin — control panel showing data stats + all admin commands
- /adminmode — toggle verbose debug mode (intent, entities, parsed times, SQL traces)
- /resettasks — delete all tasks AND reset task IDs back to 1 (with YES RESET confirm)
- /resetmemory — wipe all memories
- /resethabits — wipe all habits + streak logs
- /resetlearning — wipe preference-learning data
- /resetall — nuclear reset of everything + ID reset (with YES NUKE EVERYTHING confirm)
- /sql <SELECT query> — run read-only SQL for debugging
- All admin commands are INVISIBLE to non-admins (they get "Unknown command")
- admin_id.txt persists the admin lock across restarts (gitignored — never committed)

New DB functions: reset_all_tasks (resets autoincrement), reset_all_memories,
  reset_all_habits, reset_learning_data, reset_everything, get_data_stats
New: .gitignore protects admin_id.txt and .env
Modified: main.py (admin infra, 11 admin commands, reset confirmations), database.py

---

## v6.0 — Preference Learning
Phase 6 — BAKA finally lives up to its name as Behavioral Adaptive Knowledge Assistant.

Added:
- Every task completion is logged (when, category, delay-from-scheduled)
- Every snooze is logged (category, duration) — reveals avoidance patterns
- Every interaction is timestamp-logged — reveals your active hours
- /insights — comprehensive learned-pattern report
  Shows: tone classification, active hours, snooze patterns, top categories,
  completion rate, and actionable observations like "you snooze Study often"
- Auto-derived tone: gentle (frequent snoozer) / strict (high completion) / balanced
- suggest_time_for_task() — when user creates a new Health task, BAKA can suggest
  the time they usually complete Health tasks at
- suggest_interval_for_task() — heavy snoozers get longer reminder intervals
  per category, so the bot doesn't nag categories you avoid
- Natural language: "insights", "what have you learned", "my patterns",
  "what do you know about me"

New tables: completions_log, snooze_log, interaction_log
New module: preferences.py — analyze_user, suggest_time_for_task, suggest_interval_for_task
Modified: main.py (logging hooks in done/snooze/messages), database.py (3 new tables + 7 helpers)

---

## v5.0 — Habit Engine
Phase 5 — habits become first-class with streaks and missed-day tracking.

Added:
- Habits are stored separately from tasks (is_habit flag) and tracked via habit_log table
- /habits — list all habits with streak summary and fire emojis
- /streak <id> — detailed view of a habit with 14-day grid (🟩 done, ⬜ missed)
- /habitlog <id> — full 30-day completion log
- /addhabit <text> — quick habit creation
- /skiphabit <id> — reset streak when you intentionally skip
- Marking a habit done auto-logs it AND updates the streak
- Longest-streak tracking (your personal best)
- Missed-days detection (compares expected days vs logged days)
- Suggests adjustment tip when you miss 3+ days
- HABIT intent (from v3.0) now creates real habits, not just recurring tasks
- All habit commands work without slash: "habits", "streak 5", "addhabit gym daily", etc.

New DB: habit_log table (per-day completion records, UNIQUE on habit_id+log_date)
New columns: is_habit, habit_start_date, current_streak, longest_streak, last_completed
New functions: add_habit, is_habit, log_habit_completion, get_habit_log,
  get_habits, get_missed_days, reset_streak
Modified: main.py, database.py — done_task and inline-done callback are habit-aware

---

## v4.0 — Smart Planning + Task Breakdown
Phase 4 — the bot stops being just a reminder app and becomes a planner.

Added:
- /plan [today|week] — AI-generated time-blocked schedule
  Considers your quiet hours, prioritizes by urgency, suggests breaks
- /breakdown <id> — breaks any task into 3-5 actionable subtasks
  Subtasks are linked to parent via parent_task_id and can be saved as real tasks
- /reschedule <id> — AI picks a new time avoiding conflicts with your other tasks
- /overload — shows next 2 weeks of task load, flags overloaded days (>4 tasks)
- Natural language: "plan my day", "plan my week", "what should I do today",
  "am I overloaded", "busy days" — all work without slashes
- PLAN intent now generates actual structured plans, not just AI chat
- Subtask support via parent_task_id column — big goals broken into trackable pieces

New DB column: parent_task_id
New functions: add_subtask, get_subtasks, get_tasks_for_planning,
  count_tasks_per_day, generate_daily_plan, generate_weekly_plan,
  generate_task_breakdown, suggest_reschedule_time
Modified: main.py, database.py, baka_brain.py

---

## v3.0 — Vague Time Understanding + Smarter Clarification + Habits
Phase 3 — the bot now understands how humans ACTUALLY speak about time.

Added:
- Vague time phrases → smart defaults:
  "later" → 2hrs, "soon" → 30min, "evening/shaam ko" → 18:00,
  "morning/subah" → 08:00, "tonight" → 21:00, "end of day" → 17:00,
  "midnight" → 00:00, "lunch" → 13:00, "noon" → 12:00,
  "end of week" → next Friday
- Hinglish vague time: "shaam ko", "shaam mein", "baad mein", "thodi der"
- ASAP/urgent → time = now+30min AND priority = high automatically
- "whenever/no rush/koi jaldi nahi" → priority = low automatically
- Urgency detection: "urgent", "ASAP", "jaldi", "critical", "zaruri" → high priority
- Smarter clarification: if date/time known but title missing, asks
  "What task should I set for [date] at [time]?" instead of just "What's the task?"
- HABIT intent: "I want to start running daily" → sets up recurring task automatically
- Priority from parser auto-merged into entities (no longer ignored)

Modified: date_parser.py (vague times, urgency, end-of-week), main.py (habit intent, smarter clarification, priority merge)

---

## v2.0 — Passive PA: Remind Until Done + Escalation + Quiet Hours
Phase 2 — the bot now OWNS tasks until they're completed. Not just one ping.

Added:
- Remind until done: overdue tasks get re-reminded every 30 min (configurable)
- Escalation: reminder frequency increases near deadline (30m → 15m → 10m → 5m)
- Batching: if you have 3+ overdue tasks, they're grouped into one message
- Quiet hours: no reminders between 11PM-7AM (default). /quiethours to change
- Auto carry-forward: at midnight, overdue tasks move to today automatically
- Follow-up reminders show urgency: 🔵 first, 🟡 repeat, 🔴 urgent
- /quiethours — view/change quiet hours. /quiethours off to disable
- /settings — view all your preferences at a glance
- /interval <minutes> — change how often overdue tasks are re-reminded
- Max reminders cap (default 5 per task, then stops nagging)
- reminder_count tracks how many times each task was reminded

New DB: user_preferences table (quiet_start, quiet_end, interval, max_reminders)
New column: tasks.reminder_count
New scheduler jobs: check_followups (every 5 min), daily_carry_forward (midnight)
Modified: main.py, database.py, scheduler.py

---

## v1.2 — Overdue Task Handling + Deadline Warnings + Tags
Phase 1 completion — the bot now tracks time and warns you proactively.

Added:
- /overdue — list all overdue tasks with red indicators
- /deadlines — show tasks due in the next 3 days with urgency labels
- /carryforward — move all overdue tasks to today in one command
- /tag <id> <tags> — add searchable tags to any task
- /tagged <tag> — find all tasks with a specific tag
- Overdue tasks marked with ⏰ OVERDUE in all task lists
- Automatic deadline warnings every hour (tasks due today get flagged)
- Automatic overdue notifications (summarizes what you missed)
- Tasks lists now show urgency: 🔴 TODAY, 🟡 1d left, 🟢 2d+ left
- Tags stored in database, searchable by keyword

New DB column: tags
New functions: get_overdue_tasks, get_upcoming_deadlines, set_tags,
  get_tasks_by_tag, carry_forward_overdue
Modified: main.py, database.py, scheduler.py

---

## v1.1 — Snooze / Postpone / Pause + Persistent Reminder Buttons
Phase 1 of the roadmap — making reminders actionable instead of ignorable.

Added:
- Inline buttons on every reminder: ✅ Done, ⏰ Snooze 10m, 🕐 Snooze 1h, 📅 Tomorrow
- Tapping a button acts instantly (no typing needed)
- Snooze: temporarily silences a reminder, re-fires after the chosen delay
- Postpone: moves a task to tomorrow in one tap
- /pause <id> — stop all reminders for a task without deleting it
- /resume <id> — turn reminders back on
- /paused — list all paused tasks
- Scheduler now respects paused flag and snooze_until timestamp
- last_reminded tracking (groundwork for v2.0 escalation)

New DB columns: paused, snooze_until, last_reminded
New functions: snooze_task, postpone_task, pause_task, resume_task, mark_reminded, get_paused_tasks
Modified: main.py (inline buttons, handle_callback, pause/resume/paused commands),
          scheduler.py (pause + snooze aware), database.py

---


## v1.0 — Debug & Bug-Tracking System
Built the debugging foundation FIRST, as the roadmap recommends, before
adding more features. This makes every future version easier to test and fix.

Added:
- /debug — toggle debug mode (shows detected intent + entities + parsed date/time inline after each message)
- /report <description> — report a bug; auto-captures your last message and what the bot understood
- /bugs — list all open bug reports
- /resolve <id> — mark a bug resolved
- /trace — show the last AI interaction in detail (input, intent, entities, reply)
- /selftest — get the full test-message checklist to run through
- Automatic exception logging — every crash is auto-saved to bugs.db with full traceback and context
- Separate bugs.db database so debug data never touches your task data
- Interaction history stored (last 50 per user) for tracing

New file: debug_system.py
Modified: main.py (wired in all debug commands + auto exception logging + debug output)

---

## Planned Versions (from roadmap)

- v1.1 — Snooze/Postpone/Pause + persistent reminder buttons (Done/Snooze/Postpone)
- v1.2 — Overdue task handling + deadline warnings + tags
- v2.0 — Passive PA: remind until done, escalate near deadline, carry forward unfinished
- v2.1 — Quiet hours + reminder batching
- v3.0 — Vague time understanding ("later", "evening", "soon") + smarter clarification
- v4.0 — Daily/weekly planner + task breakdown into subtasks
- v5.0 — Habit engine: streaks, missed tracking, active-hours-only
- v6.0 — Preference learning: preferred times, tone, active/sleep hours
- v7.0 — Follow-up intelligence: ask if done, detect repeated snoozes
- v8.0 — Proactive suggestions: deadlines, subtasks, break reminders
- v9.0 — Dashboards: morning briefing, evening review, weekly reports
- v10.0 — Advanced: calendar, location, voice notes, attachments

---

# 🗺️ Planned Roadmap

Everything below is planned but NOT yet built. Listed in rough priority order.

---

## v12.0 — Voice Notes
- Accept Telegram voice messages
- Transcribe via Whisper (on-device or via API)
- Treat transcript as regular text input — create tasks from voice
- Show transcript before acting so user can confirm

## v12.1 — Task Dependencies
- "Task B depends on Task A" — B's reminder only fires after A is done
- `/depends <task_b_id> <task_a_id>` command
- Visual chain in task list: "→ unblocked by [5]"
- Existing `parent_task_id` column in tasks table is the foundation

## v12.2 — Location-Based Reminders
- "Remind me to buy milk when I'm near a grocery store"
- Uses Telegram's location-sharing feature
- Geofence check runs in the reminder scheduler
- Requires user to share live location

## v12.3 — Personalized Briefing Times
- v6.0 already collects active-hours data
- Instead of fixed 08:00 morning briefing, send it at the user's actual wake-up hour
- Inferred from `interaction_log` timestamps

## v12.4 — Bulk Task Import
- Paste a numbered/bulleted list of tasks
- BAKA parses all of them in one AI call
- Presents a confirmation of all detected tasks before saving
- Handles: "1. Call dentist\n2. Buy groceries\n3. Pay rent" etc.

## v12.5 — Named Goal Milestones + Task Linking
- Goals can have named milestones: "Read 4/12 books" → "Q1 done"
- Individual tasks can be linked to a goal: completing the task ticks progress
- ai_observations table already supports the action_type hook for this

---

## v13.0 — GLM 5.2 Upgrade (when available)
- MODEL_MAIN = "z-ai/glm-5.2" (constant already in baka_brain.py)
- Benchmark both 5.1 and 5.2 side-by-side using the v11.1 analytics
- Switch when 5.2 shows clearly better intent accuracy

## v13.1 — Fast Routing Enabled
- Set ENABLE_FAST_ROUTING = True in baka_brain.py
- Llama 3.1 8B handles simple intent pre-classification
- If confidence ≥ 0.8 → skip GLM call entirely (saves 70% of API calls)
- Fallback to GLM for anything ambiguous
- Analytics will measure the actual savings

## v13.2 — /replay Command
- Full debug timeline for any interaction by timestamp
- Pulls from: ai_usage table, missed_capabilities, interaction_log, debug_system
- Shows: what user sent → parser result → AI intent → entities → action taken
- Foundation already in analytics/ logging

## v13.3 — /export_usage
- Export ai_usage table as CSV or JSON
- Analytics query infrastructure already exists in usage_service.py
- Just needs the command + file creation
- 30-line implementation

---

## v14.0 — Multi-User Mode
- Currently all features work per-user via user_id scoping in DB
- But the admin panel is single-user
- Multi-user would add: per-user API key, per-user preferences panel, user management
- Non-trivial but the data model already supports it

## v14.1 — Pomodoro Mode
- `/pomodoro <task_id>` starts a 25-min focus timer
- Bot sends "Focus started on: Study Physics"
- After 25 min: "Time! Take a 5-min break."
- Logs focus sessions to a new `pomodoro_log` table
- Integrates with productivity dashboard

## v14.2 — AI Weekly Insights
- Every Sunday, GLM 5.2 analyzes the week's ai_usage + completions data
- Generates a natural-language productivity narrative
- "You were most productive on Wednesday evenings. Physics tasks take you ~2hrs. Consider scheduling them before 8pm."
- More personal than the /insights command (which is pattern-based, not narrative)

## v14.3 — Themes / Personalities
- User can switch BAKA's communication style:
  - `baka mode strict` — no fluff, just facts
  - `baka mode friendly` — warm, emoji-heavy
  - `baka mode motivator` — hype-forward
  - `baka mode sarcastic` — roast mode
- Stored in user_preferences, applied in think_freely() system prompt

---

## Future Integrations (No timeline yet)

- **Calendar sync** — Google Calendar two-way sync
- **Email integration** — "did I get a reply from them yet?" (Gmail via OAuth)
- **Notion/Obsidian** — export tasks as notes
- **Spotify/music** — "play study playlist" (via Telegram MusicBot API)
- **Streak heatmap** — GitHub-style year view of completed tasks per day
- **Claude/Gemini fallback** — if NVIDIA NIM is down, route through another provider
  (analytics provider column already supports this — just add the client init)