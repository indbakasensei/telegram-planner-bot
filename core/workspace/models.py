"""
models.py -- typed domain objects for the Workspace Foundation
(v15.0-alpha.1, docs/v15/WED.md).

These dataclasses are the boundary between the raw tuples database.py
returns (via the Storage Facade) and the Service/UI layers above. The
Repository maps a positional DB row -> one of these, so the FROZEN column
orders in database.py (WORKSPACE_COLS / MILESTONE_COLS / NOTE_COLS) and
the `from_row` classmethods here must stay in lock-step.

Pure data + trivial helpers only -- no SQL, no I/O, no business logic
(that lives in service.py). Frozen so a model can't drift out of sync
with the row it was built from.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

# Workspace lifecycle statuses (WED §5).
STATUS_ACTIVE = "active"
STATUS_ARCHIVED = "archived"
STATUS_DONE = "done"

# Milestone lifecycle statuses.
MS_TODO = "todo"
MS_IN_PROGRESS = "in_progress"
MS_DONE = "done"
MS_BLOCKED = "blocked"

# The default workspace every user gets (MIGRATION.md §2). NULL
# workspace_id on a task/goal/memory is interpreted as "belongs to Inbox".
DEFAULT_WORKSPACE_TITLE = "Inbox"


def _parse_metadata(raw: Any) -> dict:
    """Metadata is stored as a JSON string; tolerate NULL, a dict already,
    or malformed JSON (never raise -- a bad blob becomes {})."""
    if raw is None or raw == "":
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, TypeError):
        return {}


@dataclass(frozen=True, slots=True)
class Workspace:
    id: int
    user_id: int
    template: str
    title: str
    status: str = STATUS_ACTIVE
    icon: str | None = None
    metadata: dict = field(default_factory=dict)
    ai_summary: str | None = None
    telegram_topic_id: int | None = None
    sort_order: int = 0
    created_at: str | None = None
    updated_at: str | None = None
    archived_at: str | None = None

    @classmethod
    def from_row(cls, row) -> "Workspace | None":
        """Build from a database.py WORKSPACE_COLS tuple, or None."""
        if row is None:
            return None
        return cls(
            id=row[0], user_id=row[1], template=row[2], title=row[3],
            status=row[4], icon=row[5], metadata=_parse_metadata(row[6]),
            ai_summary=row[7], telegram_topic_id=row[8], sort_order=row[9],
            created_at=row[10], updated_at=row[11], archived_at=row[12],
        )

    @property
    def is_active(self) -> bool:
        return self.status == STATUS_ACTIVE


@dataclass(frozen=True, slots=True)
class Milestone:
    id: int
    workspace_id: int
    goal_id: int | None
    title: str
    status: str = MS_TODO
    progress: int = 0
    sort_order: int = 0
    created_at: str | None = None
    completed_at: str | None = None

    @classmethod
    def from_row(cls, row) -> "Milestone | None":
        if row is None:
            return None
        return cls(
            id=row[0], workspace_id=row[1], goal_id=row[2], title=row[3],
            status=row[4], progress=row[5], sort_order=row[6],
            created_at=row[7], completed_at=row[8],
        )

    @property
    def is_done(self) -> bool:
        return self.status == MS_DONE


@dataclass(frozen=True, slots=True)
class Note:
    id: int
    workspace_id: int
    milestone_id: int | None
    kind: str
    content: str
    source: str
    created_at: str | None = None

    @classmethod
    def from_row(cls, row) -> "Note | None":
        if row is None:
            return None
        return cls(
            id=row[0], workspace_id=row[1], milestone_id=row[2],
            kind=row[3], content=row[4], source=row[5], created_at=row[6],
        )
