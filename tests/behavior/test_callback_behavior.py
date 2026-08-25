"""
Callback regression lock tests — Phase 4C.

Freeze callback query behavior and inline keyboard interactions as
immutable baselines. These tests characterize the CURRENT production
behavior exactly — no improvements, no refactoring.

Run: pytest tests/behavior/test_callback_behavior.py -v
"""
import sqlite3
from contextlib import ExitStack
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import database as db
from main import (
    handle_callback,
    route_dashboard_callback,
    is_admin,
    UI,
)
from core.storage import Storage

IST = ZoneInfo("Asia/Kolkata")
UID = 555000111


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def temp_db(monkeypatch, tmp_path):
    """Fresh temporary database for each test."""
    db_path = str(tmp_path / "test_planner.db")
    monkeypatch.setattr(db, "DB_NAME", db_path)
    db.init_db()
    yield db_path


@pytest.fixture
def storage(temp_db):
    return Storage()


@pytest.fixture
def mock_update():
    """Mock Telegram Update with callback_query."""
    update = MagicMock()
    update.callback_query = MagicMock()
    update.callback_query.from_user = MagicMock()
    update.callback_query.from_user.id = UID
    update.callback_query.data = ""
    update.callback_query.message = MagicMock()
    update.callback_query.message.chat = MagicMock()
    update.callback_query.message.chat.id = UID
    update.callback_query.message.message_id = 1
    return update


@pytest.fixture
def mock_context():
    """Mock Telegram Context."""
    context = MagicMock()
    context.bot = MagicMock()
    context.bot.send_message = AsyncMock()
    context.args = []
    return context


def _make_patches():
    """Create all the patch objects for Telegram services."""
    patches = {
        "answer": patch("main.safe_answer_callback_query", new_callable=AsyncMock),
        "edit": patch("main.safe_edit_message_text", new_callable=AsyncMock),
        "get_task": patch("main.get_task_by_id"),
        "get_tasks": patch("main.get_tasks"),
        "get_goals": patch("main.get_goals_full"),
        "get_habits": patch("main.get_habits"),
        "get_proj": patch("main.get_project_overview"),
        "get_materials": patch("main.get_all_pending_materials"),
        "is_habit": patch("main.is_habit"),
        "log_habit": patch("main.log_habit_completion"),
        "mark_done": patch("main.mark_done"),
        "log_comp": patch("main.log_completion"),
        "log_int": patch("main.db_log_interaction"),
        "snooze": patch("main.snooze_task"),
        "inc_snooze": patch("main.increment_snooze_count"),
        "get_snooze": patch("main.get_snooze_count"),
        "suggest": patch("main.suggest_time_for_task"),
        "postpone": patch("main.postpone_task"),
        "pause": patch("main.pause_task"),
        "resume": patch("main.resume_task"),
        "mark_deadline": patch("main.mark_as_deadline"),
        "stop_rem": patch("main.stop_reminders"),
        "del_task": patch("main.delete_task"),
        "add_worklog": patch("main.add_worklog"),
        "mark_mat": patch("main.mark_material_acquired"),
        "is_admin": patch("main.is_admin", return_value=False),
        "get_pending": patch("main.get_pending_action"),
        "clear_state": patch("main.clear_state"),
        "task_exists": patch("main.task_exists"),
        "add_task": patch("main.add_task"),
        "set_pending": patch("main.set_pending_action"),
        "set_editing": patch("main.set_editing"),
        "run_blocking": patch("main.run_blocking"),
        "breakdown": patch("main.generate_task_breakdown"),
        "yes_no": patch("main.yes_no_menu"),
        "gather_dash": patch("main._gather_dashboard_data"),
        "build_today": patch("main._build_today_groups"),
        "build_stats": patch("main._build_stats"),
    }
    return patches


@pytest.fixture(autouse=True)
def patch_telegram_services():
    """Patch external Telegram services to avoid network calls."""
    patches = _make_patches()

    # Use ExitStack to manage all patches
    with ExitStack() as stack:
        mocks = {k: stack.enter_context(v) for k, v in patches.items()}

        # Setup common mocks
        mocks["gather_dash"].return_value = {
            "pending": 0, "overdue": 0, "today_count": 0,
            "done_today": 0, "goals": [], "habits": [],
            "completion_rate": 0, "streak_best": 0,
            "date_str": datetime.now(IST).strftime("%A, %d %B")
        }
        mocks["build_today"].return_value = {
            "overdue": [], "high": [], "upcoming": [], "done": []
        }
        mocks["build_stats"].return_value = {
            "completion_rate": 0, "overdue_rate": 0,
            "total_tasks": 0, "done_tasks": 0,
            "top_categories": [], "tone": "", "active_hour": None,
            "insights": []
        }

        yield mocks


# ── Helpers ──────────────────────────────────────────────────────────────


def setup_callback(update, data, task_id=None):
    """Set up a callback query on the mock update."""
    update.callback_query.data = data
    if task_id is not None:
        # Parts will be parsed inside handle_callback
        pass


def get_edit_call(mock_edit):
    """Extract the text and keyboard from the last edit call."""
    if mock_edit.called:
        args, kwargs = mock_edit.call_args
        return args[1] if len(args) > 1 else kwargs.get("text"), kwargs.get("reply_markup")
    return None, None


