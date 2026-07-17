"""
Tests for ui_components.py — the UI Phase 0 component library
(UI_SPEC_v1.md §12). Two jobs:

1. Pin HTML/button generation for every component (hostile input always
   escaped — the v7.1 lesson — and the §14 canonical empty-state copy
   pinned verbatim so screens can't drift the wording).
2. Prove the MECHANICAL enforcement layer: the spec rules that raise at
   build time (closed icon vocabulary §5.5, canonical labels §7,
   status-with-words §6.3, card row cap §5.3, message budget §6.1,
   64-byte callbacks §5.7, row/keyboard caps §6.2, fixed nav order
   §2.5, safe-left confirmations §8, breadcrumb depth §2.4).

No business logic is tested because none exists here: every component
is a stateless text/keyboard builder with no handler, storage, or
network dependency (importing telegram's dataclasses only, like
tests/test_notification_service.py already does).
"""
from datetime import datetime

import pytest

import ui_components as uic
from fmt import link

HOSTILE = 'Read <b>ooks & "sleep"'
HOSTILE_ESC = 'Read &lt;b&gt;ooks &amp; "sleep"'


# ── Vocabulary enforcement (§5.5, §7) ────────────────────────────────────

def test_icon_lookup_and_closed_vocabulary():
    assert uic.icon("habit") == "🌱"
    assert uic.icon("success") == "✅"
    with pytest.raises(KeyError):
        uic.icon("party_parrot")


def test_label_lookup_and_closed_table():
    assert uic.label("add_task") == "➕ Add Task"
    assert uic.label("cancel") == "✕ Cancel"
    with pytest.raises(KeyError):
        uic.label("create_task")      # banned synonym isn't a key


# ── Typography (§5.1, §2.4, §5.6) ────────────────────────────────────────

def test_page_title_shape_and_escaping():
    assert uic.page_title("habit", "Habits") == "🌱 <b>HABITS</b>"
    assert HOSTILE_ESC.upper()[:12] in uic.page_title("task", HOSTILE).upper()


def test_breadcrumb_shape_and_depth_cap():
    assert uic.breadcrumb("Tasks", "Today") == (
        "<i>🏠 Dashboard › Tasks › Today</i>")
    with pytest.raises(ValueError):
        uic.breadcrumb("a", "b", "c", "d")


def test_breadcrumb_escapes_segments():
    assert "&lt;q&gt;" in uic.breadcrumb("Search", "<q>")


def test_status_indicator_requires_words():
    assert uic.status_indicator("success", "Saved") == "✅ Saved"
    with pytest.raises(ValueError):
        uic.status_indicator("success", "  ")
    with pytest.raises(ValueError):
        uic.status_indicator("fatal", "boom")


def test_timestamp_rules():
    now = datetime(2026, 7, 17, 10, 0)
    assert uic.fmt_timestamp(datetime(2026, 6, 17), now) == "Wed 17 Jun"
    assert uic.fmt_timestamp(datetime(2027, 6, 17), now) == "17 Jun 2027"
    assert uic.fmt_time("09:00") == "09:00"
    assert uic.fmt_time(datetime(2026, 6, 17, 17, 0)) == "17:00"


def test_progress_indicator_clamps_and_renders():
    assert uic.progress_indicator(30) == "▓▓▓░░░░░░░ 30%"
    assert uic.progress_indicator(250).endswith(" 100%")
    assert uic.progress_indicator(-5).startswith("░")


# ── Page skeleton (§12, §6.1) ────────────────────────────────────────────

def test_render_header_full_and_minimal():
    full = uic.render_header("habit", "Habits", ["Habits"], "3 active")
    assert full.splitlines() == [
        "🌱 <b>HABITS</b>",
        "<i>🏠 Dashboard › Habits</i>",
        "<i>3 active</i>",
    ]
    assert uic.render_header("home", "BAKA") == "🏠 <b>BAKA</b>"   # Home: no crumb


def test_render_section_and_footer():
    assert uic.render_section("Today", "body") == "<b>Today</b>\nbody"
    assert uic.render_footer() == ""
    footer = uic.render_footer("Slash is optional")
    assert footer.startswith(uic.separator())
    assert "<i>Slash is optional</i>" in footer


def test_render_page_joins_blocks_and_skips_empties():
    page = uic.render_page("H", "S1", "", "S2", footer="F")
    assert page == "H\n\nS1\n\nS2\n\nF"


def test_render_page_enforces_message_budget():
    with pytest.raises(ValueError):
        uic.render_page("H", "x" * 4100)


# ── Cards (§5.3, §5.4) ───────────────────────────────────────────────────

def test_information_card_shape_escaping_and_row_cap():
    card = uic.render_information_card("Task", [("Due", "Fri"), ("Pri", HOSTILE)])
    assert card.startswith("<b>Task</b>\n<blockquote>")
    assert "Due: Fri" in card and HOSTILE_ESC in card
    with pytest.raises(ValueError):
        uic.render_information_card("Too big", [("r", k) for k in range(9)])


def test_status_card_levels():
    card = uic.render_status_card("warning", "3 overdue", "<b>list</b>")
    assert card.startswith("⚠️ 3 overdue")
    assert "<blockquote><b>list</b></blockquote>" in card


def test_statistics_card_with_progress():
    card = uic.render_statistics_card("Week", [("Done", 12)], progress_percent=60)
    assert "Done: <b>12</b>" in card
    assert "▓▓▓▓▓▓░░░░ 60%" in card


# ── States (§5.4, §11.3) ─────────────────────────────────────────────────

