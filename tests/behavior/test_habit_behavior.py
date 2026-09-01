"""
Characterization tests for Habit behavior — freezes CURRENT behavior exactly.

Covers: create, complete, skip, streak increment, delete.
No improvements, no refactoring, no snapshots.
"""
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

import database as db
from core.actions import create_habit, complete_habit, skip_habit, habit_views
from core.intent.intent_types import Intent
from core.offline.engine import OfflineEngine
from core.offline.request_context import RequestContext
from core.storage import Storage

IST = ZoneInfo("Asia/Kolkata")
UID = 555000111


def _now():
    return datetime.now(IST)


def ctx(text, intent=Intent.ADD_TASK, now=None):
    return RequestContext(user_id=UID, text=text, intent=intent, entities={}, now=now if now is not None else _now())


def ctx_edit(text, intent=Intent.EDIT_TASK, now=None):
    return RequestContext(user_id=UID, text=text, intent=intent, entities={}, now=now if now is not None else _now())


@pytest.fixture
def storage(temp_db):
    return Storage()


@pytest.fixture
def engine(storage):
    return OfflineEngine(storage)


# ── CREATE ──────────────────────────────────────────────────────────────────

def test_habit_create_basic(storage):
    """Creating a basic habit stores it with expected defaults."""
    result = create_habit.execute("Meditate", ctx("add habit Meditate"), storage)
    assert result.success is True
    assert "Habit created!" in result.message

    hid = result.metadata["habit_id"]
    conn = sqlite3.connect(db.DB_NAME)
    row = conn.execute("SELECT * FROM tasks WHERE id=?", (hid,)).fetchone()
    conn.close()

    assert row[2] == "Meditate"           # title (index 2: id=0, user_id=1, title=2)
    assert row[8] == "daily"              # recurrence_type (index 8)
    assert row[18] == 1                   # is_habit (index 18)
    assert row[20] == 0                   # current_streak (index 20)
    assert row[21] == 0                   # longest_streak (index 21)
    assert row[5] == "Health"             # category default (index 5)
    assert row[6] == "medium"             # priority default (index 6)


def test_habit_create_with_time(storage):
    """Creating a habit with time stores due_time."""
    result = create_habit.execute("Run at 07:00", ctx("add habit Run at 07:00"), storage)
    assert result.success is True

    hid = result.metadata["habit_id"]
    conn = sqlite3.connect(db.DB_NAME)
    row = conn.execute("SELECT due_time FROM tasks WHERE id=?", (hid,)).fetchone()
    conn.close()
    assert row[0] == "07:00"


def test_habit_create_weekly(storage):
    """Creating a weekly habit stores recurrence_type and weekday."""
    result = create_habit.execute("Gym every monday", ctx("add habit Gym every monday"), storage)
    assert result.success is True

    hid = result.metadata["habit_id"]
    conn = sqlite3.connect(db.DB_NAME)
    row = conn.execute("SELECT recurrence_type, recurrence_weekday FROM tasks WHERE id=?", (hid,)).fetchone()
    conn.close()
    assert row[0] == "weekly"
    assert row[1] == 0  # Monday = 0


def test_habit_create_monthly(storage):
    """Creating a monthly habit stores recurrence_type and day."""
    # Note: date_parser doesn't recognize "every 1st" as monthly, returns daily
    # This test documents current behavior
    result = create_habit.execute("Pay rent every 1st", ctx("add habit Pay rent every 1st"), storage)
    assert result.success is True

    hid = result.metadata["habit_id"]
    conn = sqlite3.connect(db.DB_NAME)
    row = conn.execute("SELECT recurrence_type, recurrence_day FROM tasks WHERE id=?", (hid,)).fetchone()
    conn.close()
    assert row[0] == "daily"  # current behavior: not recognized as monthly
    assert row[1] is None


def test_habit_create_custom_category(storage):
    """Creating a habit with custom category stores it."""
    # Note: _STRIP_RE regex r"(at HH:MM)|(daily|every day|every week|weekly|monthly)" doesn't remove #learning
    # So title is "Code #learning" (untouched since it doesn't match the patterns)
    # Default category in database.add_habit is "Health", not "General"
    result = create_habit.execute("Code #learning", ctx("add habit Code #learning"), storage)
    assert result.success is True

    hid = result.metadata["habit_id"]
    conn = sqlite3.connect(db.DB_NAME)
    row = conn.execute("SELECT category FROM tasks WHERE id=?", (hid,)).fetchone()
    conn.close()
    assert row[0] == "Health"  # default category since "#learning" not stripped


# ── COMPLETE ────────────────────────────────────────────────────────────────

