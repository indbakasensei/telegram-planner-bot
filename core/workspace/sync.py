"""
sync.py -- the Synchronization Engine (v15.0-alpha.6, docs/v15/TWID.md).

Reliable OUTBOUND synchronization via the outbox pattern. Workspace writes
never call an external service inline; they land in the append-only
Timeline (alpha.5), the engine ENQUEUES one durable `sync_outbox` row per
registered adapter, and a DRAIN pass delivers those rows, marking each
sent (with the delivered ref) or, after retries, failed. Correctness
(SQLite) is decoupled from delivery (Telegram/etc.), so an outage never
blocks the workspace layer and the backlog drains on recovery.

This milestone is solely the engine + the adapter contract + the first
adapter (Telegram). It is NOT wired into the running bot's job_queue and
adds no user-facing controls -- with `WORKSPACE` OFF nothing constructs it,
so behaviour is byte-identical. Adapters deliver through an injected
callable, never by importing the live bot, so the offline test suite stays
Telegram-free.

    SyncEngine  ->  SyncOutboxRepository / TimelineRepository
                ->  Storage Facade  ->  database.py
    SyncEngine  ->  SyncAdapter (telegram, ...)  -- pluggable delivery
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from core.storage import Storage
from core.workspace.timeline import TimelineEvent, TimelineRepository

# Outbox statuses.
PENDING = "pending"
SENT = "sent"
FAILED = "failed"


@dataclass(frozen=True, slots=True)
class SyncItem:
    """One outbox row handed to an adapter for delivery."""
    id: int
    user_id: int
    workspace_id: int | None
    timeline_event_id: int | None
    adapter: str
    target_id: int | None
    payload: str
    status: str
    attempts: int
    last_error: str | None

    @classmethod
    def from_row(cls, row) -> "SyncItem | None":
        if row is None:
            return None
        # SYNC_COLS: id,user_id,workspace_id,timeline_event_id,adapter,
        #            target_id,payload,status,attempts,last_error,created_at,
        #            sent_at,ref
        return cls(
            id=row[0], user_id=row[1], workspace_id=row[2],
            timeline_event_id=row[3], adapter=row[4], target_id=row[5],
            payload=row[6], status=row[7], attempts=row[8], last_error=row[9],
        )


@dataclass(frozen=True, slots=True)
class SyncResult:
    """An adapter's delivery outcome."""
    ok: bool
    ref: str | None = None      # e.g. a Telegram message id
    error: str | None = None

    @classmethod
    def success(cls, ref=None) -> "SyncResult":
        return cls(ok=True, ref=ref)

    @classmethod
    def failure(cls, error) -> "SyncResult":
        return cls(ok=False, error=str(error))


class SyncAdapter(ABC):
    """The contract every synchronization target implements. The engine
    knows nothing about Telegram/email/etc. -- only this interface, so a
    new target is a new adapter and the engine never changes (alpha.7's AI
    Orchestrator consumes the same infrastructure without touching this)."""

    #: unique adapter key stored on each outbox row (e.g. "telegram").
    name: str = "base"

    @abstractmethod
    def render(self, event: TimelineEvent) -> str:
        """Turn a timeline event into this target's outbound payload."""

    @abstractmethod
    def deliver(self, item: SyncItem) -> SyncResult:
        """Deliver one outbox item. Must NOT raise for expected transport
        failures -- return SyncResult.failure(...) instead; the engine also
        guards against unexpected exceptions."""


class SyncOutboxRepository:
    """Typed access over the sync-outbox Storage domain."""

    def __init__(self, storage: Storage | None = None):
        self._s = storage or Storage()

    def exists(self, timeline_event_id, adapter) -> bool:
        return self._s.sync.exists(timeline_event_id, adapter)

    def enqueue(self, user_id, adapter, payload, timeline_event_id=None,
                workspace_id=None, target_id=None) -> int:
        return self._s.sync.enqueue(user_id, adapter, payload,
                                    timeline_event_id, workspace_id, target_id)

    def pending(self, user_id, limit=100) -> list[SyncItem]:
        return [SyncItem.from_row(r) for r in self._s.sync.pending(user_id, limit)]

    def get(self, outbox_id) -> SyncItem | None:
        return SyncItem.from_row(self._s.sync.get(outbox_id))

    def mark_sent(self, outbox_id, ref=None) -> None:
        self._s.sync.mark_sent(outbox_id, ref)

    def mark_retry(self, outbox_id, error) -> None:
        self._s.sync.mark_retry(outbox_id, error)

    def mark_failed(self, outbox_id, error) -> None:
        self._s.sync.mark_failed(outbox_id, error)

    def remaining_for_event(self, timeline_event_id) -> int:
        return self._s.sync.remaining_for_event(timeline_event_id)

    def count(self, user_id, status=None) -> int:
        return self._s.sync.count(user_id, status)


