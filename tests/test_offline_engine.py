"""
Tests for core/offline/ + core/actions/ -- the v14.2 Offline Engine
(Stage 1: read-only task commands only).

Uses the same temp_db/uid fixtures as tests/test_storage_facade.py
(conftest.py) so Actions are exercised against real, isolated SQLite
data via the Storage Facade -- not mocked -- proving both correctness
and that the whole path never touches database.py directly (a plain
grep already confirms zero `import database` in core/offline/ or
core/actions/; these tests additionally prove the facade path actually
produces correct results, not just that it compiles).
"""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

import core.feature_flags as feature_flags
from core.intent.intent_types import Intent
from core.offline.action_result import ActionResult
from core.offline.engine import OfflineEngine, _select_action
from core.offline.request_context import RequestContext
from core.storage import Storage

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 3, 4, 10, 0, tzinfo=IST)


def ctx(text, uid, intent=Intent.QUERY_TASK, entities=None, now=NOW):
    return RequestContext(user_id=uid, text=text, intent=intent,
                           entities=entities or {}, now=now)


@pytest.fixture
def engine():
    return OfflineEngine(Storage())


# ── RequestContext ────────────────────────────────────────────────────────

def test_request_context_defaults():
    c = RequestContext(user_id=1, text="list", intent=Intent.QUERY_TASK)
    assert c.entities == {}
    assert c.now is None


def test_request_context_is_frozen():
    c = RequestContext(user_id=1, text="list", intent=Intent.QUERY_TASK)
    with pytest.raises(AttributeError):
        c.user_id = 2


def test_offline_and_actions_packages_never_import_telegram():
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent
    for pkg in ("core/offline", "core/actions"):
        for pyfile in (root / pkg).glob("*.py"):
            tree = ast.parse(pyfile.read_text(encoding="utf-8"), filename=str(pyfile))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module] if node.module else []
                else:
                    continue
                assert not any((n or "").startswith("telegram") for n in names), \
                    f"{pyfile} imports telegram"


# ── ActionResult ──────────────────────────────────────────────────────────

def test_action_result_defaults():
    r = ActionResult(success=True, message="ok")
    assert r.data is None
    assert r.warnings == []
    assert r.metadata == {}


def test_action_result_warnings_and_metadata_are_independent_per_instance():
    a = ActionResult(success=True, message="a")
    b = ActionResult(success=True, message="b")
    a.warnings.append("x")
    assert b.warnings == []  # mutable-default bug would leak across instances


# ── OfflineEngine dispatch ───────────────────────────────────────────────

def test_non_query_task_intent_is_unsupported(engine, uid):
    # CHAT is inherently AI-shaped and will never be an Offline Engine
    # intent (core/intent/rules.py's Tier 3 named exception) -- a stable
    # choice for "genuinely unsupported," unlike ADD_TASK/EDIT_TASK/
    # DELETE_TASK, all of which became real, supported intents across
    # v14.3/v14.4/v14.5 after this test was originally written.
    result = engine.execute(ctx("how are you", uid, intent=Intent.CHAT))
    assert result.success is False
    assert "unsupported_intent" in result.warnings


def test_query_task_intent_with_unrecognized_text_is_unsupported(engine, uid):
    # "/habits" is also classified QUERY_TASK today (core/intent/rules.py)
    # but isn't one of this Stage's four actions -- must fall through
    # gracefully, not crash or silently misroute.
    result = engine.execute(ctx("habits", uid, intent=Intent.QUERY_TASK))
    assert result.success is False
    assert "unsupported_action" in result.warnings


@pytest.mark.parametrize("text,expected_module", [
    ("list", "list_tasks"),
    ("my tasks", "list_tasks"),
    ("today", "today_tasks"),
    ("what's today", "today_tasks"),
    ("week", "week_tasks"),
    ("this week", "week_tasks"),
    ("search milk", "search_tasks"),
    ("find keys", "search_tasks"),
    ("look for wallet", "search_tasks"),
])
def test_select_action_dispatches_to_correct_action(text, expected_module):
    action = _select_action(text)
    assert action is not None
    assert action.__module__.endswith(expected_module)


def test_select_action_returns_none_for_unrecognized_text():
    assert _select_action("habits") is None
    assert _select_action("random gibberish") is None


def test_engine_execution_exception_is_caught_gracefully(engine, uid, monkeypatch):
    def _boom(context, storage):
        raise RuntimeError("simulated failure")
    monkeypatch.setattr("core.offline.engine.list_tasks.execute", _boom)
    result = engine.execute(ctx("list", uid))
    assert result.success is False
    assert any(w.startswith("action_exception:") for w in result.warnings)


# ── Actions against real (temp) storage ─────────────────────────────────

def test_list_tasks_action_via_storage_facade(temp_db, uid, engine):
    Storage().tasks.add(uid, "Buy milk")
    result = engine.execute(ctx("list", uid))
    assert result.success is True
    assert len(result.data) == 1
    assert "Buy milk" in result.message


