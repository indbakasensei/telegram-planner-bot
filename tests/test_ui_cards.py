"""
Characterization tests for ui.py's dashboard cards — written BEFORE the
Phase 1 migration (UI_SPEC_v1.md §15 Phase 1; the migration's mandatory
first task) and kept green through it.

What these tests pin, and how strictly:

- **Fields**: every piece of data a card displays today (ids, titles,
  dates, times, categories, priorities, streaks, percentages, counts,
  insight lines) must still be displayed — asserted byte-exact on the
  data itself.
- **Callbacks and button labels**: byte-exact. Phase 1 may not change a
  single callback_data or button label ("no callback changes", "no new
  buttons").
- **Structure**: progress bars' exact glyph format, priority dots,
  recurrence icons, strikethrough on completed tasks, per-row button
  layouts.
- **Headings**: asserted case-insensitively — UI_SPEC §5.1 makes H1s
  uppercase, and the brief allows "the richer formatting produced by
  the shared components"; everything else about a heading (icon, text,
  position: line 1) is pinned.
- **Empty-state copy**: pinned verbatim (§14's canonical copy is a
  Phase 2+ concern; Phase 1 must not change wording).
"""
import ui


def _texts(kb):
    return [[btn.text for btn in row] for row in kb.inline_keyboard]


def _cbs(kb):
    return [[btn.callback_data for btn in row] for row in kb.inline_keyboard]


TASK = (17, "Submit report", "2026-07-18", "17:00", "College", "high", 0, "daily")
TASK_DONE = (18, "Old chore", None, None, "General", "low", 1, None)


# ── Primitives ───────────────────────────────────────────────────────────

def test_progress_bar_exact_format():
    assert ui.progress_bar(50) == "▓▓▓▓▓░░░░░ 50%"
    assert ui.progress_bar(0) == "░░░░░░░░░░ 0%"
    assert ui.progress_bar(None) == "░░░░░░░░░░ 0%"     # None tolerated
    assert ui.progress_bar(130) == "▓▓▓▓▓▓▓▓▓▓ 100%"    # clamped


def test_priority_dot_mapping():
    assert ui.priority_dot("high") == "🔴"
    assert ui.priority_dot("medium") == "🟡"
    assert ui.priority_dot("low") == "🟢"
    assert ui.priority_dot("anything-else") == "🟡"


def test_recurrence_icon_mapping():
    assert ui.recurrence_icon("daily") == "🔁"
    assert ui.recurrence_icon("weekly") == "📆"
    assert ui.recurrence_icon("monthly") == "🗓"
    assert ui.recurrence_icon(None) == ""


def test_section_shape():
    assert ui.section("Overdue (2)", "⚠️") == "⚠️ <b>Overdue (2)</b>"
    assert ui.section("Plain") == "<b>Plain</b>"


# ── Dashboard card (redesigned in Phase 2; field + callback continuity
#    pinned against the pre-redesign card) ─────────────────────────────────

# The pre-Phase-2 dashboard exposed exactly these six destinations; the
# redesign may not add or remove any ("no callback changes").
PRE_PHASE2_DASH_CALLBACKS = {
    "dash:today", "dash:tasks", "dash:goals",
    "dash:habits", "dash:stats", "dash:home",
}

DASH_DATA = {
    "date_str": "Fri 17 Jul", "today_count": 4, "overdue": 3,
    "pending": 9, "done_today": 2, "goals": [1, 2],
    "habits": [1, 2, 3], "streak_best": 12, "completion_rate": 0.5,
}


def test_dashboard_card_fields_survive_redesign():
    text, _ = ui.dashboard_card(DASH_DATA)
    first = text.splitlines()[0]
    assert first.startswith("🏠") and "baka dashboard" in first.lower()
    assert "Fri 17 Jul" in text                       # date still visible
    assert "📅 Today: <b>4</b>" in text               # every pre-redesign
    assert "⚠️ Overdue: <b>3</b>" in text             # field, same format
    assert "📋 Pending: <b>9</b>" in text
    assert "✅ Done today: <b>2</b>" in text
    assert "2 active" in text and "3 active" in text
    assert "🔥 best streak 12" in text
    assert "▓▓▓▓▓░░░░░ 50%" in text


def test_dashboard_card_callback_set_identical_to_pre_redesign():
    _, kb = ui.dashboard_card(DASH_DATA)
    flat = {btn.callback_data for row in kb.inline_keyboard for btn in row}
    assert flat == PRE_PHASE2_DASH_CALLBACKS


