"""
Tests for core/storage/ -- the v14.1C Storage Facade.

Verifies pure delegation: every facade method must produce exactly what
calling the corresponding database.py function directly would produce.
Uses the same temp_db/uid fixtures tests/test_database.py already
established (conftest.py) -- database.py's DB_NAME is monkeypatched, and
core/storage/storage.py's `import database` sees the same patched module
object, so no separate fixture plumbing is needed.
"""
import database as db
from core.storage import Storage


def test_storage_instantiates_all_four_domains():
    s = Storage()
    assert s.tasks is not None
    assert s.habits is not None
    assert s.goals is not None
    assert s.projects is not None


# ── TaskStorage ───────────────────────────────────────────────────────────

def test_task_add_and_get_all_delegate_correctly(temp_db, uid):
    s = Storage()
    s.tasks.add(uid, "Buy milk", due_date="2026-03-05")
    facade_result = s.tasks.get_all(uid)
    direct_result = db.get_tasks(uid)
    assert facade_result == direct_result
    assert len(facade_result) == 1
    assert facade_result[0][1] == "Buy milk"


def test_task_get_by_id_delegates_correctly(temp_db, uid):
    s = Storage()
    s.tasks.add(uid, "Call mom")
    task_id = s.tasks.get_all(uid)[0][0]
    assert s.tasks.get_by_id(task_id, uid) == db.get_task_by_id(task_id, uid)


def test_task_get_by_date_and_week_delegate_correctly(temp_db, uid):
    s = Storage()
    s.tasks.add(uid, "Dentist", due_date="2026-03-05")
    assert s.tasks.get_by_date(uid, "2026-03-05") == db.get_tasks_by_date(uid, "2026-03-05")
    assert (s.tasks.get_by_week(uid, "2026-03-01", "2026-03-07")
            == db.get_tasks_by_week(uid, "2026-03-01", "2026-03-07"))


def test_task_search_by_title_delegates_correctly(temp_db, uid):
    s = Storage()
    s.tasks.add(uid, "Submit report")
    assert (s.tasks.search_by_title(uid, "report")
            == db.search_tasks_by_title(uid, "report"))


def test_task_mark_done_delegates_correctly(temp_db, uid):
    s = Storage()
    s.tasks.add(uid, "Finish chapter")
    task_id = s.tasks.get_all(uid)[0][0]
    s.tasks.mark_done(task_id, uid)
    assert s.tasks.get_all(uid, done=1)[0][0] == task_id


def test_task_update_delegates_correctly(temp_db, uid):
    s = Storage()
    s.tasks.add(uid, "Old title")
    task_id = s.tasks.get_all(uid)[0][0]
    s.tasks.update(task_id, uid, title="New title")
    assert s.tasks.get_by_id(task_id, uid)[1] == "New title"


def test_task_delete_delegates_correctly(temp_db, uid):
    s = Storage()
    s.tasks.add(uid, "Temporary")
    task_id = s.tasks.get_all(uid)[0][0]
    s.tasks.delete(task_id, uid)
    assert s.tasks.get_all(uid) == []


def test_task_exists_delegates_correctly(temp_db, uid):
    s = Storage()
    assert s.tasks.exists(uid, "Nonexistent", "2026-03-05") is False
    s.tasks.add(uid, "Real task", due_date="2026-03-05")
    assert s.tasks.exists(uid, "Real task", "2026-03-05") is True


# ── HabitStorage ──────────────────────────────────────────────────────────

def test_habit_add_and_get_all_delegate_correctly(temp_db, uid):
    s = Storage()
    s.habits.add(uid, "Drink water")
    facade_result = s.habits.get_all(uid)
    assert facade_result == db.get_habits(uid)
    assert len(facade_result) == 1


def test_habit_is_habit_delegates_correctly(temp_db, uid):
    s = Storage()
    s.habits.add(uid, "Meditate")
    habit_id = s.habits.get_all(uid)[0][0]
    assert s.habits.is_habit(habit_id) == db.is_habit(habit_id) is True


