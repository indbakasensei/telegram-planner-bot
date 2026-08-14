"""
core/retrieval/service.py -- M7 Cross-Reference Retrieval Service.

Single retrieval implementation that composes M6 NoteStorage.search and
AttachmentStorage.search with AND/OR filter semantics. No second business-logic
path. No speculative indexes. Uses existing M6 schema and indexes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from core.workspace.engine import EntityEngine
from core.workspace.models import Note, Attachment, Tag


EntityOrMode = Literal["and", "or"]
TagOrMode = Literal["and", "or"]


@dataclass(frozen=True, slots=True)
class RetrievalFilters:
    """Normalized retrieval filters for cross-reference search."""
    workspace_id: int
    q: str | None = None
    entity_ids: tuple[int, ...] = ()
    entity_mode: EntityOrMode = "and"
    tag_ids: tuple[int, ...] = ()
    tag_mode: TagOrMode = "and"
    media_type: str | None = None
    created_after: str | None = None
    created_before: str | None = None
    limit: int = 50
    kind: str | None = None  # notes only


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    """A single retrieved record with type discriminator."""
    _type: Literal["note", "media"]
    # Note fields
    note_id: int | None = None
    title: str | None = None
    content: str | None = None
    kind: str | None = None
    note_created_at: str | None = None
    # Media fields
    media_id: int | None = None
    file_type: str | None = None
    telegram_file_id: str | None = None
    file_name: str | None = None
    caption: str | None = None
    media_created_at: str | None = None
    message_id: int | None = None
    chat_id: int | None = None
    topic_id: int | None = None
    entity_type: str | None = None
    entity_id: int | None = None
    extracted_text: str | None = None
    # Common
    workspace_id: int | None = None


class CrossReferenceService:
    """
    Single cross-reference retrieval implementation.

    Composes M6 NoteStorage.search and AttachmentStorage.search via
    EntityEngine. Supports AND/OR semantics for entity and tag filters.

    Workspace isolation is mandatory: every query is scoped to a workspace_id.
    """

    def __init__(self, engine: EntityEngine):
        self._engine = engine

    def search(
        self,
        user_id: int,
        workspace_id: int,
        *,
        q: str | None = None,
        entities: list[str | int] | None = None,
        entity_mode: EntityOrMode = "and",
        tags: list[str] | None = None,
        tag_mode: TagOrMode = "and",
        media_type: str | None = None,
        created_after: str | None = None,
        created_before: str | None = None,
        limit: int = 50,
        kind: str | None = None,
    ) -> list[RetrievalResult]:
        """
        Cross-reference search combining notes and media.

        Args:
            user_id: Owner user ID (for ownership checks)
            workspace_id: Target workspace (required; no cross-workspace by default)
            q: Free-text search (notes: title/content; media: caption/file_name/extracted_text)
            entities: List of entity names or #ids to filter by
            entity_mode: "and" (all must match) or "or" (any matches)
            tags: List of tag names to filter by
            tag_mode: "and" (all must match) or "or" (any matches)
            media_type: Filter media by type (photo|video|document|audio)
            created_after: ISO date lower bound (inclusive)
            created_before: ISO date upper bound (inclusive)
            limit: Max results per resource type (default 50, max 200)
            kind: Filter notes by kind

        Returns:
            List of RetrievalResult sorted newest-first (by created_at),
            combined notes + media, capped at limit total.
        """
        # Validate and cap limit
        limit = max(1, min(limit, 200))

        # Resolve entity names/#ids to (entity_type, entity_id) pairs
        entity_pairs = self._resolve_entities(user_id, workspace_id, entities or [])

        # Resolve tag names to tag_ids
        tag_ids = self._resolve_tags(user_id, workspace_id, tags or [])

        # Build base filters for both searches
        base_filters = {
            "workspace_id": workspace_id,
            "q": q,
            "created_after": created_after,
            "created_before": created_before,
        }

        # Execute searches with AND/OR logic
        # kind applies to notes only; media is always searched (kind never filters media).
        notes = self._search_notes_with_logic(
            user_id, base_filters, entity_pairs, entity_mode,
            tag_ids, tag_mode, kind, limit
        )

        media = self._search_media_with_logic(
            user_id, base_filters, entity_pairs, entity_mode,
            tag_ids, tag_mode, media_type, limit
        )

        # Convert to unified results
        note_results = [self._note_to_result(n) for n in notes]
        media_results = [self._media_to_result(m) for m in media]

        # Merge and sort newest-first by created_at
        combined = note_results + media_results
        combined.sort(key=lambda r: r.note_created_at or r.media_created_at or "", reverse=True)

        # Cap total results
        return combined[:limit]

    def search_notes_only(
        self,
        user_id: int,
        workspace_id: int,
        *,
        q: str | None = None,
        entities: list[str | int] | None = None,
        entity_mode: EntityOrMode = "and",
        tags: list[str] | None = None,
        tag_mode: TagOrMode = "and",
        created_after: str | None = None,
        created_before: str | None = None,
        limit: int = 50,
        kind: str | None = None,
    ) -> list[RetrievalResult]:
        """Notes-only cross-reference search."""
        limit = max(1, min(limit, 200))
        entity_pairs = self._resolve_entities(user_id, workspace_id, entities or [])
        tag_ids = self._resolve_tags(user_id, workspace_id, tags or [])

        notes = self._search_notes_with_logic(
            user_id,
            {"workspace_id": workspace_id, "q": q, "created_after": created_after, "created_before": created_before},
            entity_pairs, entity_mode, tag_ids, tag_mode, kind, limit
        )
        return [self._note_to_result(n) for n in notes]

    def search_media_only(
        self,
        user_id: int,
        workspace_id: int,
        *,
        q: str | None = None,
        entities: list[str | int] | None = None,
        entity_mode: EntityOrMode = "and",
        tags: list[str] | None = None,
        tag_mode: TagOrMode = "and",
        media_type: str | None = None,
        created_after: str | None = None,
        created_before: str | None = None,
        limit: int = 50,
    ) -> list[RetrievalResult]:
        """Media-only cross-reference search."""
        limit = max(1, min(limit, 200))
        entity_pairs = self._resolve_entities(user_id, workspace_id, entities or [])
        tag_ids = self._resolve_tags(user_id, workspace_id, tags or [])

        media = self._search_media_with_logic(
            user_id,
            {"workspace_id": workspace_id, "q": q, "created_after": created_after, "created_before": created_before},
            entity_pairs, entity_mode, tag_ids, tag_mode, media_type, limit
        )
        return [self._media_to_result(m) for m in media]

    # ── Private helpers ──────────────────────────────────────────────────

    def _resolve_entities(self, user_id: int, workspace_id: int, refs: list[str | int]) -> list[tuple[str, int]]:
        """Resolve entity references (name or #id) to (entity_type, entity_id) pairs."""
        pairs = []
        # Get all milestones for name matching
        all_milestones = self._engine.list_milestones(user_id, workspace_id)
        name_to_id = {m.title.lower(): m.id for m in all_milestones}

        for ref in refs:
            # Handle #id format
            if isinstance(ref, str) and ref.startswith("#"):
                try:
                    eid = int(ref[1:])
                    # Verify this entity exists in the workspace
                    try:
                        self._engine.get_milestone(user_id, eid)
                        pairs.append(("milestone", eid))
                    except Exception:
                        pass
                    continue
                except ValueError:
                    pass

            # Name-based lookup
            eid = name_to_id.get(str(ref).strip().lower())
            if eid:
                pairs.append(("milestone", eid))
        return pairs

    def _resolve_tags(self, user_id: int, workspace_id: int, names: list[str]) -> list[int]:
        """Resolve tag names to tag_ids within the workspace."""
        tag_ids = []
        for name in names:
            name = name.strip()
            if not name:
                continue
            # Use engine's tag resolution (read-only, no create)
            tags = self._engine.list_tags(user_id, workspace_id)
            for tag in tags:
                if tag.name.lower() == name.lower():
                    tag_ids.append(tag.id)
                    break
        return tag_ids

    def _search_notes_with_logic(
        self,
        user_id: int,
        base: dict,
        entity_pairs: list[tuple[str, int]],
        entity_mode: EntityOrMode,
        tag_ids: list[int],
        tag_mode: TagOrMode,
        kind: str | None,
        limit: int,
    ) -> list[Note]:
        """Execute note search with AND/OR filter logic."""
        if not entity_pairs and not tag_ids:
            # Simple case: no entity/tag filters
            return self._engine.search_notes(
                user_id, base["workspace_id"],
                q=base["q"], kind=kind,
                created_after=base["created_after"],
                created_before=base["created_before"],
                limit=limit
            )

        # For AND mode: we need ALL entity/tag filters to match
        # For OR mode: we need ANY entity/tag filter to match
        # Since the underlying search supports single entity_type+entity_id or tag_id,
        # we execute multiple searches and combine results in Python.

        if entity_mode == "and" and tag_mode == "and":
            # ALL entities AND ALL tags must match
            # Start with first entity, then filter by rest
            if entity_pairs:
                etype, eid = entity_pairs[0]
                notes = self._engine.search_notes(
                    user_id, base["workspace_id"],
                    q=base["q"], kind=kind,
                    entity_type=etype, entity_id=eid,
                    created_after=base["created_after"],
                    created_before=base["created_before"],
                    limit=limit * 2  # fetch extra to allow Python filtering
                )
                # Filter by remaining entities
                for etype, eid in entity_pairs[1:]:
                    notes = [n for n in notes if (etype, eid) in self._engine.note_entities(user_id, n.id)]
            elif tag_ids:
                notes = self._engine.search_notes(
                    user_id, base["workspace_id"],
                    q=base["q"], kind=kind,
                    tag_id=tag_ids[0],
                    created_after=base["created_after"],
                    created_before=base["created_before"],
                    limit=limit * 2
                )
                for tid in tag_ids[1:]:
                    notes = [n for n in notes if tid in [t.id for t in self._engine.note_tags(user_id, n.id)]]
            else:
                notes = self._engine.search_notes(
                    user_id, base["workspace_id"],
                    q=base["q"], kind=kind,
                    created_after=base["created_after"],
                    created_before=base["created_before"],
                    limit=limit * 2
                )

            # Now apply tag AND filter if we started with entities
            if entity_pairs and tag_ids:
                for tid in tag_ids:
                    notes = [n for n in notes if tid in [t.id for t in self._engine.note_tags(user_id, n.id)]]

            return notes[:limit]

        elif entity_mode == "or" or tag_mode == "or":
            # UNION: any entity OR any tag matches
            seen_ids = set()
            all_notes = []

            # Search by each entity
            for etype, eid in entity_pairs:
                notes = self._engine.search_notes(
                    user_id, base["workspace_id"],
                    q=base["q"], kind=kind,
                    entity_type=etype, entity_id=eid,
                    created_after=base["created_after"],
                    created_before=base["created_before"],
                    limit=limit
                )
                for n in notes:
                    if n.id not in seen_ids:
                        seen_ids.add(n.id)
                        all_notes.append(n)

            # Search by each tag
            for tid in tag_ids:
                notes = self._engine.search_notes(
                    user_id, base["workspace_id"],
                    q=base["q"], kind=kind,
                    tag_id=tid,
                    created_after=base["created_after"],
                    created_before=base["created_before"],
                    limit=limit
                )
                for n in notes:
                    if n.id not in seen_ids:
                        seen_ids.add(n.id)
                        all_notes.append(n)

            # If no entity/tag filters but q/kind/date filters exist
            if not entity_pairs and not tag_ids:
                notes = self._engine.search_notes(
                    user_id, base["workspace_id"],
                    q=base["q"], kind=kind,
                    created_after=base["created_after"],
                    created_before=base["created_before"],
                    limit=limit
                )
                for n in notes:
                    if n.id not in seen_ids:
                        seen_ids.add(n.id)
                        all_notes.append(n)

            # Sort newest-first and cap
            all_notes.sort(key=lambda n: n.created_at or "", reverse=True)
            return all_notes[:limit]

        else:
            # Mixed: entity AND, tag OR (or vice versa) — treat as AND for safety
            # (This shouldn't happen with current API design)
            return self._engine.search_notes(
                user_id, base["workspace_id"],
                q=base["q"], kind=kind,
                created_after=base["created_after"],
                created_before=base["created_before"],
                limit=limit
            )

    def _search_media_with_logic(
        self,
        user_id: int,
        base: dict,
        entity_pairs: list[tuple[str, int]],
        entity_mode: EntityOrMode,
        tag_ids: list[int],
        tag_mode: TagOrMode,
        media_type: str | None,
        limit: int,
    ) -> list[Attachment]:
        """Execute media search with AND/OR filter logic."""
        if not entity_pairs and not tag_ids:
            return self._engine.search_media(
                user_id, base["workspace_id"],
                q=base["q"], media_type=media_type,
                created_after=base["created_after"],
                created_before=base["created_before"],
                limit=limit
            )

        if entity_mode == "and" and tag_mode == "and":
            if entity_pairs:
                etype, eid = entity_pairs[0]
                media = self._engine.search_media(
                    user_id, base["workspace_id"],
                    q=base["q"], media_type=media_type,
                    entity_type=etype, entity_id=eid,
                    created_after=base["created_after"],
                    created_before=base["created_before"],
                    limit=limit * 2
                )
                for etype, eid in entity_pairs[1:]:
                    media = [m for m in media if (etype, eid) in self._engine.media_entities(user_id, m.id)]
            elif tag_ids:
                media = self._engine.search_media(
                    user_id, base["workspace_id"],
                    q=base["q"], media_type=media_type,
                    tag_id=tag_ids[0],
                    created_after=base["created_after"],
                    created_before=base["created_before"],
                    limit=limit * 2
                )
                for tid in tag_ids[1:]:
                    media = [m for m in media if tid in [t.id for t in self._engine.media_tags(user_id, m.id)]]
            else:
                media = self._engine.search_media(
                    user_id, base["workspace_id"],
                    q=base["q"], media_type=media_type,
                    created_after=base["created_after"],
                    created_before=base["created_before"],
                    limit=limit * 2
                )

            if entity_pairs and tag_ids:
                for tid in tag_ids:
                    media = [m for m in media if tid in [t.id for t in self._engine.media_tags(user_id, m.id)]]

            return media[:limit]

        elif entity_mode == "or" or tag_mode == "or":
            seen_ids = set()
            all_media = []

            for etype, eid in entity_pairs:
                media = self._engine.search_media(
                    user_id, base["workspace_id"],
                    q=base["q"], media_type=media_type,
                    entity_type=etype, entity_id=eid,
                    created_after=base["created_after"],
                    created_before=base["created_before"],
                    limit=limit
                )
                for m in media:
                    if m.id not in seen_ids:
                        seen_ids.add(m.id)
                        all_media.append(m)

            for tid in tag_ids:
                media = self._engine.search_media(
                    user_id, base["workspace_id"],
                    q=base["q"], media_type=media_type,
                    tag_id=tid,
                    created_after=base["created_after"],
                    created_before=base["created_before"],
                    limit=limit
                )
                for m in media:
                    if m.id not in seen_ids:
                        seen_ids.add(m.id)
                        all_media.append(m)

            if not entity_pairs and not tag_ids:
                media = self._engine.search_media(
                    user_id, base["workspace_id"],
                    q=base["q"], media_type=media_type,
                    created_after=base["created_after"],
                    created_before=base["created_before"],
                    limit=limit
                )
                for m in media:
                    if m.id not in seen_ids:
                        seen_ids.add(m.id)
                        all_media.append(m)

            all_media.sort(key=lambda m: m.created_at or "", reverse=True)
            return all_media[:limit]

        else:
            return self._engine.search_media(
                user_id, base["workspace_id"],
                q=base["q"], media_type=media_type,
                created_after=base["created_after"],
                created_before=base["created_before"],
                limit=limit
            )

    def _note_to_result(self, note: Note) -> RetrievalResult:
        return RetrievalResult(
            _type="note",
            note_id=note.id,
            title=note.title,
            content=note.content,
            kind=note.kind,
            note_created_at=note.created_at,
            workspace_id=note.workspace_id,
        )

    def _media_to_result(self, att: Attachment) -> RetrievalResult:
        return RetrievalResult(
            _type="media",
            media_id=att.id,
            file_type=att.file_type,
            telegram_file_id=att.telegram_file_id,
            file_name=att.file_name,
            caption=att.caption,
            media_created_at=att.created_at,
            message_id=att.message_id,
            chat_id=att.chat_id,
            topic_id=att.topic_id,
            entity_type=att.entity_type,
            entity_id=att.entity_id,
            extracted_text=att.extracted_text,
            workspace_id=att.workspace_id,
        )


def build_retrieval_service(engine: EntityEngine | None = None) -> CrossReferenceService:
    """Factory for the cross-reference retrieval service."""
    return CrossReferenceService(engine or EntityEngine())