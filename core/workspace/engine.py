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
    Attachment,
    Milestone,
    Note,
    Tag,
    Workspace,
)
from core.workspace.repository import WorkspaceRepository
from core.workspace.templates.registry import (
    PROGRESS_CHAPTERS,
    PROGRESS_CHECKLIST,
    PROGRESS_MANUAL,
    PROGRESS_MILESTONES,
    normalize_entity_fields,     # v15.1.0-alpha.9
    validate_entity_fields,      # v15.1.0-alpha.9
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
# v15.4 M6 Knowledge + Media + Tags events.
EV_NOTE_UPDATED = "note.updated"
EV_NOTE_DELETED = "note.deleted"
EV_FILE_UPLOADED = "file.uploaded"
EV_MEDIA_DELETED = "media.deleted"
EV_TAG_CREATED = "tag.created"
EV_TAG_DELETED = "tag.deleted"

# The only workspace entity kind today; a future milestone extends this set.
_ENTITY_KINDS = ("milestone",)

# Stable discriminator used in junction tables (note_entities,
# attachment_entities, entity_tags) to identify workspace entity rows.
# This is the DB-level entity kind, NOT the semantic entity_type like
# "character" or "weapon". Using a stable discriminator means links
# survive a semantic kind re-adopt (adopt_entity_type).
ENTITY_TYPE = "milestone"

# file_type values the media layer accepts (spec §3 -- Telegram is the blob
# store; the DB row is the metadata index).
_MEDIA_TYPES = ("photo", "video", "document", "audio", "voice")

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
    def add_milestone(self, user_id, workspace_id, title,
                      entity_type: str | None = None) -> Milestone:
        title = (title or "").strip()
        if not title:
            raise EntityValidationError("milestone title must not be empty")
        self.get_workspace(user_id, workspace_id)  # ownership check
        existing = self._repo.list_milestones(workspace_id)
        ms = self._repo.add_milestone(workspace_id, title,
                                      sort_order=len(existing),
                                      entity_type=entity_type)
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

    def get_milestone(self, user_id, milestone_id) -> Milestone:
        """Public single-milestone fetch (ownership-checked). v15.2 M4:
        the Worker renderer uses this to re-fetch a full entity for card
        rendering from a ToolResult's entity_id."""
        return self._owned_milestone(user_id, milestone_id)

    def adopt_entity_type(self, user_id, milestone_id, entity_type) -> Milestone:
        """Adopt an entity kind on an existing milestone (v15.2 M4 canonical
        binding). Used by create when a same-name row of a different kind
        already exists: the existing row is reused (one entity, one topic)
        and its kind upgraded, instead of inserting a second duplicate."""
        ms = self._owned_milestone(user_id, milestone_id)
        entity_type = (entity_type or "entity").strip().lower() or "entity"
        updated = self._repo.set_milestone_entity_type(milestone_id, entity_type)
        self._emit(EV_MILESTONE_ADDED, "milestone", updated, user_id)
        return updated

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
        milestone.deleted with the pre-delete snapshot. v15.0-alpha.4.
        Also cascades to remove note/media entity links (no ghost refs).

        The junction tables store the stable discriminator "milestone" (the
        ENTITY_TYPE constant), not the semantic entity_type like "character"
        or "weapon". This ensures links survive a semantic kind re-adopt."""
        ms = self._owned_milestone(user_id, milestone_id)
        entity_type = ENTITY_TYPE  # stable discriminator used in junctions
        entity_id = ms.id

        # Cascade: remove all note↔entity links for this entity
        for note_id in self._repo.note_ids_for_entity(entity_type, entity_id):
            self._repo.unlink_note_entity(note_id, entity_type, entity_id)

        # Cascade: remove all media↔entity links for this entity
        for att_id in self._repo.media_ids_for_entity(entity_type, entity_id):
            self._repo.unlink_media_entity(att_id, entity_type, entity_id)

        self._repo.soft_delete_milestone(milestone_id)
        self._emit(EV_MILESTONE_DELETED, "milestone", ms, user_id)
        return ms

    # ── Notes ──────────────────────────────────────────
    def add_note(self, user_id, workspace_id, content, kind="note",
                source="user", title=None) -> Note:
        content = (content or "").strip()
        if not content:
            raise EntityValidationError("note content must not be empty")
        self.get_workspace(user_id, workspace_id)  # ownership check
        note = self._repo.add_note(workspace_id, content, kind=kind,
                                   source=source, title=title)
        self._emit(EV_NOTE_ADDED, "note", note, user_id, source=source)
        return note

    def list_notes(self, user_id, workspace_id, kind=None) -> list[Note]:
        self.get_workspace(user_id, workspace_id)  # ownership check
        return self._repo.list_notes(workspace_id, kind)

    # ── Knowledge + Media + Tags (v15.4 M6) ────────────
    # Notes and media are workspace-scoped (NO user_id column -- ownership
    # is inherited from the parent workspace, exactly like milestones). Every
    # read/write re-resolves the workspace so cross-user access is refused.

    def _owned_note(self, user_id, note_id) -> Note:
        note = self._repo.get_note(note_id)
        if note is None:
            raise EntityNotFound(f"note {note_id}")
        if self._repo.get_workspace(note.workspace_id, user_id) is None:
            raise EntityNotFound(f"note {note_id}")
        return note

    def _owned_media(self, user_id, attachment_id) -> Attachment:
        att = self._repo.get_media(attachment_id)
        if att is None:
            raise EntityNotFound(f"media {attachment_id}")
        if self._repo.get_workspace(att.workspace_id, user_id) is None:
            raise EntityNotFound(f"media {attachment_id}")
        return att

    def _owned_tag(self, user_id, tag_id) -> Tag:
        tag = self._repo.get_tag(tag_id)
        if tag is None:
            raise EntityNotFound(f"tag {tag_id}")
        if tag.user_id != user_id:
            raise EntityNotFound(f"tag {tag_id}")
        return tag

    def _owned_entity(self, user_id, entity_type, entity_id):
        """A workspace entity (only 'milestone' today) owned by user_id.
        Generic by construction: a future entity kind adds its kind to
        _ENTITY_KINDS and a resolver here."""
        if entity_type not in _ENTITY_KINDS:
            raise EntityValidationError(
                f"unsupported entity kind: {entity_type!r}")
        return self._owned_milestone(user_id, entity_id)

    def _same_workspace(self, owner_id, owner_ws, target_id, target_ws):
        if target_ws != owner_ws:
            raise EntityValidationError(
                f"entity/tag {target_id} is not in the same workspace")

    def get_note(self, user_id, note_id) -> Note:
        return self._owned_note(user_id, note_id)

    def update_note(self, user_id, note_id, content=None, title=None,
                    kind=None) -> Note:
        """Edit a note's content/title/kind. A None field is left unchanged;
        at least one must be provided (else a no-op that returns the note).
        Ownership-checked; raises EntityNotFound when missing/deleted."""
        if content is not None:
            content = content.strip()
            if not content:
                raise EntityValidationError("note content must not be empty")
        note = self._owned_note(user_id, note_id)
        updated = self._repo.update_note(note_id, content, title, kind)
        self._emit(EV_NOTE_UPDATED, "note", updated, user_id)
        return updated

    def delete_note(self, user_id, note_id) -> Note:
        """Soft-delete a note: stamped deleted_at, reads as gone, row kept.
        The DB record + links are removed from view; the Telegram topic and
        any projected message are NEVER touched (the delete ≠ topic rule)."""
        note = self._owned_note(user_id, note_id)
        self._repo.delete_note(note_id)
        self._emit(EV_NOTE_DELETED, "note", note, user_id)
        return note

    def search_notes(self, user_id, workspace_id, q=None, kind=None,
                     entity_type=None, entity_id=None, tag_id=None,
                     created_after=None, created_before=None,
                     limit=50) -> list[Note]:
        self.get_workspace(user_id, workspace_id)  # ownership check
        return self._repo.search_notes(
            workspace_id, q=q, kind=kind, entity_type=entity_type,
            entity_id=entity_id, tag_id=tag_id, created_after=created_after,
            created_before=created_before, limit=limit)

    def link_note_entity(self, user_id, note_id, entity_type, entity_id) -> Note:
        """Attach a note to a workspace entity (many-to-many). Refuses an
        unknown kind or an entity in another workspace -- a note can never
        reference an entity it doesn't share a workspace with."""
        note = self._owned_note(user_id, note_id)
        ent = self._owned_entity(user_id, entity_type, entity_id)
        self._same_workspace(note.id, note.workspace_id, ent.id, ent.workspace_id)
        self._repo.link_note_entity(note_id, entity_type, entity_id)
        return note

    def unlink_note_entity(self, user_id, note_id, entity_type, entity_id) -> None:
        self._owned_note(user_id, note_id)
        self._repo.unlink_note_entity(note_id, entity_type, entity_id)

    def note_entities(self, user_id, note_id) -> list[tuple[str, int]]:
        self._owned_note(user_id, note_id)
        return self._repo.note_entities(note_id)

    def note_ids_for_entity(self, user_id, workspace_id, entity_type,
                            entity_id) -> list[int]:
        self.get_workspace(user_id, workspace_id)
        ent = self._owned_entity(user_id, entity_type, entity_id)
        self._same_workspace(ent.id, ent.workspace_id, workspace_id, workspace_id)
        return self._repo.note_ids_for_entity(entity_type, entity_id)

    def link_note_tag(self, user_id, note_id, tag_id) -> Note:
        note = self._owned_note(user_id, note_id)
        tag = self._owned_tag(user_id, tag_id)
        self._same_workspace(note.id, note.workspace_id, tag.id, tag.workspace_id)
        self._repo.link_note_tag(note_id, tag_id)
        return note

    def unlink_note_tag(self, user_id, note_id, tag_id) -> None:
        self._owned_note(user_id, note_id)
        self._owned_tag(user_id, tag_id)
        self._repo.unlink_note_tag(note_id, tag_id)

    def note_tags(self, user_id, note_id) -> list[Tag]:
        self._owned_note(user_id, note_id)
        return self._repo.note_tags(note_id)

    def store_media(self, user_id, workspace_id, telegram_file_id=None,
                    file_type="photo", file_name=None, caption=None,
                    note_id=None, entity_type=None, entity_id=None,
                    extracted_text=None, message_id=None, chat_id=None,
                    topic_id=None) -> Attachment:
        """Record media metadata (Telegram file/message identity + optional
        note/entity binding). Telegram is canonical storage -- this writes
        the index row, never a binary. Ownership-checked; an optional note
        or entity must live in the same workspace."""
        file_type = (file_type or "").strip().lower()
        if file_type not in _MEDIA_TYPES:
            raise EntityValidationError(
                f"unsupported media type: {file_type!r} "
                f"(expected one of {', '.join(_MEDIA_TYPES)})")
        self.get_workspace(user_id, workspace_id)  # ownership check
        if note_id is not None:
            note = self._owned_note(user_id, note_id)
            self._same_workspace(note.id, note.workspace_id,
                                 workspace_id, workspace_id)
        if entity_type and entity_id is not None:
            ent = self._owned_entity(user_id, entity_type, entity_id)
            self._same_workspace(ent.id, ent.workspace_id,
                                 workspace_id, workspace_id)
        att = self._repo.add_media(
            workspace_id, note_id=note_id, telegram_file_id=telegram_file_id,
            file_type=file_type, file_name=file_name, caption=caption,
            message_id=message_id, chat_id=chat_id, topic_id=topic_id,
            entity_type=entity_type, entity_id=entity_id,
            extracted_text=extracted_text)
        if entity_type and entity_id is not None:
            self._repo.link_media_entity(att.id, entity_type, entity_id)
        self._emit(EV_FILE_UPLOADED, "attachment", att, user_id)
        return att

    def get_media(self, user_id, attachment_id) -> Attachment:
        return self._owned_media(user_id, attachment_id)

    def update_media(self, user_id, attachment_id, caption=None,
                     file_name=None, extracted_text=None) -> Attachment:
        att = self._owned_media(user_id, attachment_id)
        updated = self._repo.update_media(
            attachment_id, caption=caption, file_name=file_name,
            extracted_text=extracted_text)
        return updated or att

    def delete_media(self, user_id, attachment_id) -> Attachment:
        """Soft-delete a media record (metadata + links only). The Telegram
        message is NEVER deleted -- deleting the index never deletes the
        blob (spec §3, M5 delete≠topic rule)."""
        att = self._owned_media(user_id, attachment_id)
        self._repo.delete_media(attachment_id)
        self._emit(EV_MEDIA_DELETED, "attachment", att, user_id)
        return att

    def search_media(self, user_id, workspace_id, q=None, media_type=None,
                     entity_type=None, entity_id=None, tag_id=None,
                     created_after=None, created_before=None,
                     limit=50) -> list[Attachment]:
        self.get_workspace(user_id, workspace_id)  # ownership check
        return self._repo.search_media(
            workspace_id, q=q, media_type=media_type, entity_type=entity_type,
            entity_id=entity_id, tag_id=tag_id, created_after=created_after,
            created_before=created_before, limit=limit)

    def list_media(self, user_id, workspace_id, note_id=None) -> list[Attachment]:
        self.get_workspace(user_id, workspace_id)  # ownership check
        return self._repo.list_media(workspace_id, note_id)

    def link_media_entity(self, user_id, attachment_id, entity_type,
                          entity_id) -> Attachment:
        att = self._owned_media(user_id, attachment_id)
        ent = self._owned_entity(user_id, entity_type, entity_id)
        self._same_workspace(att.id, att.workspace_id, ent.id, ent.workspace_id)
        self._repo.link_media_entity(attachment_id, entity_type, entity_id)
        return att

    def unlink_media_entity(self, user_id, attachment_id, entity_type,
                            entity_id) -> None:
        self._owned_media(user_id, attachment_id)
        self._repo.unlink_media_entity(attachment_id, entity_type, entity_id)

    def media_entities(self, user_id, attachment_id) -> list[tuple[str, int]]:
        self._owned_media(user_id, attachment_id)
        return self._repo.media_entities(attachment_id)

    def link_media_tag(self, user_id, attachment_id, tag_id) -> Attachment:
        att = self._owned_media(user_id, attachment_id)
        tag = self._owned_tag(user_id, tag_id)
        self._same_workspace(att.id, att.workspace_id, tag.id, tag.workspace_id)
        self._repo.link_media_tag(attachment_id, tag_id)
        return att

    def unlink_media_tag(self, user_id, attachment_id, tag_id) -> None:
        self._owned_media(user_id, attachment_id)
        self._owned_tag(user_id, tag_id)
        self._repo.unlink_media_tag(attachment_id, tag_id)

    def media_tags(self, user_id, attachment_id) -> list[Tag]:
        self._owned_media(user_id, attachment_id)
        return self._repo.media_tags(attachment_id)

    def create_tag(self, user_id, workspace_id, name) -> Tag:
        """Resolve-or-create a workspace tag by name (case-insensitive).
        Idempotent: an existing same-name tag in the workspace is returned
        (tag = the category name; two rows can never carry the same name)."""
        name = (name or "").strip()
        if not name:
            raise EntityValidationError("tag name must not be empty")
        self.get_workspace(user_id, workspace_id)  # ownership check
        tag_id, created = self._repo.create_tag(user_id, workspace_id, name)
        tag = self._repo.get_tag(tag_id)
        if created:
            self._emit(EV_TAG_CREATED, "tag", tag, user_id)
        return tag

    def get_tag(self, user_id, tag_id) -> Tag:
        return self._owned_tag(user_id, tag_id)

    def rename_tag(self, user_id, tag_id, name) -> Tag:
        name = (name or "").strip()
        if not name:
            raise EntityValidationError("tag name must not be empty")
        tag = self._owned_tag(user_id, tag_id)
        self._repo.rename_tag(tag_id, name)
        return self._repo.get_tag(tag_id)

    def delete_tag(self, user_id, tag_id) -> Tag:
        """Delete a tag and every link to it (notes/media/entities keep their
        rows -- only the label goes away)."""
        tag = self._owned_tag(user_id, tag_id)
        self._repo.delete_tag(tag_id)
        self._emit(EV_TAG_DELETED, "tag", tag, user_id)
        return tag

    def list_tags(self, user_id, workspace_id) -> list[Tag]:
        self.get_workspace(user_id, workspace_id)  # ownership check
        return self._repo.list_tags(user_id, workspace_id)

    def tag_links(self, user_id, tag_id) -> list[tuple[str, int]]:
        self._owned_tag(user_id, tag_id)
        return self._repo.tag_links(tag_id)

    def tags_for_target(self, user_id, workspace_id, entity_type,
                        entity_id) -> list[Tag]:
        """Tags linked to one target within a workspace. `entity_type` is a
        workspace row kind (milestone) or 'note'/'attachment'. Ownership is
        enforced: the workspace must be the caller's and, for a milestone,
        the entity must exist and belong to it."""
        self.get_workspace(user_id, workspace_id)  # ownership check
        if entity_type in _ENTITY_KINDS:
            ent = self._owned_entity(user_id, entity_type, entity_id)
            self._same_workspace(ent.id, ent.workspace_id,
                                 workspace_id, workspace_id)
        elif entity_type == "note":
            note = self._owned_note(user_id, entity_id)
            self._same_workspace(note.id, note.workspace_id,
                                 workspace_id, workspace_id)
        elif entity_type == "attachment":
            att = self._owned_media(user_id, entity_id)
            self._same_workspace(att.id, att.workspace_id,
                                 workspace_id, workspace_id)
        else:
            raise EntityValidationError(
                f"unsupported target kind: {entity_type!r}")
        return self._repo.tags_for_target(entity_type, entity_id)

    def tags_for_entity(self, user_id, workspace_id, entity_type,
                        entity_id) -> list[Tag]:
        """Tags on the notes/media linked to a workspace entity (the indirect
        'what categories is my knowledge about X filed under' lookup)."""
        self.get_workspace(user_id, workspace_id)  # ownership check
        ent = self._owned_entity(user_id, entity_type, entity_id)
        self._same_workspace(ent.id, ent.workspace_id,
                             workspace_id, workspace_id)
        return self._repo.tags_for_entity(entity_type, entity_id)

    # ── Structured entity fields (v15.1.0-alpha.9) ─────
    def get_fields(self, user_id, milestone_id) -> dict:
        """Return a milestone's structured entity fields (or {} if none).
        Ownership-checked. Non-raising on missing fields."""
        ms = self._owned_milestone(user_id, milestone_id)
        return ms.fields

    def set_fields(self, user_id, milestone_id, fields) -> Milestone:
        """Validate structured entity fields against the milestone's template
        schema and store them. Unknown field keys are allowed (forward-
        compatible). Returns the updated milestone."""
        if not isinstance(fields, dict):
            raise EntityValidationError("fields must be a dict")
        ms = self._owned_milestone(user_id, milestone_id)
        tpl_key = self._repo.get_workspace(ms.workspace_id, user_id).template
        errors = validate_entity_fields(tpl_key, fields)
        if errors:
            raise EntityValidationError("; ".join(errors))
        clean = normalize_entity_fields(tpl_key, fields)
        self._repo.set_milestone_fields(milestone_id, clean)
        updated = self._repo.get_milestone(milestone_id)
        self._emit(EV_MILESTONE_STATUS, "milestone", updated, user_id)
        return updated

    def update_field(self, user_id, milestone_id, name, value) -> Milestone:
        """Update a single structured entity field by name. Validates the
        new value against the template's field schema; unknown field names
        are allowed (forward-compatible). Returns the updated milestone."""
        ms = self._owned_milestone(user_id, milestone_id)
        tpl_key = self._repo.get_workspace(ms.workspace_id, user_id).template
        single = {name: value}
        errors = validate_entity_fields(tpl_key, single)
        if errors:
            raise EntityValidationError("; ".join(errors))
        current = self._repo.get_milestone_fields(milestone_id)
        merged = {**current, name: value}
        clean = normalize_entity_fields(tpl_key, merged)
        self._repo.set_milestone_fields(milestone_id, clean)
        updated = self._repo.get_milestone(milestone_id)
        self._emit(EV_MILESTONE_STATUS, "milestone", updated, user_id)
        return updated

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
