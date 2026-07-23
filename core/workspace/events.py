"""
events.py -- the EntityEvent record emitted by the Entity Engine
(v15.0-alpha.5).

alpha.2 introduced an `on_event` seam on the Entity Engine; alpha.5 makes
what flows through it a self-contained record so any subscriber -- the
Timeline (this milestone), and later Telegram Sync (alpha.6) and the AI
Orchestrator (alpha.7) -- gets everything it needs without re-deriving it
or reaching back into the engine. In particular a Milestone/Note model
carries no user_id, but the engine knows it at emit time, so it is stamped
onto the event here (not left for each subscriber to resolve).

Pure data. The hook is `Callable[[EntityEvent], None]`; the default sink is
a no-op, so with no subscriber attached the engine's behaviour is exactly
as before (byte-identical, flag OFF).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

# source values (KTD): who caused the event.
SRC_USER = "user"
SRC_AI = "ai"
SRC_SYSTEM = "system"


@dataclass(frozen=True, slots=True)
class EntityEvent:
    event_type: str            # "milestone.archived", "workspace.created", ...
    entity_type: str           # "workspace" | "milestone" | "note"
    user_id: int
    workspace_id: int | None   # the workspace this event belongs under
    entity_id: int | None      # the affected entity's id
    entity: object             # the model (or pre-delete snapshot)
    source: str = SRC_USER


# The Entity Engine's event-hook type.
EventHook = Callable[[EntityEvent], None]


def noop_event(event: EntityEvent) -> None:
    """Default sink: does nothing. Replaced by a subscriber (e.g. the
    Timeline) when one is attached."""


def build_event(event_type: str, entity_type: str, entity: object,
                user_id: int, source: str = SRC_USER) -> EntityEvent:
    """Assemble an EntityEvent from a model + the user_id in engine scope.
    entity_id is the model's id; workspace_id is the model's id for a
    workspace, else its workspace_id."""
    entity_id = getattr(entity, "id", None)
    if entity_type == "workspace":
        workspace_id = getattr(entity, "id", None)
    else:
        workspace_id = getattr(entity, "workspace_id", None)
    return EntityEvent(
        event_type=event_type, entity_type=entity_type, user_id=user_id,
        workspace_id=workspace_id, entity_id=entity_id, entity=entity,
        source=source,
    )
