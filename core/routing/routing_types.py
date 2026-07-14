"""
routing_types.py -- core data types for the Routing Layer (v14.1B,
DRG-001_Intent_Aware_Routing.md / docs/adr/ADR-006-intent-aware-routing.md).

Pure data only: no I/O, no Telegram, no database, no AI. Does not modify
core/intent/intent_types.py's IntentResult -- a RoutingDecision *carries*
one, per DRG-001 Section 5's explicit "not duplicated here" design.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from core.intent.intent_types import IntentResult


class Destination(Enum):
    """
    Where a message could be routed. Four values, per DRG-001 Section 3's
    target-flow design -- not the two-way Offline/AI split
    INTENT_ENGINE.md's original (pre-Stage-1) sketch used, because most of
    main.py's ~90 handlers aren't ported to the Offline Engine yet
    (OFFLINE_ENGINE.md's migration is Stage 2, not started). LEGACY exists
    specifically to represent "confidently classified, but not yet
    migrated" without forcing a false choice between pretending Offline
    already covers it or treating it as AI-shaped.
    """

    OFFLINE = auto()
    LEGACY = auto()
    AI_ROUTER = auto()
    CLARIFY = auto()


@dataclass(slots=True)
class RoutingDecision:
    """
    The Routing Layer's sole output type, mirroring IntentResult's own
    "never a dict" discipline (core/intent/intent_types.py).

    v14.1B (this sprint) hard-codes `destination` to Destination.LEGACY on
    every call -- see router.py's module docstring for why. `destination`
    and `recommended_destination` are deliberately two separate fields so
    that divergence between them (which will be the common case this
    sprint, by design) is visible in the record itself, not something a
    log reader has to infer.

    Field reconciliation note (v14.1B implementation): the task brief that
    requested this sprint sketched slightly different example fields
    (`confidence`, `reasoning`, `metadata`) than DRG-001 Section 5's
    reviewed contract (`intent_result`, `fallback_reason`, no generic
    metadata bag). This implementation follows DRG-001 as the source of
    truth, with one deliberate resolution: DRG-001's Open Question 1 asked
    whether a generic `metadata: dict` might prove necessary once Sub-stage
    B revealed a real need to record "the future preferred destination."
    This sprint IS that need -- resolved with a named `recommended_destination`
    field instead of an untyped bag, consistent with DRG-001's own stated
    preference for named fields. `clarification_required` is a small,
    justified addition: a convenience boolean derived from
    `recommended_destination == Destination.CLARIFY`, added because it's
    cheap, unambiguous, and saves every log/metrics consumer from
    re-deriving it. See DRG-001's "Implementation Note (v14.1B)" for the
    full reconciliation record.
    """

    trace_id: str
    intent_result: IntentResult
    destination: Destination
    recommended_destination: Destination
    clarification_required: bool
    fallback_reason: str | None
    decision_latency_ms: float
