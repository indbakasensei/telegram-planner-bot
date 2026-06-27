"""
ui.py — v9.0 UI Component System

Pure presentation layer. Every function returns either an HTML string or a
(text, InlineKeyboardMarkup) tuple. NO database access, NO business logic —
callers pass in already-fetched data. This keeps UI separate from logic
(spec #12) and makes components trivially testable.

Built on top of fmt.py (HTML helpers). All text uses Telegram HTML parse mode.
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from fmt import b, i, code, esc, HTML, DIVIDER

# ── Primitives ────────────────────────────────────────

def progress_bar(percent, width=10):
    """Render a text progress bar: ▓▓▓▓▓░░░░░ 50%"""
    percent = max(0, min(100, int(percent or 0)))
    filled = round(width * percent / 100)
    return "▓" * filled + "░" * (width - filled) + f" {percent}%"


def priority_dot(priority):
    return "🔴" if priority == "high" else "🟢" if priority == "low" else "🟡"


def recurrence_icon(recurrence):
    return {"daily": "🔁", "weekly": "📆", "monthly": "🗓"}.get(recurrence, "")


def section(title, emoji=""):
    prefix = f"{emoji} " if emoji else ""
    return f"{prefix}{b(title)}"


# ── Cards ─────────────────────────────────────────────

def dashboard_card(data: dict):
    """
    Central hub. `data` keys (all optional, dashboard adapts to what exists):
      date_str, pending, overdue, upcoming, today_count, done_today,
      goals, habits, completion_rate, streak_best
    Returns (text, InlineKeyboardMarkup).
    """
    lines = [f"🏠 {b('BAKA Dashboard')}"]
    if data.get("date_str"):
        lines.append(f"<i>{esc(data['date_str'])}</i>")
    lines.append("")

    # Snapshot counts
    snapshot = []
    if data.get("today_count") is not None:
        snapshot.append(f"📅 Today: {b(data['today_count'])}")
    if data.get("overdue") is not None:
        snapshot.append(f"⚠️ Overdue: {b(data['overdue'])}")
    if data.get("pending") is not None:
        snapshot.append(f"📋 Pending: {b(data['pending'])}")
    if data.get("done_today") is not None:
        snapshot.append(f"✅ Done today: {b(data['done_today'])}")
    if snapshot:
        lines.append("  ·  ".join(snapshot))
        lines.append("")

    # Goals / habits quick lines
    if data.get("goals"):
        lines.append(f"🎯 {b('Goals')}: {len(data['goals'])} active")
    if data.get("habits"):
        best = data.get("streak_best", 0)
        lines.append(f"🌱 {b('Habits')}: {len(data['habits'])} active"
                     + (f" · 🔥 best streak {best}" if best else ""))
    if data.get("completion_rate") is not None:
        lines.append(f"📊 Completion: {progress_bar(data['completion_rate']*100 if data['completion_rate']<=1 else data['completion_rate'])}")

    if not snapshot and not data.get("goals") and not data.get("habits"):
        lines.append(i("Nothing tracked yet. Add a task to get started!"))

    text = "\n".join(lines)

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📅 Today", callback_data="dash:today"),
            InlineKeyboardButton("📋 Tasks", callback_data="dash:tasks"),
        ],
        [
            InlineKeyboardButton("🎯 Goals", callback_data="dash:goals"),
            InlineKeyboardButton("🌱 Habits", callback_data="dash:habits"),
        ],
        [
            InlineKeyboardButton("📊 Stats", callback_data="dash:stats"),
            InlineKeyboardButton("🔄 Refresh", callback_data="dash:home"),
        ],
    ])
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

    dot = "✅" if done else priority_dot(priority)
    rec = recurrence_icon(recurrence)
    rec_s = f" {rec}" if rec else ""

    lines = [f"{dot} {b(title)}{rec_s}"]
    meta = []
    if ddate:
        meta.append(f"📅 {esc(ddate)}")
    if dtime:
        meta.append(f"⏰ {esc(dtime)}")
    meta.append(f"🏷 {esc(category)}")
    meta.append(f"{priority_dot(priority)} {esc(priority)}")
    lines.append("<i>" + " · ".join(meta) + "</i>")
    text = "\n".join(lines)

    if not show_actions or done:
        return text, None

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Done", callback_data=f"done:{tid}"),
            InlineKeyboardButton("⏰ Snooze", callback_data=f"snooze:{tid}:30"),
            InlineKeyboardButton("📅 Tomorrow", callback_data=f"postpone:{tid}"),
        ],
        [
            InlineKeyboardButton("✏️ Edit", callback_data=f"dash:edit:{tid}"),
            InlineKeyboardButton("🗑 Delete", callback_data=f"deltask:{tid}"),
            InlineKeyboardButton("« Back", callback_data="dash:tasks"),
        ],
    ])
    return text, keyboard


def today_card(groups: dict, date_str=""):
    """
    Grouped today view. `groups` keys: overdue, high, upcoming, done — each a
    list of task tuples. Returns (text, InlineKeyboardMarkup).
    """
    lines = [f"📅 {b('Today')}"]
    if date_str:
        lines.append(f"<i>{esc(date_str)}</i>")
    lines.append("")

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
        lines.append(i("Nothing scheduled today. Enjoy! 🌟"))

    text = "\n".join(lines).rstrip()
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Refresh", callback_data="dash:today"),
            InlineKeyboardButton("🏠 Home", callback_data="dash:home"),
        ],
    ])
    return text, keyboard


def task_list_card(tasks, title="Your Tasks", page_cb="dash:tasks"):
    """List of tasks, each tappable to open its task_card."""
    lines = [f"📋 {b(title)}", ""]
    rows = []
    if not tasks:
        lines.append(i("No tasks here. Add one anytime!"))
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
            rows.append([InlineKeyboardButton(
                f"{dot} {t[1][:28]}", callback_data=f"dash:task:{t[0]}")])
    rows.append([
        InlineKeyboardButton("🔄 Refresh", callback_data=page_cb),
        InlineKeyboardButton("🏠 Home", callback_data="dash:home"),
    ])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


def goal_card(goals, date_str=""):
    """
    Goals dashboard. `goals` is a list of tuples:
      (id, title, deadline, progress[, target])
    Returns (text, InlineKeyboardMarkup).
    """
    lines = [f"🎯 {b('Goals')}", ""]
    rows = []
    if not goals:
        lines.append(i("No goals yet. Tell me something you're working toward!"))
        lines.append("")
        lines.append(f"<i>e.g. \"I want to read 12 books this year\"</i>")
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
                InlineKeyboardButton("➖", callback_data=f"dash:goalminus:{gid}"),
                InlineKeyboardButton(f"{title[:18]}", callback_data=f"dash:goals"),
                InlineKeyboardButton("➕", callback_data=f"dash:goalplus:{gid}"),
            ])
    rows.append([
        InlineKeyboardButton("🔄 Refresh", callback_data="dash:goals"),
        InlineKeyboardButton("🏠 Home", callback_data="dash:home"),
    ])
    return "\n".join(lines).rstrip(), InlineKeyboardMarkup(rows)


def habit_card(habits):
    """
    Habit dashboard. `habits` is the get_habits() tuple list:
      (id, title, due_time, recurrence_type, recurrence_weekday,
       current_streak, longest_streak, last_completed, habit_start_date)
    """
    lines = [f"🌱 {b('Habits')}", ""]
    rows = []
    if not habits:
        lines.append(i("No habits yet. Start one like \"meditate daily at 7am\"."))
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
            rows.append([InlineKeyboardButton(
                f"✅ Did '{title[:20]}'", callback_data=f"done:{hid}")])
    rows.append([
        InlineKeyboardButton("🔄 Refresh", callback_data="dash:habits"),
        InlineKeyboardButton("🏠 Home", callback_data="dash:home"),
    ])
    return "\n".join(lines).rstrip(), InlineKeyboardMarkup(rows)


def stat_card(stats: dict):
    """
    Productivity dashboard. `stats` keys:
      completion_rate, overdue_rate, total_tasks, done_tasks, top_categories
      (list of (cat,count)), tone, active_hour, insights (list)
    """
    lines = [f"📊 {b('Productivity')}", ""]

    if stats.get("completion_rate") is not None:
        cr = stats["completion_rate"]
        cr = cr * 100 if cr <= 1 else cr
        lines.append(f"✅ Completion rate")
        lines.append(f"   {progress_bar(cr)}")
    if stats.get("overdue_rate") is not None:
        orate = stats["overdue_rate"]
        orate = orate * 100 if orate <= 1 else orate
        lines.append(f"⚠️ Overdue rate")
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

    text = "\n".join(lines).rstrip()
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Refresh", callback_data="dash:stats"),
            InlineKeyboardButton("🏠 Home", callback_data="dash:home"),
        ],
    ])
    return text, keyboard


def reminder_card(task):
    """
    Rich reminder card (spec #9). `task` tuple: (id, title, due_date, due_time).
    Returns (text, InlineKeyboardMarkup).
    """
    tid = task[0]
    title = task[1]
    ddate = task[2] if len(task) > 2 else None
    dtime = task[3] if len(task) > 3 else None
    text = (f"🔔 {b('Reminder')}\n\n📌 {b(title)}\n"
            f"<i>📅 {esc(ddate or 'No date')} · ⏰ {esc(dtime or 'No time')}</i>")
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Done", callback_data=f"done:{tid}"),
            InlineKeyboardButton("⏰ 10m", callback_data=f"snooze:{tid}:10"),
            InlineKeyboardButton("🕐 1h", callback_data=f"snooze:{tid}:60"),
        ],
        [
            InlineKeyboardButton("📅 Tomorrow", callback_data=f"postpone:{tid}"),
            InlineKeyboardButton("🔕 Stop", callback_data=f"stoprem:{tid}"),
            InlineKeyboardButton("🗑 Delete", callback_data=f"deltask:{tid}"),
        ],
    ])
    return text, keyboard