"""
Tests for database.py: init_db()/migrations/infrastructure (formalizing
the ad-hoc validation done during Sprint 1C and Sprint 3), plus CRUD
across every major entity type, the Sprint 1C reset-command fix, and
project (materials/worklog) tables.

Uses temp_db/raw_db_path fixtures (see conftest.py) -- every test here
runs against an isolated temporary SQLite file, never planner.db.
"""
import os
import sqlite3

import pytest

import database as db


# ── init_db() / idempotent startup ────────────────────────────────────────

def test_init_db_creates_all_required_tables(raw_db_path):
    db.init_db()
    conn = sqlite3.connect(raw_db_path)
    existing = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    for table in db.REQUIRED_TABLES:
        assert table in existing, f"{table} missing after init_db()"


def test_init_db_creates_all_required_indexes(raw_db_path):
    db.init_db()
    conn = sqlite3.connect(raw_db_path)
    existing = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index'")}
    conn.close()
    for idx_name, _table, _cols, _why in db.REQUIRED_INDEXES:
        assert idx_name in existing, f"{idx_name} missing after init_db()"


def test_init_db_enables_wal_mode(raw_db_path):
    db.init_db()
    conn = sqlite3.connect(raw_db_path)
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    conn.close()
    assert mode == "wal"


def test_init_db_sets_schema_version(raw_db_path):
    db.init_db()
    conn = sqlite3.connect(raw_db_path)
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    conn.close()
    assert version == db.SCHEMA_VERSION


def test_init_db_is_idempotent(raw_db_path):
    db.init_db()
    db.add_task(1, "Persisted task")
    db.init_db()  # second call must not error or wipe data
    db.init_db()  # third, for good measure
    tasks = db.get_tasks(1)
    assert any(t[1] == "Persisted task" for t in tasks)


def test_init_db_does_not_create_backup_on_brand_new_database(raw_db_path):
    db.init_db()
    backups_dir = os.path.join(os.path.dirname(os.path.abspath(raw_db_path)), "backups")
    assert not os.path.exists(backups_dir) or len(os.listdir(backups_dir)) == 0


def test_init_db_creates_backup_on_second_call_with_existing_data(raw_db_path):
    db.init_db()
    db.add_task(1, "Some data")
    db.init_db()  # now the file has data -- this call should back it up first
    backups_dir = os.path.join(os.path.dirname(os.path.abspath(raw_db_path)), "backups")
    assert os.path.isdir(backups_dir)
    assert len(os.listdir(backups_dir)) >= 1


# ── verify_schema_integrity() ──────────────────────────────────────────────

def test_verify_schema_integrity_ok_after_init(temp_db):
    report = db.verify_schema_integrity(temp_db)
    assert report["ok"] is True
    assert report["missing_tables"] == []
    assert report["missing_indexes"] == []
    assert report["journal_mode"] == "wal"
    assert report["schema_version"] == db.SCHEMA_VERSION


def test_verify_schema_integrity_detects_missing_table(temp_db):
    conn = sqlite3.connect(temp_db)
    conn.execute("DROP TABLE goals")
    conn.commit()
    conn.close()
    report = db.verify_schema_integrity(temp_db)
    assert report["ok"] is False
    assert "goals" in report["missing_tables"]


def test_verify_schema_integrity_detects_missing_index(temp_db):
    conn = sqlite3.connect(temp_db)
    conn.execute("DROP INDEX idx_tasks_user_done_paused")
    conn.commit()
    conn.close()
    report = db.verify_schema_integrity(temp_db)
    assert report["ok"] is False
    assert "idx_tasks_user_done_paused" in report["missing_indexes"]


def test_verify_schema_integrity_never_raises_on_nonexistent_db(tmp_path):
    report = db.verify_schema_integrity(str(tmp_path / "does_not_exist.db"))
    assert isinstance(report, dict)
    assert report["ok"] is False


# ── _safe_add_column / migration handling ──────────────────────────────────

def test_safe_add_column_existing_column_is_silent(temp_db):
    conn = sqlite3.connect(temp_db)
    c = conn.cursor()
    db._safe_add_column(c, "tasks", "priority", "TEXT DEFAULT 'medium'")
    conn.commit()
    conn.close()  # must not raise


def test_safe_add_column_new_column_actually_added(temp_db):
    conn = sqlite3.connect(temp_db)
    c = conn.cursor()
    db._safe_add_column(c, "tasks", "brand_new_test_col", "TEXT DEFAULT NULL")
    conn.commit()
    cols = {row[1] for row in conn.execute("PRAGMA table_info(tasks)")}
    conn.close()
    assert "brand_new_test_col" in cols


# ── backup_database() ───────────────────────────────────────────────────────

