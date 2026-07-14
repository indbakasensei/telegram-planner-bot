"""
confidence.py -- the Routing Layer's Confidence Policy (DRG-001 Section 6).

Pure decision logic: given an IntentResult, computes which destination
*would* be chosen if the Routing Layer acted on its own recommendation.
v14.1B never acts on this -- router.py always hard-codes the actual
destination to Destination.LEGACY -- but the recommendation is computed
in full and logged, so Sub-stage B's comparison-logging data
(DRG-001 Section 10) is real from day one, not deferred to whenever
Sub-stage C starts.
"""
from __future__ import annotations

from core.intent.intent_types import IntentResult
from core.routing.routing_matrix import (
    AMBIGUITY_CAP,
    CLARIFY_BAND_LOW,
    INTENT_WRITE_CLASS,
    OFFLINE_ENGINE_IMPLEMENTED_INTENTS,
    OFFLINE_THRESHOLD,
    WriteClass,
)
from core.routing.routing_types import Destination


def evaluate(intent_result: IntentResult) -> tuple[Destination, str | None]:
    """
    Returns (recommended_destination, fallback_reason). `fallback_reason`
    is None only when the recommendation is a direct, unambiguous match
    (mirrors IntentResult.reasoning's own "why", one level up: this
    explains why routing landed where it did, not why classification did).
    """
    write_class = INTENT_WRITE_CLASS.get(intent_result.intent, WriteClass.ALWAYS_AI)

    if write_class is WriteClass.ALWAYS_AI:
        return (
            Destination.AI_ROUTER,
            f"{intent_result.intent.name} is AI-shaped by definition (DRG-001 Section 6)",
        )

    threshold = OFFLINE_THRESHOLD[write_class]
    confidence = intent_result.confidence

    if confidence < CLARIFY_BAND_LOW:
        return (
            Destination.AI_ROUTER,
            f"confidence {confidence:.2f} below the clarify band "
            f"({CLARIFY_BAND_LOW}) for {write_class.name} -- too little "
            f"deterministic signal to even recommend a re-prompt",
        )

    if confidence < threshold:
        return (
            Destination.CLARIFY,
            f"confidence {confidence:.2f} in the ambiguous band "
            f"[{CLARIFY_BAND_LOW}, {threshold}) for {write_class.name} -- "
            f"matched, but a required field is likely missing or ambiguous "
            f"(INTENT_ENGINE.md's 0.6-0.84 confidence band)",
        )

    if intent_result.ambiguity > AMBIGUITY_CAP:
        return (
            Destination.LEGACY,
            f"ambiguity {intent_result.ambiguity:.2f} exceeds the safety cap "
            f"{AMBIGUITY_CAP} -- capped at Legacy regardless of confidence "
            f"{confidence:.2f} (DRG-001 Section 6, point 2)",
        )

    if intent_result.intent in OFFLINE_ENGINE_IMPLEMENTED_INTENTS:
        return (
            Destination.OFFLINE,
            None,
        )

    return (
        Destination.LEGACY,
        f"confidence {confidence:.2f} clears the {write_class.name} threshold "
        f"({threshold}) but the Offline Engine does not yet implement "
        f"{intent_result.intent.name} (Stage 2 not started, v14.1B)",
    )
