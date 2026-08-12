"""
resolution_trace.py -- v15.2 M4.x -- in-memory entity-resolution trace.

The "find WHY the wrong entity was updated" instrument. Every entity
resolution decision (Worker tool adapters AND the legacy EntityManager) is
recorded as a small structured entry so the owner can read the recent trace
(`/diag`) without grepping bot.log or re-reading raw messages.

Deliberately:
  * IN-MEMORY (per-process ring buffer). A durable log is bot.log's job; this
    is the last-N diagnostic view. No new tables, no second data layer.
  * NEVER carries secrets or raw user text -- only the requested reference
    (name/#id the model passed), workspace id, resolution outcome, and the
    resolved entity's title/id. The `/diag` renderer can therefore never
    leak a BOT_TOKEN / API key (they are never recorded).
  * Shared as a module-level singleton (the same ownership pattern as
    `_WORKER_TYPED_REFS` in main.py) so both the Worker adapters and the
    legacy EntityManager record into the SAME trace and `/diag` reads it.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

__all__ = ["ResolutionTrace", "get_resolution_trace"]

_IST = ZoneInfo("Asia/Kolkata")
_MAX_PER_USER = 20


@dataclass(frozen=True, slots=True)
class ResolutionEntry:
    """One entity-resolution decision (non-secret, title/id only)."""
    ts: str                       # ISO-8601-ish local time
    user_id: int
    workspace_id: "int | None"
    action: str                   # create / update / get / topic / resolve
    requested: str                # the reference the caller passed (name/#id)
    kind: str                     # entity / character / weapon / artifact / ...
    resolution: str               # FOUND / NOT_FOUND / EXISTS / CONFLICT / NO_REF
    fallback: str                 # EXACT / REFERENT / NONE
    entity_title: "str | None" = None
    entity_id: "int | None" = None


class ResolutionTrace:
    """Per-user ring buffer of the last N resolution entries."""

    def __init__(self, max_per_user: int = _MAX_PER_USER):
        self._max = max_per_user
        self._by_user: dict[int, deque[ResolutionEntry]] = defaultdict(
            lambda: deque(maxlen=max_per_user))

    def record(self, *, user_id: int, workspace_id: "int | None",
               action: str, requested: str, kind: str,
               resolution: str, fallback: str,
               entity_title: "str | None" = None,
               entity_id: "int | None" = None,
               ts: "datetime | None" = None) -> None:
        entry = ResolutionEntry(
            ts=(ts or datetime.now(_IST)).strftime("%H:%M:%S"),
            user_id=user_id, workspace_id=workspace_id, action=action,
            requested=requested or "", kind=kind or "entity",
            resolution=resolution, fallback=fallback,
            entity_title=entity_title, entity_id=entity_id)
        self._by_user[user_id].append(entry)

    def recent(self, user_id: int, limit: int | None = None) -> list[ResolutionEntry]:
        """Newest first."""
        items = list(self._by_user.get(user_id, ()))
        if limit is not None:
            items = items[-limit:]
        return list(reversed(items))

    def clear(self, user_id: int) -> None:
        self._by_user.pop(user_id, None)


# Module-level singleton shared by the Worker adapters and EntityManager.
_TRACE = ResolutionTrace()


def get_resolution_trace() -> ResolutionTrace:
    return _TRACE
