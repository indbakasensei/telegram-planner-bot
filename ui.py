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


# ── Utility screens (extracted in Phase 5R, redesigned in Phase 5) ────────
# UI_SPEC_v1.md §15 Phase 5: every builder below now renders through the
# shared component library (header → caption → cards → footer, §5
# typography, HTML only — the six former-Markdown screens are converted;
# their handlers pass parse_mode=HTML accordingly). Behavior unchanged:
# same inputs, same variants, and the single keyboard (AI status Re-run)
# keeps its byte-identical dash:home callback. help_cards() keeps its
# v14.12 design (already spec-styled); selftest_report() gets the
# component header/status treatment.

def settings_card(prefs, is_quiet):
    """Settings screen (Phase 5: HTML via components). Inputs:
    get_user_prefs() dict, is_quiet_hours() bool. Returns text."""
    header = uic.render_header(
        "settings", "Settings",
        caption_text="Quiet hours active now 🔕" if is_quiet else None)
    info = uic.render_information_card("Preferences", [
        ("🌙 Quiet hours", f"{prefs['quiet_start']} — {prefs['quiet_end']}"
                           + (" (active now)" if is_quiet else "")),
        ("🔁 Reminder interval", f"{prefs['interval']} min"),
        ("📊 Max reminders per task", str(prefs['max_reminders'])),
    ])
    footer = uic.render_footer(
        "Change: quiethours <start> <end> · interval <minutes>")
    return uic.render_page(header, info, footer=footer)


def debug_toggle_card(on):
    """Debug-mode toggle result (Phase 5: status components)."""
    if on:
        return uic.render_success(
            "Debug mode ON",
            "I'll show you the detected intent and entities after each message.")
    return uic.render_info("Debug mode OFF", "Back to normal responses.")


def bugs_card(bugs):
    """Open-bugs list (Phase 5: components; §14 dev empty state).
    Inputs: get_open_bugs() rows. Returns text."""
    header = uic.render_header(
        "dev", "Open Bugs",
        caption_text=f"{len(bugs)} open" if bugs else None)
    if not bugs:
        return uic.render_page(
            header,
            uic.empty_dev("bugs list is empty — nothing reported since last review"))
    lines = []
    for bug in bugs:
        icon = "💥" if bug[1] == "auto_exception" else "📝"
        lines.append(f"{icon} {b('#' + str(bug[0]))} — {esc(bug[2][:60])}")
        if bug[3]:
            lines.append(f"   {uic.caption('on: ' + bug[3][:50])}")
    footer = uic.render_footer("Use resolve <id> to close one.")
    return uic.render_page(header, "\n".join(lines), footer=footer)


def trace_card(trace):
    """Last-interaction trace (Phase 5: components; dev code block for
    entities per §5.3). Inputs: get_last_trace() dict or None."""
    from fmt import code_block
    import json as _json
    header = uic.render_header("search", "Last Interaction Trace")
    if not trace:
        return uic.render_page(
            header,
            uic.empty_dev("no interaction traced yet — send a message first"))
    info = uic.render_information_card("Interaction", [
        ("📥 You said", trace["user_input"]),
        ("🎯 Intent", trace["intent"]),
        ("📤 Reply", trace["response"][:200]),
        ("🕐 Time", trace["time"]),
    ])
    entities = code_block(
        _json.dumps(trace["entities"], indent=2, ensure_ascii=False), "json")
    return uic.render_page(header, info, f"📦 {b('Entities')}\n{entities}")


def insights_card(data):
    """Learning insights (Phase 5: components; §14 statistics empty
    state for the not-enough-data variant). Inputs: analyze_user() dict."""
    if data["total_tasks"] < 3:
        return uic.render_page(
            uic.render_header("stats", "Insights"),
            uic.empty_statistics())
    header = uic.render_header(
        "stats", "Insights",
        caption_text=f"based on last 30 days · {data['total_tasks']} tasks")
    blocks = ["\n".join(f"• {line}" for line in data["insights"])]
    if data["active_hours_top3"]:
        blocks.append(uic.render_section("Active hours", "\n".join(
            f"• {h:02d}:00 ({n} interactions)"
            for h, n in data["active_hours_top3"])))
    if data["snooze_patterns"]:
        blocks.append(uic.render_section("Snooze patterns", "\n".join(
            f"• {esc(cat)}: {count}x (avg {int(avg_min)}m)"
            for cat, count, avg_min in data["snooze_patterns"][:3])))
    if data["category_focus"]:
        sorted_cats = sorted(data["category_focus"].items(), key=lambda x: -x[1])
        blocks.append(uic.render_section("Top categories", "\n".join(
            f"• {esc(cat)}: {n} tasks" for cat, n in sorted_cats[:5])))
    footer = uic.render_footer(
        "Use these insights to tweak settings for better defaults.")
    return uic.render_page(header, *blocks, footer=footer)


