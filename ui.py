"""
ui.py — v9.0 UI Component System, migrated onto the Phase-0 component
library in UI Phase 1 (UI_SPEC_v1.md §15).

Pure presentation layer. Every function returns either an HTML string or
a (text, InlineKeyboardMarkup) tuple. NO database access, NO business
logic — callers pass in already-fetched data.

Phase 1 rules honored here (tests/test_ui_cards.py pins them):
- Every field, every button label, and every callback_data is
  byte-identical to the pre-migration cards. The only visible delta is
  spec-required typography from the shared components (§5.1 uppercase
  H1 titles) — explicitly permitted by the Phase 1 brief.
- Formerly-local formatting primitives (progress bar, priority dots,
  recurrence icons) now delegate to ui_components — the mappings have
  exactly one owner.
- Fixed keyboards are built with ui_components' checked builders
  (action_row/nav_row/keyboard). The goal and habit keyboards grow one
  row PER ITEM with no cap (pre-existing behavior), so they can exceed
  keyboard()'s §5.7 twelve-button design cap with real data — they use
  uic.button() (64-byte check) with a direct InlineKeyboardMarkup,
  byte-preserving today's behavior; their §6.2-compliant pagination is
  Phase 3/4's job, not Phase 1's.
- Empty-state wording is unchanged (the §14 canonical copy swap happens
  when each screen is redesigned in Phases 2–8, not during migration).
"""
from telegram import InlineKeyboardMarkup

from fmt import b, i, code, esc
import ui_components as uic

# ── Primitives (delegating to the component library, Phase 1) ─────────────

def progress_bar(percent, width=10):
    """Render a text progress bar: ▓▓▓▓▓░░░░░ 50%  (delegates to
    ui_components.progress_indicator — byte-identical output)."""
    return uic.progress_indicator(percent or 0, width)


def priority_dot(priority):
    return uic.priority_dot(priority)


def recurrence_icon(recurrence):
    return uic.RECURRENCE_ICONS.get(recurrence, "")


def section(title, emoji=""):
    prefix = f"{emoji} " if emoji else ""
    return f"{prefix}{uic.subheader(title)}"


# ── Cards ─────────────────────────────────────────────

def _dashboard_status_level(data: dict):
    """Status-card level + headline, deterministic from the counters
    (UI_SPEC_v1.md §5.4: one status level per message, worst wins)."""
    overdue = data.get("overdue")
    today_count = data.get("today_count")
    if overdue:
        return "warning", f"{overdue} overdue"
    if today_count:
        return "info", f"{today_count} due today"
    return "success", "All clear"


def _dashboard_motivation(pct: float) -> str:
    """Short motivational status for the productivity card (Phase 2
    brief) — deterministic tiers, presentation only."""
    if pct >= 80:
        return "Crushing it — keep the streak alive!"
    if pct >= 50:
        return "Good pace — keep going."
    if pct > 0:
        return "Warming up — one task at a time."
    return "Fresh start — pick one task."


def dashboard_card(data: dict):
    """
    Central hub, redesigned in UI Phase 2 (UI_SPEC_v1.md §15) as the
    primary navigation hub. `data` keys (all optional, dashboard adapts
    to what exists): date_str, pending, overdue, upcoming, today_count,
    done_today, goals, habits, completion_rate, streak_best.
    Returns (text, InlineKeyboardMarkup).

    Phase 2 constraints honored (tests/test_ui_cards.py pins them):
    every pre-redesign field renders in the same format; the callback
    set is EXACTLY the pre-redesign six (dash:today/tasks/goals/habits/
    stats/home) — the brief's prescribed ➕ Add Task / 🤖 AI /
    ⚙ Settings / ❓ Help buttons have no existing callbacks, and new
    callbacks/handler branches are forbidden this phase, so those slots
    are deferred to Phases 3/5/8 (documented in CHANGELOG). Labels are
    §7-canonical ("📊 Statistics"); the root page carries Refresh-only
    navigation per §2.5.
    """
    date_str = data.get("date_str")
    cap = ("Today's productivity overview"
           + (f" · {date_str}" if date_str else ""))
    header = uic.render_header("home", "BAKA Dashboard", caption_text=cap)

    blocks = []

    # ── Status card: 2×2 counters + goals/habits lines ──
    row_top, row_bottom = [], []
    if data.get("today_count") is not None:
        row_top.append(f"📅 Today: {b(data['today_count'])}")
    if data.get("overdue") is not None:
        row_top.append(f"⚠️ Overdue: {b(data['overdue'])}")
    if data.get("pending") is not None:
        row_bottom.append(f"📋 Pending: {b(data['pending'])}")
    if data.get("done_today") is not None:
        row_bottom.append(f"✅ Done today: {b(data['done_today'])}")

    status_lines = []
    if row_top:
        status_lines.append("  ·  ".join(row_top))
    if row_bottom:
        status_lines.append("  ·  ".join(row_bottom))
    if data.get("goals"):
        status_lines.append(f"🎯 {b('Goals')}: {len(data['goals'])} active")
    if data.get("habits"):
        best = data.get("streak_best", 0)
        status_lines.append(f"🌱 {b('Habits')}: {len(data['habits'])} active"
                            + (f" · 🔥 best streak {best}" if best else ""))

    if status_lines:
        level, headline = _dashboard_status_level(data)
        blocks.append(uic.render_status_card(level, headline,
                                              "\n".join(status_lines)))
    else:
        blocks.append(i("Nothing tracked yet. Add a task to get started!"))

    # ── Productivity card ──
    if data.get("completion_rate") is not None:
        rate = data["completion_rate"]
        pct = rate * 100 if rate <= 1 else rate
        card = uic.render_statistics_card(
            "Productivity", [("Completion", f"{int(pct)}%")],
            progress_percent=pct)
        blocks.append(f"{card}\n{uic.caption(_dashboard_motivation(pct))}")

    text = uic.render_page(header, *blocks)

    keyboard = uic.keyboard(
        uic.action_row(("📅 Today", "dash:today"),
                        ("🎯 Goals", "dash:goals"),
                        ("🌱 Habits", "dash:habits")),
        uic.action_row(("📋 Tasks", "dash:tasks"),
                        ("📊 Statistics", "dash:stats")),
        uic.nav_row(refresh_cb="dash:home"),
    )
    return text, keyboard


