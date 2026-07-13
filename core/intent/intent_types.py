"""
intent_types.py -- core data types for the Intent Engine.

Pure data only: no I/O, no Telegram, no database, no AI. See
docs/adr/ADR-002-intent-engine.md for why this package is rule-based
rather than ML-based, and INTENT_ENGINE.md for the tiered design these
types support.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any


class Intent(Enum):
    """
    Closed, strongly typed set of intents the Stage 1 Intent Engine can
    produce. Deliberately the coarse-grained set given in the v14.0
    Stage 1 brief, not BAKA's full existing AI intent taxonomy
    (baka_brain.py's get_baka_response() already distinguishes
    TASK/HABIT/EDIT/DELETE/VIEW/MEMORY_SAVE/MEMORY_GET/GOAL/PLAN/ADVICE/
    CHAT/MULTIPLE) -- narrowing to a smaller, well-understood set for the
    first, additive, observation-only stage is deliberate. Widening this
    enum to match the AI's finer-grained taxonomy is reserved for a
    future stage (see Risk Assessment in the deliverables report).

    Plugin extensibility: Python's stdlib Enum is closed at class
    definition time, so a plugin cannot add a member to this class at
    runtime. Until the Plugin System (docs/adr/ADR-004-plugin-system.md,
    not yet built) exists, a plugin-specific intent is represented as
    Intent.UNKNOWN with the plugin's own intent name carried in
    IntentResult.entities["plugin_intent"] -- zero changes to this enum
    are needed when a new plugin ships. When the Plugin System is
    actually implemented, THIS is the natural place to introduce a
    registry-backed replacement; not built speculatively now, per this
    task's "avoid unnecessary abstractions" instruction.
    """

    ADD_TASK = auto()
    EDIT_TASK = auto()
    DELETE_TASK = auto()
    QUERY_TASK = auto()
    CHAT = auto()
    GREETING = auto()
    HELP = auto()
    MEDIA = auto()
    FILE = auto()
    SETTINGS = auto()
    UNKNOWN = auto()


@dataclass(slots=True, frozen=True)
class ConversationContext:
    """
    Everything the Intent Engine needs about "where is this conversation
    right now", supplied entirely by the caller. The engine never reads
    conversation_state.py, the database, or the system clock itself --
    that is what keeps IntentEngine.classify() a pure function of its
    two arguments.

    state: mirrors conversation_state.py's state strings ("idle",
        "gathering", "confirming", "editing"). Passed as a plain str
        rather than importing conversation_state.py's own representation,
        so this package stays dependency-free; the caller does the
        translation.
    partial_data: mirrors conversation_state.py's get_gathering() dict,
        when state == "gathering". Not used by any Stage 1 rule yet
        (reserved for a future stage that classifies follow-up replies
        in context) but accepted now so the call site's shape doesn't
        need to change later.
    now: the current moment, IST-aware, supplied by the caller. Per
        CLAUDE.md's "All datetime handling must use IST" convention,
        the engine follows it by construction -- by never calling
        datetime.now() itself and requiring an already-IST-aware value.
    """

    state: str = "idle"
    partial_data: dict[str, Any] = field(default_factory=dict)
    now: datetime | None = None


@dataclass(slots=True)
class IntentResult:
    """
    The Intent Engine's sole output type. Never a dict, per this task's
    explicit instruction -- callers get typed attribute access.

    Two fields beyond the brief's example, both justified:

    tier: which priority tier (0-5) produced this classification. The
        brief's own logging example implies this ("Reason: Matched
        scheduling keywords" is meaningless without knowing which stage
        produced it); storing it as a field, not just folded into
        `reasoning` prose, lets tests assert *why* a result was reached
        without parsing a sentence.
    latency_ms: classification wall-clock time. The brief's logging
        example explicitly includes "Latency: 3 ms" -- storing it here
        (measured by classify() itself) means every caller gets that log
        line for free instead of re-implementing timing at each call site.
    """

    intent: Intent
    confidence: float
    entities: dict[str, Any]
    ambiguity: float
    reasoning: str
    tier: int
    latency_ms: float