# ── DASHBOARD CALLBACK TESTS ─────────────────────────────────────────────


class TestDashboardCallbacks:
    """Tests for dash:* callback namespace."""

    @pytest.mark.asyncio
    async def test_dash_home_renders_dashboard(self, mock_update, mock_context, patch_telegram_services):
        """dash:home renders the dashboard card."""
        setup_callback(mock_update, "dash:home")

        await handle_callback(mock_update, mock_context)

        patch_telegram_services["gather_dash"].assert_called()
        patch_telegram_services["edit"].assert_called()
        text, _ = get_edit_call(patch_telegram_services["edit"])
        assert "BAKA DASHBOARD" in text

    @pytest.mark.asyncio
    async def test_dash_today_renders_today_view(self, mock_update, mock_context, patch_telegram_services):
        """dash:today renders the today grouped view."""
        setup_callback(mock_update, "dash:today")

        await handle_callback(mock_update, mock_context)

        patch_telegram_services["build_today"].assert_called()
        patch_telegram_services["edit"].assert_called()

    @pytest.mark.asyncio
    async def test_dash_tasks_renders_task_list(self, mock_update, mock_context, patch_telegram_services):
        """dash:tasks renders the task list card."""
        setup_callback(mock_update, "dash:tasks")

        await handle_callback(mock_update, mock_context)

        patch_telegram_services["get_tasks"].assert_called()
        patch_telegram_services["edit"].assert_called()

    @pytest.mark.asyncio
    async def test_dash_task_detail_renders_task_card(self, mock_update, mock_context, patch_telegram_services):
        """dash:task:<id> renders the task detail card."""
        mock_task = (1, "Test task", "2026-08-24", "10:00", "Work", "high", 0, "daily")
        patch_telegram_services["get_task"].return_value = mock_task
        setup_callback(mock_update, "dash:task:1")

        await handle_callback(mock_update, mock_context)

        patch_telegram_services["get_task"].assert_called_with(1, UID)
        patch_telegram_services["edit"].assert_called()
        text, _ = get_edit_call(patch_telegram_services["edit"])
        assert "Test task" in text

    @pytest.mark.asyncio
    async def test_dash_goals_renders_goals(self, mock_update, mock_context, patch_telegram_services):
        """dash:goals renders the goals card."""
        patch_telegram_services["get_goals"].return_value = []
        setup_callback(mock_update, "dash:goals")

        await handle_callback(mock_update, mock_context)

        patch_telegram_services["get_goals"].assert_called()
        patch_telegram_services["edit"].assert_called()

    @pytest.mark.asyncio
    async def test_dash_habits_renders_habits(self, mock_update, mock_context, patch_telegram_services):
        """dash:habits renders the habits card."""
        patch_telegram_services["get_habits"].return_value = []
        setup_callback(mock_update, "dash:habits")

        await handle_callback(mock_update, mock_context)

        patch_telegram_services["get_habits"].assert_called()
        patch_telegram_services["edit"].assert_called()

    @pytest.mark.asyncio
    async def test_dash_stats_renders_stats(self, mock_update, mock_context, patch_telegram_services):
        """dash:stats renders the stats card."""
        setup_callback(mock_update, "dash:stats")

        await handle_callback(mock_update, mock_context)

        patch_telegram_services["build_stats"].assert_called()
        patch_telegram_services["edit"].assert_called()


# ── TASK CALLBACK TESTS ───────────────────────────────────────────────────