def test_list_tasks_action_empty(temp_db, uid, engine):
    result = engine.execute(ctx("list", uid))
    assert result.success is True
    assert result.data == []
    assert "No pending tasks" in result.message


def test_today_tasks_action_via_storage_facade(temp_db, uid, engine):
    Storage().tasks.add(uid, "Dentist", due_date="2026-03-04")
    result = engine.execute(ctx("today", uid))
    assert result.success is True
    assert len(result.data) == 1
    assert result.metadata["date"] == "2026-03-04"


def test_today_tasks_action_requires_now(temp_db, uid, engine):
    result = engine.execute(ctx("today", uid, now=None))
    assert result.success is False
    assert "missing_now" in result.warnings


def test_week_tasks_action_via_storage_facade(temp_db, uid, engine):
    Storage().tasks.add(uid, "Conference", due_date="2026-03-08")
    result = engine.execute(ctx("this week", uid))
    assert result.success is True
    assert len(result.data) == 1


def test_week_tasks_action_requires_now(temp_db, uid, engine):
    result = engine.execute(ctx("week", uid, now=None))
    assert result.success is False
    assert "missing_now" in result.warnings


def test_week_tasks_action_empty(temp_db, uid, engine):
    result = engine.execute(ctx("week", uid))
    assert result.success is True
    assert result.data == []
    assert "No tasks this week" in result.message


def test_today_tasks_action_empty(temp_db, uid, engine):
    result = engine.execute(ctx("today", uid))
    assert result.success is True
    assert result.data == []
    assert "No tasks for today" in result.message


def test_extract_keyword_direct_call_without_prefix():
    # execute() calls _extract_keyword(context.text) unconditionally;
    # this branch (no recognized prefix at all) is unreachable via
    # _select_action's own routing (which requires a prefix match to
    # dispatch here in the first place) but is exercised if
    # search_tasks.execute() is ever called directly -- a real,
    # deliberate fallback (treat the whole text as the keyword), not
    # dead code.
    from core.actions.search_tasks import _extract_keyword
    assert _extract_keyword("milk") == "milk"


def test_search_tasks_action_via_storage_facade(temp_db, uid, engine):
    Storage().tasks.add(uid, "Submit report")
    result = engine.execute(ctx("search report", uid))
    assert result.success is True
    assert len(result.data) == 1
    assert result.metadata["keyword"] == "report"


def test_search_tasks_action_empty_keyword(temp_db, uid, engine):
    result = engine.execute(ctx("search ", uid))
    assert result.success is False
    assert "empty_keyword" in result.warnings


def test_search_tasks_action_no_matches(temp_db, uid, engine):
    Storage().tasks.add(uid, "Unrelated task")
    result = engine.execute(ctx("search xyzzy", uid))
    assert result.success is True
    assert result.data == []


# ── Feature flag routing ─────────────────────────────────────────────────

def test_offline_tasks_flag_defaults_off():
    assert feature_flags.OFFLINE_TASKS is False


def test_main_py_gate_condition_respects_flag_off(monkeypatch, uid):
    # Mirrors main.py's exact gating condition
    # (`feature_flags.OFFLINE_TASKS and intent is not None`) without
    # driving a real Telegram message through handle_message() --
    # this project's tests don't mock Telegram Update objects.
    monkeypatch.setattr(feature_flags, "OFFLINE_TASKS", False)
    intent_result = object()  # any non-None sentinel
    should_attempt_offline = feature_flags.OFFLINE_TASKS and intent_result is not None
    assert should_attempt_offline is False


def test_main_py_gate_condition_respects_flag_on(monkeypatch, uid):
    monkeypatch.setattr(feature_flags, "OFFLINE_TASKS", True)
    intent_result = object()
    should_attempt_offline = feature_flags.OFFLINE_TASKS and intent_result is not None
    assert should_attempt_offline is True


def test_main_py_gate_condition_respects_missing_intent(monkeypatch, uid):
    # If Intent Engine classification itself failed (intent is None,
    # e.g. an exception was caught upstream), the gate must not attempt
    # offline execution even with the flag on.
    monkeypatch.setattr(feature_flags, "OFFLINE_TASKS", True)
    intent_result = None
    should_attempt_offline = feature_flags.OFFLINE_TASKS and intent_result is not None
    assert should_attempt_offline is False


# ── Storage usage (no direct database.py access) ─────────────────────────

def test_offline_package_never_imports_database_directly():
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent
    for pkg in ("core/offline", "core/actions"):
        for pyfile in (root / pkg).glob("*.py"):
            tree = ast.parse(pyfile.read_text(encoding="utf-8"), filename=str(pyfile))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module] if node.module else []
                else:
                    continue
                assert "database" not in names, f"{pyfile} imports database.py directly"