def test_dashboard_card_phase2_layout():
    text, kb = ui.dashboard_card(DASH_DATA)
    assert "<i>Today's productivity overview · Fri 17 Jul</i>" in text
    assert "⚠️ 3 overdue" in text                     # status headline (worst level)
    assert "Completion: <b>50%</b>" in text           # statistics card metric
    assert "<i>Good pace — keep going.</i>" in text   # motivation tier 50–79
    assert _texts(kb) == [["📅 Today", "🎯 Goals", "🌱 Habits"],
                          ["📋 Tasks", "📊 Statistics"],
                          ["🔄 Refresh"]]
    assert _cbs(kb) == [["dash:today", "dash:goals", "dash:habits"],
                        ["dash:tasks", "dash:stats"],
                        ["dash:home"]]


def test_dashboard_status_level_tiers():
    text, _ = ui.dashboard_card({"today_count": 4, "overdue": 0})
    assert "ℹ️ 4 due today" in text                   # no overdue -> info
    text, _ = ui.dashboard_card({"today_count": 0, "overdue": 0,
                                  "pending": 1})
    assert "✅ All clear" in text                     # nothing pressing


def test_dashboard_motivation_tiers():
    assert "Crushing it" in ui.dashboard_card({"completion_rate": 0.9,
                                                "pending": 1})[0]
    assert "Warming up" in ui.dashboard_card({"completion_rate": 0.2,
                                               "pending": 1})[0]
    assert "Fresh start" in ui.dashboard_card({"completion_rate": 0,
                                                "pending": 1})[0]


def test_dashboard_card_empty_copy():
    text, _ = ui.dashboard_card({})
    assert "Nothing tracked yet. Add a task to get started!" in text


# ── Task card ────────────────────────────────────────────────────────────

def test_task_card_fields_and_buttons():
    text, kb = ui.task_card(TASK)
    assert "🔴 <b>Submit report</b> 🔁" in text
    assert "📅 2026-07-18" in text and "⏰ 17:00" in text
    assert "🏷 College" in text and "🔴 high" in text
    assert _texts(kb) == [["✅ Done", "⏰ Snooze", "📅 Tomorrow"],
                          ["✏️ Edit", "🗑 Delete", "« Back"]]
    assert _cbs(kb) == [["done:17", "snooze:17:30", "postpone:17"],
                        ["dash:edit:17", "deltask:17", "dash:tasks"]]


def test_task_card_done_has_check_and_no_keyboard():
    text, kb = ui.task_card(TASK_DONE)
    assert text.startswith("✅ <b>Old chore</b>")
    assert kb is None


def test_task_card_accepts_dicts():
    text, _ = ui.task_card({"id": 5, "title": "Dict task", "priority": "low"})
    assert "🟢 <b>Dict task</b>" in text


# ── Today card ───────────────────────────────────────────────────────────

def test_today_card_groups_and_fields():
    groups = {
        "overdue": [TASK],
        "high": [(19, "Urgent thing", None, "09:00", "General", "high", 0, None)],
        "upcoming": [],
        "done": [TASK_DONE],
    }
    text, kb = ui.today_card(groups, date_str="Fri 17 Jul")
    first = text.splitlines()[0]
    assert first.startswith("📅") and "today" in first.lower()
    assert "<i>Fri 17 Jul</i>" in text
    assert "⚠️ <b>Overdue (1)</b>" in text
    assert "🔴 <b>High Priority (1)</b>" in text
    assert "<code>[17]</code> Submit report ⏰ 17:00" in text
    assert "✅ <b>Completed (1)</b>" in text
    assert "<s>Old chore</s>" in text
    assert _cbs(kb) == [["dash:today", "dash:home"]]
    assert _texts(kb) == [["🔄 Refresh", "🏠 Home"]]


def test_today_card_empty_copy():
    text, _ = ui.today_card({})
    assert "Nothing scheduled today. Enjoy! 🌟" in text


# ── Task list card ───────────────────────────────────────────────────────

def test_task_list_card_rows_and_buttons():
    text, kb = ui.task_list_card([TASK], title="Your Tasks")
    first = text.splitlines()[0]
    assert first.startswith("📋") and "your tasks" in first.lower()
    assert "🔴 <code>[17]</code> Submit report 🔁" in text
    assert "<i>· 2026-07-18 · 17:00</i>" in text
    rows = _cbs(kb)
    assert rows[0] == ["dash:task:17"]
    assert rows[-1] == ["dash:tasks", "dash:home"]
    assert _texts(kb)[0][0].startswith("🔴 Submit report")
    assert _texts(kb)[-1] == ["🔄 Refresh", "🏠 Home"]


def test_task_list_card_empty_copy():
    text, _ = ui.task_list_card([])
    assert "No tasks here. Add one anytime!" in text


# ── Goal card ────────────────────────────────────────────────────────────