class TestTaskCallbacks:
    """Tests for task action callbacks."""

    @pytest.mark.asyncio
    async def test_done_regular_task_marks_done(self, mock_update, mock_context, patch_telegram_services):
        """done:<id> marks a regular task as done."""
        mock_task = (1, "Test task", "2026-08-24", "10:00", "Work", "high", 0)
        patch_telegram_services["get_task"].return_value = mock_task
        patch_telegram_services["is_habit"].return_value = False
        setup_callback(mock_update, "done:1")

        await handle_callback(mock_update, mock_context)

        patch_telegram_services["mark_done"].assert_called_with(1, UID)
        patch_telegram_services["edit"].assert_called()
        text, _ = get_edit_call(patch_telegram_services["edit"])
        assert "Done!" in text
        assert "Test task" in text

    @pytest.mark.asyncio
    async def test_done_habit_logs_completion(self, mock_update, mock_context, patch_telegram_services):
        """done:<id> logs habit completion for habit tasks."""
        mock_task = (1, "Meditate", "2026-08-24", "07:00", "Health", "medium", 0, "daily")
        patch_telegram_services["get_task"].return_value = mock_task
        patch_telegram_services["is_habit"].return_value = True
        patch_telegram_services["log_habit"].return_value = (True, 5)
        setup_callback(mock_update, "done:1")

        await handle_callback(mock_update, mock_context)

        patch_telegram_services["log_habit"].assert_called_with(1, UID)
        patch_telegram_services["edit"].assert_called()
        text, _ = get_edit_call(patch_telegram_services["edit"])
        assert "Habit completed" in text
        assert "Streak: *5*" in text

    @pytest.mark.asyncio
    async def test_done_task_not_found(self, mock_update, mock_context, patch_telegram_services):
        """done:<id> shows error for nonexistent task."""
        patch_telegram_services["get_task"].return_value = None
        setup_callback(mock_update, "done:999")

        await handle_callback(mock_update, mock_context)

        patch_telegram_services["edit"].assert_called()
        text, _ = get_edit_call(patch_telegram_services["edit"])
        assert "Task not found" in text

    @pytest.mark.asyncio
    async def test_snooze_sets_snooze_time(self, mock_update, mock_context, patch_telegram_services):
        """snooze:<id>:<minutes> sets snooze until time."""
        mock_task = (1, "Test task", "2026-08-24", "10:00", "Work", "high", 0)
        patch_telegram_services["get_task"].return_value = mock_task
        patch_telegram_services["get_snooze"].return_value = 1
        setup_callback(mock_update, "snooze:1:10")

        await handle_callback(mock_update, mock_context)

        patch_telegram_services["snooze"].assert_called()
        patch_telegram_services["inc_snooze"].assert_called()
        patch_telegram_services["edit"].assert_called()
        text, _ = get_edit_call(patch_telegram_services["edit"])
        assert "Snoozed for 10 minutes" in text

    @pytest.mark.asyncio
    async def test_snooze_repeated_shows_suggestion(self, mock_update, mock_context, patch_telegram_services):
        """snooze:<id>:<minutes> shows suggestion after 3+ snoozes."""
        mock_task = (1, "Test task", "2026-08-24", "10:00", "Work", "high", 0)
        patch_telegram_services["get_task"].return_value = mock_task
        patch_telegram_services["get_snooze"].return_value = 3
        patch_telegram_services["suggest"].return_value = "14:00"
        setup_callback(mock_update, "snooze:1:10")

        await handle_callback(mock_update, mock_context)

        patch_telegram_services["edit"].assert_called()
        text, _ = get_edit_call(patch_telegram_services["edit"])
        assert "You've snoozed this 3 times" in text
        assert "14:00" in text

    @pytest.mark.asyncio
    async def test_postpone_moves_to_tomorrow(self, mock_update, mock_context, patch_telegram_services):
        """postpone:<id> moves task to tomorrow."""
        mock_task = (1, "Test task", "2026-08-24", "10:00", "Work", "high", 0)
        patch_telegram_services["get_task"].return_value = mock_task
        setup_callback(mock_update, "postpone:1")

        await handle_callback(mock_update, mock_context)

        patch_telegram_services["postpone"].assert_called()
        patch_telegram_services["edit"].assert_called()
        text, _ = get_edit_call(patch_telegram_services["edit"])
        assert "Moved to tomorrow" in text

    @pytest.mark.asyncio
    async def test_pause_stops_reminders(self, mock_update, mock_context, patch_telegram_services):
        """pause:<id> pauses the task."""
        setup_callback(mock_update, "pause:1")

        await handle_callback(mock_update, mock_context)

        patch_telegram_services["pause"].assert_called_with(1, UID)
        patch_telegram_services["edit"].assert_called()
        text, _ = get_edit_call(patch_telegram_services["edit"])
        assert "paused" in text.lower()

    @pytest.mark.asyncio
    async def test_resume_restarts_reminders(self, mock_update, mock_context, patch_telegram_services):
        """resume:<id> resumes the task."""
        setup_callback(mock_update, "resume:1")

        await handle_callback(mock_update, mock_context)

        patch_telegram_services["resume"].assert_called_with(1, UID)
        patch_telegram_services["edit"].assert_called()
        text, _ = get_edit_call(patch_telegram_services["edit"])
        assert "resumed" in text.lower()

    @pytest.mark.asyncio
    async def test_unflagdeadline_mutes_buffer(self, mock_update, mock_context, patch_telegram_services):
        """unflagdeadline:<id> mutes buffer reminders."""
        setup_callback(mock_update, "unflagdeadline:1")

        await handle_callback(mock_update, mock_context)

        patch_telegram_services["mark_deadline"].assert_called_with(1, UID, False)
        patch_telegram_services["edit"].assert_called()
        text, _ = get_edit_call(patch_telegram_services["edit"])
        assert "Buffer reminders muted" in text

    @pytest.mark.asyncio
    async def test_finish_yes_completes_task(self, mock_update, mock_context, patch_telegram_services):
        """finish_yes:<id> marks task as done."""
        mock_task = (1, "Test task", "2026-08-24", "10:00", "Work", "high", 0)
        patch_telegram_services["get_task"].return_value = mock_task
        patch_telegram_services["is_habit"].return_value = False
        setup_callback(mock_update, "finish_yes:1")

        await handle_callback(mock_update, mock_context)

        patch_telegram_services["mark_done"].assert_called_with(1, UID)
        patch_telegram_services["edit"].assert_called()
        text, _ = get_edit_call(patch_telegram_services["edit"])
        assert "Great job" in text
        assert "Test task" in text

    @pytest.mark.asyncio
    async def test_finish_no_shows_options(self, mock_update, mock_context, patch_telegram_services):
        """finish_no:<id> shows reschedule/breakdown/stop options."""
        mock_task = (1, "Test task", "2026-08-24", "10:00", "Work", "high", 0)
        patch_telegram_services["get_task"].return_value = mock_task
        setup_callback(mock_update, "finish_no:1")

        await handle_callback(mock_update, mock_context)

        patch_telegram_services["edit"].assert_called()
        text, keyboard = get_edit_call(patch_telegram_services["edit"])
        assert "No worries" in text
        assert "postpone:1" in str(keyboard)
        assert "dobreak:1" in str(keyboard)
        assert "stoprem:1" in str(keyboard)

    @pytest.mark.asyncio
    async def test_dobreak_triggers_breakdown(self, mock_update, mock_context, patch_telegram_services):
        """dobreak:<id> triggers AI breakdown and shows confirmation."""
        mock_task = (1, "Big task", "2026-08-24", "10:00", "Work", "high", 0)
        patch_telegram_services["get_task"].return_value = mock_task
        patch_telegram_services["run_blocking"].return_value = [
            {"title": "Step 1"}, {"title": "Step 2"}
        ]
        patch_telegram_services["yes_no"].return_value = MagicMock()
        setup_callback(mock_update, "dobreak:1")

        await handle_callback(mock_update, mock_context)

        # run_blocking is called with generate_task_breakdown and args
        patch_telegram_services["run_blocking"].assert_called()
        patch_telegram_services["set_pending"].assert_called()
        patch_telegram_services["edit"].assert_called()
        text, _ = get_edit_call(patch_telegram_services["edit"])
        assert "Breaking down" in text
        assert "Big task" in text

    @pytest.mark.asyncio
    async def test_stoprem_stops_reminders(self, mock_update, mock_context, patch_telegram_services):
        """stoprem:<id> stops reminders for task."""
        mock_task = (1, "Test task", "2026-08-24", "10:00", "Work", "high", 0)
        patch_telegram_services["get_task"].return_value = mock_task
        setup_callback(mock_update, "stoprem:1")

        await handle_callback(mock_update, mock_context)

        patch_telegram_services["stop_rem"].assert_called_with(1, UID)
        patch_telegram_services["edit"].assert_called()
        text, _ = get_edit_call(patch_telegram_services["edit"])
        assert "Reminders stopped" in text
        assert "Test task" in text

    @pytest.mark.asyncio
    async def test_deltask_deletes_task(self, mock_update, mock_context, patch_telegram_services):
        """deltask:<id> deletes the task."""
        mock_task = (1, "Test task", "2026-08-24", "10:00", "Work", "high", 0)
        patch_telegram_services["get_task"].return_value = mock_task
        setup_callback(mock_update, "deltask:1")

        await handle_callback(mock_update, mock_context)

        patch_telegram_services["del_task"].assert_called_with(1, UID)
        patch_telegram_services["edit"].assert_called()
        text, _ = get_edit_call(patch_telegram_services["edit"])
        assert "Deleted" in text
        assert "Test task" in text


