"""
Tests for core/actions/habit_views.py -- the v14.9 Habit-domain Stage 1
read-only views (habits list / streak detail / habit log), plus the
per-domain flag-aware registry construction (build_enabled_registry,
ADR-013) they ship with.

Follows the same structure as every prior action suite: matchers, each
view against real temp-DB data via the Storage Facade, engine dispatch
through the default registry, Behavioral Equivalence (query-count
parity with the exact database.py call sequence Legacy's handlers
make -- reads mutate nothing, so DB-state equivalence is invariance,
asserted too), Failure Injection, and latency/memory benchmarks.

Rendering equivalence caveat (habit_views.py's module docstring,
DEBUGGING.md): Legacy's habit handlers still reply in Markdown with
unescaped titles; these views render the same content as HTML through
fmt.py. Equivalence tests therefore assert content (fields, lines,
conditionals, emoji), not raw markup bytes.

Dates are computed relative to the real clock, never hard-coded:
database.py's get_habit_log()/get_missed_days() cutoffs use
datetime.now(IST) internally (Legacy behavior, unchanged), so fixed
historical dates would silently age out of the window -- the exact
testing pitfall DEBUGGING.md documents from the v14.1C storage-facade
suite.
"""
import sqlite3
import time
import tracemalloc

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

import database as db
from core.actions import habit_views
from core.intent.intent_types import Intent
from core.offline.engine import OfflineEngine
from core.offline.registrations import build_default_registry, build_enabled_registry
from core.offline.request_context import RequestContext
from core.storage import Storage

IST = ZoneInfo("Asia/Kolkata")
UID = 555000111


def _now():
    # Real-clock IST, matching what Legacy's handlers pass around; the
    # log-window functions inside database.py use the real clock
    # regardless (see module docstring).
    return datetime.now(IST)


def ctx(text, intent=Intent.QUERY_TASK, now=None):
    return RequestContext(user_id=UID, text=text, intent=intent,
                           entities={}, now=now if now is not None else _now())


@pytest.fixture
def storage(temp_db):
    return Storage()


@pytest.fixture
def engine(storage):
    return OfflineEngine(storage)


def _seed_habit(storage, title="Meditate", days_logged=(), **kw):
    """A habit with completions logged on `days_logged` days-ago
    offsets (0 = today), oldest first so streak recomputation sees the
    full chain."""
    hid = storage.habits.add(UID, title, **kw)
    for offset in sorted(days_logged, reverse=True):
        log_date = (_now().date() - timedelta(days=offset)).strftime("%Y-%m-%d")
        storage.habits.log_completion(hid, UID, log_date=log_date)
    return hid


# ── Matchers ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("streak 5", 5),
    ("  Streak 12  ", 12),
    ("streak 5 please", 5),
    ("streak", None),            # id-less -> Legacy's usage reply
    ("streak abc", None),        # malformed -> Legacy's usage reply
    ("reset streak 5", None),    # skiphabit alias (write) -- not Stage 1
    ("winning streak 5", None),
])
def test_match_streak_command(text, expected):
    assert habit_views.match_streak_command(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("habitlog 3", 3),
    ("habit log 3", 3),
    ("HabitLog 3", 3),
    ("habitlog", None),
    ("habitlog abc", None),
    ("my habitlog 3", None),
])
def test_match_habitlog_command(text, expected):
    assert habit_views.match_habitlog_command(text) == expected


def test_habits_view_phrases_mirror_rules():
    # Must stay verbatim-identical to core/intent/rules.py's habit
    # exact group (the accepted phrase-mirror duplication).
    assert habit_views.HABITS_VIEW_PHRASES == (
        "habits", "show habits", "my habits", "list habits")


# ── habits_list ──────────────────────────────────────────────────────────

def test_habits_list_empty_is_onboarding_message(storage):
    result = habit_views.habits_list(ctx("habits"), storage)
    assert result.success is True
    assert result.data == []
    assert "No habits yet!" in result.message
    assert "addhabit Drink water hourly" in result.message


