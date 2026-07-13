# Reminders

User-facing behavior of the reminder system. For the underlying query
mechanics, see [docs/scheduler.md](scheduler.md).

## How a reminder fires

Every 60 seconds, `check_reminders` calls `scheduler.get_due_tasks()`
and sends a `reminder_card` (see [docs/dashboard.md](dashboard.md)) for
each due task, with buttons: ✅ Done · ⏰ Snooze 10m · 🕐 Snooze 1h ·
📅 Tomorrow · 🔕 Stop · 🗑 Delete.

If a reminder isn't acted on, `check_followups` (every 5 min) re-sends it
with escalating frequency as the deadline approaches, up to a per-user cap
(`max_reminders`, default 5). Three or more overdue tasks get batched into
a single follow-up message instead of spamming one per task.

## Snooze, pause, stop

- **Snooze** (`/snooze <id> <minutes>` or the 10m/1h buttons) — sets
  `snooze_until`; the reminder re-fires once that time passes, then
  `snooze_until` is cleared automatically
- **Pause** (`/pause <id>`) — stops reminders without deleting the task;
  `/resume` turns them back on; `/paused` lists everything currently paused
- **Stop** (🔕 button or `/stopreminder <id>`) — stops reminders for a task
  permanently without deleting it (distinct from pause, which is meant to
  be temporary — the practical DB effect may be the same flag; see
  `database.py`'s `stop_reminders()` if the exact semantic difference
  matters for a change you're making)

## Recurrence

Daily/weekly/monthly recurring tasks (and habits, which are tasks with
`is_habit=1`) re-fire on their schedule automatically — see
[docs/scheduler.md](scheduler.md#recurrence--duplicate-prevention) for the
exact matching logic and how double-firing is prevented.

## Deadline buffer warnings (v10.1) — distinct from plain reminders

Tasks with deadline phrasing ("due by", "submit by", "tak karna hai", ...)
get `is_deadline=1` and a separate warning track: staged alerts at
**7 days, 3 days, 1 day, 6 hours, and 1 hour** before the deadline, each
with its own button set (✅ Done now · 🔨 Break down · 📅 Plan today ·
🔕 Mute buffers). This is checked by the `deadline_buffer_check` job every
30 minutes, independent of the regular `check_reminders`/`check_followups`
cycle. Each buffer level fires exactly once per task (tracked in the
comma-separated `buffer_sent` column) — toggle a task in/out of deadline
mode with `/deadline <id> [on|off]`.

Detection is two-layered: `date_parser.py`'s regex catches deadline
phrasing deterministically, and the AI also returns an `is_deadline` field
independently — either one triggering is enough to enable deadline mode.

## Quiet hours

Set via `/quiethours <start> <end>` (or `/quiethours off` to disable).
Nearly every proactive job checks `is_quiet_hours()` before sending
anything — **with two exceptions**, `check_reminders` and
`check_followups`, which currently fire regardless of quiet hours. See
[DEBUGGING.md](../DEBUGGING.md#known-issues) for whether this is
intentional.

## Stagnation nudges (v12.0, projects only)

Separate from task/habit reminders entirely — the `project_nudge` job
(daily 20:00) checks each active project (a goal with materials/worklog
rows) for two conditions: deadline within 3 days with materials still
missing (urgent alert), or no worklog entry in 7+ days with a deadline
still 30+ days out (gentle nudge). Respects quiet hours. See
[CHANGELOG.md](../CHANGELOG.md#v120--project-management-current) for the
full feature.

## Wellness & priority nudges (v8.0) — opt-in, not task-specific

Not tied to any single task. `wellness_reminder` (opt-in, default off) — 💧
water / 🧘 break / 👀 eye-rest / 🪑 posture nudges on a per-user interval.
`priority_nudge` — a one-time heads-up when a high-priority task is due
within 3 hours. Both respect quiet hours and awake-hours gating.