# ── PROJECT CALLBACK TESTS ────────────────────────────────────────────────


class TestProjectCallbacks:
    """Tests for proj:* callback namespace."""

    @pytest.mark.asyncio
    async def test_proj_started_logs_worklog(self, mock_update, mock_context, patch_telegram_services):
        """proj:started:<gid> logs work started."""
        setup_callback(mock_update, "proj:started:5")

        await handle_callback(mock_update, mock_context)

        patch_telegram_services["add_worklog"].assert_called_with(UID, 5, "Work started", kind="started")
        patch_telegram_services["edit"].assert_called()
        text, _ = get_edit_call(patch_telegram_services["edit"])
        assert "started" in text.lower()
        assert "5" in text

    @pytest.mark.asyncio
    async def test_proj_finished_logs_worklog(self, mock_update, mock_context, patch_telegram_services):
        """proj:finished:<gid> logs project finished."""
        setup_callback(mock_update, "proj:finished:5")

        await handle_callback(mock_update, mock_context)

        patch_telegram_services["add_worklog"].assert_called_with(UID, 5, "Project finished", kind="finished")
        patch_telegram_services["edit"].assert_called()
        text, _ = get_edit_call(patch_telegram_services["edit"])
        assert "finished" in text.lower()

    @pytest.mark.asyncio
    async def test_proj_got_marks_material_acquired(self, mock_update, mock_context, patch_telegram_services):
        """proj:got:<mid> marks material as acquired."""
        setup_callback(mock_update, "proj:got:10")

        await handle_callback(mock_update, mock_context)

        patch_telegram_services["mark_mat"].assert_called_with(UID, 10, True)
        patch_telegram_services["edit"].assert_called()
        text, _ = get_edit_call(patch_telegram_services["edit"])
        assert "acquired" in text.lower()

    @pytest.mark.asyncio
    async def test_proj_view_shows_project_overview(self, mock_update, mock_context, patch_telegram_services):
        """proj:view:<gid> shows project overview."""
        mock_proj = {
            "title": "Project X", "progress": 60,
            "materials_acquired": 3, "materials_total": 5
        }
        patch_telegram_services["get_proj"].return_value = mock_proj
        setup_callback(mock_update, "proj:view:5")

        await handle_callback(mock_update, mock_context)

        patch_telegram_services["get_proj"].assert_called_with(UID, 5)
        patch_telegram_services["edit"].assert_called()
        text, _ = get_edit_call(patch_telegram_services["edit"])
        assert "Project X" in text
        assert "60%" in text

    @pytest.mark.asyncio
    async def test_proj_shopping_shows_pending_materials(self, mock_update, mock_context, patch_telegram_services):
        """proj:shopping shows shopping list."""
        patch_telegram_services["get_materials"].return_value = [("Item A",), ("Item B",)]
        setup_callback(mock_update, "proj:shopping")

        await handle_callback(mock_update, mock_context)

        patch_telegram_services["get_materials"].assert_called_with(UID)
        patch_telegram_services["edit"].assert_called()
        text, _ = get_edit_call(patch_telegram_services["edit"])
        assert "Still need" in text
        assert "Item A" in text
        assert "Item B" in text

    @pytest.mark.asyncio
    async def test_proj_shopping_empty(self, mock_update, mock_context, patch_telegram_services):
        """proj:shopping shows empty message when no pending materials."""
        patch_telegram_services["get_materials"].return_value = []
        setup_callback(mock_update, "proj:shopping")

        await handle_callback(mock_update, mock_context)

        patch_telegram_services["edit"].assert_called()
        text, _ = get_edit_call(patch_telegram_services["edit"])
        assert "empty" in text.lower()


