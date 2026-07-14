"""
router.py -- BAKA v14.1B Routing Layer (decision-logging only).

Implements DRG-001_Intent_Aware_Routing.md / docs/adr/ADR-006-intent-aware-routing.md's
Sub-stage B ("Decision"): the Routing Layer runs on every message and
computes a real RoutingDecision, but the decision is logged only, never
acted on. This is DELIBERATE, not a placeholder -- DRG-001 Section 10
identifies skipping this comparison-logging period as the dominant risk
in this whole migration, and DRG-001 Section 13 conditions approval of
the entire design on it not being skipped.

MUST NOT (and does not): call AI, call database.py, call scheduler.py,
import Telegram objects, mutate conversation state, dispatch commands,
execute handlers, send replies, or perform any I/O beyond a debug log
line -- the same constraints core/intent/intent_engine.py's IntentEngine
already operates under (DRG-001 Section 4's "What the Routing Layer does
NOT own").
"""
from __future__ import annotations

import logging
import time
import uuid

from core.intent.intent_types import IntentResult
from core.routing.confidence import evaluate
from core.routing.routing_types import Destination, RoutingDecision

logger = logging.getLogger(__name__)


class RoutingLayer:
    """
    v14.1B: ALWAYS resolves `destination` to Destination.LEGACY. This is a
    hard-coded property of this sprint, not a bug and not configurable --
    see this module's docstring and DRG-001 Section 10, Sub-stage B. The
    *recommended* destination (what the Confidence Policy would actually
    choose) is still computed in full and carried on the returned
    RoutingDecision, so real comparison data accumulates from day one.

    Holds no state between calls; every route() call is independent.
    """

    def route(self, intent_result: IntentResult) -> RoutingDecision:
        """
        Never raises for ordinary input. Never executes anything --
        returns a RoutingDecision for the caller to log; main.py's
        existing Legacy routing continues completely unchanged below it.
        """
        start = time.perf_counter()
        trace_id = str(uuid.uuid4())

        recommended_destination, fallback_reason = evaluate(intent_result)

        decision = RoutingDecision(
            trace_id=trace_id,
            intent_result=intent_result,
            destination=Destination.LEGACY,  # hard-coded, v14.1B -- see docstring above
            recommended_destination=recommended_destination,
            clarification_required=(recommended_destination is Destination.CLARIFY),
            fallback_reason=fallback_reason,
            decision_latency_ms=round((time.perf_counter() - start) * 1000, 4),
        )
        self._log(decision)
        return decision

    @staticmethod
    def _log(decision: RoutingDecision) -> None:
        # Lazy %-style formatting, same discipline as
        # core/intent/intent_engine.py's _log() -- zero cost when DEBUG
        # logging is disabled.
        logger.debug(
            "[Routing]\nIntent:\n%s\nConfidence:\n%.2f\nRecommended Destination:\n%s\n"
            "Actual Destination:\n%s\nTrace ID:\n%s\nFallback Reason:\n%s\n"
            "Clarification Required:\n%s\nDecision Latency:\n%.2f ms",
            decision.intent_result.intent.name,
            decision.intent_result.confidence,
            decision.recommended_destination.name,
            decision.destination.name,
            decision.trace_id,
            decision.fallback_reason or "(none -- direct match)",
            decision.clarification_required,
            decision.decision_latency_ms,
        )
