"""
Tests for v15.0-alpha.6 -- the Synchronization Engine + Telegram Adapter
(core/workspace/sync.py + adapters/telegram.py + the sync_outbox DB layer).

All offline: the Telegram adapter delivers through an injected fake sender,
never the live bot. Proves reliable outbound sync -- durable outbox,
idempotent enqueue, oldest-first drain, bounded retries with error capture,
graceful failure, and timeline synced_at stamping once delivered. The
full pipeline test wires Entity Engine -> Timeline -> Sync end to end.
"""
import sqlite3

import pytest

import database as db
from core.storage import Storage
from core.workspace.engine import EntityEngine
from core.workspace.sync import (
    FAILED,
    PENDING,
    SENT,
    SyncAdapter,
    SyncEngine,
    SyncItem,
    SyncResult,
)
from core.workspace.adapters.telegram import TelegramAdapter
from core.workspace.timeline import TimelineEngine, TimelineEvent


# ── test doubles ──────────────────────────────────────────────────────────

class RecordingSender:
    """A fake Telegram sender: records calls, returns an incrementing id."""
    def __init__(self):
        self.calls = []
        self._n = 0
    def __call__(self, user_id, text, target_id):
        self._n += 1
        self.calls.append((user_id, text, target_id))
        return self._n


class FlakyAdapter(SyncAdapter):
    """Fails a configurable number of times, then succeeds."""
    name = "flaky"
    def __init__(self, fail_times):
        self.remaining = fail_times
        self.deliveries = 0
    def render(self, event):
        return event.summary
    def deliver(self, item):
        self.deliveries += 1
        if self.remaining > 0:
            self.remaining -= 1
            return SyncResult.failure("temporary")
        return SyncResult.success(ref="ok")


class ExplodingAdapter(SyncAdapter):
    name = "boom"
    def render(self, event):
        return event.summary
    def deliver(self, item):
        raise RuntimeError("network down")


def _make_event(uid, summary="Created workspace: A"):
    eid = db.add_timeline_event(uid, "workspace.created", summary,
                                entity_type="workspace", entity_id=1,
                                workspace_id=1)
    return TimelineEvent.from_row(db.get_timeline(uid)[0])


# ── Schema ────────────────────────────────────────────────────────────────