def task_card(task, show_actions=True):
    """
    Rich single-task card. `task` is the DB tuple:
      (id, title, due_date, due_time, category, priority, done, recurrence_type)
    or a dict with those keys. Returns (text, InlineKeyboardMarkup|None).
    """
    if isinstance(task, dict):
        tid = task.get("id")
        title = task.get("title")
        ddate = task.get("due_date")
        dtime = task.get("due_time")
        category = task.get("category", "General")
        priority = task.get("priority", "medium")
        done = task.get("done", 0)
        recurrence = task.get("recurrence_type")
    else:
        tid = task[0]
        title = task[1]
        ddate = task[2] if len(task) > 2 else None
        dtime = task[3] if len(task) > 3 else None
        category = task[4] if len(task) > 4 else "General"
        priority = task[5] if len(task) > 5 else "medium"
        done = task[6] if len(task) > 6 else 0
        recurrence = task[7] if len(task) > 7 else None

    # KNOWN QUIRK, preserved (v9.0, found + documented in Phase 3 --
    # DEBUGGING.md): the real caller (dash:task -> get_task_by_id)
    # passes a 7-tuple whose index 6 is recurrence_type, not `done` --
    # so a RECURRING task's detail view renders as completed (✅, no
    # action buttons) in production. Phase 3 is presentation-only and
    # replicates it; the fix (widening get_task_by_id or reindexing)
    # is a behavior change deferred to the Board.
    dot = "✅" if done else priority_dot(priority)
    rec = recurrence_icon(recurrence)
    rec_s = f" {rec}" if rec else ""

    header = uic.render_header("task", f"Task {tid}")
    title_line = f"{dot} {b(title)}{rec_s}"
    info_rows = []
    if ddate:
        info_rows.append(("📅 Due", ddate))
    if dtime:
        info_rows.append(("⏰ Time", dtime))
    info_rows.append(("🏷 Category", category))
    info_rows.append((f"{priority_dot(priority)} Priority", priority))
    body = f"{title_line}\n{uic.render_information_card('Details', info_rows)}"
    # Richer detail fields (tags, subtasks, reminder/deadline state) are
    # NOT in the 7-column row the handler passes; rendering them would
    # need a wider database read -- deferred, documented in CHANGELOG.
    text = uic.render_page(header, body)

    if not show_actions or done:
        return text, None

    keyboard = uic.keyboard(
        uic.action_row(("✅ Done", f"done:{tid}"),
                        ("⏰ Snooze", f"snooze:{tid}:30"),
                        ("📅 Tomorrow", f"postpone:{tid}")),
        uic.action_row(("✏️ Edit", f"dash:edit:{tid}"),
                        ("🗑 Delete", f"deltask:{tid}"),
                        ("« Back", "dash:tasks")),
    )
    return text, keyboard


