"""
errors.py -- typed exceptions for the Workspace Entity Engine
(v15.0-alpha.2).

The engine turns "bad input" and "illegal state" into these specific
exceptions instead of bare ValueError/None, so the callers a later phase
adds (handlers, the AI Orchestrator's safety gate) can distinguish
"doesn't exist / not yours" from "you can't do that from this state" from
"that field is invalid" -- each maps to a different user-facing reply.

All inherit EntityError, so a caller that only cares "did the engine
refuse?" can catch the base.
"""
from __future__ import annotations


class EntityError(Exception):
    """Base class for every Entity Engine refusal."""


class EntityNotFound(EntityError):
    """The requested entity does not exist, or is not owned by this user
    (the engine deliberately does not distinguish the two -- same silent-
    denial stance as the admin commands, CLAUDE.md)."""


class EntityValidationError(EntityError):
    """A field failed validation (empty title, unknown template, out-of-
    range value) before anything was written."""


class InvalidTransition(EntityError):
    """A lifecycle transition is not allowed from the entity's current
    state (e.g. a workspace already archived, an unknown target status)."""

    def __init__(self, entity_type: str, from_state: str, to_state: str):
        self.entity_type = entity_type
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(
            f"{entity_type}: cannot transition {from_state!r} -> {to_state!r}"
        )