# ── VISION CALLBACK TESTS ─────────────────────────────────────────────────


class TestVisionCallbacks:
    """Tests for vision-related callbacks."""

    @pytest.mark.asyncio
    async def test_vision_save_tasks_creates_tasks(self, mock_update, mock_context, patch_telegram_services):
        """vision_save_tasks extracts and creates tasks from vision result."""
        patch_telegram_services["get_pending"].return_value = (
            "vision_result",
            {"text": "- Task 1\n- Task 2\n- Task 3"}
        )
        patch_telegram_services["task_exists"].return_value = False
        patch_telegram_services["add_task"].side_effect = [1, 2, 3]
        setup_callback(mock_update, "vision_save_tasks")

        await handle_callback(mock_update, mock_context)

        patch_telegram_services["clear_state"].assert_called()
        assert patch_telegram_services["add_task"].call_count == 3
        patch_telegram_services["edit"].assert_called()
        text, _ = get_edit_call(patch_telegram_services["edit"])
        assert "Created 3 task(s)" in text
        assert "Task 1" in text

    @pytest.mark.asyncio
    async def test_vision_save_tasks_expired(self, mock_update, mock_context, patch_telegram_services):
        """vision_save_tasks shows expired message when no pending action."""
        patch_telegram_services["get_pending"].return_value = (None, None)
        setup_callback(mock_update, "vision_save_tasks")

        await handle_callback(mock_update, mock_context)

        patch_telegram_services["edit"].assert_called()
        text, _ = get_edit_call(patch_telegram_services["edit"])
        assert "expired" in text.lower()

    @pytest.mark.asyncio
    async def test_vision_ask_again_shows_prompt(self, mock_update, mock_context, patch_telegram_services):
        """vision_ask_again prompts for more specific caption."""
        setup_callback(mock_update, "vision_ask_again")

        await handle_callback(mock_update, mock_context)

        patch_telegram_services["edit"].assert_called()
        text, _ = get_edit_call(patch_telegram_services["edit"])
        assert "Send the same image again" in text
        assert "more specific caption" in text


# ── DEVELOPER CENTER CALLBACK TESTS ───────────────────────────────────────


class TestDeveloperCallbacks:
    """Tests for dev:* callback namespace (admin-only)."""

    @pytest.mark.asyncio
    async def test_dev_menu_renders_for_admin(self, mock_update, mock_context, patch_telegram_services):
        """dev:menu renders developer menu for admin."""
        patch_telegram_services["is_admin"].return_value = True
        with patch("main.dbg.is_debug_on", return_value=False):
            setup_callback(mock_update, "dev:menu")

            await handle_callback(mock_update, mock_context)

        patch_telegram_services["edit"].assert_called()
        text, keyboard = get_edit_call(patch_telegram_services["edit"])
        assert "DEVELOPER CENTER" in text

    @pytest.mark.asyncio
    async def test_dev_menu_silent_for_non_admin(self, mock_update, mock_context, patch_telegram_services):
        """dev:menu is silent no-op for non-admin."""
        patch_telegram_services["is_admin"].return_value = False
        setup_callback(mock_update, "dev:menu")

        await handle_callback(mock_update, mock_context)

        patch_telegram_services["edit"].assert_not_called()

    @pytest.mark.asyncio
    async def test_dev_toggle_toggles_debug(self, mock_update, mock_context, patch_telegram_services):
        """dev:toggle toggles debug mode for admin."""
        patch_telegram_services["is_admin"].return_value = True
        with patch("main.dbg.toggle_debug", return_value=True) as mock_toggle:
            setup_callback(mock_update, "dev:toggle")

            await handle_callback(mock_update, mock_context)

            mock_toggle.assert_called_with(UID)
            patch_telegram_services["edit"].assert_called()

    @pytest.mark.asyncio
    async def test_dev_st_run_executes_selftest(self, mock_update, mock_context, patch_telegram_services):
        """dev:st:run executes self-test suite."""
        patch_telegram_services["is_admin"].return_value = True
        from core.selftest.results import SelfTestReport
        from core.selftest.models import SelfTestResult, Status

        # Create a proper mock report
        mock_report = SelfTestReport(
            results=[
                SelfTestResult(name="test1", category="core", status=Status.PASS, message="ok", duration_ms=10),
                SelfTestResult(name="test2", category="core", status=Status.PASS, message="ok", duration_ms=20),
                SelfTestResult(name="test3", category="core", status=Status.PASS, message="ok", duration_ms=30),
                SelfTestResult(name="test4", category="core", status=Status.PASS, message="ok", duration_ms=40),
                SelfTestResult(name="test5", category="core", status=Status.PASS, message="ok", duration_ms=50),
            ],
            duration_ms=150
        )

        # Patch run_blocking to return our mock report (it's called with selftest.run as first arg)
        mock_run_blocking = patch_telegram_services["run_blocking"]
        mock_run_blocking.return_value = mock_report

        setup_callback(mock_update, "dev:st:run")

        await handle_callback(mock_update, mock_context)

        # run_blocking should have been called with selftest.run
        mock_run_blocking.assert_called()
        # First call shows running, second shows results
        assert patch_telegram_services["edit"].call_count >= 2


