"""
Tests for core/actions/create_habit.py + skip_habit.py -- the v14.10
Habit-domain Stage 2 deterministic writes -- plus the pins for the two
"CRUD" letters that need no habit code: habit update (v14.4's task edit
flow already covers habit rows) and habit delete (v14.5's task delete
flow already covers them, orphaned habit_log rows and all).

Same structure as every prior write-action suite: matchers, direct
execution against real temp-DB data, engine dispatch (including
no-crosstalk with create_task in the shared ADD_TASK bucket),
Behavioral Equivalence (Legacy call-sequence replicas compared row by
row + query-count parity), Failure Injection, and benchmarks.

Confirmation-flow equivalence is an *absence* both sides: Legacy's
/addhabit and /skiphabit never confirm (v14.10 Phase 0, ADR-010 --
creation is reversible by delete; skip's reset is self-healing), so
neither action emits needs_confirmation/start_editing metadata and
conversation state is never touched. "Cancel" therefore has no offline
surface to test (nothing pends) -- documented here rather than
invented.
"""
import sqlite3
import time
import tracemalloc

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

import database as db
import date_parser
from core.actions import create_habit, skip_habit
from core.intent.intent_types import Intent
from core.offline.engine import OfflineEngine
from core.offline.request_context import RequestContext
from core.storage import Storage

IST = ZoneInfo("Asia/Kolkata")
UID = 555000111


def _now():
    return datetime.now(IST)


def ctx(text, intent=Intent.ADD_TASK, now=None):
    return RequestContext(user_id=UID, text=text, intent=intent,
                           entities={}, now=now if now is not None else _now())


@pytest.fixture
def storage(temp_db):
    return Storage()


@pytest.fixture
def engine(storage):
    return OfflineEngine(storage)


def _habit_row(hid):
    conn = sqlite3.connect(db.DB_NAME)
    row = conn.execute(
        """SELECT title, due_time, recurrence_type, recurrence_weekday,
                  is_habit, current_streak, longest_streak, category, priority
           FROM tasks WHERE id=?""", (hid,)).fetchone()
    conn.close()
    return row


# ── create_habit: matcher ────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("addhabit Drink water", "Drink water"),
    ("add habit Run at 07:00", "Run at 07:00"),
    ("new habit Meditate", "Meditate"),
    ("  Add Habit   Run   fast  ", "Run fast"),   # case + collapse (args round-trip)
    ("addhabit", None),                            # bare -> Legacy usage card
    ("addhabit   ", None),
    ("add task Buy milk", None),                   # create_task's, not ours
    ("my add habit thing", None),
])
def test_match_create_habit(text, expected):
    assert create_habit.match_entry_command(text) == expected


# ── create_habit: execution ──────────────────────────────────────────────

def test_create_simple_habit_defaults(storage):
    result = create_habit.execute("Meditate", ctx("add habit Meditate"), storage)
    assert result.success is True
    hid = result.metadata["habit_id"]
    title, dtime, rec, weekday, is_h, cur, longest, cat, pri = _habit_row(hid)
    assert (title, dtime, rec, weekday) == ("Meditate", None, "daily", None)
    assert is_h == 1 and cur == 0 and longest == 0
    assert (cat, pri) == ("Health", "medium")      # add_habit()'s defaults
    assert "Habit created!" in result.message
    assert "⏰ flexible" in result.message and "🔄 daily" in result.message


def test_create_habit_parses_time_and_strips_title(storage):
    result = create_habit.execute("Drink water at 09:00 daily",
                                   ctx("addhabit Drink water at 09:00 daily"), storage)
    assert result.success is True
    title, dtime, rec, weekday, *_ = _habit_row(result.metadata["habit_id"])
    # Legacy's strip regex removes "at 09:00" (colon form) and "daily".
    assert (title, dtime, rec) == ("Drink water", "09:00", "daily")
    assert "⏰ 09:00" in result.message


def test_create_weekly_habit_title_quirk_replicated(storage):
    # Legacy's strip regex does NOT remove "every monday" or "at 7 AM"
    # (no colon) -- parse_all still extracts weekly/weekday-0/07:00, but
    # the words stay in the title. Verified Legacy behavior, replicated
    # not fixed (DEBUGGING.md v14.10 entry).
    result = create_habit.execute("gym every monday at 7 AM",
                                   ctx("add habit gym every monday at 7 AM"), storage)
    assert result.success is True
    title, dtime, rec, weekday, *_ = _habit_row(result.metadata["habit_id"])
    assert (dtime, rec, weekday) == ("07:00", "weekly", 0)
    assert title == "gym every monday at 7 AM"
    assert "🔄 weekly (day 0)" in result.message