def test_goal_card_fields_and_plusminus_buttons():
    text, kb = ui.goal_card([(4, "Read 12 books", "2026-12-31", 6, 12)])
    assert "🎯 <b>Read 12 books</b>" in text
    assert "▓▓▓▓▓░░░░░ 50%" in text
    assert "📅 by 2026-12-31" in text
    rows = _cbs(kb)
    assert rows[0] == ["dash:goalminus:4", "dash:goals", "dash:goalplus:4"]
    assert _texts(kb)[0] == ["➖", "Read 12 books", "➕"]
    assert rows[-1] == ["dash:goals", "dash:home"]


def test_goal_card_empty_copy():
    text, _ = ui.goal_card([])
    assert "No goals yet. Tell me something you're working toward!" in text
    assert "I want to read 12 books this year" in text


# ── Habit card ───────────────────────────────────────────────────────────

def test_habit_card_fields_and_checkin_buttons():
    habits = [(7, "Meditate", "07:00", "daily", None, 3, 5, "2026-07-16", "2026-07-01")]
    text, kb = ui.habit_card(habits)
    first = text.splitlines()[0]
    assert first.startswith("🌱") and "habits" in first.lower()
    assert "🔥🔥🔥 <b>Meditate</b>" in text
    assert "Streak <b>3</b> · best 5 · ⏰ 07:00" in text
    rows = _cbs(kb)
    assert rows[0] == ["done:7"]
    assert _texts(kb)[0] == ["✅ Did 'Meditate'"]
    assert rows[-1] == ["dash:habits", "dash:home"]


def test_habit_card_zero_streak_and_empty_copy():
    text, _ = ui.habit_card([(7, "Read", None, "daily", None, 0, 0, None, None)])
    assert "○ <b>Read</b>" in text
    empty, _ = ui.habit_card([])
    assert 'No habits yet. Start one like "meditate daily at 7am".' in empty


# ── Stat card ────────────────────────────────────────────────────────────

def test_stat_card_fields():
    stats = {
        "completion_rate": 0.75, "overdue_rate": 10, "total_tasks": 40,
        "done_tasks": 30, "tone": "casual", "active_hour": 9,
        "top_categories": [("College", 12), ("Health", 8)],
        "insights": ["You complete most tasks in the morning"],
    }
    text, kb = ui.stat_card(stats)
    first = text.splitlines()[0]
    assert first.startswith("📊") and "productivity" in first.lower()
    assert "✅ Completion rate" in text and "▓▓▓▓▓▓▓▓░░ 75%" in text
    assert "⚠️ Overdue rate" in text and "▓░░░░░░░░░ 10%" in text
    assert "📋 Total tasks: <b>40</b> · done <b>30</b>" in text
    assert "🎭 Style: <b>casual</b>" in text
    assert "🕐 Most active around <b>09:00</b>" in text
    assert "🏷 <b>Top categories</b>" in text and "College: 12" in text
    assert "💡 <b>Insights</b>" in text
    assert "• You complete most tasks in the morning" in text
    assert _cbs(kb) == [["dash:stats", "dash:home"]]


# ── Reminder card (regression-critical: ping buttons byte-identical) ────

def test_reminder_card_fields_and_buttons():
    text, kb = ui.reminder_card((17, "Submit report", "2026-07-18", "17:00"))
    first = text.splitlines()[0]
    assert first.startswith("🔔") and "reminder" in first.lower()
    assert "📌 <b>Submit report</b>" in text
    assert "📅 2026-07-18 · ⏰ 17:00" in text
    assert _texts(kb) == [["✅ Done", "⏰ 10m", "🕐 1h"],
                          ["📅 Tomorrow", "🔕 Stop", "🗑 Delete"]]
    assert _cbs(kb) == [["done:17", "snooze:17:10", "snooze:17:60"],
                        ["postpone:17", "stoprem:17", "deltask:17"]]


def test_reminder_card_no_date_fallbacks():
    text, _ = ui.reminder_card((17, "Task", None, None))
    assert "📅 No date · ⏰ No time" in text


# ── Escaping (the v7.1 law, pinned across every card) ────────────────────

def test_cards_escape_hostile_titles():
    hostile = "Read <b>ooks & sleep"
    esc_form = "Read &lt;b&gt;ooks &amp; sleep"
    assert esc_form in ui.task_card((1, hostile, None, None, "G", "low", 0, None))[0]
    assert esc_form in ui.task_list_card([(1, hostile, None, None, "G", "low", 0, None)])[0]
    assert esc_form in ui.habit_card([(1, hostile, None, "daily", None, 1, 1, None, None)])[0]
    assert esc_form in ui.reminder_card((1, hostile, None, None))[0]