def _seed_habit(storage, title="Meditate", days_logged=()):
    hid = storage.habits.add(UID, title)
    for offset in sorted(days_logged, reverse=True):
        log_date = (_now().date() - timedelta(days=offset)).strftime("%Y-%m-%d")
        storage.habits.log_completion(hid, UID, log_date=log_date)
    return hid


def test_habit_complete_first_time(storage):
    """Completing a habit for the first time logs completion and sets streak to 1."""
    hid = _seed_habit(storage, "Meditate")
    task = storage.tasks.get_by_id(hid, UID)
    result = complete_habit.execute(task, UID, storage)
    assert result.success is True
    assert "Habit completed!" in result.message
    assert "Streak: <b>1</b> day!" in result.message

    # Check habit_log - columns: id(0), habit_id(1), user_id(2), log_date(3), completed(4), created_at(5)
    conn = sqlite3.connect(db.DB_NAME)
    row = conn.execute("SELECT * FROM habit_log WHERE habit_id=?", (hid,)).fetchone()
    conn.close()
    assert row is not None
    assert row[4] == 1  # completed = 1 (index 4)

    # Check streak columns - use raw SQL since get_by_id only returns 7 columns
    conn = sqlite3.connect(db.DB_NAME)
    row = conn.execute("SELECT current_streak, longest_streak FROM tasks WHERE id=?", (hid,)).fetchone()
    conn.close()
    assert row[0] == 1  # current_streak
    assert row[1] == 1  # longest_streak


def test_habit_complete_increments_streak(storage):
    """Completing a habit on consecutive days increments streak."""
    hid = _seed_habit(storage, "Meditate", days_logged=(1,))  # completed yesterday
    task = storage.tasks.get_by_id(hid, UID)
    result = complete_habit.execute(task, UID, storage)
    assert result.success is True
    assert "Streak: <b>2</b> days!" in result.message

    conn = sqlite3.connect(db.DB_NAME)
    row = conn.execute("SELECT current_streak, longest_streak FROM tasks WHERE id=?", (hid,)).fetchone()
    conn.close()
    assert row[0] == 2  # current_streak
    assert row[1] == 2  # longest_streak


def test_habit_complete_already_done_today(storage):
    """Completing a habit already logged today succeeds with zero writes."""
    hid = _seed_habit(storage, "Meditate", days_logged=(0,))  # completed today
    task = storage.tasks.get_by_id(hid, UID)
    result = complete_habit.execute(task, UID, storage)
    assert result.success is True
    assert "already logged today" in result.message.lower()

    # No new log entry
    conn = sqlite3.connect(db.DB_NAME)
    rows = conn.execute("SELECT * FROM habit_log WHERE habit_id=?", (hid,)).fetchall()
    conn.close()
    assert len(rows) == 1


def test_habit_complete_broken_streak_resets(storage):
    """Completing after a gap resets streak to 1."""
    # Completed 3 days ago, not yesterday or today
    hid = _seed_habit(storage, "Meditate", days_logged=(3,))
    task = storage.tasks.get_by_id(hid, UID)
    result = complete_habit.execute(task, UID, storage)
    assert result.success is True
    assert "Streak: <b>1</b> day!" in result.message

    conn = sqlite3.connect(db.DB_NAME)
    row = conn.execute("SELECT current_streak, longest_streak FROM tasks WHERE id=?", (hid,)).fetchone()
    conn.close()
    assert row[0] == 1  # current_streak reset
    assert row[1] == 1  # longest_streak unchanged (was 1)


def test_habit_complete_paused_habit(storage):
    """Completing a paused habit works (paused flag doesn't block completion)."""
    hid = _seed_habit(storage, "Meditate")
    storage.tasks.pause(hid, UID)
    task = storage.tasks.get_by_id(hid, UID)
    result = complete_habit.execute(task, UID, storage)
    assert result.success is True
    assert "Streak: <b>1</b> day!" in result.message


def test_habit_complete_nonexistent(storage):
    """Completing a nonexistent habit fails."""
    result = complete_habit.execute_by_id(99999, UID, storage)
    assert result.success is False
    assert "task_not_found" in result.warnings


def test_habit_complete_not_a_habit(storage):
    """Completing a regular task via habit completion fails."""
    tid = storage.tasks.add(UID, "Plain task")
    result = complete_habit.execute_by_id(tid, UID, storage)
    assert result.success is False
    assert "not_a_habit" in result.warnings


# ── SKIP ────────────────────────────────────────────────────────────────────