def today_card(groups: dict, date_str=""):
    """
    Grouped today view. `groups` keys: overdue, high, upcoming, done — each a
    list of task tuples. Returns (text, InlineKeyboardMarkup).
    """
    header = uic.render_header("date", "Today",
                                caption_text=date_str or None)
    lines = []

    def render_group(title, emoji, tasks, show_time=True):
        out = []
        if tasks:
            out.append(section(f"{title} ({len(tasks)})", emoji))
            for t in tasks[:8]:
                dot = priority_dot(t[5] if len(t) > 5 else "medium")
                tm = f" ⏰ {esc(t[3])}" if show_time and len(t) > 3 and t[3] else ""
                out.append(f"  {dot} {code('['+str(t[0])+']')} {esc(t[1])}{tm}")
            out.append("")
        return out

    lines += render_group("Overdue", "⚠️", groups.get("overdue", []))
    lines += render_group("High Priority", "🔴", groups.get("high", []))
    lines += render_group("Upcoming", "📋", groups.get("upcoming", []))

    done = groups.get("done", [])
    if done:
        lines.append(section(f"Completed ({len(done)})", "✅"))
        for t in done[:5]:
            lines.append(f"  ✅ <s>{esc(t[1])}</s>")
        lines.append("")

    total = sum(len(groups.get(k, [])) for k in ("overdue", "high", "upcoming"))
    if total == 0 and not done:
        # Phase 3: the §14 canonical empty state (approved wording).
        lines.append(uic.empty_today())

    text = uic.render_page(header, "\n".join(lines).rstrip())
    keyboard = uic.keyboard(
        uic.nav_row(refresh_cb="dash:today", home_cb="dash:home"))
    return text, keyboard


def task_list_card(tasks, title="Your Tasks", page_cb="dash:tasks"):
    """List of tasks, each tappable to open its task_card. Shows the
    first 10 (pre-existing slice; §6.2 pagination buttons would need
    new pg: callbacks -- forbidden this phase, deferred)."""
    shown = min(len(tasks), 10)
    cap = (f"{shown} of {len(tasks)} tasks" if len(tasks) > 10
           else f"{len(tasks)} task{'s' if len(tasks) != 1 else ''}") if tasks else None
    header = uic.render_header("list", title, caption_text=cap)
    lines = []
    rows = []
    if not tasks:
        # Phase 3: the §14 canonical empty state (approved wording).
        lines.append(uic.empty_tasks())
    else:
        for t in tasks[:10]:
            dot = priority_dot(t[5] if len(t) > 5 else "medium")
            rec = recurrence_icon(t[7] if len(t) > 7 else None)
            rec_s = f" {rec}" if rec else ""
            meta = []
            if len(t) > 2 and t[2]:
                meta.append(esc(t[2]))
            if len(t) > 3 and t[3]:
                meta.append(esc(t[3]))
            metatxt = f" <i>· {' · '.join(meta)}</i>" if meta else ""
            lines.append(f"{dot} {code('['+str(t[0])+']')} {esc(t[1])}{rec_s}{metatxt}")
            rows.append([uic.button(f"{dot} {t[1][:28]}", f"dash:task:{t[0]}")])
    rows.append(uic.nav_row(refresh_cb=page_cb, home_cb="dash:home"))
    return uic.render_page(header, "\n".join(lines)), InlineKeyboardMarkup(rows)


def goal_card(goals, date_str=""):
    """
    Goals dashboard. `goals` is a list of tuples:
      (id, title, deadline, progress[, target])
    Returns (text, InlineKeyboardMarkup).

    Keyboard note: one 3-button row per goal with no cap (pre-existing
    behavior) — assembled directly, not via uic.keyboard(), since real
    data can exceed the §5.7 twelve-button design cap; pagination is
    Phase 3b's job.
    """
    cap = (f"{len(goals)} active goal{'s' if len(goals) != 1 else ''}"
           if goals else None)
    header = uic.render_header("goal", "Goals", caption_text=cap)
    lines = []
    rows = []
    if not goals:
        # Copy kept verbatim (Phase 4): UI_SPEC §14 has no approved
        # Goals empty state, and inventing copy is forbidden -- a §14
        # addition is a spec-revision item (CHANGELOG).
        lines.append(i("No goals yet. Tell me something you're working toward!"))
        lines.append("")
        lines.append("<i>e.g. \"I want to read 12 books this year\"</i>")
    else:
        for g in goals:
            gid = g[0]
            title = g[1]
            deadline = g[2] if len(g) > 2 else None
            progress = g[3] if len(g) > 3 else 0
            target = g[4] if len(g) > 4 and g[4] else 100
            pct = int((progress / target) * 100) if target else progress
            lines.append(f"🎯 {b(title)}")
            lines.append(f"   {progress_bar(pct)}")
            if deadline:
                lines.append(f"   <i>📅 by {esc(deadline)}</i>")
            lines.append("")
            rows.append([
                uic.button("➖", f"dash:goalminus:{gid}"),
                uic.button(f"{title[:18]}", "dash:goals"),
                uic.button("➕", f"dash:goalplus:{gid}"),
            ])
    rows.append(uic.nav_row(refresh_cb="dash:goals", home_cb="dash:home"))
    text = uic.render_page(header, "\n".join(lines).rstrip())
    return text, InlineKeyboardMarkup(rows)