def test_habits_list_renders_all_legacy_fields(storage):
    hid = _seed_habit(storage, "Meditate", days_logged=(2, 1, 0), time="07:00")
    result = habit_views.habits_list(ctx("habits"), storage)
    assert result.success is True
    assert result.metadata["count"] == 1
    msg = result.message
    assert "Your Habits (1)" in msg
    assert f"[{hid}]" in msg and "Meditate" in msg
    assert "🔥🔥🔥" in msg                      # streak 3 -> three fires
    assert "Streak: <b>3</b> | Best: 3" in msg
    assert "⏰ 07:00 • daily" in msg
    assert "Last done:" in msg
    assert "Use /streak <id> for details." in msg


def test_habits_list_fire_emoji_caps_at_five(storage):
    _seed_habit(storage, "Run", days_logged=tuple(range(8)))  # streak 8
    result = habit_views.habits_list(ctx("habits"), storage)
    assert "🔥" * 5 in result.message
    assert "🔥" * 6 not in result.message


def test_habits_list_zero_streak_shows_circle(storage):
    _seed_habit(storage, "Stretch")
    result = habit_views.habits_list(ctx("habits"), storage)
    assert "○ Streak: <b>0</b>" in result.message
    assert "Last done:" not in result.message   # conditional line absent


def test_habits_list_weekly_label_and_flexible_time(storage):
    _seed_habit(storage, "Gym", recurrence="weekly", recurrence_weekday=0)
    result = habit_views.habits_list(ctx("habits"), storage)
    assert "⏰ flexible • weekly (day 0)" in result.message


def test_habits_list_escapes_html_in_title(storage):
    _seed_habit(storage, "Read <books> & sleep")
    result = habit_views.habits_list(ctx("habits"), storage)
    assert "Read &lt;books&gt; &amp; sleep" in result.message
    assert "<books>" not in result.message


def test_habits_list_excludes_paused_and_done(storage):
    _seed_habit(storage, "Keep")
    paused = _seed_habit(storage, "Paused one")
    storage.tasks.pause(paused, UID)
    result = habit_views.habits_list(ctx("habits"), storage)
    assert "Keep" in result.message
    assert "Paused one" not in result.message   # get_habits filters paused=0


# ── streak_detail ────────────────────────────────────────────────────────

def test_streak_detail_rejects_missing_and_non_habit(storage):
    result = habit_views.streak_detail(999, ctx("streak 999"), storage)
    assert result.success is False
    assert "not_a_habit" in result.warnings
    tid = storage.tasks.add(UID, "Plain task")
    result = habit_views.streak_detail(tid, ctx(f"streak {tid}"), storage)
    assert result.success is False
    assert "not_a_habit" in result.warnings
    assert "That's not a habit" in result.message


def test_streak_detail_paused_habit_replicates_legacy_quirk(storage):
    # Legacy's double lookup: get_task_by_id + is_habit pass, but the
    # second fetch through get_habits (paused=0 filter) comes back
    # empty -> "Habit not found or paused." Verified in streak_cmd(),
    # replicated not fixed.
    hid = _seed_habit(storage, "Napping")
    storage.tasks.pause(hid, UID)
    result = habit_views.streak_detail(hid, ctx(f"streak {hid}"), storage)
    assert result.success is False
    assert "habit_not_visible" in result.warnings
    assert result.message == "Habit not found or paused."


def test_streak_detail_requires_now(storage):
    hid = _seed_habit(storage, "Meditate")
    context = RequestContext(user_id=UID, text=f"streak {hid}",
                              intent=Intent.QUERY_TASK, entities={}, now=None)
    result = habit_views.streak_detail(hid, context, storage)
    assert result.success is False
    assert "missing_now" in result.warnings