def test_habit_skip_resets_streak(storage):
    """Skipping a habit resets current_streak to 0."""
    hid = _seed_habit(storage, "Meditate", days_logged=(1, 0))  # streak 2
    result = skip_habit.execute(hid, ctx(f"skip habit {hid}"), storage)
    assert result.success is True
    assert "Streak reset" in result.message

    conn = sqlite3.connect(db.DB_NAME)
    row = conn.execute("SELECT current_streak, longest_streak FROM tasks WHERE id=?", (hid,)).fetchone()
    conn.close()
    assert row[0] == 0  # current_streak reset
    assert row[1] == 2  # longest_streak preserved


def test_habit_skip_zero_streak(storage):
    """Skipping a habit with zero streak works."""
    hid = _seed_habit(storage, "Meditate")
    result = skip_habit.execute(hid, ctx(f"skip habit {hid}"), storage)
    assert result.success is True

    conn = sqlite3.connect(db.DB_NAME)
    row = conn.execute("SELECT current_streak FROM tasks WHERE id=?", (hid,)).fetchone()
    conn.close()
    assert row[0] == 0


def test_habit_skip_nonexistent(storage):
    """Skipping a nonexistent habit fails."""
    result = skip_habit.execute(99999, ctx("skip habit 99999"), storage)
    assert result.success is False
    assert "not_a_habit" in result.warnings


def test_habit_skip_not_a_habit(storage):
    """Skipping a regular task fails."""
    tid = storage.tasks.add(UID, "Plain task")
    result = skip_habit.execute(tid, ctx(f"skip habit {tid}"), storage)
    assert result.success is False
    assert "not_a_habit" in result.warnings


# ── STREAK INCREMENT (via consecutive completions) ──────────────────────────

def test_habit_streak_increment_daily_consecutive(storage):
    """Daily habit: consecutive completions increment streak."""
    hid = _seed_habit(storage, "Meditate")
    # Day 1 - complete today
    task = storage.tasks.get_by_id(hid, UID)
    result = complete_habit.execute(task, UID, storage)
    assert result.success is True
    assert "Streak: <b>1</b> day!" in result.message

    # Day 2 - simulate yesterday completed, now complete today
    # First remove today's log by manually inserting yesterday
    conn = sqlite3.connect(db.DB_NAME)
    conn.execute("DELETE FROM habit_log WHERE habit_id=?", (hid,))
    conn.commit()
    conn.close()

    # Log yesterday's completion
    storage.habits.log_completion(hid, UID, log_date=(_now().date() - timedelta(days=1)).strftime("%Y-%m-%d"))
    # Now complete for today
    task = storage.tasks.get_by_id(hid, UID)
    result = complete_habit.execute(task, UID, storage)
    assert result.success is True
    assert "Streak: <b>2</b> days!" in result.message


def test_habit_streak_increment_weekly(storage):
    """Weekly habit: completions on correct weekdays increment streak."""
    hid = storage.habits.add(UID, "Gym", recurrence="weekly", recurrence_weekday=0)  # Monday
    # Complete on Monday
    task = storage.tasks.get_by_id(hid, UID)
    result = complete_habit.execute(task, UID, storage)
    assert result.success is True
    assert "Streak: <b>1</b> day!" in result.message


def test_habit_longest_streak_preserved(storage):
    """Longest streak is preserved when current streak drops."""
    hid = _seed_habit(storage, "Meditate", days_logged=(3, 2, 1, 0))  # streak 4
    # Break streak
    result = skip_habit.execute(hid, ctx(f"skip habit {hid}"), storage)
    assert result.success is True

    conn = sqlite3.connect(db.DB_NAME)
    row = conn.execute("SELECT current_streak, longest_streak FROM tasks WHERE id=?", (hid,)).fetchone()
    conn.close()
    assert row[0] == 0  # current_streak reset
    assert row[1] == 4  # longest_streak preserved


# ── DELETE ──────────────────────────────────────────────────────────────────

def test_habit_delete_removes_task_and_log(storage):
    """Deleting a habit removes task row (but NOT habit_log entries - no cascade in Legacy)."""
    hid = _seed_habit(storage, "Meditate", days_logged=(1, 0))
    # Use delete_task logic since habits use task delete
    from core.actions import delete_task
    delete_task.commit({"task_id": hid}, UID, storage)

    assert storage.tasks.get_by_id(hid, UID) is None

    # Note: Legacy's delete_task does NOT cascade to habit_log - log entries remain orphaned
    conn = sqlite3.connect(db.DB_NAME)
    rows = conn.execute("SELECT * FROM habit_log WHERE habit_id=?", (hid,)).fetchall()
    conn.close()
    assert len(rows) == 2  # habit_log entries remain (no cascade)