def test_create_habit_empty_title_after_strip(storage):
    result = create_habit.execute("daily at 09:00",
                                   ctx("add habit daily at 09:00"), storage)
    assert result.success is False
    assert "empty_title" in result.warnings
    assert result.message == "Tell me what the habit is."
    assert db.get_habits(UID) == []                # nothing written


def test_create_habit_requires_now(storage):
    context = RequestContext(user_id=UID, text="add habit Run",
                              intent=Intent.ADD_TASK, entities={}, now=None)
    result = create_habit.execute("Run", context, storage)
    assert result.success is False and "missing_now" in result.warnings


def test_create_habit_has_no_duplicate_detection(storage):
    # Verified: addhabit_cmd() never checks for an existing habit --
    # two identical creates yield two habits, Legacy and Offline alike.
    create_habit.execute("Run", ctx("addhabit Run"), storage)
    result = create_habit.execute("Run", ctx("addhabit Run"), storage)
    assert result.success is True
    assert len(db.get_habits(UID)) == 2


def test_create_habit_escapes_html_in_title(storage):
    result = create_habit.execute("Read <b>ooks & sleep",
                                   ctx("addhabit Read <b>ooks & sleep"), storage)
    assert "&lt;b&gt;ooks &amp; sleep" in result.message
    assert "<b>ooks" not in result.message


# ── skip_habit: matcher ──────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("skiphabit 5", 5),
    ("skip habit 5", 5),
    ("reset streak 12", 12),
    ("  Skip  Habit 7  ", 7),
    ("skiphabit", None),                # bare -> Legacy usage reply
    ("skiphabit abc", None),
    ("streak 5", None),                 # the read view, not ours
    ("please reset streak 5", None),
])
def test_match_skip_habit(text, expected):
    assert skip_habit.match_entry_command(text) == expected


# ── skip_habit: execution ────────────────────────────────────────────────

def _seed_streaky_habit(storage, days=3):
    hid = storage.habits.add(UID, "Meditate")
    from datetime import timedelta
    for offset in sorted(range(days), reverse=True):
        storage.habits.log_completion(
            hid, UID, (_now().date() - timedelta(days=offset)).strftime("%Y-%m-%d"))
    return hid


def test_skip_rejects_missing_and_non_habit(storage):
    result = skip_habit.execute(999, ctx("skiphabit 999", Intent.EDIT_TASK), storage)
    assert result.success is False and "not_a_habit" in result.warnings
    tid = storage.tasks.add(UID, "Plain task")
    result = skip_habit.execute(tid, ctx(f"skiphabit {tid}", Intent.EDIT_TASK), storage)
    assert result.success is False
    assert result.message == "That's not a habit."


def test_skip_resets_current_streak_only(storage):
    hid = _seed_streaky_habit(storage, days=3)
    assert _habit_row(hid)[5] == 3                  # current_streak
    result = skip_habit.execute(hid, ctx(f"skiphabit {hid}", Intent.EDIT_TASK), storage)
    assert result.success is True
    row = _habit_row(hid)
    assert row[5] == 0                              # current reset
    assert row[6] == 3                              # longest untouched
    assert "Streak reset for <b>Meditate</b>" in result.message
    # habit_log rows untouched (the reset is display-state only).
    conn = sqlite3.connect(db.DB_NAME)
    assert conn.execute("SELECT COUNT(*) FROM habit_log WHERE habit_id=?",
                         (hid,)).fetchone()[0] == 3
    conn.close()


def test_skip_is_idempotent_like_legacy(storage):
    # Legacy's UPDATE is guardless -- a second skip repeats the reply.
    hid = _seed_streaky_habit(storage)
    first = skip_habit.execute(hid, ctx(f"skiphabit {hid}", Intent.EDIT_TASK), storage)
    second = skip_habit.execute(hid, ctx(f"skiphabit {hid}", Intent.EDIT_TASK), storage)
    assert first.success is True and second.success is True
    assert first.message == second.message


def test_skip_reset_is_self_healing(storage):
    # The DEBUGGING.md finding, pinned: the next completion recomputes
    # the streak from the full habit_log history, overwriting the reset
    # -- which is why ADR-010 correctly classifies skip as reversible
    # (hence no confirm, matching Legacy).
    from datetime import timedelta
    hid = storage.habits.add(UID, "Meditate")
    for offset in (2, 1):
        storage.habits.log_completion(
            hid, UID, (_now().date() - timedelta(days=offset)).strftime("%Y-%m-%d"))
    skip_habit.execute(hid, ctx(f"skiphabit {hid}", Intent.EDIT_TASK), storage)
    assert _habit_row(hid)[5] == 0
    storage.habits.log_completion(hid, UID, _now().date().strftime("%Y-%m-%d"))
    assert _habit_row(hid)[5] == 3                  # recomputed, reset undone


# ── Engine dispatch ──────────────────────────────────────────────────────