def habit_card(habits):
    """
    Habit dashboard. `habits` is the get_habits() tuple list:
      (id, title, due_time, recurrence_type, recurrence_weekday,
       current_streak, longest_streak, last_completed, habit_start_date)

    Keyboard note: one check-in row per habit, uncapped (pre-existing) —
    direct assembly, same reasoning as goal_card.
    """
    cap = (f"{len(habits)} active habit{'s' if len(habits) != 1 else ''}"
           if habits else None)
    header = uic.render_header("habit", "Habits", caption_text=cap)
    lines = []
    rows = []
    if not habits:
        # Phase 4: the §14 canonical empty state (approved wording).
        lines.append(uic.empty_habits())
    else:
        for h in habits:
            hid, title, dtime = h[0], h[1], h[2]
            streak = h[5] if len(h) > 5 else 0
            longest = h[6] if len(h) > 6 else 0
            fire = "🔥" * min(streak or 0, 5) if streak else "○"
            lines.append(f"{fire} {b(title)}")
            lines.append(f"   Streak {b(streak or 0)} · best {longest or 0}"
                         + (f" · ⏰ {esc(dtime)}" if dtime else ""))
            lines.append("")
            rows.append([uic.button(f"✅ Did '{title[:20]}'", f"done:{hid}")])
    rows.append(uic.nav_row(refresh_cb="dash:habits", home_cb="dash:home"))
    text = uic.render_page(header, "\n".join(lines).rstrip())
    return text, InlineKeyboardMarkup(rows)


def stat_card(stats: dict):
    """
    Productivity dashboard. `stats` keys:
      completion_rate, overdue_rate, total_tasks, done_tasks, top_categories
      (list of (cat,count)), tone, active_hour, insights (list)
    """
    header = uic.render_header("stats", "Productivity")
    lines = []

    if stats.get("completion_rate") is not None:
        cr = stats["completion_rate"]
        cr = cr * 100 if cr <= 1 else cr
        lines.append("✅ Completion rate")
        lines.append(f"   {progress_bar(cr)}")
    if stats.get("overdue_rate") is not None:
        orate = stats["overdue_rate"]
        orate = orate * 100 if orate <= 1 else orate
        lines.append("⚠️ Overdue rate")
        lines.append(f"   {progress_bar(orate)}")
    lines.append("")

    if stats.get("total_tasks") is not None:
        lines.append(f"📋 Total tasks: {b(stats['total_tasks'])} · "
                     f"done {b(stats.get('done_tasks', 0))}")
    if stats.get("tone"):
        lines.append(f"🎭 Style: {b(stats['tone'])}")
    if stats.get("active_hour") is not None:
        lines.append(f"🕐 Most active around {b(f'{stats['active_hour']:02d}:00')}")
    lines.append("")

    if stats.get("top_categories"):
        lines.append(section("Top categories", "🏷"))
        for cat, n in stats["top_categories"][:5]:
            lines.append(f"   {esc(cat)}: {n}")
        lines.append("")

    if stats.get("insights"):
        lines.append(section("Insights", "💡"))
        for ins in stats["insights"][:4]:
            lines.append(f"   • {ins}")

    text = uic.render_page(header, "\n".join(lines).rstrip())
    keyboard = uic.keyboard(
        uic.nav_row(refresh_cb="dash:stats", home_cb="dash:home"))
    return text, keyboard


def reminder_card(task):
    """
    Rich reminder card (spec #9). `task` tuple: (id, title, due_date, due_time).
    Returns (text, InlineKeyboardMarkup). REGRESSION-CRITICAL: the ping
    buttons and callbacks are byte-identical to pre-Phase-1
    (UI_SPEC_v1.md §3: reminder pings are restyled header only).
    """
    tid = task[0]
    title = task[1]
    ddate = task[2] if len(task) > 2 else None
    dtime = task[3] if len(task) > 3 else None
    meta = f"📅 {ddate or 'No date'} · ⏰ {dtime or 'No time'}"
    body = f"📌 {b(title)}\n{uic.caption(meta)}"
    text = uic.render_page(uic.render_header("bell", "Reminder"), body)
    keyboard = uic.keyboard(
        uic.action_row(("✅ Done", f"done:{tid}"),
                        ("⏰ 10m", f"snooze:{tid}:10"),
                        ("🕐 1h", f"snooze:{tid}:60")),
        uic.action_row(("📅 Tomorrow", f"postpone:{tid}"),
                        ("🔕 Stop", f"stoprem:{tid}"),
                        ("🗑 Delete", f"deltask:{tid}")),
    )
    return text, keyboard


