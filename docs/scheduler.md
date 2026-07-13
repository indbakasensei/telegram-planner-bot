# Scheduler

The scheduler is two things working together: `scheduler.py`'s query
helpers (pure functions that decide *which* tasks need attention), and PTB's
`job_queue`, registered inline in `main.py`'s `main()`, which decides
*when* to call them.

## `scheduler.py` functions

### `get_due_tasks()`
Called by the `check_reminders` job (every 60s). Runs five separate SQL
queries and de-duplicates by task ID:
1. **One-time tasks** due within the last `LOOKBACK_MINUTES` (5) minutes,
   not yet reminded today (guards against firing every minute)
2. **Daily recurring** tasks whose time-of-day falls in the lookback window
3. **Weekly recurring** tasks — same, plus `recurrence_weekday` match
4. **Monthly recurring** tasks — same, plus `recurrence_day` match
5. **Snoozed tasks** whose `snooze_until` has passed — fired regardless of
   `last_reminded` (a deliberate bug fix: a snooze can be set *after* the
   original `last_reminded` timestamp, so gating on `last_reminded` alone
   missed re-fires). `snooze_until` is cleared immediately after firing to
   prevent re-firing every minute.

The 5-minute lookback window exists specifically to catch reminders missed
during a bot restart or a busy event loop.

### `get_tasks_needing_followup()`
Called by the `check_followups` job (every 300s). Finds overdue,
non-recurring tasks and, per task, checks:
- `is_quiet_hours(uid)` — skip if true
- `reminder_count >= prefs["max_reminders"]` — skip if the cap is hit
- `should_remind_again(last_reminded, interval)` — skip if too soon

The interval itself is computed by `get_escalated_interval()`, which
shortens as a deadline approaches (≤60 min left → 5 min interval; ≤180 min
→ 10 min) or as `reminder_count` climbs (escalates from the user's base
interval down to a 10-minute floor).

### `auto_carry_forward()`
Called by the `daily_carry_forward` job (00:05 daily). Iterates every known
user ID and calls `database.carry_forward_overdue(uid, today)`, moving
overdue non-recurring tasks onto today's date.

### `is_quiet_hours(user_id)`
Reads `quiet_start`/`quiet_end` from `user_preferences` (via
`database.get_user_prefs`). Handles the overnight-wraparound case
(`start > end`, e.g. 23:00–07:00) as well as the same-day case. Returns
`False` (quiet hours disabled) when `start == end`.

## Scheduled jobs (registered in `main.py`'s `main()`)

| Job | Interval | Purpose | Respects quiet hours? |
|---|---|---|---|
| `check_reminders` | 60s | Primary due-task pings (Done/Snooze/Tomorrow/Stop/Delete buttons) | **No** — see [DEBUGGING.md](../DEBUGGING.md#known-issues) |
| `check_followups` | 300s | Escalating re-reminders for overdue tasks, batched if >1 pending | **No** — see [DEBUGGING.md](../DEBUGGING.md#known-issues) |
| `daily_carry_forward` | 00:05 daily | Moves overdue tasks to today | n/a |
| `check_did_you_finish` | 900s | "Did you finish?" follow-up 15 min after a task's time passes | Yes |
| `end_of_day_summary` | 21:00 daily | Evening Review digest | Yes |
| `wellness_reminder` | 900s check / per-user interval gate | Opt-in water/break/eye nudges | Yes |
| `priority_nudge` | 1800s | One-time heads-up for high-priority tasks due within 3h | Yes |
| `morning_briefing` | 08:00 daily | Today's priorities, deadlines, overdue, goals | Yes |
| `weekly_report` | Sunday 20:00 | Weekly digest | Yes |
| `deadline_buffer_check` | 1800s | Staged 7d/3d/1d/6h/1h pre-deadline warnings | Yes |
| `observation_engine` | 22:00 daily | AI-generated daily suggestions → `ai_observations` | Yes |
| `project_nudge` | 20:00 daily | v12.0 stagnation/urgent project alerts | Yes |
| `check_deadlines` | 3600s | Legacy overdue + today-deadline check | Yes |

`check_deadlines` is the one job that bypasses `database.py`, using a raw
`sqlite3.connect("planner.db")` directly — see
[DEBUGGING.md](../DEBUGGING.md#known-issues).

## Recurrence & duplicate prevention

Recurrence type/weekday/day-of-month live directly on the `tasks` row
(`recurrence_type`, `recurrence_weekday`, `recurrence_day`) — there's no
separate recurrence table. Duplicate-firing prevention differs by case:
one-time and recurring tasks compare `last_reminded` against the current
date (one-time) or a 20-hour-back timestamp (recurring, so a daily task
can't double-fire within the same day but will fire again the next); snoozed
tasks clear `snooze_until` immediately after firing.

See also [docs/reminders.md](reminders.md) for the user-facing behavior
this produces, and [docs/database.md](database.md) for the relevant `tasks`
columns.