def test_habit_delete_not_found(storage):
    """Deleting a nonexistent habit succeeds idempotently (already_deleted flag)."""
    from core.actions import delete_task
    result = delete_task.commit({"task_id": 99999}, UID, storage)
    assert result.success is True  # Idempotent: already deleted is success
    assert result.metadata.get("already_deleted") is True
    assert result.metadata.get("task_id") == 99999


# ── VIEWS (freezing current rendering behavior) ────────────────────────────

def test_habits_list_empty_onboarding(storage):
    """Empty habits list shows onboarding message."""
    result = habit_views.habits_list(ctx("habits"), storage)
    assert result.success is True
    assert result.data == []
    assert "No habits yet!" in result.message
    assert "addhabit Drink water hourly" in result.message


def test_habits_list_renders_streak_fires(storage):
    """Habits list renders fire emojis for streak."""
    hid = _seed_habit(storage, "Meditate", days_logged=(2, 1, 0))
    result = habit_views.habits_list(ctx("habits"), storage)
    assert result.success is True
    assert "🔥🔥🔥" in result.message  # 3 fires for streak 3


def test_habits_list_caps_fires_at_five(storage):
    """Habits list caps fire emojis at 5."""
    _seed_habit(storage, "Run", days_logged=tuple(range(8)))  # streak 8
    result = habit_views.habits_list(ctx("habits"), storage)
    assert "🔥" * 5 in result.message
    assert "🔥" * 6 not in result.message


def test_habits_list_zero_streak_shows_circle(storage):
    """Habits list shows circle for zero streak."""
    _seed_habit(storage, "Stretch")
    result = habit_views.habits_list(ctx("habits"), storage)
    assert "○ Streak: <b>0</b>" in result.message
    assert "Last done:" not in result.message


def test_habits_list_excludes_paused(storage):
    """Habits list excludes paused habits."""
    _seed_habit(storage, "Keep")
    paused = _seed_habit(storage, "Paused one")
    storage.tasks.pause(paused, UID)
    result = habit_views.habits_list(ctx("habits"), storage)
    assert "Keep" in result.message
    assert "Paused one" not in result.message


def test_habit_streak_detail_grid(storage):
    """Streak detail renders 14-day grid."""
    hid = _seed_habit(storage, "Meditate", days_logged=(2, 1, 0))
    result = habit_views.streak_detail(hid, ctx(f"streak {hid}"), storage)
    assert result.success is True
    assert result.metadata["streak"] == 3
    # 14-day grid: 11 empty + 3 filled
    assert "⬜" * 11 + "🟩" * 3 in result.message


def test_habit_streak_detail_missed_days_warning(storage):
    """Streak detail shows missed days warning when applicable."""
    hid = _seed_habit(storage, "Meditate", days_logged=(0,))
    # Backdate start to 6 days ago -> 6 missed
    start = (_now().date() - timedelta(days=6)).strftime("%Y-%m-%d")
    conn = sqlite3.connect(db.DB_NAME)
    conn.execute("UPDATE tasks SET habit_start_date=? WHERE id=?", (start, hid))
    conn.commit()
    conn.close()

    result = habit_views.streak_detail(hid, ctx(f"streak {hid}"), storage)
    assert result.success is True
    assert result.metadata["missed"] == 6
    assert "⚠️ Missed 6 day(s) in this window." in result.message


def test_habit_log_view_empty(storage):
    """Habit log view for habit with no entries."""
    hid = _seed_habit(storage, "Meditate")
    result = habit_views.habit_log_view(hid, ctx(f"habitlog {hid}"), storage)
    assert result.success is True
    assert result.data == []
    assert "No log entries yet for <b>Meditate</b>." in result.message


def test_habit_log_view_entries_newest_first(storage):
    """Habit log view shows entries newest first."""
    hid = _seed_habit(storage, "Meditate", days_logged=(1, 0))
    result = habit_views.habit_log_view(hid, ctx(f"habitlog {hid}"), storage)
    assert result.success is True
    assert result.metadata["entries"] == 2
    today = _now().date().strftime("%Y-%m-%d")
    lines = result.message.splitlines()
    assert lines[2] == f"✅ {today}"  # today first (DESC)


def test_habit_log_view_not_a_habit(storage):
    """Habit log view rejects non-habit."""
    tid = storage.tasks.add(UID, "Plain task")
    result = habit_views.habit_log_view(tid, ctx(f"habitlog {tid}"), storage)
    assert result.success is False
    assert "not_a_habit" in result.warnings
    assert result.message == "That's not a habit."


# ── ENGINE DISPATCH ────────────────────────────────────────────────────────