# ── Utility screens (Phase 5R extraction, UI_SPEC_v1.md) ──────────────────
# Every builder below is a VERBATIM move of string assembly that lived
# inline in main.py handlers through v14.17 -- byte-for-byte output, per
# the Phase 5R mandate. Several still emit Markdown (the pre-v7.1 style
# their handlers always used); converting them to spec-compliant HTML is
# Phase 5 proper's job, now finally possible because these are pure,
# offline-testable functions. Handlers keep: data gathering, permission
# gates, parse_mode, reply/edit calls, and main_menu() reply keyboards.

def settings_card(prefs, is_quiet):
    """main.py settings_cmd() presentation (Markdown). Inputs:
    get_user_prefs() dict, is_quiet_hours() bool. Returns text."""
    return (
        f"⚙️ *Your Settings*\n\n"
        f"🌙 Quiet hours: *{prefs['quiet_start']} — {prefs['quiet_end']}*"
        f" {'(active now 🔕)' if is_quiet else '(inactive 🔔)'}\n"
        f"🔁 Reminder interval: *{prefs['interval']} min*\n"
        f"📊 Max reminders per task: *{prefs['max_reminders']}*\n\n"
        f"*Change settings:*\n"
        f"/quiethours <start> <end>\n"
        f"/interval <minutes> — change reminder repeat interval"
    )


def debug_toggle_card(on):
    """main.py debug_cmd() presentation (Markdown). Returns text."""
    return (
        f"🐞 Debug mode is now *{'ON' if on else 'OFF'}*.\n"
        + ("I'll show you the detected intent and entities after each message."
           if on else "Back to normal responses.")
    )


def bugs_card(bugs):
    """main.py bugs_cmd() presentation (Markdown), including the
    no-open-bugs variant. Inputs: get_open_bugs() rows. Returns text."""
    if not bugs:
        return "🎉 No open bugs!"
    msg = "🐞 *Open Bugs:*\n\n"
    for bug in bugs:
        icon = "💥" if bug[1] == "auto_exception" else "📝"
        msg += f"{icon} *#{bug[0]}* — {bug[2][:60]}\n"
        if bug[3]:
            msg += f"     _on: {bug[3][:50]}_\n"
        msg += "\n"
    msg += "Use /resolve <id> to close one."
    return msg


def trace_card(trace):
    """main.py trace_cmd() presentation (Markdown), including the
    no-trace variant. Inputs: get_last_trace() dict or None."""
    if not trace:
        return "No interaction traced yet. Send a message first."
    import json as _json
    return (
        f"🔍 *Last Interaction Trace:*\n\n"
        f"📥 You said: `{trace['user_input']}`\n"
        f"🎯 Intent: `{trace['intent']}`\n"
        f"📦 Entities:\n`{_json.dumps(trace['entities'], indent=2, ensure_ascii=False)}`\n"
        f"📤 Reply: {trace['response'][:200]}\n"
        f"🕐 Time: {trace['time']}"
    )


def insights_card(data):
    """main.py insights_cmd() presentation (Markdown), including the
    not-enough-data variant. Inputs: analyze_user() dict."""
    if data["total_tasks"] < 3:
        return (
            "\U0001f4ca *Not enough data yet*\n\n"
            "I need at least 3 tasks across a few days to learn your patterns. "
            "Keep using me — I'll start spotting trends soon!"
        )
    msg = "\U0001f9e0 *What I've learned about you*\n"
    msg += f"_(based on last 30 days, {data['total_tasks']} tasks)_\n\n"
    for line in data["insights"]:
        msg += f"• {line}\n"
    msg += "\n"
    if data["active_hours_top3"]:
        msg += "\U0001f550 *Active hours:*\n"
        for h, n in data["active_hours_top3"]:
            msg += f"   {h:02d}:00 ({n} interactions)\n"
        msg += "\n"
    if data["snooze_patterns"]:
        msg += "⏰ *Snooze patterns:*\n"
        for cat, count, avg_min in data["snooze_patterns"][:3]:
            msg += f"   {cat}: {count}x (avg {int(avg_min)}m)\n"
        msg += "\n"
    if data["category_focus"]:
        msg += "\U0001f4cc *Top categories:*\n"
        sorted_cats = sorted(data["category_focus"].items(), key=lambda x: -x[1])
        for cat, n in sorted_cats[:5]:
            msg += f"   {cat}: {n} tasks\n"
        msg += "\n"
    msg += "_Use these insights to tweak `/settings` for better defaults._"
    return msg


