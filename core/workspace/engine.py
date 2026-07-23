"""
engine.py -- the Workspace Entity Engine (v15.0-alpha.2).

The reusable core every future template depends on. It sits above the
Repository and is the single choke-point through which entity mutations
flow, adding the three things a raw Repository does not:

  1. Ownership + input VALIDATION -- every operation is scoped to a
     user_id and refuses (EntityNotFound / EntityValidationError) rather
     than silently touching another user's data or writing junk.
  2. LIFECYCLE enforcement -- status changes go through the declarative
     state machines in lifecycle.py (InvalidTransition on an illegal move;
     a no-op when already in the target state).
  3. An EVENT SEAM -- every mutation calls an `on_event` hook. The default
     is a no-op; the Knowledge Timeline (KTD, a later phase) plugs in here
     so "if a mutation doesn't emit an event, it's a bug" becomes true
     without the engine changing.

It is deliberately template-AGNOSTIC: it stores/reads a workspace's
`template` key and asks the Template registry for defaults and the
progress model, so adding a template never means editing this file
(Open/Closed -- same stance as ADR-012's ActionRegistry).

NO user-facing behaviour lives here: no commands, no Telegram, no UI, no
AI. Those are later phases; this milestone ships only the engine + tests.
"""
from __future__ import annotations

from core.workspace import lifecycle, templates
from core.workspace.errors import (
    EntityNotFound,
    EntityValidationError,
)
from core.workspace.events import (
    SRC_SYSTEM,
    SRC_USER,
    EventHook,
    build_event,
    noop_event,
)
from core.workspace.models import (
    MS_ARCHIVED,
    MS_DONE,
    STATUS_ARCHIVED,
    STATUS_DONE,
    Milestone,
    Note,
    Workspace,
)
from core.workspace.repository import WorkspaceRepository
from core.workspace.templates.registry import (
    PROGRESS_CHAPTERS,
    PROGRESS_CHECKLIST,
    PROGRESS_MANUAL,
    PROGRESS_MILESTONES,
)

# Event types the engine emits through the on_event seam. A subset of the
# KTD catalogue -- named here so the Timeline phase can match on constants,
# not magic strings. Emitting is all this milestone does with them.
EV_WORKSPACE_CREATED = "workspace.created"
EV_WORKSPACE_UPDATED = "workspace.updated"
EV_WORKSPACE_STATUS = "workspace.status_changed"
EV_MILESTONE_ADDED = "milestone.added"
EV_MILESTONE_STATUS = "milestone.status_changed"
EV_MILESTONE_ARCHIVED = "milestone.archived"
EV_MILESTONE_DELETED = "milestone.deleted"
EV_NOTE_ADDED = "note.added"