def test_engine_dispatches_create_habit(storage, engine):
    """Engine dispatches create_habit for recognized phrases."""
    for phrase in ("addhabit Drink water", "add habit Run", "new habit Meditate"):
        result = engine.execute(ctx(phrase))
        assert result.success is True, phrase
        assert "Habit created!" in result.message


def test_engine_dispatches_habits_list(storage, engine):
    """Engine dispatches habits_list for recognized phrases."""
    _seed_habit(storage, "Meditate")
    for phrase in ("habits", "show habits", "my habits", "list habits"):
        # habits_list is registered under QUERY_TASK intent
        result = engine.execute(ctx(phrase, intent=Intent.QUERY_TASK))
        assert result.success is True, phrase
        assert "Your Habits (1)" in result.message


def test_engine_dispatches_streak_and_log(storage, engine):
    """Engine dispatches streak_detail and habit_log_view."""
    hid = _seed_habit(storage, "Meditate", days_logged=(0,))
    # streak is registered under QUERY_TASK intent
    result = engine.execute(ctx(f"streak {hid}", intent=Intent.QUERY_TASK))
    assert result.success is True
    assert "Current streak" in result.message

    # habitlog is registered under EDIT_TASK intent
    result = engine.execute(ctx(f"habitlog {hid}", intent=Intent.EDIT_TASK))
    assert result.success is True
    assert "Log for Meditate" in result.message


# ── BEHAVIORAL EQUIVALENCE ──────────────────────────────────────────────────

def test_create_habit_equivalence_legacy_vs_offline(storage):
    """Legacy database.add_habit() vs Offline create_habit produce identical rows."""
    # Legacy path
    legacy_hid = db.add_habit(UID, "Equivalence habit")

    # Offline path
    offline_result = create_habit.execute(
        "Equivalence habit",
        ctx("add habit Equivalence habit"),
        storage
    )
    assert offline_result.success is True
    offline_hid = offline_result.metadata["habit_id"]

    legacy_row = storage.tasks.get_by_id(legacy_hid, UID)
    offline_row = storage.tasks.get_by_id(offline_hid, UID)

    for i in range(1, len(legacy_row)):
        assert legacy_row[i] == offline_row[i], f"Field {i} differs: legacy={legacy_row[i]} offline={offline_row[i]}"


def test_complete_habit_equivalence_legacy_vs_offline(storage):
    """Legacy log_habit_completion vs Offline complete_habit produce identical state."""
    storage = Storage()

    # Legacy path
    legacy_hid = db.add_habit(UID, "Complete me")
    db.log_habit_completion(legacy_hid, UID, _now().strftime("%Y-%m-%d"))

    # Offline path
    offline_hid = storage.habits.add(UID, "Complete me")
    # Use execute_by_id since we're passing habit_id, not task row
    result = complete_habit.execute_by_id(offline_hid, UID, storage)
    assert result.success is True

    legacy_row = storage.tasks.get_by_id(legacy_hid, UID)
    offline_row = storage.tasks.get_by_id(offline_hid, UID)

    for i in range(1, len(legacy_row)):
        assert legacy_row[i] == offline_row[i], f"Task field {i} differs"

    # Check habit_log - columns: id(0), habit_id(1), user_id(2), log_date(3), completed(4), created_at(5)
    # habit_id differs (different habit rows), so compare fields 2-5
    conn = sqlite3.connect(db.DB_NAME)
    legacy_log = conn.execute("SELECT * FROM habit_log WHERE habit_id=?", (legacy_hid,)).fetchone()
    offline_log = conn.execute("SELECT * FROM habit_log WHERE habit_id=?", (offline_hid,)).fetchone()
    conn.close()

    assert legacy_log is not None and offline_log is not None
    # Skip habit_id (index 1) and created_at (index 5 which can differ across second boundary)
    for i in [2, 3, 4]:
        assert legacy_log[i] == offline_log[i], f"Log field {i} differs"
    assert legacy_log[5] is not None and offline_log[5] is not None


def test_delete_habit_equivalence_legacy_vs_offline(storage):
    """Legacy database.delete_task() vs Offline delete_task produce identical state for habits."""
    storage = Storage()

    # Legacy path
    legacy_hid = db.add_habit(UID, "Delete me")
    db.delete_task(legacy_hid, UID)

    # Offline path
    offline_hid = storage.habits.add(UID, "Delete me")
    from core.actions import delete_task
    delete_task.commit({"task_id": offline_hid}, UID, storage)

    assert storage.tasks.get_by_id(legacy_hid, UID) is None
    assert storage.tasks.get_by_id(offline_hid, UID) is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])