class SyncEngine:
    """Enqueues timeline events to registered adapters and drains the
    outbox reliably (idempotent enqueue, bounded retries, per-row error
    capture). Stateless apart from its adapters + repositories."""

    def __init__(self, adapters=None, outbox: SyncOutboxRepository | None = None,
                 timeline: TimelineRepository | None = None, max_attempts=5):
        self._adapters = {}
        for a in (adapters or []):
            self.register(a)
        self._outbox = outbox or SyncOutboxRepository()
        self._timeline = timeline or TimelineRepository()
        self._max_attempts = max_attempts

    def register(self, adapter: SyncAdapter) -> None:
        self._adapters[adapter.name] = adapter

    @property
    def adapters(self) -> tuple[str, ...]:
        return tuple(self._adapters)

    # ── enqueue ────────────────────────────────────────
    def enqueue(self, event: TimelineEvent) -> list[int]:
        """Create one pending outbox row per registered adapter for a
        timeline event. Idempotent: a row already existing for
        (event, adapter) is skipped, so re-enqueuing never double-posts."""
        ids = []
        for name, adapter in self._adapters.items():
            if self._outbox.exists(event.id, name):
                continue
            payload = adapter.render(event)
            ids.append(self._outbox.enqueue(
                user_id=event.user_id, adapter=name, payload=payload,
                timeline_event_id=event.id, workspace_id=event.workspace_id))
        return ids

    def enqueue_backlog(self, user_id, limit=100) -> int:
        """Enqueue every not-yet-synced timeline event (reconciliation /
        catch-up). Returns the number of outbox rows created."""
        created = 0
        for ev in self._timeline.unsynced(user_id, limit):
            created += len(self.enqueue(ev))
        return created

    # ── drain ──────────────────────────────────────────
    def drain(self, user_id, limit=100) -> dict:
        """Deliver pending outbox rows oldest-first. Each row: on success →
        'sent' (+ ref) and, once all of its event's rows are sent, the
        timeline event is stamped synced_at; on failure → retry (kept
        pending) until max_attempts, then 'failed'. Unexpected adapter
        exceptions are caught and treated as failures (offline-tolerant).
        Returns a {sent, failed, retried, processed} report."""
        report = {"sent": 0, "failed": 0, "retried": 0, "processed": 0}
        for item in self._outbox.pending(user_id, limit):
            report["processed"] += 1
            adapter = self._adapters.get(item.adapter)
            if adapter is None:
                # No adapter registered for this row this pass -- leave it.
                continue
            try:
                result = adapter.deliver(item)
            except Exception as e:  # transport blew up unexpectedly
                result = SyncResult.failure(repr(e))
            if result.ok:
                self._outbox.mark_sent(item.id, result.ref)
                report["sent"] += 1
                self._maybe_mark_event_synced(item.timeline_event_id)
            elif item.attempts + 1 >= self._max_attempts:
                self._outbox.mark_failed(item.id, result.error)
                report["failed"] += 1
            else:
                self._outbox.mark_retry(item.id, result.error)
                report["retried"] += 1
        return report

    def _maybe_mark_event_synced(self, timeline_event_id) -> None:
        if timeline_event_id is None:
            return
        if self._outbox.remaining_for_event(timeline_event_id) == 0:
            self._timeline.mark_synced(timeline_event_id)

    # ── convenience ────────────────────────────────────
    def sync(self, user_id, limit=100) -> dict:
        """Enqueue the backlog then drain -- one full outbound pass."""
        self.enqueue_backlog(user_id, limit)
        return self.drain(user_id, limit)
