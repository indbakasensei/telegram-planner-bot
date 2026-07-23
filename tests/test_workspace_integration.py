"""
Integration tests for v15.0-beta.1 -- Workspace OS production wiring
(core/workspace/app.py + llm_interpreter.py + the main.py feature-flag
branch and scheduler registration).

Covers the beta.1 acceptance list, all offline (AI + Telegram faked):
feature-flag OFF/ON, message -> proposal -> execution, Timeline recording,
Sync delivery, AI fallback, worker lifecycle, and graceful shutdown.
"""
import asyncio
import threading

import pytest

import database as db
from core import feature_flags
from core.workspace import app
from core.workspace.engine import EntityEngine
from core.workspace.llm_interpreter import LLMInterpreter
from core.workspace.orchestrator import (
    Action,
    OrchestratorContext,
    Proposal,
    RuleBasedInterpreter,
    Status,
    WorkspaceOrchestrator,
)
from core.workspace.sync import SyncEngine
from core.workspace.adapters.telegram import TelegramAdapter
from core.workspace.timeline import TimelineEngine


@pytest.fixture(autouse=True)
def _clean_app_state():
    app.reset_state()
    yield
    app.reset_state()


def _rule_orch():
    te = TimelineEngine()
    eng = EntityEngine(on_event=te.record)
    return WorkspaceOrchestrator(engine=eng, interpreter=RuleBasedInterpreter()), te


class RecordingSender:
    def __init__(self):
        self.calls = []
    def __call__(self, user_id, text, target_id):
        self.calls.append((user_id, text, target_id))
        return len(self.calls)


# ══ 1. Feature-flag OFF / ON ══════════════════════════════════════════════

def test_flag_off_registers_no_worker():
    class FakeJQ:
        def __init__(self): self.registered = []
        def run_repeating(self, *a, **k): self.registered.append(k.get("name"))
    class FakeApp: job_queue = FakeJQ()
    assert feature_flags.WORKSPACE is False
    app_ = FakeApp()
    assert app.register_workers(app_) is False
    assert app_.job_queue.registered == []


def test_flag_on_registers_worker(monkeypatch):
    monkeypatch.setattr(feature_flags, "WORKSPACE", True)
    class FakeJQ:
        def __init__(self): self.registered = []
        def run_repeating(self, cb, **k): self.registered.append(k.get("name"))
    class FakeApp: job_queue = FakeJQ()
    app_ = FakeApp()
    assert app.register_workers(app_) is True
    assert "workspace_sync" in app_.job_queue.registered


# ══ 2. message -> proposal -> execution ═══════════════════════════════════

def test_create_then_followup_uses_active_workspace(temp_db, uid):
    orch, te = _rule_orch()
    handled, reply = app.process_message(uid, "create workspace Robot", orchestrator=orch)
    assert handled and "Robot" in reply
    assert db.get_workspace_by_title(uid, "Robot") is not None
    # follow-up with no explicit workspace uses the tracked active one
    handled, reply = app.process_message(uid, "add milestone Frame", orchestrator=orch)
    assert handled
    ws = db.get_workspace_by_title(uid, "Robot")
    titles = [m[3] for m in db.get_milestones(ws[0])]
    assert "Frame" in titles


def test_unknown_message_falls_through_to_legacy(temp_db, uid):
    orch, _ = _rule_orch()
    handled, reply = app.process_message(uid, "what's the weather", orchestrator=orch)
    assert handled is False   # Legacy pipeline should handle it


def test_confirmation_flow(temp_db, uid):
    orch, _ = _rule_orch()
    app.process_message(uid, "create workspace Robot", orchestrator=orch)
    app.process_message(uid, "add milestone Doomed", orchestrator=orch)
    # delete is irreversible -> needs confirmation, nothing deleted yet
    handled, reply = app.process_message(uid, "delete milestone Doomed", orchestrator=orch)
    assert handled and "confirm" in reply.lower()
    ws = db.get_workspace_by_title(uid, "Robot")
    assert db.get_milestones(ws[0])   # still there
    # confirm applies it
    handled, reply = app.process_message(uid, "yes", orchestrator=orch)
    assert handled
    assert db.get_milestones(ws[0]) == []


def test_confirmation_cancel(temp_db, uid):
    orch, _ = _rule_orch()
    app.process_message(uid, "create workspace Robot", orchestrator=orch)
    app.process_message(uid, "add milestone Keep", orchestrator=orch)
    app.process_message(uid, "delete milestone Keep", orchestrator=orch)
    handled, reply = app.process_message(uid, "no", orchestrator=orch)
    assert handled and "cancel" in reply.lower()
    ws = db.get_workspace_by_title(uid, "Robot")
    assert db.get_milestones(ws[0])   # not deleted


# ══ 3. Timeline recording ═════════════════════════════════════════════════

def test_pipeline_records_timeline(temp_db, uid):
    orch, te = _rule_orch()
    app.process_message(uid, "create workspace Robot", orchestrator=orch)
    app.process_message(uid, "add milestone Frame", orchestrator=orch)
    types = [e.event_type for e in te.timeline(uid)]
    assert "workspace.created" in types and "milestone.added" in types