def test_streak_detail_full_render_with_grid(storage):
    hid = _seed_habit(storage, "Meditate", days_logged=(2, 1, 0), time="07:00")
    result = habit_views.streak_detail(hid, ctx(f"streak {hid}"), storage)
    assert result.success is True
    assert result.metadata["streak"] == 3
    msg = result.message
    assert "Current streak: <b>3 days</b>" in msg
    assert "Longest streak: <b>3 days</b>" in msg
    assert "📅 Started:" in msg and "✅ Last done:" in msg
    # 14-day grid: 11 empty then 3 filled (logged today and 2 days back).
    assert "⬜" * 11 + "🟩" * 3 in msg
    # Daily habit created today with 3/3 days logged since start: no
    # missed days -> no warning block.
    assert "Missed" not in msg


def test_streak_detail_singular_day(storage):
    hid = _seed_habit(storage, "Meditate", days_logged=(0,))
    result = habit_views.streak_detail(hid, ctx(f"streak {hid}"), storage)
    assert "Current streak: <b>1 day</b>" in result.message


def test_streak_detail_missed_days_warning_and_tip(storage, monkeypatch):
    # Backdate habit_start_date so the daily habit "should" have run on
    # unlogged days -- 4+ missed triggers both the warning and the tip.
    hid = _seed_habit(storage, "Meditate", days_logged=(0,))
    start = (_now().date() - timedelta(days=6)).strftime("%Y-%m-%d")
    conn = sqlite3.connect(db.DB_NAME)
    conn.execute("UPDATE tasks SET habit_start_date=? WHERE id=?", (start, hid))
    conn.commit()
    conn.close()
    result = habit_views.streak_detail(hid, ctx(f"streak {hid}"), storage)
    assert result.success is True
    assert result.metadata["missed"] == 6
    assert "⚠️ Missed 6 day(s) in this window." in result.message
    assert "Tip: try changing the time or making it easier." in result.message


# ── habit_log_view ───────────────────────────────────────────────────────

def test_habit_log_rejects_non_habit(storage):
    tid = storage.tasks.add(UID, "Plain task")
    result = habit_views.habit_log_view(tid, ctx(f"habitlog {tid}"), storage)
    assert result.success is False
    assert "not_a_habit" in result.warnings
    assert result.message == "That's not a habit."


def test_habit_log_empty_is_a_real_answer(storage):
    # Legacy replies (doesn't fall through) on an empty log -- success.
    hid = _seed_habit(storage, "Meditate")
    result = habit_views.habit_log_view(hid, ctx(f"habitlog {hid}"), storage)
    assert result.success is True
    assert result.data == []
    assert "No log entries yet for <b>Meditate</b>." in result.message


def test_habit_log_renders_entries_newest_first(storage):
    hid = _seed_habit(storage, "Meditate", days_logged=(1, 0))
    result = habit_views.habit_log_view(hid, ctx(f"habitlog {hid}"), storage)
    assert result.success is True
    assert result.metadata["entries"] == 2
    lines = result.message.splitlines()
    assert "Log for Meditate" in lines[0] and "(last 30 days)" in lines[0]
    today = _now().date().strftime("%Y-%m-%d")
    assert lines[2] == f"✅ {today}"            # DESC order: today first


# ── Engine dispatch through the default registry ─────────────────────────

def test_engine_dispatches_habits_list(storage, engine):
    _seed_habit(storage, "Meditate")
    for phrase in ("habits", "show habits", "my habits", "list habits"):
        result = engine.execute(ctx(phrase))
        assert result.success is True, phrase
        assert "Your Habits (1)" in result.message


def test_engine_dispatches_streak_and_habitlog(storage, engine):
    hid = _seed_habit(storage, "Meditate", days_logged=(0,))
    result = engine.execute(ctx(f"streak {hid}"))
    assert result.success is True and "Current streak" in result.message
    result = engine.execute(ctx(f"habitlog {hid}", intent=Intent.EDIT_TASK))
    assert result.success is True and "Log for Meditate" in result.message


