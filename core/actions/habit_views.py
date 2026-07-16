"""
habit_views.py -- Offline Engine actions: the three read-only habit
views (v14.9, Habit domain Stage 1 -- the first non-Task domain).

One module for three views, deliberately (same reasoning as
lifecycle_task.py's grouping): all three are read-only single-fetch
renders, and two of them (streak, habitlog) share an identical
locate -> is_habit-guard -> read-log -> render skeleton. Verified
against Legacy before writing (v14.9 Phase 0):

  habits list   main.py habits_cmd()      exact phrases ("habits",
                                          "show habits", "my habits",
                                          "list habits") -> QUERY_TASK
  streak view   main.py streak_cmd()      "streak <id>" -> QUERY_TASK
  habit log     main.py habitlog_cmd()    "habitlog <id>" /
                                          "habit log <id>" -> EDIT_TASK
                                          (Tier 0 groups it there;
                                          read-only despite the intent)

Verified NOT to exist in Legacy, documented rather than invented (same
discipline as v14.7's archive/restore finding): habit-specific update,
delete, today view, search, statistics, archive/restore. Creation
(/addhabit + the AI HABIT flow), skip (/skiphabit -> reset_streak) and
completion (done_task()'s habit branch) are write operations -- later
Habit stages, not Stage 1.

Rendering note (unavoidable, documented difference -- DEBUGGING.md):
Legacy's habit handlers still send parse_mode="Markdown" with raw,
unescaped titles -- they were never migrated in v7.1's HTML switch, so
a habit title containing '*' or '_' corrupts in Legacy. These actions
render the same content as Telegram HTML through fmt.py's escaping
helpers (the project-wide convention), so byte-equality with Legacy's
reply markup is impossible by design; equivalence here means same
fields, same lines, same conditionals, same emoji.

Error paths (not-a-habit, missing id) return success=False with the
Legacy-equivalent message; main.py's integration point replies only on
success, so these fall through to Legacy, which produces the same
reply -- identical UX, and the offline result is still asserted in
tests. Id-less or malformed phrasings ("streak", "habitlog abc") don't
match the entry regexes at all and fall through to Legacy's usage
replies, exactly like v14.7's id-less lifecycle phrasings.

Read-only: no writes, no conversation state, no learning logs.
Storage Facade only (core/storage/), never database.py directly.
"""
from __future__ import annotations

import re

from datetime import timedelta

from fmt import b, esc, i
from core.offline.action_result import ActionResult
from core.offline.request_context import RequestContext
from core.storage import Storage

# Mirrors core/intent/rules.py's ("habits", "show habits", "my habits",
# "list habits") QUERY_TASK exact group, verbatim -- same accepted
# phrase-mirror duplication as every other view (DEBUGGING.md).
HABITS_VIEW_PHRASES = ("habits", "show habits", "my habits", "list habits")

# Entry regexes use \s+ between words, matching the style of
# complete_task/lifecycle_task's entry regexes (marginally more
# generous than Legacy's single-space prefix match; a phrase like
# "habit  log 5" matches here but falls to AI in Legacy -- same
# accepted nuance as the existing action regexes).
_STREAK_RE = re.compile(r"^streak\s+(\d+)\b", re.IGNORECASE)
_HABITLOG_RE = re.compile(r"^(?:habitlog|habit\s+log)\s+(\d+)\b", re.IGNORECASE)


def match_streak_command(text: str) -> int | None:
    """Returns the habit_id, or None if this isn't a recognized
    "streak <id>" phrase (id-less "streak" is Legacy-only: its usage
    reply needs no data access)."""
    m = _STREAK_RE.match(text.strip())
    return int(m.group(1)) if m else None


def match_habitlog_command(text: str) -> int | None:
    """Returns the habit_id, or None if this isn't a recognized
    "habitlog <id>" / "habit log <id>" phrase."""
    m = _HABITLOG_RE.match(text.strip())
    return int(m.group(1)) if m else None


def _recurrence_label(rec: str | None, weekday: int | None) -> str:
    """Replicates habits_cmd()'s rec_label expression exactly,
    including its fallback chain for non-daily/non-weekly values."""
    if rec == "daily":
        return "daily"
    if rec == "weekly":
        return f"weekly (day {weekday})"
    return rec or "—"