def test_backup_database_noop_on_missing_file(tmp_path):
    result = db.backup_database(db_name=str(tmp_path / "nope.db"))
    assert result is None


def test_backup_database_creates_file_for_existing_db(temp_db):
    db.add_task(1, "seed data so the file is non-empty")
    path = db.backup_database(reason="test", db_name=temp_db)
    assert path is not None
    assert os.path.exists(path)


def test_backup_database_prunes_old_backups_beyond_keep_limit(temp_db):
    db.add_task(1, "seed")
    for _ in range(8):
        db.backup_database(reason="pruning_test", db_name=temp_db, keep=3)
    backups_dir = os.path.join(os.path.dirname(os.path.abspath(temp_db)), "backups")
    matching = [f for f in os.listdir(backups_dir) if "pruning_test" in f]
    assert len(matching) <= 3


# ── get_connection() ─────────────────────────────────────────────────────

def test_get_connection_sets_wal(temp_db):
    conn = db.get_connection(temp_db)
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    conn.close()
    assert mode == "wal"


# ── CRUD: tasks ────────────────────────────────────────────────────────────

def test_task_crud_round_trip(temp_db, uid):
    tid = db.add_task(uid, "Buy milk", due_date="2026-07-15", due_time="18:00",
                       category="Personal", priority="high")
    task = db.get_task_by_id(tid, uid)
    assert task[1] == "Buy milk"
    assert task[2] == "2026-07-15"

    db.update_task(tid, uid, title="Buy oat milk")
    updated = db.get_task_by_id(tid, uid)
    assert updated[1] == "Buy oat milk"

    db.mark_done(tid, uid)
    assert any(t[0] == tid for t in db.get_tasks(uid, done=1))

    db.delete_task(tid, uid)
    assert db.get_task_by_id(tid, uid) is None


def test_task_exists_prevents_duplicate_detection(temp_db, uid):
    db.add_task(uid, "Study physics", due_date="2026-07-15")
    assert db.task_exists(uid, "Study physics", "2026-07-15") is True
    assert db.task_exists(uid, "Study chemistry", "2026-07-15") is False


def test_tasks_scoped_by_user_id(temp_db, uid):
    other_uid = uid + 1
    tid = db.add_task(uid, "My task")
    assert db.get_task_by_id(tid, other_uid) is None
    assert db.get_task_by_id(tid, uid) is not None


# ── CRUD: habits ───────────────────────────────────────────────────────────

def test_habit_crud_and_streak(temp_db, uid):
    hid = db.add_habit(uid, "Drink water", time="09:00")
    assert db.is_habit(hid) is True

    ok1, streak1 = db.log_habit_completion(hid, uid, log_date="2026-07-13")
    assert ok1 and streak1 == 1

    ok2, reason = db.log_habit_completion(hid, uid, log_date="2026-07-13")
    assert ok2 is False and reason == "already_logged"

    ok3, streak3 = db.log_habit_completion(hid, uid, log_date="2026-07-14")
    assert ok3 and streak3 == 2


def test_reset_streak(temp_db, uid):
    hid = db.add_habit(uid, "Exercise")
    db.log_habit_completion(hid, uid, log_date="2026-07-13")
    db.reset_streak(hid)
    habits = db.get_habits(uid)
    habit = next(h for h in habits if h[0] == hid)
    assert habit[5] == 0  # current_streak column


# ── CRUD: goals ────────────────────────────────────────────────────────────

def test_goal_crud_and_progress(temp_db, uid):
    gid = db.add_goal(uid, "Read 12 books", deadline="2026-12-31")
    goals = db.get_goals(uid)
    assert any(g[0] == gid for g in goals)

    result = db.update_goal_progress(gid, uid, 50)
    assert result is not None


# ── CRUD: memories ─────────────────────────────────────────────────────────

def test_memory_crud_round_trip(temp_db, uid):
    db.save_memory(uid, "exam_date", "June 20")
    assert db.get_memory(uid, "exam_date") == "June 20"

    db.save_memory(uid, "exam_date", "June 25")  # update, not duplicate
    all_mem = db.get_all_memories(uid)
    matching = [m for m in all_mem if m[0] == "exam_date"]
    assert len(matching) == 1
    assert matching[0][1] == "June 25"

    db.delete_memory(uid, "exam_date")
    assert db.get_memory(uid, "exam_date") is None


def test_memory_separator_variants_overwrite(temp_db, uid):
    # v14.26 bug fix (MEM-002): the AI spells the same fact's key
    # inconsistently ('favorite color' vs 'favorite_color'); those must
    # overwrite, not duplicate.
    db.save_memory(uid, "favorite color", "blue")
    db.save_memory(uid, "favorite_color", "red")     # same fact, other spelling
    assert db.get_memory(uid, "favorite color") == "red"
    assert db.get_memory(uid, "favorite_color") == "red"
    assert len(db.get_all_memories(uid)) == 1         # one row, not two
    # Delete matches either spelling.
    assert db.delete_memory(uid, "Favorite-Color") is True
    assert db.get_all_memories(uid) == []


