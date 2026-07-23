"""
lifecycle.py -- declarative state machines for Workspace entities
(v15.0-alpha.2).

The reusable rule-set the Entity Engine enforces. Each entity type gets a
`Lifecycle`: an initial state, a table of allowed `from -> {to, ...}`
transitions, and the set of valid states. This is deliberately DATA, not
code branches -- adding a template or an entity type never means editing a
big if/elif in the engine; it means (at most) declaring another Lifecycle
here. Same edit-nothing-central philosophy as the Template and Action
registries.

Transitioning an entity to the state it is already in is treated as a
no-op success (the engine short-circuits before writing), so callers can
be idempotent without special-casing.
"""
from __future__ import annotations

from dataclasses import dataclass

from core.workspace.errors import InvalidTransition
from core.workspace.models import (
    MS_ARCHIVED,
    MS_BLOCKED,
    MS_DONE,
    MS_IN_PROGRESS,
    MS_TODO,
    STATUS_ACTIVE,
    STATUS_ARCHIVED,
    STATUS_DONE,
)


@dataclass(frozen=True, slots=True)
class Lifecycle:
    entity_type: str
    initial: str
    transitions: dict  # from_state -> tuple[to_state, ...]

    def states(self) -> frozenset:
        """Every state reachable in this machine (initial + every from/to
        mentioned in the transition table)."""
        seen = {self.initial}
        for frm, tos in self.transitions.items():
            seen.add(frm)
            seen.update(tos)
        return frozenset(seen)

    def can(self, from_state: str, to_state: str) -> bool:
        """True if `to_state` is reachable from `from_state` (or equal to
        it -- staying put is always allowed). Unknown target states are
        never reachable."""
        if to_state == from_state:
            return to_state in self.states()
        return to_state in self.transitions.get(from_state, ())

    def validate(self, from_state: str, to_state: str) -> None:
        """Raise InvalidTransition unless `can(...)`."""
        if not self.can(from_state, to_state):
            raise InvalidTransition(self.entity_type, from_state, to_state)

    def is_noop(self, from_state: str, to_state: str) -> bool:
        return from_state == to_state


# Workspaces: active <-> done, either -> archived, archived -> active.
# Nothing is hard-terminal; archive/done are reversible (soft), matching
# WED §5 and the "never delete, only archive" stance.
WORKSPACE_LIFECYCLE = Lifecycle(
    entity_type="workspace",
    initial=STATUS_ACTIVE,
    transitions={
        STATUS_ACTIVE: (STATUS_DONE, STATUS_ARCHIVED),
        STATUS_DONE: (STATUS_ACTIVE, STATUS_ARCHIVED),
        STATUS_ARCHIVED: (STATUS_ACTIVE,),
    },
)

# Milestones: the todo -> in_progress -> done flow, plus blocked as a side
# state, reopen (done -> in_progress/todo), and archive from any active
# state (archived -> todo restores). v15.0-alpha.4. Soft delete is NOT a
# lifecycle transition -- it is an orthogonal deleted_at flag the engine
# handles separately.
MILESTONE_LIFECYCLE = Lifecycle(
    entity_type="milestone",
    initial=MS_TODO,
    transitions={
        MS_TODO: (MS_IN_PROGRESS, MS_DONE, MS_BLOCKED, MS_ARCHIVED),
        MS_IN_PROGRESS: (MS_TODO, MS_DONE, MS_BLOCKED, MS_ARCHIVED),
        MS_BLOCKED: (MS_TODO, MS_IN_PROGRESS, MS_ARCHIVED),
        MS_DONE: (MS_IN_PROGRESS, MS_TODO, MS_ARCHIVED),
        MS_ARCHIVED: (MS_TODO,),
    },
)


_BY_TYPE = {
    "workspace": WORKSPACE_LIFECYCLE,
    "milestone": MILESTONE_LIFECYCLE,
}


def for_entity(entity_type: str) -> Lifecycle:
    """Return the Lifecycle for an entity type, or raise KeyError for an
    unknown type (a programming error, not a user error)."""
    return _BY_TYPE[entity_type]
