# JARVIS Bot — Version History

## v2.0 — Passive PA: Remind Until Done + Escalation + Quiet Hours (current)
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