# ── COMMAND REFERENCE CALLBACK TESTS ──────────────────────────────────────


class TestCommandReferenceCallbacks:
    """Tests for cmd:* callback namespace."""

    @pytest.mark.asyncio
    async def test_cmd_category_renders_page(self, mock_update, mock_context, patch_telegram_services):
        """cmd:<category> renders command reference page."""
        with patch("main.UI.commands_category_page", return_value=("Text", MagicMock())) as mock_cmd:
            setup_callback(mock_update, "cmd:tasks")

            await handle_callback(mock_update, mock_context)

            mock_cmd.assert_called()
            patch_telegram_services["edit"].assert_called()
            text, _ = get_edit_call(patch_telegram_services["edit"])
            assert text == "Text"


# ── CONTROL PLANE CALLBACK TESTS ──────────────────────────────────────────


class TestControlPlaneCallbacks:
    """Tests for ctl:* callback namespace (admin-only)."""

    @pytest.mark.asyncio
    async def test_ctl_silent_for_non_admin(self, mock_update, mock_context, patch_telegram_services):
        """ctl:* is silent no-op for non-admin."""
        patch_telegram_services["is_admin"].return_value = False
        setup_callback(mock_update, "ctl:status")

        await handle_callback(mock_update, mock_context)

        patch_telegram_services["edit"].assert_not_called()


# ── CALLBACK ROUTING BEHAVIOR TESTS ───────────────────────────────────────


class TestCallbackRouting:
    """Tests for callback routing and parsing behavior."""

    @pytest.mark.asyncio
    async def test_callback_logs_debug_info(self, mock_update, mock_context, patch_telegram_services):
        """Callback handler logs user and data for debugging."""
        with patch("main.logger.info") as mock_log:
            setup_callback(mock_update, "dash:home")

            await handle_callback(mock_update, mock_context)

            mock_log.assert_called()
            log_call = str(mock_log.call_args)
            assert "user=" in log_call
            assert "page=home" in log_call

    @pytest.mark.asyncio
    async def test_callback_safe_answer_called(self, mock_update, mock_context, patch_telegram_services):
        """safe_answer_callback_query is always called first."""
        setup_callback(mock_update, "dash:home")

        await handle_callback(mock_update, mock_context)

        patch_telegram_services["answer"].assert_called_once_with(mock_update.callback_query)

    @pytest.mark.asyncio
    async def test_callback_parses_task_id_safely(self, mock_update, mock_context, patch_telegram_services):
        """Task ID is parsed safely (non-numeric payloads don't crash)."""
        setup_callback(mock_update, "dash:home")  # Non-numeric second part

        await handle_callback(mock_update, mock_context)

        # Should not crash
        patch_telegram_services["edit"].assert_called()

    @pytest.mark.asyncio
    async def test_callback_unknown_action_silent(self, mock_update, mock_context, patch_telegram_services):
        """Unknown callback action is handled silently (no crash)."""
        setup_callback(mock_update, "unknown:action")

        await handle_callback(mock_update, mock_context)

        # Should not crash, just not match any branch
        patch_telegram_services["answer"].assert_called()


# ── ROUTE DASHBOARD CALLBACK TESTS ────────────────────────────────────────