def test_habit_log_completion_and_get_log_delegate_correctly(temp_db, uid):
    # get_habit_log() filters by a real datetime.now(IST)-relative cutoff
    # (database.py:936), not an injectable `now` -- so log_completion()
    # must omit log_date (defaults to today) rather than use a fixed
    # historical date that could fall outside the default 30-day window.
    s = Storage()
    s.habits.add(uid, "Read")
    habit_id = s.habits.get_all(uid)[0][0]
    s.habits.log_completion(habit_id, uid)
    assert s.habits.get_log(habit_id, uid) == db.get_habit_log(habit_id, uid)
    assert len(s.habits.get_log(habit_id, uid)) == 1


def test_habit_get_missed_days_and_reset_streak_delegate_correctly(temp_db, uid):
    s = Storage()
    s.habits.add(uid, "Stretch")
    habit_id = s.habits.get_all(uid)[0][0]
    assert s.habits.get_missed_days(habit_id, uid) == db.get_missed_days(habit_id, uid)
    s.habits.reset_streak(habit_id)  # must not raise; delegates to db.reset_streak


# ── GoalStorage ───────────────────────────────────────────────────────────

def test_goal_add_and_get_all_delegate_correctly(temp_db, uid):
    s = Storage()
    s.goals.add(uid, "Learn Rust", deadline="2026-12-31")
    facade_result = s.goals.get_all(uid)
    assert facade_result == db.get_goals(uid)
    assert len(facade_result) == 1


def test_goal_get_all_full_delegates_correctly(temp_db, uid):
    s = Storage()
    s.goals.add(uid, "Run a marathon")
    assert s.goals.get_all_full(uid) == db.get_goals_full(uid)


def test_goal_update_progress_delegates_correctly(temp_db, uid):
    s = Storage()
    s.goals.add(uid, "Save money")
    goal_id = s.goals.get_all(uid)[0][0]
    s.goals.update_progress(goal_id, uid, 10)
    direct = db.get_goals_full(uid)
    facade = s.goals.get_all_full(uid)
    assert facade == direct


# ── ProjectStorage ────────────────────────────────────────────────────────

def test_project_materials_lifecycle_delegates_correctly(temp_db, uid):
    s = Storage()
    s.goals.add(uid, "Build a PC")
    goal_id = s.goals.get_all(uid)[0][0]

    s.projects.add_materials(uid, goal_id, ["GPU", "PSU"], quantity=1)
    facade_materials = s.projects.get_materials(uid, goal_id)
    assert facade_materials == db.get_materials(uid, goal_id)
    assert len(facade_materials) == 2

    material_id = facade_materials[0][0]
    s.projects.mark_material_acquired(uid, material_id, True)
    assert s.projects.get_materials(uid, goal_id) == db.get_materials(uid, goal_id)

    found = s.projects.find_material_by_name(uid, "GPU", goal_id)
    assert found == db.find_material_by_name(uid, "GPU", goal_id)

    s.projects.delete_material(uid, material_id)
    assert s.projects.get_materials(uid, goal_id) == db.get_materials(uid, goal_id)


def test_project_worklog_delegates_correctly(temp_db, uid):
    s = Storage()
    s.goals.add(uid, "Write a novel")
    goal_id = s.goals.get_all(uid)[0][0]

    s.projects.add_worklog(uid, goal_id, "Wrote chapter 1", kind="note")
    facade_log = s.projects.get_worklog(uid, goal_id)
    assert facade_log == db.get_worklog(uid, goal_id)
    assert len(facade_log) == 1

    assert (s.projects.get_last_worklog_days(uid, goal_id)
            == db.get_last_worklog_days(uid, goal_id))


def test_project_progress_and_overview_delegate_correctly(temp_db, uid):
    s = Storage()
    s.goals.add(uid, "Renovate kitchen")
    goal_id = s.goals.get_all(uid)[0][0]

    assert s.projects.compute_progress(uid, goal_id) == db.compute_project_progress(uid, goal_id)
    assert s.projects.get_overview(uid, goal_id) == db.get_project_overview(uid, goal_id)


def test_project_active_and_pending_materials_delegate_correctly(temp_db, uid):
    s = Storage()
    s.goals.add(uid, "Garden shed")
    goal_id = s.goals.get_all(uid)[0][0]
    s.projects.add_materials(uid, goal_id, ["Wood"], quantity=1)

    assert s.projects.get_active(uid) == db.get_active_projects(uid)
    assert (s.projects.get_all_pending_materials(uid)
            == db.get_all_pending_materials(uid))
