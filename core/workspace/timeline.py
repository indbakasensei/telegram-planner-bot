"""
timeline.py -- the Knowledge Timeline (v15.0-alpha.5, docs/v15/KTD.md).

Append-only, persistent event infrastructure. The `TimelineEngine` is a
SUBSCRIBER to the Entity Engine's event hook (alpha.2/alpha.5): attach its
`.record` as `EntityEngine(on_event=...)` and every mutation is persisted
as one immutable `timeline_events` row. This milestone is *purely
persistence* -- no Telegram, no AI, and no aggregate/journal summaries. The
per-event `summary` is a short factual label (the schema requires it
NOT NULL); the AI-written roll-up reports KTD describes are explicitly out
of scope here.

    EntityEngine --emits EntityEvent--> TimelineEngine.record --> timeline_events

Later subscribers layer on the same seam without touching the engine:
Telegram Sync (alpha.6) drains unsynced rows; the AI Orchestrator
(alpha.7) reads history. The layering mirrors the rest of the stack:

    TimelineEngine  ->  TimelineRepository  ->  Storage Facade  ->  database.py
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from core.storage import Storage
from core.workspace.events import EntityEvent


@dataclass(frozen=True, slots=True)
class TimelineEvent:
    id: int
    user_id: int
    workspace_id: int | None
    entity_type: str | None
    entity_id: int | None
    event_type: str
    summary: str
    payload: dict
    source: str
    created_at: str | None
    synced_at: str | None

    @classmethod
    def from_row(cls, row) -> "TimelineEvent | None":
        if row is None:
            return None
        raw_payload = row[7]
        try:
            payload = json.loads(raw_payload) if raw_payload else {}
            if not isinstance(payload, dict):
                payload = {}
        except (ValueError, TypeError):
            payload = {}
        return cls(
            id=row[0], user_id=row[1], workspace_id=row[2], entity_type=row[3],
            entity_id=row[4], event_type=row[5], summary=row[6], payload=payload,
            source=row[8], created_at=row[9], synced_at=row[10],
        )


class TimelineRepository:
    """Typed access over the Timeline Storage domain (tuples -> models)."""

    def __init__(self, storage: Storage | None = None):
        self._s = storage or Storage()

    def add(self, user_id, event_type, summary, entity_type=None,
            entity_id=None, workspace_id=None, payload=None, source="user") -> int:
        return self._s.timeline.add(
            user_id, event_type, summary, entity_type, entity_id,
            workspace_id, payload, source)

    def for_user(self, user_id, workspace_id=None, limit=50) -> list[TimelineEvent]:
        return [TimelineEvent.from_row(r)
                for r in self._s.timeline.list_for_user(user_id, workspace_id, limit)]

    def for_entity(self, entity_type, entity_id, limit=50) -> list[TimelineEvent]:
        return [TimelineEvent.from_row(r)
                for r in self._s.timeline.list_for_entity(entity_type, entity_id, limit)]

    def unsynced(self, user_id, limit=100) -> list[TimelineEvent]:
        return [TimelineEvent.from_row(r)
                for r in self._s.timeline.unsynced(user_id, limit)]

    def count(self, user_id, workspace_id=None) -> int:
        return self._s.timeline.count(user_id, workspace_id)

    def mark_synced(self, event_id, synced_at=None) -> None:
        self._s.timeline.mark_synced(event_id, synced_at)


# Deterministic per-event summary templates (NOT the AI roll-up reports,
# which are out of scope). Keyed by event_type; {title} is the entity's
# title, {status} its status where relevant.
_SUMMARY_TEMPLATES = {
    "workspace.created": "Created workspace: {title}",
    "workspace.updated": "Updated workspace: {title}",
    "workspace.status_changed": "Workspace '{title}' → {status}",
    "milestone.added": "Added milestone: {title}",
    "milestone.status_changed": "Milestone '{title}' → {status}",
    "milestone.archived": "Archived milestone: {title}",
    "milestone.deleted": "Deleted milestone: {title}",
    "note.added": "Note added",
    "note.updated": "Note updated",
    "note.deleted": "Note deleted",
    "file.uploaded": "File uploaded",
    "media.deleted": "Media record deleted",
    "tag.created": "Created tag: {title}",
    "tag.deleted": "Deleted tag: {title}",
}


class TimelineEngine:
    """Subscriber that records Entity Engine events into the append-only
    timeline. Stateless apart from its repository."""

    def __init__(self, repo: TimelineRepository | None = None):
        self._repo = repo or TimelineRepository()

    def record(self, event: EntityEvent) -> int:
        """The event hook: persist one EntityEvent as a timeline row and
        return its id. Pass this as `EntityEngine(on_event=timeline.record)`."""
        summary = self._summarize(event)
        payload = self._payload(event)
        return self._repo.add(
            user_id=event.user_id, event_type=event.event_type, summary=summary,
            entity_type=event.entity_type, entity_id=event.entity_id,
            workspace_id=event.workspace_id, payload=payload, source=event.source)

    # ── reads ──────────────────────────────────────────
    def timeline(self, user_id, workspace_id=None, limit=50) -> list[TimelineEvent]:
        return self._repo.for_user(user_id, workspace_id, limit)

    def entity_history(self, entity_type, entity_id, limit=50) -> list[TimelineEvent]:
        return self._repo.for_entity(entity_type, entity_id, limit)

    def count(self, user_id, workspace_id=None) -> int:
        return self._repo.count(user_id, workspace_id)

    # ── internal ───────────────────────────────────────
    def _summarize(self, event: EntityEvent) -> str:
        # Tags carry `name` rather than `title`; both map to {title}.
        title = (getattr(event.entity, "title", None)
                 or getattr(event.entity, "name", None) or "")
        status = getattr(event.entity, "status", None) or ""
        template = _SUMMARY_TEMPLATES.get(event.event_type)
        if template:
            return template.format(title=title, status=status)
        return event.event_type  # factual fallback, never empty

    def _payload(self, event: EntityEvent) -> dict:
        """A small structured snapshot of the affected entity. Keeps only
        cheap scalar fields -- the timeline is a log, not a mirror."""
        entity = event.entity
        snap = {}
        for field in ("title", "status", "template", "progress", "kind"):
            val = getattr(entity, field, None)
            if val is not None:
                snap[field] = val
        return snap