def admin_panel_card(stats, in_mode):
    """main.py admin_cmd() presentation (Markdown). Inputs:
    get_data_stats() dict, admin-debug-mode bool. Admin visibility is
    the HANDLER's job (silent deny), not this builder's."""
    return (
        "\U0001f6e0 *ADMIN CONTROL PANEL*\n"
        f"Debug mode: {'\U0001f7e2 ON' if in_mode else '⚪ OFF'}\n\n"
        "\U0001f4ca *Your Data:*\n"
        f"  Active tasks: {stats['active_tasks']}\n"
        f"  Completed: {stats['done_tasks']}\n"
        f"  Habits: {stats['habits']}\n"
        f"  Memories: {stats['memories']}\n"
        f"  Goals: {stats['goals']}\n"
        f"  Highest task ID: {stats['max_task_id']}\n"
        f"  Learning logs: {stats['completions_logged']} done, {stats['snoozes_logged']} snoozed\n\n"
        "\U0001f527 *Commands:*\n"
        "/adminmode — toggle debug/admin mode\n"
        "/resettasks — delete all tasks + reset IDs to 0\n"
        "/resetmemory — wipe all memories\n"
        "/resethabits — wipe all habits + streaks\n"
        "/resetlearning — wipe preference-learning data\n"
        "/resetall — ⚠️ nuke EVERYTHING + reset IDs\n"
        "/sql <query> — run a read-only SQL query (debug)\n"
    )


def proactive_card(wellness, prefs):
    """main.py proactive_cmd() presentation (HTML). Inputs:
    get_wellness_prefs() dict, get_user_prefs() dict."""
    return (
        f"🤖 {b('Proactive Features')}\n\n"
        f"These are things BAKA does on its own to help you:\n\n"
        f"🔔 {b('Reminders')} — always on\n"
        f"   <i>Reminds until done, escalates near deadlines</i>\n\n"
        f"👀 {b('Follow-ups')} — always on\n"
        f"   <i>Asks 'did you finish?' after tasks pass</i>\n\n"
        f"🌙 {b('End-of-day summary')} — 21:00 daily\n"
        f"   <i>Lists what's still pending today</i>\n\n"
        f"🌿 {b('Wellness nudges')} — {'🟢 ON' if wellness['on'] else '⚪ OFF'}\n"
        f"   <i>Water/break/eye reminders. Toggle: {code('wellness on')}</i>\n\n"
        f"⏰ {b('Quiet hours')} — {esc(prefs['quiet_start'])}–{esc(prefs['quiet_end'])}\n"
        f"   <i>No proactive messages during this window</i>\n\n"
        f"💡 High-priority tasks due soon get a heads-up automatically."
    )


