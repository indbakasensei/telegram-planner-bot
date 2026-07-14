"""
request_context.py -- the Offline Engine's input contract (v14.2).

Domain information only. No telegram.Update, no telegram.CallbackQuery,
no python-telegram-bot import of any kind -- Phase 0's "Telegram
decoupling" review point, enforced here by construction: this module has
no PTB dependency to accidentally reach for.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from core.intent.intent_types import Intent


@dataclass(slots=True, frozen=True)
class RequestContext:
    """
    user_id: who is asking -- every Storage Facade call needs this for
        database.py's user_id-scoping invariant (docs/database.md).
    text: the original raw message text. Needed because Intent.QUERY_TASK
        is deliberately coarser than the four read-only actions this
        Stage covers (list/today/week/search all currently share one
        Intent value -- core/intent/intent_types.py's Intent docstring).
        OfflineEngine's action dispatch uses this to distinguish them --
        see engine.py's module docstring for why this is a narrow,
        sprint-scoped stopgap, not a general design pattern.
    intent: the Intent Engine's classification (core/intent/intent_types.py),
        carried through unmodified.
    entities: the Intent Engine's extracted entities, carried through
        unmodified.
    now: the current moment, IST-aware, supplied by the caller -- same
        "caller injects the clock" discipline ConversationContext already
        established (core/intent/intent_types.py), for the same reason:
        keeps every Action a pure function of its inputs.
    """

    user_id: int
    text: str
    intent: Intent
    entities: dict[str, Any] = field(default_factory=dict)
    now: datetime | None = None
