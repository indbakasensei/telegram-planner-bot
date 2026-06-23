# JARVIS Bot — Version History

## v1.0 — Debug & Bug-Tracking System (current)
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