def test_engine_idless_and_write_phrases_fall_through(storage, engine):
    # "streak" bare / "skiphabit" bare -> Legacy usage replies, no spec
    # claims them. ("skiphabit 5" was also unclaimed when this test was
    # written; v14.10 migrated it -- see tests/test_habit_writes.py.)
    result = engine.execute(ctx("streak"))
    assert result.success is False and "unsupported_action" in result.warnings
    result = engine.execute(ctx("skiphabit", intent=Intent.EDIT_TASK))
    assert result.success is False and "unsupported_action" in result.warnings


def test_habit_views_touch_no_conversation_state(storage, engine):
    # Read-only views return no state-changing metadata -- main.py only
    # sets editing/confirming state off start_editing/needs_confirmation
    # markers, which reads must never emit.
    _seed_habit(storage, "Meditate")
    for text, intent in (("habits", Intent.QUERY_TASK),
                          ("streak 1", Intent.QUERY_TASK),
                          ("habitlog 1", Intent.EDIT_TASK)):
        result = engine.execute(ctx(text, intent=intent))
        assert "start_editing" not in result.metadata
        assert "needs_confirmation" not in result.metadata


# ── build_enabled_registry (ADR-013): per-domain flag gating ─────────────

def _set_flags(monkeypatch, tasks, habits):
    import core.feature_flags as ff
    monkeypatch.setattr(ff, "OFFLINE_TASKS", tasks)
    monkeypatch.setattr(ff, "OFFLINE_HABITS", habits)


def test_enabled_registry_all_flags_off_is_empty(monkeypatch):
    _set_flags(monkeypatch, tasks=False, habits=False)
    registry = build_enabled_registry()
    assert registry.intents() == frozenset()
    assert registry.pending_types() == frozenset()


def test_enabled_registry_tasks_only_has_no_habit_specs(monkeypatch):
    _set_flags(monkeypatch, tasks=True, habits=False)
    registry = build_enabled_registry()
    names = [s.name for s in registry.resolve(Intent.QUERY_TASK)]
    assert "habits_list" not in names and "streak_view" not in names
    assert names == ["search_tasks", "today_tasks", "week_tasks",
                     "list_tasks", "paused_list"]


def test_enabled_registry_habits_only_leaves_tasks_to_legacy(temp_db, monkeypatch):
    _set_flags(monkeypatch, tasks=False, habits=True)
    engine = OfflineEngine(Storage(), registry=build_enabled_registry())
    # Habit view works...
    result = engine.execute(ctx("habits"))
    assert result.success is True
    # ...but task phrases resolve nothing and fall through to Legacy.
    # (v14.10: ADD_TASK is no longer empty in a habits-only build --
    # create_habit lives there -- so "todo ..." is unsupported_action,
    # a registered intent whose specs all declined, not
    # unsupported_intent.)
    result = engine.execute(ctx("list"))
    assert result.success is False and "unsupported_action" in result.warnings
    result = engine.execute(ctx("todo Buy milk", intent=Intent.ADD_TASK))
    assert result.success is False and "unsupported_action" in result.warnings


def test_enabled_registry_both_on_equals_default_catalog(monkeypatch):
    _set_flags(monkeypatch, tasks=True, habits=True)
    enabled, default = build_enabled_registry(), build_default_registry()
    assert enabled.intents() == default.intents()
    for intent in default.intents():
        assert ([s.name for s in enabled.resolve(intent)]
                == [s.name for s in default.resolve(intent)])
    assert enabled.pending_types() == default.pending_types()


# ── Failure Injection ────────────────────────────────────────────────────

class _RaisingHabits:
    def __init__(self, exc):
        self._exc = exc

    def __getattr__(self, name):
        def boom(*a, **k):
            raise self._exc
        return boom


class _FakeStorage:
    def __init__(self, habits, tasks=None):
        self.habits = habits
        self.tasks = tasks if tasks is not None else Storage().tasks


def test_database_exception_is_contained(temp_db):
    engine = OfflineEngine(_FakeStorage(_RaisingHabits(RuntimeError("boom"))))
    result = engine.execute(ctx("habits"))
    assert result.success is False
    assert "action_exception:RuntimeError" in result.warnings