def help_cards(version, user_is_admin):
    """main.py help_command() presentation (HTML, v14.12 design --
    moved verbatim in Phase 5R). Inputs: BAKA_VERSION string, is_admin
    bool (visibility decided by the caller's check; the builder only
    renders). Returns (msg1, msg2)."""
    from fmt import blockquote, expandable_blockquote

    def _sec(emoji, title, body):
        return f"{emoji} {b(title)}\n{expandable_blockquote(body, escape=False)}"

    intro = (
        f"🤖 {b('BAKA')} — Behavioral Adaptive Knowledge Assistant\n"
        f"{i('v' + version + ' · offline-first · English / Hindi / Hinglish')}\n\n"
        f"Talk naturally, or use commands — {b('slash is optional')}.\n"
        + blockquote(
            f"{i('Remind me to submit assignment by Friday 5pm')}\n"
            f"{i('Kal subah 8 baje gym yaad dila dena')}\n"
            f"{code('list')} = {code('/list')} = {code('show my tasks')}",
            escape=False)
        + "\n\nTap a section to expand it. ▾"
    )

    tasks = "\n".join([
        f"{code('list')} · {code('today')} · {code('week')} — task views",
        f"{code('add task <title>')} — create (also just describe it)",
        f"{code('done <id>')} — complete   {code('edit <id>')} — modify",
        f"{code('delete <id>')} — remove (asks to confirm)",
        f"{code('deadline <id>')} — pre-warns 7d/3d/1d/6h/1h before",
        f"{code('tag <id> <tags>')} · {code('tagged <tag>')} — organize",
    ])
    reminders = "\n".join([
        "Reminder pings have tap-able buttons:",
        "✅ Done · ⏰ 10m · 🕐 1h · 📅 Tomorrow · 🔕 Stop · 🗑 Delete",
        f"{code('snooze <id> <min>')} — custom snooze",
        f"{code('pause <id>')} / {code('resume <id>')} · {code('paused')} — view",
        f"{code('overdue')} · {code('deadlines')} · {code('review')} — follow-ups",
        f"{code('carryforward')} — move all overdue to today",
    ])
    habits = "\n".join([
        f"{code('habits')} — all habits + streaks",
        f"{code('done <id>')} — log today (builds the streak 🔥)",
        f"{code('streak <id>')} — 14-day grid   {code('habitlog <id>')} — 30-day log",
        f"{code('addhabit <title> [at HH:MM] [daily|weekly]')} — create",
        f"{code('skiphabit <id>')} — intentional skip (resets streak)",
    ])
    goals_projects = "\n".join([
        f"{code('goals')} — dashboard with progress bars",
        f"{i('I want to read 12 books this year')} — then tap ➕/➖",
        f"{code('projects')} · {code('project <id>')} — project cards",
        f"{code('need <id> <items>')} — materials   {code('got <name>')} — acquired",
        f"{code('started <id>')} · {code('worklog <id> <text>')} · {code('finished <id>')}",
        f"{code('shopping')} — auto shopping list across projects",
    ])
    ai_planning = "\n".join([
        f"{code('think <question>')} — reasoning over your data",
        f"{code('plan today')} / {code('plan week')} — time-blocked plans",
        f"{code('breakdown <id>')} — split into subtasks",
        f"{code('reschedule <id>')} — pick a conflict-free time",
        f"{code('analyze')} · {code('insights')} · {code('overload')} — reports",
        f"{code('suggestions')} · {code('approve <id>')} · {code('dismiss <id>')}",
    ])
    media = "\n".join([
        f"{code('image <prompt>')} — generate an image",
        f"{code('video <prompt>')} — generate a video (1–3 min)",
        "📷 send any photo — description or todo extraction",
    ])
    memory_search = "\n".join([
        f"{i('Remember my exam is June 20')} — then ask about it later",
        f"{code('memory')} — stored memories   {code('forget <key>')} — delete one",
        f"{code('search <keyword>')} — tasks, memories, habits, goals",
        f"{code('template')} · {code('savetemplate <name> <id>')} — reusables",
        f"{code('export')} — full plain-text backup",
    ])
    settings_utils = "\n".join([
        f"{code('settings')} — all preferences",
        f"{code('quiethours <start> <end>')} — no pings while you sleep",
        f"{code('interval <min>')} — reminder frequency",
        f"{code('wellness on/off')} — 💧 water/break/eye nudges",
        f"{code('dashboard')} — inline-button home view",
        f"{code('status')} — AI benchmark   {code('selftest')} — diagnostics",
        f"{code('debug')} · {code('report <issue>')} · {code('bugs')} · {code('trace')}",
        f"{code('cancel')} — abort any pending question",
    ])

    msg1 = "\n\n".join([
        intro,
        _sec("📌", "TASKS", tasks),
        _sec("🔔", "REMINDERS", reminders),
        _sec("🌱", "HABITS", habits),
    ])
    msg2_parts = [
        _sec("🎯", "GOALS & PROJECTS", goals_projects),
        _sec("🧠", "AI & PLANNING", ai_planning),
        _sec("🖼", "MEDIA", media),
        _sec("🗂", "MEMORY, SEARCH & TEMPLATES", memory_search),
        _sec("⚙️", "SETTINGS & UTILITIES", settings_utils),
    ]
    if user_is_admin:
        admin = "\n".join([
            f"{code('admin')} · {code('adminmode')} — admin dashboard",
            f"{code('resettasks')} · {code('resethabits')} · {code('resetall')} — destructive resets",
            f"{code('sql <query>')} — raw read-only queries",
            f"{code('misses')} · {code('reviewed <id>')} — capability gap review",
        ])
        msg2_parts.append(_sec("👑", "ADMIN (visible only to you)", admin))
    msg2_parts.append(
        f"💡 {i('Slash is optional for every command. English, Hindi, and Hinglish all work.')}")
    msg2 = "\n\n".join(msg2_parts)
    return msg1, msg2


def ai_status_error_card(result):
    """main.py status_cmd() offline-branch presentation (HTML).
    Inputs: check_api_status() dict with status != 'online'."""
    if result["status"] == "rate_limited":
        return f"⚠️ {b('Rate Limited')}\nWait 1-2 min. (40 req/min limit)"
    if result["status"] == "invalid_key":
        return f"❌ {b('Invalid API Key')} — Regenerate at build.nvidia.com"
    return f"❌ {b('Error')} — {code(str(result.get('error','Unknown'))[:150])}"


