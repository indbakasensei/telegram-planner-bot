"""
Tests for core/actions/complete_habit.py -- v14.11, the final Habit
migration (habit completion) -- and for the two-domain composition of
the shared completion phrases in core/offline/registrations.py.

The load-bearing Phase 0 facts, each pinned here: habit completion is
ONE storage call (log_habit_completion -- habit_log INSERT + streak
recompute + tasks streak-column UPDATE in one connection); already-
logged-today is a SUCCESS reply with ZERO writes; Legacy intentionally
writes NO learning logs (completions_log/interaction_log) for habits --
unlike task completion; scheduler state is untouched (done stays 0);
a paused habit completes fine; no confirmation/pending/editing state
anywhere.

Flag-matrix pins (ADR-013, amended v14.11 for the one action two
domains share): both-domains builds route "done <habit>" through the
shared complete_task spec into complete_habit.execute; tasks-only
builds preserve v14.6's habit_not_supported fall-through (Legacy owns
habits there); habits-only builds register their own complete_habit
spec, which declines real tasks to Legacy.
"""
import ast
import pathlib
import sqlite3
import time
import tracemalloc

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

import database as db
from core.actions import complete_habit
from core.intent.intent_types import Intent
from core.offline.engine import OfflineEngine
from core.offline.registrations import build_default_registry, build_enabled_registry
from core.offline.request_context import RequestContext
from core.storage import Storage

IST = ZoneInfo("Asia/Kolkata")
UID = 555000111


def _now():
    return datetime.now(IST)


def ctx(text, intent=Intent.EDIT_TASK, uid=UID):
    return RequestContext(user_id=uid, text=text, intent=intent,
                           entities={}, now=_now())


@pytest.fixture
def storage(temp_db):
    return Storage()


@pytest.fixture
def engine(storage):
    return OfflineEngine(storage)


def _seed_habit(storage, uid=UID, title="Meditate", days_logged=()):
    hid = storage.habits.add(uid, title)
    for offset in sorted(days_logged, reverse=True):
        storage.habits.log_completion(
            hid, uid, (_now().date() - timedelta(days=offset)).strftime("%Y-%m-%d"))
    return hid


def _task_row(hid):
    conn = sqlite3.connect(db.DB_NAME)
    row = conn.execute("SELECT * FROM tasks WHERE id=?", (hid,)).fetchone()
    conn.close()
    return row


def _habit_log_rows(hid):
    conn = sqlite3.connect(db.DB_NAME)
    rows = conn.execute(
        "SELECT log_date, completed FROM habit_log WHERE habit_id=? ORDER BY log_date",
        (hid,)).fetchall()
    conn.close()
    return rows


def _learning_counts():
    conn = sqlite3.connect(db.DB_NAME)
    c = (conn.execute("SELECT COUNT(*) FROM completions_log").fetchone()[0],
         conn.execute("SELECT COUNT(*) FROM interaction_log").fetchone()[0])
    conn.close()
    return c


# ── AST purity (the brief's explicit requirement for this file) ──────────