class TestRouteDashboardCallback:
    """Tests for the route_dashboard_callback function directly."""

    @pytest.mark.asyncio
    async def test_route_dash_home(self, mock_update, mock_context, patch_telegram_services):
        """route_dashboard_callback handles dash:home."""
        patch_telegram_services["gather_dash"].return_value = {"pending": 0}
        mock_update.callback_query.data = "dash:home"

        await route_dashboard_callback(mock_update, mock_context, ["dash", "home"])

        patch_telegram_services["edit"].assert_called()

    @pytest.mark.asyncio
    async def test_route_dash_today(self, mock_update, mock_context, patch_telegram_services):
        """route_dashboard_callback handles dash:today."""
        mock_update.callback_query.data = "dash:today"

        await route_dashboard_callback(mock_update, mock_context, ["dash", "today"])

        patch_telegram_services["build_today"].assert_called()
        patch_telegram_services["edit"].assert_called()

    @pytest.mark.asyncio
    async def test_route_dash_tasks(self, mock_update, mock_context, patch_telegram_services):
        """route_dashboard_callback handles dash:tasks."""
        mock_update.callback_query.data = "dash:tasks"

        await route_dashboard_callback(mock_update, mock_context, ["dash", "tasks"])

        patch_telegram_services["get_tasks"].assert_called()
        patch_telegram_services["edit"].assert_called()

    @pytest.mark.asyncio
    async def test_route_dash_task_detail(self, mock_update, mock_context, patch_telegram_services):
        """route_dashboard_callback handles dash:task:<id>."""
        mock_task = (1, "Test", "2026-08-24", "10:00", "Work", "high", 0, "daily")
        patch_telegram_services["get_task"].return_value = mock_task
        mock_update.callback_query.data = "dash:task:1"

        await route_dashboard_callback(mock_update, mock_context, ["dash", "task", "1"])

        patch_telegram_services["get_task"].assert_called_with(1, UID)
        patch_telegram_services["edit"].assert_called()

    @pytest.mark.asyncio
    async def test_route_dash_goals(self, mock_update, mock_context, patch_telegram_services):
        """route_dashboard_callback handles dash:goals."""
        mock_update.callback_query.data = "dash:goals"

        await route_dashboard_callback(mock_update, mock_context, ["dash", "goals"])

        patch_telegram_services["get_goals"].assert_called()
        patch_telegram_services["edit"].assert_called()

    @pytest.mark.asyncio
    async def test_route_dash_goalplus_increments(self, mock_update, mock_context, patch_telegram_services):
        """route_dashboard_callback handles dash:goalplus:<id>."""
        with patch("main.update_goal_progress", return_value=(1, 110, True)) as mock_update_goal:
            mock_update.callback_query.data = "dash:goalplus:1"

            await route_dashboard_callback(mock_update, mock_context, ["dash", "goalplus", "1"])

            mock_update_goal.assert_called_with(1, UID, 10)
            patch_telegram_services["edit"].assert_called()

    @pytest.mark.asyncio
    async def test_route_dash_goalminus_decrements(self, mock_update, mock_context, patch_telegram_services):
        """route_dashboard_callback handles dash:goalminus:<id>."""
        with patch("main.update_goal_progress") as mock_update_goal:
            mock_update.callback_query.data = "dash:goalminus:1"

            await route_dashboard_callback(mock_update, mock_context, ["dash", "goalminus", "1"])

            mock_update_goal.assert_called_with(1, UID, -10)
            patch_telegram_services["edit"].assert_called()

    @pytest.mark.asyncio
    async def test_route_dash_habits(self, mock_update, mock_context, patch_telegram_services):
        """route_dashboard_callback handles dash:habits."""
        mock_update.callback_query.data = "dash:habits"

        await route_dashboard_callback(mock_update, mock_context, ["dash", "habits"])

        patch_telegram_services["get_habits"].assert_called()
        patch_telegram_services["edit"].assert_called()

    @pytest.mark.asyncio
    async def test_route_dash_stats(self, mock_update, mock_context, patch_telegram_services):
        """route_dashboard_callback handles dash:stats."""
        mock_update.callback_query.data = "dash:stats"

        await route_dashboard_callback(mock_update, mock_context, ["dash", "stats"])

        patch_telegram_services["build_stats"].assert_called()
        patch_telegram_services["edit"].assert_called()

    @pytest.mark.asyncio
    async def test_route_dash_edit_triggers_edit_flow(self, mock_update, mock_context, patch_telegram_services):
        """route_dashboard_callback handles dash:edit:<id>."""
        mock_update.callback_query.data = "dash:edit:1"

        await route_dashboard_callback(mock_update, mock_context, ["dash", "edit", "1"])

        patch_telegram_services["set_editing"].assert_called_with(UID, 1)
        mock_context.bot.send_message.assert_called()
        call_args = mock_context.bot.send_message.call_args
        assert "Editing task" in str(call_args)


# ── UI CARD CALLBACK DATA TESTS ───────────────────────────────────────────