def ai_status_card(result, bench, full):
    """main.py status_cmd() success presentation (HTML). Inputs:
    check_api_status() dict, benchmark_ai() dict, full-benchmark bool.
    Returns (text, InlineKeyboardMarkup) — the Re-run button's
    callback_data stays byte-identical (dash:home)."""
    rt = result.get("response_time_ms", 0)
    speed = "⚡ Fast" if rt < 1000 else "🐢 Slow" if rt > 3000 else "✅ Normal"
    grade = bench.get("grade", "?")
    grade_emoji = "🏆" if grade in ("A+", "A") else "✅" if grade == "B" else "⚠️"

    lines = [
        f"🤖 {b('BAKA AI Diagnostics')}",
        "",
        f"📡 {b('Connection')}",
        f"   Model: {code(result.get('model', 'glm-5.1'))}",
        f"   Ping: {rt}ms {speed}",
        f"   Tokens: {result.get('prompt_tokens','?')}→{result.get('completion_tokens','?')} ({result.get('total_tokens','?')} total)",
        "",
        f"{grade_emoji} {b('Benchmark: ' + bench['score'])} (Grade: {b(grade)})",
        f"   Avg latency: {bench['avg_latency_ms']}ms",
        "",
    ]
    for t in bench["tests"]:
        icon = "✅" if t["passed"] else "❌"
        lines.append(f"   {icon} {t['name']} ({t['latency_ms']}ms)")
        if t.get("error"):
            lines.append(f"      <i>Error: {esc(t['error'][:80])}</i>")
    lines.extend([
        "",
        "💳 Free tier: 1,000 calls/month · 40 req/min",
    ])
    if not full:
        lines.append(f"\n💡 Run {code('status full')} for a deep 6-test benchmark.")

    kb = InlineKeyboardMarkup([[uic.button("🔄 Re-run", "dash:home")]])
    return "\n".join(lines), kb


def models_card(health, stats):
    """main.py models_cmd() presentation (HTML). Inputs:
    benchmark_all_models() dict, analytics per-model stats dict
    (empty when analytics is unavailable — the pre-existing state)."""
    lines = [f"🤖 {b('Multi-Model AI Status')}", ""]
    for name, r in health.items():
        model_id = r["model"]
        online = r["online"]
        role_label = {
            "main": "Main Brain", "fast": "Fast Tasks",
            "vision": "Image Understanding", "image": "Image Generation",
            "video": "Video Generation"
        }.get(name, name)
        if online is True:
            ping_str = f"🟢 {r['ms']}ms"
        elif online is False:
            ping_str = "🔴 offline"
        else:
            ping_str = f"⚪ {esc(str(online))}"
        s = stats.get(model_id)
        lines.append(f"{b(role_label)} — {ping_str}")
        lines.append(f"  {code(model_id)}")
        if s and s["total_requests"]:
            health_emoji = {"healthy": "🟢", "warning": "🟡",
                           "degraded": "🔴", "slow": "🐢"}.get(s["health"], "⚪")
            lines.append(f"  Today: {b(s['today_requests'])} · Total: {b(s['total_requests'])} · "
                         f"{health_emoji} {esc(s['health'])}")
            lines.append(f"  Avg: {s['avg_latency_ms']}ms · Success: {s['success_rate']}%")
        lines.append("")
    lines.append("<i>All visual models always on · 100% NVIDIA NIM</i>")
    return "\n".join(lines)


def selftest_report(version, python_version, provider, model_main,
                    model_fast, model_think, db_name, db_size, rss_mb,
                    flag_values, checks, elapsed_ms):
    """main.py selftest_cmd() report presentation (HTML, v14.12 design
    -- moved verbatim in Phase 5R). The live probes stay in the
    handler; this renders their results. Inputs: version/python/provider
    strings, three model ids, db display name + size string, peak-RSS
    float (MB), [(flag_name, bool)] list, [(ok, label, detail)] checks,
    elapsed float ms. Returns text."""
    from fmt import blockquote

    ok_count = sum(1 for ok, *_ in checks if ok)
    all_ok = ok_count == len(checks)
    lines = [f"{'✅' if ok else '❌'} {b(label)} — {esc(detail)}"
             for ok, label, detail in checks]

    flags = "\n".join(
        f"{'🟢' if val else '⚪'} {code(name)} {'ON' if val else 'off'}"
        for name, val in flag_values)
    env = "\n".join([
        f"BAKA {b('v' + version)} · Python {code(python_version)}",
        f"AI provider: {code(provider)}",
        f"Models: main {code(model_main)}",
        f"       fast {code(model_fast)}",
        f"  reasoning {code(model_think)}",
        f"Database: {code(db_name)} · {db_size}",
        f"Memory (peak RSS): {code(f'{rss_mb:.0f} MB')}",
    ])

    verdict = ("✅ ALL SYSTEMS OPERATIONAL" if all_ok
               else f"⚠️ {len(checks) - ok_count} CHECK(S) FAILED")
    return "\n\n".join([
        f"🧪 {b('BAKA Diagnostics')}",
        b(verdict),
        blockquote("\n".join(lines), escape=False),
        f"⚙️ {b('Environment')}\n" + blockquote(env, escape=False),
        f"🚩 {b('Feature flags')}\n" + blockquote(flags, escape=False),
        i(f"{len(checks)} live checks · report generated in {elapsed_ms:.0f}ms · "
          f"automated suite: 700+ tests, see TESTING.md"),
    ])