@pytest.mark.parametrize("fn,ic", [
    (uic.render_success, "✅"), (uic.render_warning, "⚠️"),
    (uic.render_error, "❌"), (uic.render_info, "ℹ️"),
])
def test_state_messages_icon_with_words_and_detail(fn, ic):
    assert fn("Saved") == f"{ic} <b>Saved</b>"
    out = fn(HOSTILE, detail="id 17")
    assert HOSTILE_ESC in out and "<i>id 17</i>" in out


def test_loading_verbs_closed_set():
    assert uic.render_loading("Thinking") == "⏳ <i>Thinking…</i>"
    assert uic.render_loading() == "⏳ <i>Loading…</i>"
    with pytest.raises(ValueError):
        uic.render_loading("Reticulating")


# ── Empty states: §14 canonical copy pinned verbatim ─────────────────────

def test_empty_tasks_copy():
    out = uic.empty_tasks()
    assert "📌 <b>No tasks — you're all caught up.</b>" in out
    assert "add task Read chapter 4 tomorrow 6pm" in out


def test_empty_today_with_and_without_pointer():
    assert "Nothing due today." in uic.empty_today()
    assert "<i>2 due this week</i>" in uic.empty_today(week_count=2)


def test_empty_overdue_copy():
    assert uic.empty_overdue() == "✅ <b>Nothing overdue. Keep it that way!</b>"


def test_empty_habits_copy():
    out = uic.empty_habits()
    assert "🌱 <b>No habits yet — start one small daily win.</b>" in out
    assert "addhabit Drink water at 09:00 daily" in out


def test_empty_statistics_copy():
    assert "Not enough data yet" in uic.empty_statistics()


def test_empty_search_escapes_query():
    out = uic.empty_search("<script>")
    assert "&lt;script&gt;" in out and "Try fewer words" in out


def test_empty_ai_history_is_honest():
    assert "v15 analytics" in uic.empty_ai_history()


def test_empty_projects_and_dev():
    assert "attach materials" in uic.empty_projects()
    out = uic.empty_dev("bugs list is empty")
    assert "ℹ️ <b>No entries.</b>" in out and "bugs list is empty" in out


# ── Confirmation dialog (§8) ─────────────────────────────────────────────

def test_confirmation_embeds_prebuilt_preview_unescaped():
    out = uic.render_confirmation("Delete this task?", "<b>[17]</b> Title",
                                   danger=True)
    assert out.startswith("⚠️ <b>Delete this task?</b>")
    assert "<blockquote><b>[17]</b> Title</blockquote>" in out
    assert "<i>This cannot be undone.</i>" in out


def test_confirmation_non_danger_uses_info_icon():
    out = uic.render_confirmation("Save this?", "preview")
    assert out.startswith("ℹ️") and "cannot be undone" not in out


# ── Buttons (§2.5, §6.2, §5.7, §8) ───────────────────────────────────────

def test_button_callback_size_limit():
    btn = uic.button("X", "nav:tasks")
    assert btn.callback_data == "nav:tasks"
    with pytest.raises(ValueError):
        uic.button("X", "x" * 65)


def test_primary_row_is_singular():
    row = uic.primary_row(uic.label("add_task"), "wiz:addtask")
    assert len(row) == 1 and row[0].text == "➕ Add Task"


def test_action_row_width_limits():
    assert len(uic.action_row(("A", "a"), ("B", "b"), ("C", "c"))) == 3
    with pytest.raises(ValueError):
        uic.action_row(("A", "a"), ("B", "b"), ("C", "c"), ("D", "d"))
    with pytest.raises(ValueError):
        uic.action_row()


def test_nav_row_fixed_order_and_page_classes():
    full = uic.nav_row(back_cb="nav:tasks", refresh_cb="nav:t:r",
                        home_cb="nav:home")
    assert [b.text for b in full] == ["⬅ Back", "🔄 Refresh", "🏠 Home"]
    root = uic.nav_row(refresh_cb="nav:home:r")          # Home page class
    assert [b.text for b in root] == ["🔄 Refresh"]
    detail = uic.nav_row(back_cb="nav:tasks", home_cb="nav:home")
    assert [b.text for b in detail] == ["⬅ Back", "🏠 Home"]
    with pytest.raises(ValueError):
        uic.nav_row()                                     # no exit = trap


def test_confirmation_row_safe_left():
    row = uic.confirmation_row("act:cancel", "🗑 Yes, delete", "act:del:17")
    assert [b.text for b in row] == ["✕ Cancel", "🗑 Yes, delete"]


def test_pagination_row_edges():
    first = uic.pagination_row("pg:tasks:all", 1, 3)
    assert [b.text for b in first] == ["1/3", "Next ›"]
    mid = uic.pagination_row("pg:tasks:all", 2, 3)
    assert [b.text for b in mid] == ["‹ Prev", "2/3", "Next ›"]
    assert mid[0].callback_data == "pg:tasks:all:1"
    assert mid[2].callback_data == "pg:tasks:all:3"
    last = uic.pagination_row("pg:tasks:all", 3, 3)
    assert [b.text for b in last] == ["‹ Prev", "3/3"]


def test_keyboard_caps_and_empty_rules():
    kb = uic.keyboard(uic.primary_row("A", "a"),
                       [],                                # skipped
                       uic.nav_row(home_cb="nav:home"))
    assert len(kb.inline_keyboard) == 2
    with pytest.raises(ValueError):
        uic.keyboard()
    with pytest.raises(ValueError):
        uic.keyboard([uic.button(str(k), f"c{k}") for k in range(4)])
    with pytest.raises(ValueError):
        uic.keyboard(*[[uic.button(str(k), f"c{k}")] for k in range(13)])


# ── fmt.link (Phase 0's one fmt addition) ────────────────────────────────

def test_link_escapes_text_and_quotes_in_url():
    out = link("docs <here>", 'https://x.example/a"b')
    assert out == '<a href="https://x.example/a%22b">docs &lt;here&gt;</a>'