class TestUICardCallbacks:
    """Tests that verify UI cards generate expected callback_data values."""

    def test_dashboard_card_callbacks(self):
        """Dashboard card has correct callback_data values."""
        data = {"pending": 0, "overdue": 0, "today_count": 0, "done_today": 0,
                "goals": [], "habits": [], "completion_rate": 0, "streak_best": 0,
                "date_str": "Monday, 24 August"}
        text, keyboard = UI.dashboard_card(data)

        # Extract all callback_data from keyboard
        callbacks = []
        for row in keyboard.inline_keyboard:
            for btn in row:
                callbacks.append(btn.callback_data)

        expected = ["dash:today", "dash:goals", "dash:habits",
                    "dash:tasks", "dash:stats", "dash:home"]
        for cb in expected:
            assert cb in callbacks, f"Missing callback: {cb}"

    def test_task_card_callbacks(self):
        """Task card has correct callback_data values."""
        task = (1, "Test task", "2026-08-24", "10:00", "Work", "high", 0, "daily")
        text, keyboard = UI.task_card(task)

        callbacks = []
        for row in keyboard.inline_keyboard:
            for btn in row:
                callbacks.append(btn.callback_data)

        expected = ["done:1", "snooze:1:30", "postpone:1", "dash:edit:1", "deltask:1", "dash:tasks"]
        for cb in expected:
            assert cb in callbacks, f"Missing callback: {cb}"

    def test_reminder_card_callbacks(self):
        """Reminder card has correct callback_data values."""
        task = (1, "Test task", "2026-08-24", "10:00")
        text, keyboard = UI.reminder_card(task)

        callbacks = []
        for row in keyboard.inline_keyboard:
            for btn in row:
                callbacks.append(btn.callback_data)

        expected = ["done:1", "snooze:1:10", "snooze:1:60", "postpone:1", "stoprem:1", "deltask:1"]
        for cb in expected:
            assert cb in callbacks, f"Missing callback: {cb}"

    def test_habit_card_callbacks(self):
        """Habit card has correct callback_data values."""
        habits = [(1, "Meditate", "07:00", "daily", None, 3, 5, None, None)]
        text, keyboard = UI.habit_card(habits)

        callbacks = []
        for row in keyboard.inline_keyboard:
            for btn in row:
                callbacks.append(btn.callback_data)

        assert "done:1" in callbacks
        assert "dash:habits" in callbacks
        assert "dash:home" in callbacks

    def test_goal_card_callbacks(self):
        """Goal card has correct callback_data values."""
        goals = [(1, "Goal", "2026-12-31", 50, 100)]
        text, keyboard = UI.goal_card(goals)

        callbacks = []
        for row in keyboard.inline_keyboard:
            for btn in row:
                callbacks.append(btn.callback_data)

        assert "dash:goalminus:1" in callbacks
        assert "dash:goals" in callbacks
        assert "dash:goalplus:1" in callbacks
        assert "dash:home" in callbacks

    def test_today_card_callbacks(self):
        """Today card has correct callback_data values."""
        groups = {"overdue": [], "high": [], "upcoming": [], "done": []}
        text, keyboard = UI.today_card(groups, "Monday, 24 August")

        callbacks = []
        for row in keyboard.inline_keyboard:
            for btn in row:
                callbacks.append(btn.callback_data)

        assert "dash:today" in callbacks
        assert "dash:home" in callbacks


# ── INTEGRATION SNAPSHOT TESTS ────────────────────────────────────────────


class TestCallbackIntegrationSnapshots:
    """Snapshot tests for complete callback flows."""

    @pytest.mark.asyncio
    async def test_full_task_done_flow(self, mock_update, mock_context, patch_telegram_services, temp_db):
        """Complete flow: task done callback -> database update -> response."""
        # Setup real database state
        storage = Storage()
        tid = storage.tasks.add(UID, "Real task", "2026-08-24", "10:00", "Work", "high")

        # Now test with real database
        with patch("main.get_task_by_id", side_effect=lambda t, u: storage.tasks.get_by_id(t, u)), \
             patch("main.is_habit", return_value=False), \
             patch("main.mark_done", side_effect=lambda t, u: storage.tasks.mark_done(t, u)), \
             patch("main.log_completion") as mock_log, \
             patch("main.db_log_interaction") as mock_int, \
             patch("main.safe_answer_callback_query", new_callable=AsyncMock), \
             patch("main.safe_edit_message_text", new_callable=AsyncMock) as mock_edit:

            mock_update.callback_query.data = f"done:{tid}"
            await handle_callback(mock_update, mock_context)

            # Verify database was updated
            task = storage.tasks.get_by_id(tid, UID)
            assert task is not None
            assert task[6] == 1  # done column

            mock_edit.assert_called()
            text, _ = get_edit_call(mock_edit)
            assert "Done!" in text

    @pytest.mark.asyncio
    async def test_full_habit_done_flow(self, mock_update, mock_context, patch_telegram_services, temp_db):
        """Complete flow: habit done callback -> habit log -> streak update."""
        storage = Storage()
        hid = storage.habits.add(UID, "Meditate")

        with patch("main.get_task_by_id", side_effect=lambda t, u: storage.tasks.get_by_id(t, u)), \
             patch("main.is_habit", return_value=True), \
             patch("main.log_habit_completion", side_effect=lambda t, u: storage.habits.log_completion(t, u)), \
             patch("main.safe_answer_callback_query", new_callable=AsyncMock), \
             patch("main.safe_edit_message_text", new_callable=AsyncMock) as mock_edit:

            mock_update.callback_query.data = f"done:{hid}"
            await handle_callback(mock_update, mock_context)

            # Verify habit log was created
            conn = sqlite3.connect(db.DB_NAME)
            log = conn.execute("SELECT * FROM habit_log WHERE habit_id=?", (hid,)).fetchone()
            conn.close()
            assert log is not None

            mock_edit.assert_called()
            text, _ = get_edit_call(mock_edit)
            assert "Habit completed" in text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])