# ══ 4. Sync delivery ══════════════════════════════════════════════════════

def test_sync_delivers_pipeline_events(temp_db, uid):
    orch, te = _rule_orch()
    app.process_message(uid, "create workspace Robot", orchestrator=orch)
    app.process_message(uid, "add milestone Frame", orchestrator=orch)
    sender = RecordingSender()
    engine = SyncEngine(adapters=[TelegramAdapter(sender)])
    worker = app.SyncWorker(engine, user_ids_fn=lambda: [uid])
    report = worker.run_once()
    assert report["sent"] == 2 and report["users"] == 1
    assert len(sender.calls) == 2
    assert db.get_unsynced_timeline(uid) == []   # all delivered + stamped


def test_build_sync_engine_is_telegram_only():
    eng = app.build_sync_engine(RecordingSender())
    assert eng.adapters == ("telegram",)


# ══ 5. AI fallback ════════════════════════════════════════════════════════

def test_llm_interpreter_parses_valid_json(temp_db, uid):
    def fake_ai(messages):
        return '{"action":"create_workspace","params":{"title":"Robot"},"confidence":0.9}'
    p = LLMInterpreter(ai_call=fake_ai).interpret("make a robot workspace",
                                                  OrchestratorContext(uid))
    assert p.action == Action.CREATE_WORKSPACE and p.params["title"] == "Robot"


def test_llm_interpreter_falls_back_on_ai_error(temp_db, uid):
    def boom(messages):
        raise RuntimeError("nim down")
    # fallback is the rule-based interpreter, which parses this deterministically
    p = LLMInterpreter(ai_call=boom).interpret("create workspace Robot",
                                               OrchestratorContext(uid))
    assert p.action == Action.CREATE_WORKSPACE


def test_llm_interpreter_falls_back_on_garbage(temp_db, uid):
    p = LLMInterpreter(ai_call=lambda m: "not json at all").interpret(
        "add milestone Frame", OrchestratorContext(uid))
    assert p.action == Action.ADD_MILESTONE   # fallback rule-based parsed it


def test_llm_interpreter_falls_back_on_unknown_action(temp_db, uid):
    p = LLMInterpreter(ai_call=lambda m: '{"action":"launch_rocket"}').interpret(
        "nonsense", OrchestratorContext(uid))
    assert p.action == Action.UNKNOWN   # fallback returned unknown


def test_pipeline_with_failing_ai_still_executes(temp_db, uid):
    # End-to-end with an LLM that always fails -> rule-based fallback -> engine.
    def boom(m):
        raise TimeoutError()
    te = TimelineEngine()
    eng = EntityEngine(on_event=te.record)
    orch = WorkspaceOrchestrator(engine=eng, interpreter=LLMInterpreter(ai_call=boom))
    handled, reply = app.process_message(uid, "create workspace Robot", orchestrator=orch)
    assert handled and db.get_workspace_by_title(uid, "Robot") is not None


# ══ 6. Worker lifecycle + graceful shutdown ═══════════════════════════════

def test_worker_run_once_drains(temp_db, uid):
    db.add_timeline_event(uid, "workspace.created", "Created workspace: A",
                          workspace_id=1)
    sender = RecordingSender()
    worker = app.SyncWorker(SyncEngine(adapters=[TelegramAdapter(sender)]),
                            user_ids_fn=lambda: [uid])
    report = worker.run_once()
    assert report["sent"] == 1 and len(sender.calls) == 1


def test_worker_stops_gracefully(temp_db, uid):
    db.add_timeline_event(uid, "workspace.created", "a", workspace_id=1)
    worker = app.SyncWorker(SyncEngine(adapters=[TelegramAdapter(RecordingSender())]),
                            user_ids_fn=lambda: [uid])
    worker.stop()
    report = worker.run_once()
    assert report["stopped"] is True and report["sent"] == 0
    assert db.count_sync(uid) == 0   # nothing enqueued/sent after stop


def test_worker_never_raises_on_user_error(temp_db, uid):
    class BadEngine:
        def sync(self, u):
            raise RuntimeError("boom")
    worker = app.SyncWorker(BadEngine(), user_ids_fn=lambda: [uid, uid + 1])
    report = worker.run_once()   # must not raise
    assert report["users"] == 0  # both failed but pass completed


# ══ Production Telegram sender bridge (sync -> async, no live bot) ═════════

def test_production_sender_bridges_sync_to_async():
    loop = asyncio.new_event_loop()
    t = threading.Thread(target=loop.run_forever, daemon=True)
    t.start()
    try:
        class FakeMsg:
            message_id = 4242
        class FakeBot:
            async def send_message(self, **kwargs):
                return FakeMsg()
        sender = app.make_telegram_sender(FakeBot(), loop)
        ref = sender(123, "<b>hi</b>", None)
        assert ref == 4242
    finally:
        loop.call_soon_threadsafe(loop.stop)