def test_complete_habit_never_imports_telegram_or_database():
    root = pathlib.Path(__file__).resolve().parent.parent
    tree = ast.parse((root / "core/actions/complete_habit.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        for name in names:
            assert not name.startswith("telegram"), name
            assert name != "database" and not name.startswith("database."), name


# ── execute(): the Legacy habit branch, row already fetched ──────────────

def test_first_completion_starts_streak(storage):
    hid = _seed_habit(storage)
    task = storage.tasks.get_by_id(hid, UID)
    result = complete_habit.execute(task, UID, storage)
    assert result.success is True
    assert result.metadata == {"habit_id": hid, "streak": 1}
    assert "✅ <b>Habit completed!</b>" in result.message
    assert "📌 Meditate" in result.message
    assert "🔥 Streak: <b>1</b> day!" in result.message      # singular, like Legacy


def test_consecutive_completion_extends_streak_and_columns(storage):
    hid = _seed_habit(storage, days_logged=(2, 1))
    task = storage.tasks.get_by_id(hid, UID)
    result = complete_habit.execute(task, UID, storage)
    assert result.metadata["streak"] == 3
    assert "🔥 Streak: <b>3</b> days!" in result.message
    row = dict(zip([d[0] for d in _describe_tasks()], _task_row(hid)))
    assert row["current_streak"] == 3
    assert row["longest_streak"] == 3
    assert row["last_completed"] == _now().date().strftime("%Y-%m-%d")


def _describe_tasks():
    conn = sqlite3.connect(db.DB_NAME)
    cols = [(c[1],) for c in conn.execute("PRAGMA table_info(tasks)").fetchall()]
    conn.close()
    return cols


def test_broken_chain_resets_to_one_longest_preserved(storage):
    hid = _seed_habit(storage, days_logged=(5, 4, 3))       # streak 3, then a gap
    task = storage.tasks.get_by_id(hid, UID)
    result = complete_habit.execute(task, UID, storage)
    assert result.metadata["streak"] == 1                    # today alone
    row = _task_row(hid)
    cols = [c[0] for c in _describe_tasks()]
    assert row[cols.index("current_streak")] == 1
    assert row[cols.index("longest_streak")] == 3            # preserved


def test_already_logged_today_is_success_reply_with_zero_writes(storage):
    hid = _seed_habit(storage, days_logged=(0,))
    task = storage.tasks.get_by_id(hid, UID)
    before_row, before_log = _task_row(hid), _habit_log_rows(hid)
    result = complete_habit.execute(task, UID, storage)
    assert result.success is True                            # Legacy replies, not an error
    assert "already_logged" in result.warnings
    assert "<i>(already logged today)</i>" in result.message
    assert "✅ <b>Habit completed!</b>" in result.message    # same headline as Legacy
    # The failed UNIQUE insert wrote nothing -- rows byte-identical.
    assert _task_row(hid) == before_row
    assert _habit_log_rows(hid) == before_log


def test_paused_habit_completes_fine_like_legacy(storage):
    # done_task() has no paused check; log_habit_completion() doesn't
    # care. Verified Legacy behavior -- replicated, not "fixed".
    hid = _seed_habit(storage)
    storage.tasks.pause(hid, UID)
    task = storage.tasks.get_by_id(hid, UID)
    result = complete_habit.execute(task, UID, storage)
    assert result.success is True
    assert result.metadata["streak"] == 1


def test_message_escapes_html_in_title(storage):
    hid = _seed_habit(storage, title="Read <books> & sleep")
    task = storage.tasks.get_by_id(hid, UID)
    result = complete_habit.execute(task, UID, storage)
    assert "Read &lt;books&gt; &amp; sleep" in result.message


# ── execute_by_id(): the habits-only standalone entry ────────────────────

def test_execute_by_id_missing_task(storage):
    result = complete_habit.execute_by_id(999, UID, storage)
    assert result.success is False
    assert "task_not_found" in result.warnings
    assert result.message == "❌ Task [999] not found."      # Legacy's exact reply


def test_execute_by_id_non_habit_declines_to_legacy(storage):
    tid = storage.tasks.add(UID, "Plain task")
    result = complete_habit.execute_by_id(tid, UID, storage)
    assert result.success is False
    assert "not_a_habit" in result.warnings
    assert result.message == ""                              # Legacy owns the reply
    assert _task_row(tid)[[c[0] for c in _describe_tasks()].index("done")] == 0


def test_execute_by_id_completes_a_habit(storage):
    hid = _seed_habit(storage)
    result = complete_habit.execute_by_id(hid, UID, storage)
    assert result.success is True
    assert result.metadata["streak"] == 1


# ── What Legacy intentionally does NOT do (verified, mirrored) ───────────

def test_no_learning_logs_written(storage, engine):
    # Legacy's habit branch never touches completions_log or
    # interaction_log (unlike its task branch). Mirror exactly.
    hid = _seed_habit(storage)
    before = _learning_counts()
    result = engine.execute(ctx(f"done {hid}"))
    assert result.success is True and result.metadata.get("streak") == 1
    assert _learning_counts() == before


def test_scheduler_state_untouched(storage, engine):
    # Completion never calls mark_done() for habits: done stays 0, and
    # every column scheduler.get_due_tasks() filters on is untouched --
    # only the three streak columns (and habit_log) change. Column
    # equality IS scheduler-state equality (the v14.7 principle).
    import scheduler
    hid = _seed_habit(storage)
    cols = [c[0] for c in _describe_tasks()]
    before_row = _task_row(hid)
    before_due = scheduler.get_due_tasks()
    engine.execute(ctx(f"done {hid}"))
    after_row = _task_row(hid)
    changed = {cols[k] for k in range(len(cols)) if before_row[k] != after_row[k]}
    assert changed == {"current_streak", "longest_streak", "last_completed"}
    assert after_row[cols.index("done")] == 0
    assert scheduler.get_due_tasks() == before_due


def test_no_conversation_state_markers(storage, engine):
    # Immediate execution: no confirmation, no pending, no editing.
    hid = _seed_habit(storage)
    result = engine.execute(ctx(f"done {hid}"))
    assert "needs_confirmation" not in result.metadata
    assert "start_editing" not in result.metadata
    assert "pending_data" not in result.metadata


# ── Storage-facade usage (the required architecture path) ───────────────

def test_completion_goes_through_the_facade(storage, monkeypatch):
    # Intent -> Registry -> action -> Storage Facade -> database.py:
    # spy on the facade method to prove the action calls it (and not
    # database.py directly -- the AST test proves the "not directly").
    calls = []
    real = storage.habits.log_completion

    def spy(habit_id, user_id, log_date=None):
        calls.append((habit_id, user_id, log_date))
        return real(habit_id, user_id, log_date)

    hid = _seed_habit(storage)
    monkeypatch.setattr(storage.habits, "log_completion", spy)
    result = OfflineEngine(storage).execute(ctx(f"done {hid}"))
    assert result.success is True
    assert calls == [(hid, UID, None)]      # default log_date, like Legacy


# ── Registry dispatch: the flag matrix ───────────────────────────────────

@pytest.mark.parametrize("template", [
    "done {hid}", "complete task {hid}", "finish task {hid}",
    "mark done {hid}", "DONE {hid}",
])
def test_default_registry_dispatches_habit_completion(storage, engine, template):
    hid = _seed_habit(storage, days_logged=(1,))
    result = engine.execute(ctx(template.format(hid=hid)))
    assert result.success is True
    assert result.metadata["streak"] == 2   # yesterday + today


def test_weekly_habit_completes_identically(temp_db, storage, engine):
    # Recurrence type plays no part in completion (log_habit_completion
    # never reads it) -- verified in Legacy, pinned across both paths.
    lhid = storage.habits.add(UID, "Gym", recurrence="weekly", recurrence_weekday=0)
    ohid = storage.habits.add(UID + 1, "Gym", recurrence="weekly", recurrence_weekday=0)
    ok, streak = _legacy_complete_habit(UID, lhid)
    result = engine.execute(ctx(f"done {ohid}", uid=UID + 1))
    assert ok and result.success and streak == result.metadata["streak"] == 1
    cols = [c[0] for c in _describe_tasks()]
    skip = {"id", "user_id"}
    assert ([v for c, v in zip(cols, _task_row(lhid)) if c not in skip]
            == [v for c, v in zip(cols, _task_row(ohid)) if c not in skip])


def test_default_registry_still_completes_tasks(storage, engine):
    tid = storage.tasks.add(UID, "Plain task")
    result = engine.execute(ctx(f"done {tid}"))
    assert result.success is True
    assert "Great job" in result.message                     # task branch, not habit
    cols = [c[0] for c in _describe_tasks()]
    assert _task_row(tid)[cols.index("done")] == 1


def _set_flags(monkeypatch, tasks, habits):
    import core.feature_flags as ff
    monkeypatch.setattr(ff, "OFFLINE_TASKS", tasks)
    monkeypatch.setattr(ff, "OFFLINE_HABITS", habits)


def test_tasks_only_build_preserves_v146_branch_away(storage, monkeypatch):
    # Habit domain OFF -> Legacy still owns habit completion, exactly
    # as shipped in v14.6 -- per-domain flags stay honest.
    _set_flags(monkeypatch, tasks=True, habits=False)
    engine = OfflineEngine(storage, registry=build_enabled_registry())
    hid = _seed_habit(storage)
    result = engine.execute(ctx(f"done {hid}"))
    assert result.success is False
    assert "habit_not_supported" in result.warnings
    assert _habit_log_rows(hid) == []                        # nothing written


def test_habits_only_build_has_own_completion_spec(storage, monkeypatch):
    _set_flags(monkeypatch, tasks=False, habits=True)
    registry = build_enabled_registry()
    names = [s.name for s in registry.resolve(Intent.EDIT_TASK)]
    assert names == ["habitlog_view", "skip_habit", "complete_habit"]
    engine = OfflineEngine(storage, registry=registry)
    hid = _seed_habit(storage)
    result = engine.execute(ctx(f"done {hid}"))
    assert result.success is True and result.metadata["streak"] == 1
    # ...and a real task declines to Legacy (Task domain is OFF).
    tid = storage.tasks.add(UID, "Plain task")
    result = engine.execute(ctx(f"done {tid}"))
    assert result.success is False and "not_a_habit" in result.warnings
    cols = [c[0] for c in _describe_tasks()]
    assert _task_row(tid)[cols.index("done")] == 0


def test_default_registry_has_no_separate_completion_spec(storage):
    # Both domains on -> ONE completion spec (Legacy's one-handler
    # shape), carrying the habit handler internally.
    names = [s.name for s in build_default_registry().resolve(Intent.EDIT_TASK)]
    assert names.count("complete_task") == 1
    assert "complete_habit" not in names


def test_habits_only_completion_is_edit_task_only(monkeypatch):
    # Completion phrasings are Tier 0 "done "-group prefixes -- they
    # always classify EDIT_TASK, never UNKNOWN, so the habits-only spec
    # deliberately isn't registered under UNKNOWN (unlike the shared
    # task specs, which need UNKNOWN for "rename task", ADR-009).
    _set_flags(monkeypatch, tasks=False, habits=True)
    registry = build_enabled_registry()
    assert "complete_habit" in [s.name for s in registry.resolve(Intent.EDIT_TASK)]
    assert registry.resolve(Intent.UNKNOWN) == ()


# ── Failure Injection ────────────────────────────────────────────────────

def test_missing_habit_via_engine_falls_through(storage, engine):
    result = engine.execute(ctx("done 999"))
    assert result.success is False
    assert "task_not_found" in result.warnings


def test_invalid_id_never_matches(storage, engine):
    for text in ("done abc", "done", "mark done"):
        result = engine.execute(ctx(text))
        assert result.success is False, text
        assert "unsupported_action" in result.warnings


class _RaisingHabits:
    def __init__(self, exc):
        self._exc = exc

    def is_habit(self, task_id):
        return True

    def __getattr__(self, name):
        def boom(*a, **k):
            raise self._exc
        return boom


class _FakeStorage:
    def __init__(self, habits, tasks):
        self.habits = habits
        self.tasks = tasks


def test_locked_database_is_contained(storage, temp_db):
    hid = _seed_habit(storage)
    engine = OfflineEngine(_FakeStorage(
        _RaisingHabits(sqlite3.OperationalError("database is locked")),
        storage.tasks))
    result = engine.execute(ctx(f"done {hid}"))
    assert result.success is False
    assert "action_exception:OperationalError" in result.warnings


def test_unexpected_exception_is_contained(storage, temp_db):
    hid = _seed_habit(storage)
    engine = OfflineEngine(_FakeStorage(_RaisingHabits(RuntimeError("boom")),
                                         storage.tasks))
    result = engine.execute(ctx(f"done {hid}"))
    assert result.success is False
    assert "action_exception:RuntimeError" in result.warnings


def test_integrity_rollback_leaves_no_partial_state(storage):
    # The already-logged path IS the rollback path: the UNIQUE INSERT
    # fails inside log_habit_completion's connection, which closes
    # without commit -- no habit_log row, no streak update. Pinned via
    # raw rows in test_already_logged_today_...; here via the engine.
    hid = _seed_habit(storage, days_logged=(0,))
    before = (_task_row(hid), _habit_log_rows(hid))
    result = OfflineEngine(storage).execute(ctx(f"done {hid}"))
    assert result.success is True and "already_logged" in result.warnings
    assert (_task_row(hid), _habit_log_rows(hid)) == before


# ── Behavioral Equivalence ───────────────────────────────────────────────

def _legacy_complete_habit(uid, hid):
    """done_task()'s habit branch, exactly (main.py:440-457):
    locate -> is_habit -> log_habit_completion."""
    task = db.get_task_by_id(hid, uid)
    assert task is not None and db.is_habit(hid)
    return db.log_habit_completion(hid, uid)


def test_equivalence_rows_and_streaks(temp_db, storage, engine):
    legacy_uid, offline_uid = UID, UID + 1
    lhid = _seed_habit(storage, uid=legacy_uid, days_logged=(2, 1))
    ohid = _seed_habit(storage, uid=offline_uid, days_logged=(2, 1))

    ok, streak = _legacy_complete_habit(legacy_uid, lhid)
    result = engine.execute(ctx(f"done {ohid}", uid=offline_uid))
    assert ok is True and result.success is True
    assert streak == result.metadata["streak"] == 3

    cols = [c[0] for c in _describe_tasks()]
    skip = {"id", "user_id"}
    l_row = [v for c, v in zip(cols, _task_row(lhid)) if c not in skip]
    o_row = [v for c, v in zip(cols, _task_row(ohid)) if c not in skip]
    assert l_row == o_row                                    # incl. all timestamps
    assert _habit_log_rows(lhid) == _habit_log_rows(ohid)

    # Second completion, same day: both already-logged, both zero-write.
    ok2, msg2 = _legacy_complete_habit(legacy_uid, lhid)
    result2 = engine.execute(ctx(f"done {ohid}", uid=offline_uid))
    assert ok2 is False and msg2 == "already_logged"
    assert "already_logged" in result2.warnings
    assert _habit_log_rows(lhid) == _habit_log_rows(ohid)


def test_equivalence_query_count_and_sql_order(temp_db, storage, engine, monkeypatch):
    lhid = _seed_habit(storage, uid=UID)
    ohid = _seed_habit(storage, uid=UID + 1)

    statements = []
    real_connect = db.sqlite3.connect

    def tracing_connect(*a, **k):
        conn = real_connect(*a, **k)
        conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr(db.sqlite3, "connect", tracing_connect)

    statements.clear()
    _legacy_complete_habit(UID, lhid)
    legacy_stmts = [s.split()[0] for s in statements]        # verb order

    statements.clear()
    engine.execute(ctx(f"done {ohid}", uid=UID + 1))
    offline_stmts = [s.split()[0] for s in statements]

    # Same statement count AND same SQL verb order -- the offline path
    # is the same three database.py calls through the facade.
    assert offline_stmts == legacy_stmts


# ── Performance ──────────────────────────────────────────────────────────

def test_performance_latency(temp_db, storage, engine):
    n = 40
    lhids = [_seed_habit(storage, uid=UID, title=f"L{k}") for k in range(n)]
    ohids = [_seed_habit(storage, uid=UID + 1, title=f"O{k}") for k in range(n)]
    start = time.perf_counter()
    for hid in lhids:
        _legacy_complete_habit(UID, hid)
    legacy_ms = (time.perf_counter() - start) * 1000 / n
    start = time.perf_counter()
    for hid in ohids:
        engine.execute(ctx(f"done {hid}", uid=UID + 1))
    offline_ms = (time.perf_counter() - start) * 1000 / n
    assert legacy_ms < 100 and offline_ms < 100              # loose sanity bounds


def test_performance_memory(temp_db, storage, engine):
    hid = _seed_habit(storage, days_logged=(0,))             # already-logged loop
    tracemalloc.start()
    before = tracemalloc.take_snapshot()
    for _ in range(50):
        engine.execute(ctx(f"done {hid}"))
    after = tracemalloc.take_snapshot()
    tracemalloc.stop()
    growth = sum(s.size_diff for s in after.compare_to(before, "lineno"))
    assert growth < 5_000_000
