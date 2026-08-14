"""
repository.py -- Workspace Repository (v15.0-alpha.1, docs/v15/WED.md §4).

The typed data-access boundary for the Workspace stack. It sits ON TOP of
the Storage Facade (never touches database.py or SQL directly -- the same
AST-enforced purity every other module under core/ obeys) and maps the raw
tuples the facade returns into the frozen models in models.py. It adds NO
business logic: no progress rollup, no template seeding, no flag checks --
those belong to service.py. This layer is only "tuples <-> models, one
call each".

    Service  ->  Repository  ->  Storage Facade  ->  database.py (SQL)
"""
from __future__ import annotations

from core.storage import Storage
from core.workspace.models import Attachment, Milestone, Note, Tag, Workspace


class WorkspaceRepository:
    """Model-shaped CRUD over the Workspace Foundation. Stateless; holds
    only a Storage facade (its own by default)."""

    def __init__(self, storage: Storage | None = None):
        self._s = storage or Storage()

    # ── Workspaces ─────────────────────────────────────
    def create_workspace(self, user_id, title, template="generic",
                         icon=None, metadata=None, sort_order=0) -> Workspace:
        ws_id = self._s.workspaces.create(
            user_id, title, template, icon, metadata, sort_order)
        return self.get_workspace(ws_id, user_id)

    def get_workspace(self, workspace_id, user_id) -> Workspace | None:
        return Workspace.from_row(self._s.workspaces.get(workspace_id, user_id))

    def list_workspaces(self, user_id, status="active") -> list[Workspace]:
        return [Workspace.from_row(r)
                for r in self._s.workspaces.list(user_id, status)]

    def find_by_title(self, user_id, title) -> Workspace | None:
        return Workspace.from_row(self._s.workspaces.get_by_title(user_id, title))

    def update_workspace(self, workspace_id, user_id, **fields) -> Workspace | None:
        self._s.workspaces.update(workspace_id, user_id, **fields)
        return self.get_workspace(workspace_id, user_id)

    def archive_workspace(self, workspace_id, user_id) -> Workspace | None:
        self._s.workspaces.archive(workspace_id, user_id)
        return self.get_workspace(workspace_id, user_id)

    # ── Milestones ─────────────────────────────────────
    def add_milestone(self, workspace_id, title, goal_id=None,
                      sort_order=0, fields=None,
                      entity_type: str | None = None) -> Milestone:
        """Add a milestone, optionally with structured entity fields
        (v15.1.0-alpha.9) and a per-entity kind (v15.2 M4)."""
        ms_id = self._s.milestones.add(workspace_id, title, goal_id,
                                       sort_order, fields, entity_type)
        return self.get_milestone(ms_id)

    def get_milestone(self, milestone_id) -> Milestone | None:
        return Milestone.from_row(self._s.milestones.get(milestone_id))

    def list_milestones(self, workspace_id, include_archived=False) -> list[Milestone]:
        return [Milestone.from_row(r)
                for r in self._s.milestones.list_for(workspace_id, include_archived)]

    def update_milestone(self, milestone_id, status=None, progress=None,
                        title=None) -> Milestone | None:
        self._s.milestones.update(milestone_id, status, progress, title)
        return self.get_milestone(milestone_id)

    def soft_delete_milestone(self, milestone_id) -> None:
        self._s.milestones.soft_delete(milestone_id)

    def milestone_counts(self, workspace_id) -> tuple[int, int]:
        """(total, done) -- passthrough of the DB aggregate."""
        return self._s.milestones.counts(workspace_id)

    # v15.1.0-alpha.9: structured entity field passthroughs.
    def set_milestone_fields(self, milestone_id, fields) -> None:
        self._s.milestones.set_fields(milestone_id, fields)

    def get_milestone_fields(self, milestone_id) -> dict:
        return self._s.milestones.get_fields(milestone_id)

    # v15.2 M4 canonical binding: adopt an entity kind on an existing row.
    def set_milestone_entity_type(self, milestone_id, entity_type) -> Milestone | None:
        self._s.milestones.update_entity_type(milestone_id, entity_type)
        return self.get_milestone(milestone_id)

    # ── Notes ──────────────────────────────────────────
    def add_note(self, workspace_id, content, kind="note",
                milestone_id=None, source="user", title=None) -> Note:
        note_id = self._s.notes.add(
            workspace_id, content, kind, milestone_id, source, title)
        return next((n for n in self.list_notes(workspace_id)
                     if n.id == note_id), None)

    def list_notes(self, workspace_id, kind=None) -> list[Note]:
        return [Note.from_row(r)
                for r in self._s.notes.list_for(workspace_id, kind)]

    # ── Knowledge + Media + Tags (v15.4 M6) ──────────────
    def get_note(self, note_id) -> Note | None:
        return Note.from_row(self._s.notes.get(note_id))

    def update_note(self, note_id, content=None, title=None,
                    kind=None) -> Note | None:
        self._s.notes.update(note_id, content, title, kind)
        return self.get_note(note_id)

    def delete_note(self, note_id) -> Note | None:
        self._s.notes.soft_delete(note_id)
        return None

    def search_notes(self, workspace_id, **filters) -> list[Note]:
        return [Note.from_row(r)
                for r in self._s.notes.search(workspace_id, **filters)]

    def link_note_entity(self, note_id, entity_type, entity_id) -> None:
        self._s.notes.link_entity(note_id, entity_type, entity_id)

    def unlink_note_entity(self, note_id, entity_type, entity_id) -> None:
        self._s.notes.unlink_entity(note_id, entity_type, entity_id)

    def note_entities(self, note_id) -> list[tuple[str, int]]:
        return self._s.notes.entities(note_id)

    def note_ids_for_entity(self, entity_type, entity_id) -> list[int]:
        return self._s.notes.ids_for_entity(entity_type, entity_id)

    def link_note_tag(self, note_id, tag_id) -> None:
        self._s.notes.link_tag(note_id, tag_id)

    def unlink_note_tag(self, note_id, tag_id) -> None:
        self._s.notes.unlink_tag(note_id, tag_id)

    def note_tags(self, note_id) -> list[Tag]:
        return [Tag.from_row(r) for r in self._s.notes.tags(note_id)]

    def add_media(self, workspace_id, **media) -> Attachment:
        att_id = self._s.media.add(workspace_id, **media)
        return self.get_media(att_id)

    def get_media(self, attachment_id) -> Attachment | None:
        return Attachment.from_row(self._s.media.get(attachment_id))

    def update_media(self, attachment_id, **fields) -> Attachment | None:
        self._s.media.update(attachment_id, **fields)
        return self.get_media(attachment_id)

    def delete_media(self, attachment_id) -> None:
        self._s.media.soft_delete(attachment_id)

    def search_media(self, workspace_id, **filters) -> list[Attachment]:
        return [Attachment.from_row(r)
                for r in self._s.media.search(workspace_id, **filters)]

    def list_media(self, workspace_id, note_id=None) -> list[Attachment]:
        return [Attachment.from_row(r)
                for r in self._s.media.list_for(workspace_id, note_id)]

    def link_media_entity(self, attachment_id, entity_type, entity_id) -> None:
        self._s.media.link_entity(attachment_id, entity_type, entity_id)

    def unlink_media_entity(self, attachment_id, entity_type, entity_id) -> None:
        self._s.media.unlink_entity(attachment_id, entity_type, entity_id)

    def media_entities(self, attachment_id) -> list[tuple[str, int]]:
        return self._s.media.entities(attachment_id)

    def media_ids_for_entity(self, entity_type, entity_id) -> list[int]:
        return self._s.media.ids_for_entity(entity_type, entity_id)

    def link_media_tag(self, attachment_id, tag_id) -> None:
        self._s.media.link_tag(attachment_id, tag_id)

    def unlink_media_tag(self, attachment_id, tag_id) -> None:
        self._s.media.unlink_tag(attachment_id, tag_id)

    def media_tags(self, attachment_id) -> list[Tag]:
        return [Tag.from_row(r) for r in self._s.media.tags(attachment_id)]

    def resolve_tag(self, user_id, workspace_id, name) -> int | None:
        return self._s.tags.resolve(user_id, workspace_id, name)

    def create_tag(self, user_id, workspace_id, name) -> tuple[int | None, bool]:
        return self._s.tags.create(user_id, workspace_id, name)

    def get_tag(self, tag_id) -> Tag | None:
        return Tag.from_row(self._s.tags.get(tag_id))

    def list_tags(self, user_id, workspace_id) -> list[Tag]:
        return [Tag.from_row(r)
                for r in self._s.tags.list_for(user_id, workspace_id)]

    def rename_tag(self, tag_id, name) -> None:
        self._s.tags.rename(tag_id, name)

    def delete_tag(self, tag_id) -> None:
        self._s.tags.delete(tag_id)

    def tag_links(self, tag_id) -> list[tuple[str, int]]:
        return self._s.tags.links(tag_id)

    def tags_for_target(self, entity_type, entity_id) -> list[Tag]:
        return [Tag.from_row(r)
                for r in self._s.tags.for_target(entity_type, entity_id)]

    def tags_for_entity(self, entity_type, entity_id) -> list[Tag]:
        return [Tag.from_row(r)
                for r in self._s.tags.for_entity(entity_type, entity_id)]

    # ── Migration passthroughs (logic lives in the Service) ────
    def ensure_default_workspace(self, user_id, title="Inbox",
                                template="generic") -> Workspace:
        ws_id = self._s.workspaces.ensure_default(user_id, title, template)
        return self.get_workspace(ws_id, user_id)

    def migrate_projects(self, user_id) -> int:
        return self._s.workspaces.migrate_projects(user_id)

    # ── Project<->Workspace bridge (v15.0-alpha.3) ─────
    def goal_id_for_workspace(self, user_id, workspace_id):
        """The goal backing a project workspace, or None."""
        return self._s.workspaces.goal_id_for(workspace_id, user_id)

    def workspace_for_goal(self, user_id, goal_id) -> Workspace | None:
        ws_id = self._s.workspaces.workspace_id_for_goal(goal_id, user_id)
        return self.get_workspace(ws_id, user_id) if ws_id else None

    def link_goal_to_workspace(self, user_id, goal_id, workspace_id) -> None:
        self._s.workspaces.link_goal(user_id, goal_id, workspace_id)

    def verify_project_migration(self, user_id) -> dict:
        return self._s.workspaces.verify_migration(user_id)
