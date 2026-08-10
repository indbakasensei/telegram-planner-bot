"""
projection.py -- the Telegram Projection adapter (v15.1).

Projects Workspace entities onto a Telegram forum group: the workspace is a
group, each ENTITY is a topic in that group, and workspace-level notes go to
the built-in General topic. This is the ONLY place that knows about Telegram
chat/topic ids -- the Workspace OS (engine, models, repositories) stays
completely Telegram-agnostic. The mapping lives in adapter-owned binding
tables (via the Storage Facade's `tg_bindings`), never on core entities.

The actual Telegram calls are made through an injected `TelegramClient`
(create_forum_topic / send_message / send_photo), so this module imports no
python-telegram-bot and is fully offline-testable with a fake client. The
production client that wraps the live bot is constructed in main.py.

Entities are referenced generically as (entity_type, entity_id) -- today the
workspace's entities are milestones, but nothing here is milestone-specific;
the adapter creates a topic for whatever entity it is asked to project.

v15.1.0-alpha.13: topic creation is now the full "new entity ⇒ topic"
contract. `ensure_entity_topic` takes an optional `initial_message` (the
entity's current card) posted into a NEWLY created topic only; and
`post_entity_update` appends an activity message to an entity's topic,
self-healing a missing topic first. The initial card is rendered from live
DB state by core/workspace/render.py -- nothing is invented.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

from core.storage import Storage

logger = logging.getLogger(__name__)


class TelegramClient(ABC):
    """The narrow Telegram surface the projection needs. Implemented for
    real over the live bot in main.py; a fake implements it in tests."""

    @abstractmethod
    def create_forum_topic(self, chat_id: int, name: str) -> int:
        """Create a forum topic and return its message_thread_id."""

    @abstractmethod
    def send_message(self, chat_id: int, topic_id: int | None, text: str,
                     parse_mode: str | None = None) -> int:
        """Send text to a topic (topic_id None ⇒ the General topic). Return
        the sent message id.

        ``parse_mode`` lets the projection mark its OWN bot-generated content
        (entity cards, update messages) as HTML. User-supplied note text
        stays plain (parse_mode None) so it can never break HTML parsing."""

    @abstractmethod
    def send_photo(self, chat_id: int, topic_id: int | None,
                   file_id: str, caption: str) -> int:
        """Send a photo (by Telegram file_id) to a topic. Return message id."""


@dataclass(frozen=True, slots=True)
class ProjectionResult:
    ok: bool
    reason: str = ""
    topic_id: int | None = None
    message_id: int | None = None


class TelegramProjection:
    """Maps workspace entities to Telegram topics and posts notes/photos.
    Stateless beyond the injected client + storage."""

    def __init__(self, client: TelegramClient, storage: Storage | None = None):
        self._c = client
        self._s = storage or Storage()

    # ── linking ────────────────────────────────────────
    def link_group(self, user_id, workspace_id, chat_id) -> ProjectionResult:
        """Bind a workspace to a Telegram group. The General topic is the
        group's built-in one (topic_id None), so nothing needs creating."""
        self._s.tg_bindings.link_workspace(user_id, workspace_id, chat_id)
        return ProjectionResult(True, topic_id=None)

    def is_linked(self, workspace_id) -> bool:
        return self._s.tg_bindings.get_binding(workspace_id) is not None

    def workspace_for_chat(self, chat_id):
        return self._s.tg_bindings.workspace_for_chat(chat_id)

    # ── entity → topic ─────────────────────────────────
    def ensure_entity_topic(self, user_id, workspace_id, entity_type,
                            entity_id, title,
                            initial_message: str | None = None) -> int | None:
        """Return the topic for an entity, creating it the first time. None
        if the workspace isn't linked to a group yet.

        Idempotent by construction: a binding that already exists returns the
        existing topic id and creates NOTHING -- no duplicate topic, no
        duplicate initial message. When the topic is newly created,
        ``initial_message`` (a bot-rendered HTML entity card) is posted into
        it. The post is best-effort: the topic + binding are the durable
        unit, so a send failure is logged and never fails the caller or
        corrupts the DB (the topic still exists; re-running is a no-op)."""
        binding = self._s.tg_bindings.get_binding(workspace_id)
        if binding is None:
            return None
        chat_id, _general = binding
        existing = self._s.tg_bindings.get_entity_topic(entity_type, entity_id)
        if existing is not None:
            return existing
        topic_id = self._c.create_forum_topic(chat_id, title)
        try:
            self._s.tg_bindings.set_entity_topic(
                user_id, workspace_id, entity_type, entity_id, topic_id)
        except Exception:
            # The topic already exists in Telegram; a transient DB hiccup on
            # the binding write must not orphan it (a re-run would otherwise
            # create a duplicate topic). Retry the write once, then give up.
            logger.exception("entity topic binding write failed, retrying once: "
                             "%s/%s -> topic %s", entity_type, entity_id, topic_id)
            self._s.tg_bindings.set_entity_topic(
                user_id, workspace_id, entity_type, entity_id, topic_id)
        if initial_message:
            try:
                self._c.send_message(chat_id, topic_id, initial_message,
                                     parse_mode="HTML")
            except Exception:
                logger.exception("initial card post failed for %s/%s",
                                 entity_type, entity_id)
        return topic_id

    def post_entity_update(self, user_id, workspace_id, entity_type,
                           entity_id, entity_title, text: str,
                           initial_message: str | None = None) -> ProjectionResult:
        """Post an append-only activity message to an entity's topic.

        Self-healing: if the entity somehow has no topic yet (created before
        this feature, or a create-time topic failure), the topic is created
        first and ``initial_message`` (the entity's CURRENT card) is posted,
        THEN the update. Old messages are never rewritten or deleted.
        Returns ok=False (reason='not_linked') when the workspace has no
        group yet -- the DB update is still committed by the caller."""
        binding = self._s.tg_bindings.get_binding(workspace_id)
        if binding is None:
            return ProjectionResult(False, reason="not_linked")
        chat_id, _general = binding
        topic_id = self.ensure_entity_topic(
            user_id, workspace_id, entity_type, entity_id, entity_title,
            initial_message=initial_message)
        if topic_id is None:
            return ProjectionResult(False, reason="not_linked")
        msg_id = self._c.send_message(chat_id, topic_id, text, parse_mode="HTML")
        return ProjectionResult(True, topic_id=topic_id, message_id=msg_id)

    # ── posting ────────────────────────────────────────
    def post_note(self, user_id, workspace_id, text, *, entity_type=None,
                  entity_id=None, entity_title=None,
                  photo_file_id=None) -> ProjectionResult:
        """Post a note (optionally a photo) to the right topic: the entity's
        topic when an entity is given, otherwise the workspace's General
        topic. Returns ok=False (reason='not_linked') if the workspace has no
        group yet -- callers should still have persisted the note to the DB."""
        binding = self._s.tg_bindings.get_binding(workspace_id)
        if binding is None:
            return ProjectionResult(False, reason="not_linked")
        chat_id, general_topic = binding

        topic_id = general_topic
        if entity_id is not None:
            topic_id = self.ensure_entity_topic(
                user_id, workspace_id, entity_type or "milestone",
                entity_id, entity_title or "Entity")

        if photo_file_id:
            msg_id = self._c.send_photo(chat_id, topic_id, photo_file_id, text)
        else:
            msg_id = self._c.send_message(chat_id, topic_id, text)
        return ProjectionResult(True, topic_id=topic_id, message_id=msg_id)