def test_locked_database_is_contained(temp_db):
    engine = OfflineEngine(_FakeStorage(
        _RaisingHabits(sqlite3.OperationalError("database is locked"))))
    result = engine.execute(ctx("habits"))
    assert result.success is False
    assert "action_exception:OperationalError" in result.warnings


# ── Behavioral Equivalence: query parity + read invariance ──────────────

def _raw_rows(db_path):
    conn = sqlite3.connect(db_path)
    rows = (conn.execute("SELECT * FROM tasks ORDER BY id").fetchall(),
            conn.execute("SELECT * FROM habit_log ORDER BY id").fetchall())
    conn.close()
    return rows


def test_equivalence_query_counts_and_invariance(temp_db, storage, monkeypatch):
    hid = _seed_habit(storage, "Meditate", days_logged=(1, 0), time="07:00")
    before = _raw_rows(temp_db)

    counts = {"n": 0}
    real_connect = db.sqlite3.connect

    def counting_connect(*a, **k):
        conn = real_connect(*a, **k)
        conn.set_trace_callback(lambda stmt: counts.__setitem__("n", counts["n"] + 1))
        return conn

    monkeypatch.setattr(db.sqlite3, "connect", counting_connect)

    # habits list: Legacy habits_cmd() = one get_habits() call.
    counts["n"] = 0
    db.get_habits(UID)
    legacy = counts["n"]
    counts["n"] = 0
    habit_views.habits_list(ctx("habits"), storage)
    assert counts["n"] == legacy

    # streak view: Legacy streak_cmd() = get_task_by_id + is_habit +
    # get_habit_log(14) + get_missed_days(14) + get_habits.
    counts["n"] = 0
    db.get_task_by_id(hid, UID); db.is_habit(hid)
    db.get_habit_log(hid, UID, days=14); db.get_missed_days(hid, UID, days=14)
    db.get_habits(UID)
    legacy = counts["n"]
    counts["n"] = 0
    habit_views.streak_detail(hid, ctx(f"streak {hid}"), storage)
    assert counts["n"] == legacy

    # habit log: Legacy habitlog_cmd() = get_task_by_id + is_habit +
    # get_habit_log(30).
    counts["n"] = 0
    db.get_task_by_id(hid, UID); db.is_habit(hid); db.get_habit_log(hid, UID, days=30)
    legacy = counts["n"]
    counts["n"] = 0
    habit_views.habit_log_view(hid, ctx(f"habitlog {hid}"), storage)
    assert counts["n"] == legacy

    # Reads mutate nothing: raw rows byte-identical after all views.
    monkeypatch.setattr(db.sqlite3, "connect", real_connect)
    assert _raw_rows(temp_db) == before


# ── Performance ──────────────────────────────────────────────────────────

def test_performance_latency(temp_db, storage, engine):
    _seed_habit(storage, "Meditate", days_logged=(1, 0))
    n = 50
    start = time.perf_counter()
    for _ in range(n):
        db.get_habits(UID)                       # Legacy habits_cmd read
    legacy_ms = (time.perf_counter() - start) * 1000 / n
    start = time.perf_counter()
    for _ in range(n):
        engine.execute(ctx("habits"))            # Offline incl. dispatch
    offline_ms = (time.perf_counter() - start) * 1000 / n
    # Loose sanity bounds only -- measurement, not optimization.
    assert legacy_ms < 50 and offline_ms < 50


def test_performance_memory(temp_db, storage, engine):
    hid = _seed_habit(storage, "Meditate", days_logged=(1, 0))
    tracemalloc.start()
    before = tracemalloc.take_snapshot()
    for _ in range(50):
        engine.execute(ctx("habits"))
        engine.execute(ctx(f"streak {hid}"))
        engine.execute(ctx(f"habitlog {hid}", intent=Intent.EDIT_TASK))
    after = tracemalloc.take_snapshot()
    tracemalloc.stop()
    growth = sum(s.size_diff for s in after.compare_to(before, "lineno"))
    assert growth < 5_000_000