# ── reset commands (Sprint 1C fix, re-verified here permanently) ─────────

def test_reset_all_tasks_excludes_habits(temp_db, uid):
    task_id = db.add_task(uid, "Regular task")
    habit_id = db.add_habit(uid, "Daily habit")
    db.log_habit_completion(habit_id, uid, log_date="2026-07-13")

    deleted = db.reset_all_tasks(uid)

    assert deleted == 1
    assert db.get_task_by_id(task_id, uid) is None
    remaining_habits = db.get_habits(uid)
    assert len(remaining_habits) == 1 and remaining_habits[0][0] == habit_id
    assert len(db.get_habit_log(habit_id, uid)) == 1  # habit_log untouched


def test_reset_everything_covers_all_twelve_tables_no_orphans(temp_db, uid):
    task_id = db.add_task(uid, "Task")
    habit_id = db.add_habit(uid, "Habit")
    db.log_habit_completion(habit_id, uid, log_date="2026-07-13")
    goal_id = db.add_goal(uid, "Goal")
    db.add_materials(uid, goal_id, "motor, battery")
    db.add_worklog(uid, goal_id, "started")
    db.save_template(uid, "tpl", "Template task")
    db.log_missed_capability(uid, "some input")
    db.add_observation(uid, "an observation")

    db.reset_everything(uid)

    conn = sqlite3.connect(temp_db)
    for table in db.REQUIRED_TABLES:
        n = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE user_id=?", (uid,)).fetchone()[0]
        assert n == 0, f"{table} still has rows for user after reset_everything()"
    conn.close()


def test_reset_everything_new_goal_does_not_inherit_old_project_data(temp_db, uid):
    old_goal_id = db.add_goal(uid, "Old project")
    db.add_materials(uid, old_goal_id, "motor, battery")
    db.add_worklog(uid, old_goal_id, "started work")

    db.reset_everything(uid)

    new_goal_id = db.add_goal(uid, "Completely different project")
    # This is the actual regression the Sprint 1C fix targets: a reused
    # goal ID must never surface a previous, deleted project's data.
    assert db.get_materials(uid, new_goal_id) == []
    assert db.get_worklog(uid, new_goal_id) == []


# ── project tables (materials/worklog) ────────────────────────────────────

def test_add_and_acquire_materials(temp_db, uid):
    goal_id = db.add_goal(uid, "Build drone")
    added = db.add_materials(uid, goal_id, "motor, propeller, battery")
    assert len(added) == 3

    materials = db.get_materials(uid, goal_id)
    assert len(materials) == 3
    # columns: (id, name, quantity, acquired, cost, notes, created_at, acquired_at)
    assert all(m[3] == 0 for m in materials)  # acquired column starts at 0

    mat_id = materials[0][0]
    db.mark_material_acquired(uid, mat_id, True)
    updated = db.get_materials(uid, goal_id)
    acquired = next(m for m in updated if m[0] == mat_id)
    assert acquired[3] == 1


def test_add_materials_ignores_case_insensitive_duplicates(temp_db, uid):
    goal_id = db.add_goal(uid, "Build drone")
    db.add_materials(uid, goal_id, "Motor")
    added_again = db.add_materials(uid, goal_id, "motor")  # same, different case
    assert added_again == []
    assert len(db.get_materials(uid, goal_id)) == 1


def test_find_material_by_name_fuzzy_match(temp_db, uid):
    goal_id = db.add_goal(uid, "Build drone")
    db.add_materials(uid, goal_id, "motor, battery")
    matches = db.find_material_by_name(uid, "motor")
    assert len(matches) == 1


def test_worklog_add_and_get(temp_db, uid):
    goal_id = db.add_goal(uid, "Build drone")
    db.add_worklog(uid, goal_id, "Frame mounted", kind="progress")
    db.add_worklog(uid, goal_id, "Finished wiring", kind="finished")
    entries = db.get_worklog(uid, goal_id)
    assert len(entries) == 2


def test_compute_project_progress_reflects_materials_and_worklog(temp_db, uid):
    goal_id = db.add_goal(uid, "Build drone")
    added = db.add_materials(uid, goal_id, "motor, battery")
    db.mark_material_acquired(uid, added[0][0], True)
    db.mark_material_acquired(uid, added[1][0], True)
    db.add_worklog(uid, goal_id, "finished everything", kind="finished")
    progress = db.compute_project_progress(uid, goal_id)
    assert progress is not None