def test_engine_dispatches_create_habit_and_create_task_without_crosstalk(storage, engine):
    result = engine.execute(ctx("add habit Run at 07:00 daily"))
    assert result.success is True and "Habit created!" in result.message
    assert "needs_confirmation" not in result.metadata      # direct apply
    # create_task still proposes (confirm flow) for its own prefixes.
    result = engine.execute(ctx("add task Buy milk"))
    assert result.success is True
    assert result.metadata.get("needs_confirmation") is True


def test_engine_dispatches_skip_habit(storage, engine):
    hid = _seed_streaky_habit(storage)
    for phrase in (f"skiphabit {hid}", f"skip habit {hid}", f"reset streak {hid}"):
        result = engine.execute(ctx(phrase, Intent.EDIT_TASK))
        assert result.success is True, phrase
        assert "Streak reset" in result.message


def test_engine_idless_write_phrases_fall_through(storage, engine):
    for text, intent in (("addhabit", Intent.ADD_TASK),
                          ("skip habit", Intent.EDIT_TASK),
                          ("random thing", Intent.ADD_TASK)):
        result = engine.execute(ctx(text, intent))
        assert result.success is False, text
        assert "unsupported_action" in result.warnings


def test_habit_delete_needs_no_habit_code(storage, engine):
    # "Delete Habit" is v14.5's task delete on the habit's task row --
    # dispatch pin that the existing path claims it (propose + confirm).
    hid = _seed_streaky_habit(storage)
    result = engine.execute(RequestContext(
        user_id=UID, text=f"delete task {hid}", intent=Intent.DELETE_TASK,
        entities={"task_id": hid}, now=_now()))
    assert result.success is True
    assert result.metadata.get("needs_confirmation") is True


def test_habit_update_needs_no_habit_code(storage, engine):
    # "Update Habit" doesn't exist in Legacy; habits are task rows, so
    # v14.4's edit flow already covers them -- dispatch pin.
    hid = _seed_streaky_habit(storage)
    result = engine.execute(ctx(f"edit task {hid}", Intent.EDIT_TASK))
    assert result.success is True
    assert result.metadata.get("start_editing") is True


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


def test_create_database_exception_is_contained(temp_db):
    engine = OfflineEngine(_FakeStorage(_RaisingHabits(RuntimeError("boom"))))
    result = engine.execute(ctx("add habit Run"))
    assert result.success is False
    assert "action_exception:RuntimeError" in result.warnings


def test_skip_locked_database_is_contained(temp_db, storage):
    hid = storage.habits.add(UID, "Meditate")
    engine = OfflineEngine(_FakeStorage(
        _RaisingHabits(sqlite3.OperationalError("database is locked"))))
    result = engine.execute(ctx(f"skiphabit {hid}", Intent.EDIT_TASK))
    assert result.success is False
    assert "action_exception:OperationalError" in result.warnings


def test_writes_never_touch_conversation_state_markers(storage, engine):
    hid = _seed_streaky_habit(storage)
    for text, intent in (("add habit Run at 07:00", Intent.ADD_TASK),
                          (f"skiphabit {hid}", Intent.EDIT_TASK)):
        result = engine.execute(ctx(text, intent))
        assert "needs_confirmation" not in result.metadata
        assert "start_editing" not in result.metadata


# ── Behavioral Equivalence ───────────────────────────────────────────────

def _legacy_addhabit(uid, text, now):
    """addhabit_cmd()'s exact pipeline (main.py:3027-3045), minus the
    Telegram reply."""
    import re as _re
    p = date_parser.parse_all(text, now)
    time_val = p.get("time")
    rec = p.get("recurrence")
    rec_type = rec["type"] if rec else "daily"
    rec_weekday = rec.get("weekday") if rec else None
    title = _re.sub(r"\b(at\s+\d{1,2}:\d{2})\b|\b(daily|every day|every week|weekly|monthly)\b",
                    "", text, flags=_re.IGNORECASE).strip()
    title = _re.sub(r"\s+", " ", title)
    return db.add_habit(uid, title, time=time_val,
                        recurrence=rec_type, recurrence_weekday=rec_weekday)


@pytest.mark.parametrize("description", [
    "Drink water at 09:00 daily",
    "gym every monday at 7 AM",
    "Meditate",
])
def test_equivalence_create(temp_db, storage, description):
    now = _now()
    legacy_uid, offline_uid = UID, UID + 1
    legacy_id = _legacy_addhabit(legacy_uid, description, now)
    result = create_habit.execute(description, RequestContext(
        user_id=offline_uid, text=f"addhabit {description}",
        intent=Intent.ADD_TASK, entities={}, now=now), storage)
    assert result.success is True
    assert _habit_row(legacy_id) == _habit_row(result.metadata["habit_id"])