def test_sync_outbox_schema(temp_db):
    assert "sync_outbox" in db.REQUIRED_TABLES
    conn = sqlite3.connect(temp_db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(sync_outbox)")}
    conn.close()
    assert {"user_id", "timeline_event_id", "adapter", "payload", "status",
            "attempts", "last_error", "sent_at", "ref"} <= cols
    assert db.verify_schema_integrity(temp_db)["ok"]


# ── DB layer ──────────────────────────────────────────────────────────────

def test_enqueue_and_pending(temp_db, uid):
    db.enqueue_sync(uid, "telegram", "hi", timeline_event_id=1, workspace_id=1)
    pend = db.get_pending_sync(uid)
    assert len(pend) == 1 and pend[0][4] == "telegram"
    assert db.count_sync(uid, status="pending") == 1


def test_mark_sent_and_failed(temp_db, uid):
    oid = db.enqueue_sync(uid, "telegram", "hi", timeline_event_id=1)
    db.mark_sync_sent(oid, ref="42")
    row = db.get_sync_row(oid)
    assert row[7] == "sent" and row[12] == "42" and row[11] is not None
    oid2 = db.enqueue_sync(uid, "telegram", "bye", timeline_event_id=2)
    db.mark_sync_failed(oid2, "nope")
    assert db.get_sync_row(oid2)[7] == "failed"


def test_outbox_exists_idempotency_guard(temp_db, uid):
    db.enqueue_sync(uid, "telegram", "hi", timeline_event_id=5)
    assert db.sync_outbox_exists(5, "telegram") is True
    assert db.sync_outbox_exists(5, "email") is False
    assert db.sync_outbox_exists(None, "telegram") is False


def test_reset_clears_sync_outbox(temp_db, uid):
    db.enqueue_sync(uid, "telegram", "hi", timeline_event_id=1)
    db.reset_everything(uid)
    assert db.count_sync(uid) == 0


# ── Telegram adapter ──────────────────────────────────────────────────────

def test_telegram_render_escapes(temp_db, uid):
    ev = _make_event(uid, summary="A & B <x>")
    out = TelegramAdapter().render(ev)
    assert "&amp;" in out and "&lt;x&gt;" in out   # fmt.esc applied
    assert "<b>" in out                             # fmt.b applied


def test_telegram_deliver_without_sender_fails_cleanly(temp_db, uid):
    item = SyncItem(id=1, user_id=uid, workspace_id=1, timeline_event_id=1,
                    adapter="telegram", target_id=None, payload="hi",
                    status=PENDING, attempts=0, last_error=None)
    res = TelegramAdapter().deliver(item)          # no sender
    assert res.ok is False and "not configured" in res.error


def test_telegram_deliver_with_sender(temp_db, uid):
    sender = RecordingSender()
    item = SyncItem(id=1, user_id=uid, workspace_id=1, timeline_event_id=1,
                    adapter="telegram", target_id=7, payload="hello",
                    status=PENDING, attempts=0, last_error=None)
    res = TelegramAdapter(sender).deliver(item)
    assert res.ok and res.ref == "1"
    assert sender.calls == [(uid, "hello", 7)]


# ── Engine: enqueue idempotency + drain ───────────────────────────────────

def test_enqueue_is_idempotent(temp_db, uid):
    ev = _make_event(uid)
    eng = SyncEngine(adapters=[TelegramAdapter(RecordingSender())])
    assert len(eng.enqueue(ev)) == 1
    assert eng.enqueue(ev) == []                    # already enqueued
    assert db.count_sync(uid) == 1


def test_drain_delivers_and_marks_sent(temp_db, uid):
    sender = RecordingSender()
    ev = _make_event(uid)
    eng = SyncEngine(adapters=[TelegramAdapter(sender)])
    eng.enqueue(ev)
    report = eng.drain(uid)
    assert report == {"sent": 1, "failed": 0, "retried": 0, "processed": 1}
    assert len(sender.calls) == 1
    assert db.count_sync(uid, status="sent") == 1
    # the timeline event is now marked synced (all adapters delivered)
    assert len(db.get_unsynced_timeline(uid)) == 0


def test_drain_retries_then_succeeds(temp_db, uid):
    ev = _make_event(uid)
    flaky = FlakyAdapter(fail_times=2)
    eng = SyncEngine(adapters=[flaky], max_attempts=5)
    eng.enqueue(ev)
    r1 = eng.drain(uid); assert r1["retried"] == 1
    assert db.count_sync(uid, status="pending") == 1
    row = db.get_sync_row(db.get_pending_sync(uid)[0][0])
    assert row[8] == 1 and row[9] == "temporary"    # attempts, last_error
    eng.drain(uid)                                   # 2nd retry
    r3 = eng.drain(uid); assert r3["sent"] == 1      # 3rd succeeds
    assert db.count_sync(uid, status="sent") == 1


def test_drain_gives_up_after_max_attempts(temp_db, uid):
    ev = _make_event(uid)
    eng = SyncEngine(adapters=[FlakyAdapter(fail_times=99)], max_attempts=3)
    eng.enqueue(ev)
    eng.drain(uid); eng.drain(uid)
    assert db.count_sync(uid, status="pending") == 1
    eng.drain(uid)                                   # 3rd attempt -> failed
    assert db.count_sync(uid, status="failed") == 1
    assert eng.drain(uid)["processed"] == 0          # failed rows not retried


def test_drain_tolerates_adapter_exception(temp_db, uid):
    ev = _make_event(uid)
    eng = SyncEngine(adapters=[ExplodingAdapter()], max_attempts=5)
    eng.enqueue(ev)
    report = eng.drain(uid)                           # must not raise
    assert report["retried"] == 1
    assert "network down" in db.get_pending_sync(uid)[0][9]


def test_sent_rows_not_redelivered(temp_db, uid):
    sender = RecordingSender()
    ev = _make_event(uid)
    eng = SyncEngine(adapters=[TelegramAdapter(sender)])
    eng.enqueue(ev)
    eng.drain(uid)
    eng.drain(uid)                                   # second pass
    assert len(sender.calls) == 1                    # not resent


# ── Full pipeline: Entity Engine -> Timeline -> Sync ──────────────────────

def test_full_pipeline_engine_timeline_sync(temp_db, uid):
    sender = RecordingSender()
    te = TimelineEngine()
    sync = SyncEngine(adapters=[TelegramAdapter(sender)])
    eng = EntityEngine(on_event=te.record)

    ws = eng.create_workspace(uid, "Robot")          # 1 timeline event
    eng.add_milestone(uid, ws.id, "M")               # +1

    report = sync.sync(uid)                           # enqueue backlog + drain
    assert report["sent"] == 2
    assert len(sender.calls) == 2
    assert db.count_sync(uid, status="sent") == 2
    assert len(db.get_unsynced_timeline(uid)) == 0    # all delivered


def test_multiple_adapters_enqueue_per_adapter(temp_db, uid):
    ev = _make_event(uid)
    eng = SyncEngine(adapters=[TelegramAdapter(RecordingSender()),
                              FlakyAdapter(fail_times=0)])
    ids = eng.enqueue(ev)
    assert len(ids) == 2                              # one row per adapter
    eng.drain(uid)
    assert db.count_sync(uid, status="sent") == 2


# ── flag-OFF neutrality ───────────────────────────────────────────────────

def test_nothing_enqueued_without_events(temp_db, uid):
    eng = SyncEngine(adapters=[TelegramAdapter(RecordingSender())])
    assert eng.enqueue_backlog(uid) == 0
    assert db.count_sync(uid) == 0