def habits_list(context: RequestContext, storage: Storage) -> ActionResult:
    """All active habits with streak summary -- main.py habits_cmd()
    equivalent (one get_habits() read; paused/done habits excluded by
    the query itself, same as Legacy)."""
    habits = storage.habits.get_all(context.user_id)
    if not habits:
        examples = [i("'I want to run every day at 6 AM'"),
                    i("'addhabit Drink water hourly'"),
                    i("'gym every monday at 7 AM'")]
        return ActionResult(
            success=True,
            message=(f"🌱 {b('No habits yet!')}\n\n"
                     "Start one with:\n" + "\n".join(examples)),
            data=habits,
        )
    lines = [f"🌱 {b(f'Your Habits ({len(habits)})')}", ""]
    for h in habits:
        hid, title, dtime, rec, weekday, streak, longest, last_done, start = h
        streak = streak or 0
        fire = "🔥" * min(streak, 5) if streak > 0 else "○"
        lines.append(f"{b(f'[{hid}]')} {esc(title)}")
        lines.append(f"   {fire} Streak: {b(str(streak))} | Best: {longest or 0}")
        lines.append(f"   ⏰ {esc(dtime or 'flexible')} • {esc(_recurrence_label(rec, weekday))}")
        if last_done:
            lines.append(f"   Last done: {esc(last_done)}")
        lines.append("")
    lines.append(f"{i('Mark done daily to build streaks!')}")
    lines.append("Use /streak <id> for details.")
    return ActionResult(success=True, message="\n".join(lines), data=habits,
                         metadata={"count": len(habits)})


def streak_detail(habit_id: int, context: RequestContext,
                   storage: Storage) -> ActionResult:
    """Detailed streak view for one habit -- main.py streak_cmd()
    equivalent, including its quirks (verified, replicated, not fixed):
    the double lookup (get_task_by_id + is_habit first, then a second
    fetch through get_habits), and the resulting 'Habit not found or
    paused.' reply for a habit that exists but is paused (get_habits
    filters paused=0). The 14-day grid uses context.now, never the
    system clock."""
    task = storage.tasks.get_by_id(habit_id, context.user_id)
    if not task or not storage.habits.is_habit(habit_id):
        return ActionResult(
            success=False,
            message="❌ That's not a habit. Use /habits to see them.",
            warnings=["not_a_habit"],
        )
    if context.now is None:
        return ActionResult(success=False, message="", warnings=["missing_now"])

    log = storage.habits.get_log(habit_id, context.user_id, days=14)
    missed = storage.habits.get_missed_days(habit_id, context.user_id, days=14)
    habits = [h for h in storage.habits.get_all(context.user_id) if h[0] == habit_id]
    if not habits:
        return ActionResult(
            success=False, message="Habit not found or paused.",
            warnings=["habit_not_visible"],
        )
    _, title, dtime, rec, weekday, streak, longest, last_done, start = habits[0]
    streak = streak or 0
    longest = longest or 0

    lines = [f"🌱 {b(title)}", ""]
    lines.append(f"🔥 Current streak: {b(f'{streak} day' + ('s' if streak != 1 else ''))}")
    lines.append(f"🏆 Longest streak: {b(f'{longest} day' + ('s' if longest != 1 else ''))}")
    lines.append(f"📅 Started: {esc(start or '?')}")
    if last_done:
        lines.append(f"✅ Last done: {esc(last_done)}")
    lines.append(f"\n{b('Last 14 days:')}")

    today = context.now.date()
    logged_dates = {row[0] for row in log if row[1]}
    bar = ""
    for offset in range(13, -1, -1):
        day = today - timedelta(days=offset)
        bar += "🟩" if day.strftime("%Y-%m-%d") in logged_dates else "⬜"
    lines.append(bar)

    if missed:
        lines.append(f"\n⚠️ Missed {len(missed)} day(s) in this window.")
        if len(missed) >= 3:
            lines.append(f"💡 {i('Tip: try changing the time or making it easier.')}")

    return ActionResult(
        success=True, message="\n".join(lines), data=habits,
        metadata={"habit_id": habit_id, "streak": streak, "missed": len(missed)},
    )


def habit_log_view(habit_id: int, context: RequestContext,
                    storage: Storage) -> ActionResult:
    """30-day completion history for one habit -- main.py
    habitlog_cmd() equivalent, including its Legacy-verified details:
    the empty-log case is a real answer (success), and entries render
    ✅/❌ by the log row's `completed` flag, capped at 30 lines."""
    task = storage.tasks.get_by_id(habit_id, context.user_id)
    if not task or not storage.habits.is_habit(habit_id):
        return ActionResult(
            success=False, message="That's not a habit.",
            warnings=["not_a_habit"],
        )
    log = storage.habits.get_log(habit_id, context.user_id, days=30)
    if not log:
        return ActionResult(
            success=True,
            message=f"No log entries yet for {b(task[1])}.",
            data=log,
        )
    lines = [f"📊 {b(f'Log for {task[1]}')} (last 30 days)", ""]
    for log_date, completed in log[:30]:
        lines.append(f"{'✅' if completed else '❌'} {esc(log_date)}")
    return ActionResult(success=True, message="\n".join(lines), data=log,
                         metadata={"habit_id": habit_id, "entries": len(log)})