def test_equivalence_skip_and_delete(temp_db, storage):
    from datetime import timedelta
    # Two identical habits with identical logs, one per path.
    ids = {}
    for label, uid in (("legacy", UID), ("offline", UID + 1)):
        hid = db.add_habit(uid, "Meditate")
        for offset in (1, 0):
            db.log_habit_completion(hid, uid,
                (_now().date() - timedelta(days=offset)).strftime("%Y-%m-%d"))
        ids[label] = (uid, hid)

    # Skip: Legacy = get_task_by_id + is_habit + reset_streak.
    luid, lhid = ids["legacy"]
    assert db.get_task_by_id(lhid, luid) and db.is_habit(lhid)
    db.reset_streak(lhid)
    ouid, ohid = ids["offline"]
    result = skip_habit.execute(ohid, RequestContext(
        user_id=ouid, text=f"skiphabit {ohid}", intent=Intent.EDIT_TASK,
        entities={}, now=_now()), storage)
    assert result.success is True
    assert _habit_row(lhid) == _habit_row(ohid)

    # Delete-of-habit: Legacy delete_task() vs Offline propose+commit --
    # both single-table deletes that orphan habit_log rows identically.
    from core.actions import delete_task as offline_delete
    db.delete_task(lhid, luid)
    proposal = offline_delete.propose(ohid, ouid, storage)
    commit = offline_delete.commit(proposal.metadata["pending_data"], ouid, storage)
    assert commit.success is True
    conn = sqlite3.connect(db.DB_NAME)
    remaining = conn.execute("SELECT COUNT(*) FROM tasks WHERE id IN (?,?)",
                              (lhid, ohid)).fetchone()[0]
    orphans_l = conn.execute("SELECT COUNT(*) FROM habit_log WHERE habit_id=?",
                              (lhid,)).fetchone()[0]
    orphans_o = conn.execute("SELECT COUNT(*) FROM habit_log WHERE habit_id=?",
                              (ohid,)).fetchone()[0]
    conn.close()
    assert remaining == 0
    assert orphans_l == orphans_o == 2              # orphaned alike


def test_equivalence_query_counts(temp_db, storage, monkeypatch):
    hid_legacy = db.add_habit(UID, "Meditate")
    hid_offline = db.add_habit(UID + 1, "Meditate")

    counts = {"n": 0}
    real_connect = db.sqlite3.connect

    def counting_connect(*a, **k):
        conn = real_connect(*a, **k)
        conn.set_trace_callback(lambda stmt: counts.__setitem__("n", counts["n"] + 1))
        return conn

    monkeypatch.setattr(db.sqlite3, "connect", counting_connect)
    now = _now()

    # Create: Legacy = one add_habit() call.
    counts["n"] = 0
    _legacy_addhabit(UID, "Run at 07:00 daily", now)
    legacy = counts["n"]
    counts["n"] = 0
    create_habit.execute("Run at 07:00 daily", RequestContext(
        user_id=UID + 1, text="addhabit Run at 07:00 daily",
        intent=Intent.ADD_TASK, entities={}, now=now), storage)
    assert counts["n"] == legacy

    # Skip: Legacy = get_task_by_id + is_habit + reset_streak.
    counts["n"] = 0
    db.get_task_by_id(hid_legacy, UID); db.is_habit(hid_legacy); db.reset_streak(hid_legacy)
    legacy = counts["n"]
    counts["n"] = 0
    skip_habit.execute(hid_offline, RequestContext(
        user_id=UID + 1, text=f"skiphabit {hid_offline}",
        intent=Intent.EDIT_TASK, entities={}, now=now), storage)
    assert counts["n"] == legacy


# ── Performance ──────────────────────────────────────────────────────────

def test_performance_latency(temp_db, storage, engine):
    n = 30
    now = _now()
    start = time.perf_counter()
    for k in range(n):
        _legacy_addhabit(UID, f"Legacy habit {k} at 09:00 daily", now)
    legacy_ms = (time.perf_counter() - start) * 1000 / n
    start = time.perf_counter()
    for k in range(n):
        engine.execute(ctx(f"add habit Offline habit {k} at 09:00 daily"))
    offline_ms = (time.perf_counter() - start) * 1000 / n
    assert legacy_ms < 100 and offline_ms < 100     # loose sanity bounds


def test_performance_memory(temp_db, storage, engine):
    hid = _seed_streaky_habit(storage)
    tracemalloc.start()
    before = tracemalloc.take_snapshot()
    for _ in range(50):
        engine.execute(ctx(f"skiphabit {hid}", Intent.EDIT_TASK))
    after = tracemalloc.take_snapshot()
    tracemalloc.stop()
    growth = sum(s.size_diff for s in after.compare_to(before, "lineno"))
    assert growth < 5_000_000
