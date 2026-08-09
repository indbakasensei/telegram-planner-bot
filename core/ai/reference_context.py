"""
reference_context.py -- per-user conversational reference memory (M1).

Tracks the entities/tasks a user has most recently touched and the last
ordered list shown to them, so a later pronoun / conversational / ordinal
reference can be resolved deterministically against real context instead
of being re-guessed by the LLM.

State is in-memory (per-instance dicts keyed by user_id), mirroring
conversation_state.py: it is conversational and ephemeral, NOT durable
data. The authoritative *active entity* lives in the DB-backed
tg_active_context row (core/storage/storage.py TelegramBindingStorage);
this module only supplements it with mention order and ordered-list
context that the DB does not model.
"""
from __future__ import annotations

from dataclasses import dataclass

MAX_RECENT = 10


@dataclass(frozen=True, slots=True)
class Referent:
    """A stable identity for something the user referred to.

    Identity is (kind, workspace_id, id) -- never a display-name substring.
    `title` is only for rendering and clarification.
    """
    kind: str                 # "entity" (task reserved for M4)
    id: int
    title: str | None = None
    workspace_id: int | None = None


class ReferenceContext:
    """Per-user recent-mention and last-ordered-list memory.

    One instance is owned by each EntityManager (the production singleton
    shares one across users, keyed by user_id; tests build their own so
    state never leaks between tests).
    """

    def __init__(self) -> None:
        self._recent: dict[int, list[Referent]] = {}
        self._ordered: dict[int, list[Referent]] = {}

    # ── writers ──────────────────────────────────────────────────────────
    def note_mention(self, user_id: int, referent: Referent) -> None:
        """Record that `referent` was just the focus of the conversation.
        A re-mention moves it to the most-recent slot (last in the list)."""
        lst = [r for r in self._recent.get(user_id, [])
               if not (r.kind == referent.kind and r.id == referent.id)]
        lst.append(referent)
        self._recent[user_id] = lst[-MAX_RECENT:]

    def note_ordered(self, user_id: int, referents: list[Referent]) -> None:
        """Record the last ordered list shown to the user (for ordinals)."""
        self._ordered[user_id] = list(referents)

    # ── readers ──────────────────────────────────────────────────────────
    def recent(self, user_id: int) -> list[Referent]:
        """Most-recent-last list of mentions for the user."""
        return self._recent.get(user_id, [])

    def ordered(self, user_id: int) -> list[Referent]:
        """The last ordered list shown to the user ([] if none yet)."""
        return self._ordered.get(user_id, [])