class EntityEngine:
    """Validated, lifecycle-aware operations over Workspace entities.
    Stateless apart from its Repository and event hook."""

    def __init__(self, repo: WorkspaceRepository | None = None,
                 on_event: EventHook | None = None):
        self._repo = repo or WorkspaceRepository()
        self._on_event = on_event or noop_event

    def _emit(self, event_type, entity_type, entity, user_id,
              source=SRC_USER) -> None:
        """Build a self-contained EntityEvent (alpha.5) and hand it to the
        subscriber. user_id is threaded from engine scope because the
        Milestone/Note models don't carry it."""
        self._on_event(build_event(event_type, entity_type, entity,
                                   user_id, source))

    # ── Workspaces ─────────────────────────────────────
    def create_workspace(self, user_id, title, template="generic",
                        seed_milestones=True, metadata=None) -> Workspace:
        """Create a workspace, applying its template (icon + seeded
        default milestones). Validates a non-empty title; unknown template
        keys fall back to 'generic' (templates.get is total). Emits
        workspace.created (and milestone.added per seeded milestone)."""
        title = (title or "").strip()
        if not title:
            raise EntityValidationError("workspace title must not be empty")
        tpl = templates.get(template)
        ws = self._repo.create_workspace(
            user_id, title=title, template=tpl.key, icon=tpl.icon,
            metadata=metadata)
        self._emit(EV_WORKSPACE_CREATED, "workspace", ws, user_id)
        if seed_milestones and tpl.default_milestones:
            for i, ms_title in enumerate(tpl.default_milestones):
                ms = self._repo.add_milestone(ws.id, ms_title, sort_order=i)
                # Seeded from the template, not typed by the user.
                self._emit(EV_MILESTONE_ADDED, "milestone", ms, user_id,
                           source=SRC_SYSTEM)
        return ws

    def get_workspace(self, user_id, workspace_id) -> Workspace:
        """Return the workspace or raise EntityNotFound (does not exist, or
        not owned by user_id)."""
        ws = self._repo.get_workspace(workspace_id, user_id)
        if ws is None:
            raise EntityNotFound(f"workspace {workspace_id}")
        return ws

    def get_workspace_or_none(self, user_id, workspace_id) -> Workspace | None:
        return self._repo.get_workspace(workspace_id, user_id)

    def list_workspaces(self, user_id, status="active") -> list[Workspace]:
        return self._repo.list_workspaces(user_id, status)

    def rename_workspace(self, user_id, workspace_id, title) -> Workspace:
        title = (title or "").strip()
        if not title:
            raise EntityValidationError("workspace title must not be empty")
        self.get_workspace(user_id, workspace_id)  # ownership check
        ws = self._repo.update_workspace(workspace_id, user_id, title=title)
        self._emit(EV_WORKSPACE_UPDATED, "workspace", ws, user_id)
        return ws

    def set_metadata(self, user_id, workspace_id, metadata: dict) -> Workspace:
        self.get_workspace(user_id, workspace_id)
        ws = self._repo.update_workspace(workspace_id, user_id, metadata=metadata)
        self._emit(EV_WORKSPACE_UPDATED, "workspace", ws, user_id)
        return ws

    def transition_workspace(self, user_id, workspace_id, to_status) -> Workspace:
        """Move a workspace to `to_status`, validated against
        WORKSPACE_LIFECYCLE. No-op (no write, no event) if already there."""
        ws = self.get_workspace(user_id, workspace_id)
        lc = lifecycle.for_entity("workspace")
        if lc.is_noop(ws.status, to_status):
            return ws
        lc.validate(ws.status, to_status)
        updated = self._repo.update_workspace(workspace_id, user_id,
                                              status=to_status)
        self._emit(EV_WORKSPACE_STATUS, "workspace", updated, user_id)
        return updated

    def archive_workspace(self, user_id, workspace_id) -> Workspace:
        return self.transition_workspace(user_id, workspace_id, STATUS_ARCHIVED)

    def complete_workspace(self, user_id, workspace_id) -> Workspace:
        return self.transition_workspace(user_id, workspace_id, STATUS_DONE)

    # ── Milestones (scoped through their parent workspace) ──
    def add_milestone(self, user_id, workspace_id, title) -> Milestone:
        title = (title or "").strip()
        if not title:
            raise EntityValidationError("milestone title must not be empty")
        self.get_workspace(user_id, workspace_id)  # ownership check
        existing = self._repo.list_milestones(workspace_id)
        ms = self._repo.add_milestone(workspace_id, title,
                                      sort_order=len(existing))
        self._emit(EV_MILESTONE_ADDED, "milestone", ms, user_id)
        return ms

    def list_milestones(self, user_id, workspace_id,
                       include_archived=False) -> list[Milestone]:
        self.get_workspace(user_id, workspace_id)  # ownership check
        return self._repo.list_milestones(workspace_id, include_archived)

    def _owned_milestone(self, user_id, milestone_id) -> Milestone:
        ms = self._repo.get_milestone(milestone_id)
        if ms is None:
            raise EntityNotFound(f"milestone {milestone_id}")
        # Ownership is inherited from the parent workspace.
        if self._repo.get_workspace(ms.workspace_id, user_id) is None:
            raise EntityNotFound(f"milestone {milestone_id}")
        return ms

    def transition_milestone(self, user_id, milestone_id, to_status) -> Milestone:
        """Move a milestone to `to_status`, validated against
        MILESTONE_LIFECYCLE. Setting 'done' also drives progress to 100
        (and the DB stamps completed_at). No-op if already there."""
        ms = self._owned_milestone(user_id, milestone_id)
        lc = lifecycle.for_entity("milestone")
        if lc.is_noop(ms.status, to_status):
            return ms
        lc.validate(ms.status, to_status)
        progress = 100 if to_status == MS_DONE else None
        updated = self._repo.update_milestone(milestone_id, status=to_status,
                                             progress=progress)
        self._emit(EV_MILESTONE_STATUS, "milestone", updated, user_id)
        return updated

    def complete_milestone(self, user_id, milestone_id) -> Milestone:
        return self.transition_milestone(user_id, milestone_id, MS_DONE)

    def archive_milestone(self, user_id, milestone_id) -> Milestone:
        """Archive a milestone (lifecycle-validated transition to
        'archived'; stamps archived_at; drops out of default listings and
        the progress denominator). No-op if already archived. Emits
        milestone.archived. v15.0-alpha.4."""
        ms = self._owned_milestone(user_id, milestone_id)
        lc = lifecycle.for_entity("milestone")
        if lc.is_noop(ms.status, MS_ARCHIVED):
            return ms
        lc.validate(ms.status, MS_ARCHIVED)
        updated = self._repo.update_milestone(milestone_id, status=MS_ARCHIVED)
        self._emit(EV_MILESTONE_ARCHIVED, "milestone", updated, user_id)
        return updated

    def delete_milestone(self, user_id, milestone_id) -> Milestone:
        """Soft-delete a milestone: it is stamped deleted_at and reads as
        gone, but the row is retained (never DROPped). Ownership-checked;
        raises EntityNotFound if it doesn't exist or was already deleted
        (so a double delete is a clear error, not a silent no-op). Emits
        milestone.deleted with the pre-delete snapshot. v15.0-alpha.4."""
        ms = self._owned_milestone(user_id, milestone_id)
        self._repo.soft_delete_milestone(milestone_id)
        self._emit(EV_MILESTONE_DELETED, "milestone", ms, user_id)
        return ms

    # ── Notes ──────────────────────────────────────────
    def add_note(self, user_id, workspace_id, content, kind="note",
                source="user") -> Note:
        content = (content or "").strip()
        if not content:
            raise EntityValidationError("note content must not be empty")
        self.get_workspace(user_id, workspace_id)  # ownership check
        note = self._repo.add_note(workspace_id, content, kind=kind, source=source)
        self._emit(EV_NOTE_ADDED, "note", note, user_id, source=source)
        return note

    def list_notes(self, user_id, workspace_id, kind=None) -> list[Note]:
        self.get_workspace(user_id, workspace_id)  # ownership check
        return self._repo.list_notes(workspace_id, kind)

    # ── Progress rollup (template-driven; WED §5) ──────
    def workspace_progress(self, user_id, workspace_id) -> int:
        """Derive a workspace's 0..100 progress from its template's
        progress_model. Never hand-entered. Non-raising: returns 0 for an
        unknown/empty workspace (progress is a read, not a mutation)."""
        ws = self._repo.get_workspace(workspace_id, user_id)
        if ws is None:
            return 0
        model = templates.get(ws.template).progress_model
        if model in (PROGRESS_MILESTONES, PROGRESS_CHECKLIST):
            total, done = self._repo.milestone_counts(workspace_id)
            return int(round(100 * done / total)) if total else 0
        if model == PROGRESS_CHAPTERS:
            total = _as_int(ws.metadata.get("total_chapters"))
            current = _as_int(ws.metadata.get("current_chapter"))
            return int(round(100 * current / total)) if total else 0
        if model == PROGRESS_MANUAL:
            return _clamp(_as_int(ws.metadata.get("progress")))
        return 0


def _as_int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _clamp(value, lo=0, hi=100) -> int:
    return max(lo, min(hi, value))