def admin_panel_card(stats, in_mode):
    """Admin control panel (Phase 5: components). Inputs:
    get_data_stats() dict, admin-debug-mode bool. Admin visibility is
    the HANDLER's job (silent deny), not this builder's."""
    header = uic.render_header(
        "dev", "Admin Control Panel",
        caption_text=f"Debug mode {'🟢 ON' if in_mode else '⚪ OFF'}")
    data_card = uic.render_statistics_card("Your Data", [
        ("Active tasks", stats["active_tasks"]),
        ("Completed", stats["done_tasks"]),
        ("Habits", stats["habits"]),
        ("Memories", stats["memories"]),
        ("Goals", stats["goals"]),
        ("Highest task ID", stats["max_task_id"]),
        ("Learning logs",
         f"{stats['completions_logged']} done, {stats['snoozes_logged']} snoozed"),
    ])
    commands = uic.render_section("Commands", "\n".join([
        f"{code('adminmode')} — toggle debug/admin mode",
        f"{code('resettasks')} — delete all tasks + reset IDs",
        f"{code('resetmemory')} · {code('resethabits')} · {code('resetlearning')}",
        f"{code('resetall')} — ⚠️ nuke EVERYTHING + reset IDs",
        f"{code('sql <query>')} — read-only SQL (debug)",
    ]))
    return uic.render_page(header, data_card, commands)


def proactive_card(wellness, prefs):
    """Proactive-features panel (Phase 5: components). Inputs:
    get_wellness_prefs() dict, get_user_prefs() dict."""
    header = uic.render_header(
        "settings", "Proactive Features",
        caption_text="Things BAKA does on its own to help you")
    body = "\n\n".join([
        f"🔔 {b('Reminders')} — always on\n"
        f"{uic.caption('Reminds until done, escalates near deadlines')}",
        f"👀 {b('Follow-ups')} — always on\n"
        f"{uic.caption(chr(39) + 'Did you finish?' + chr(39) + ' after tasks pass')}",
        f"🌙 {b('End-of-day summary')} — 21:00 daily\n"
        f"{uic.caption('Lists what is still pending today')}",
        f"🌿 {b('Wellness nudges')} — {'🟢 ON' if wellness['on'] else '⚪ OFF'}\n"
        f"{uic.caption('Water/break/eye reminders. Toggle: wellness on')}",
        f"⏰ {b('Quiet hours')} — {esc(prefs['quiet_start'])}–{esc(prefs['quiet_end'])}\n"
        f"{uic.caption('No proactive messages during this window')}",
    ])
    footer = uic.render_footer(
        "High-priority tasks due soon get a heads-up automatically.")
    return uic.render_page(header, body, footer=footer)


def ai_status_error_card(result):
    """AI connectivity failure states (Phase 5: status components).
    Inputs: check_api_status() dict with status != 'online'."""
    if result["status"] == "rate_limited":
        return uic.render_warning("Rate limited",
                                   "Wait 1–2 min. (40 req/min limit)")
    if result["status"] == "invalid_key":
        return uic.render_error("Invalid API key",
                                 "Regenerate at build.nvidia.com")
    return uic.render_error("AI error",
                             str(result.get("error", "Unknown"))[:150])


def ai_status_card(result, bench, full):
    """AI diagnostics (Phase 5: components). Inputs: check_api_status()
    dict, benchmark_ai() dict, full-benchmark bool. Returns
    (text, InlineKeyboardMarkup) — Re-run callback stays dash:home."""
    rt = result.get("response_time_ms", 0)
    speed = "⚡ Fast" if rt < 1000 else "🐢 Slow" if rt > 3000 else "✅ Normal"
    grade = bench.get("grade", "?")

    header = uic.render_header("ai", "AI Diagnostics")
    conn = uic.render_information_card("Connection", [
        ("Model", result.get("model", "glm-5.1")),
        ("Ping", f"{rt}ms {speed}"),
        ("Tokens", f"{result.get('prompt_tokens','?')}→"
                   f"{result.get('completion_tokens','?')} "
                   f"({result.get('total_tokens','?')} total)"),
    ])
    bench_card = uic.render_statistics_card(f"Benchmark {bench['score']}", [
        ("Grade", grade),
        ("Avg latency", f"{bench['avg_latency_ms']}ms"),
    ])
    passed = sum(1 for t in bench["tests"] if t["passed"])
    test_lines = []
    for t in bench["tests"]:
        icon = "✅" if t["passed"] else "❌"
        test_lines.append(f"{icon} {esc(t['name'])} ({t['latency_ms']}ms)")
        if t.get("error"):
            test_lines.append(f"   {uic.caption('Error: ' + t['error'][:80])}")
    tests_card = uic.render_status_card(
        "success" if passed == len(bench["tests"]) else "warning",
        f"{passed}/{len(bench['tests'])} tests passed",
        "\n".join(test_lines))
    hint = "Free tier: 1,000 calls/month · 40 req/min"
    if not full:
        hint += " · run status full for the deep 6-test benchmark"
    text = uic.render_page(header, conn, bench_card, tests_card,
                            footer=uic.render_footer(hint))
    kb = InlineKeyboardMarkup([[uic.button("🔄 Re-run", "dash:home")]])
    return text, kb


def models_card(health, stats):
    """Multi-model AI status (Phase 5: components). Inputs:
    benchmark_all_models() dict, analytics per-model stats dict (empty
    when analytics is unavailable — the pre-existing state)."""
    header = uic.render_header(
        "ai", "Multi-Model AI Status",
        caption_text=f"{len(health)} models probed")
    lines = []
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
    footer = uic.render_footer("All visual models always on · 100% NVIDIA NIM")
    return uic.render_page(header, "\n".join(lines).rstrip(), footer=footer)


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
