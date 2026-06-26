# BAKA Bot — Version History

## v5.0 — Habit Engine (current)
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