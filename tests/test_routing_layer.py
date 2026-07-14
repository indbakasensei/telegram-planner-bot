"""
Tests for core/routing/ -- the v14.1B Routing Layer (decision-logging only).

DRG-001_Intent_Aware_Routing.md / docs/adr/ADR-006-intent-aware-routing.md.
Constructs IntentResult fixtures directly (not via IntentEngine.classify())
so every recommended_destination branch in confidence.py is independently
reachable and deterministic, the same fixture-construction style
tests/test_intent_engine.py uses for its own direct rule-function tests.
"""
import uuid

import pytest

from core.intent.intent_types import Intent, IntentResult
from core.routing.confidence import evaluate
from core.routing.router import RoutingLayer
from core.routing.routing_types import Destination


def make_result(intent, confidence, ambiguity=0.0, entities=None):
    return IntentResult(
        intent=intent, confidence=confidence, entities=entities or {},
        ambiguity=ambiguity, reasoning="test fixture", tier=0, latency_ms=0.0,
    )


@pytest.fixture
def router():
    return RoutingLayer()


# ── destination is ALWAYS Legacy, regardless of input ───────────────────

@pytest.mark.parametrize("intent,confidence,ambiguity", [
    (Intent.DELETE_TASK, 1.0, 0.0),
    (Intent.ADD_TASK, 0.95, 0.0),
    (Intent.CHAT, 0.6, 0.0),
    (Intent.UNKNOWN, 0.0, 0.0),
    (Intent.ADD_TASK, 0.4, 0.9),
    (Intent.QUERY_TASK, 0.6, 0.0),
])
def test_destination_is_always_legacy(router, intent, confidence, ambiguity):
    decision = router.route(make_result(intent, confidence, ambiguity))
    assert decision.destination is Destination.LEGACY


# ── recommended_destination: confidence.evaluate() branch coverage ──────

def test_always_ai_intent_recommends_ai_router():
    dest, reason = evaluate(make_result(Intent.CHAT, 1.0))
    assert dest is Destination.AI_ROUTER
    assert "AI-shaped by definition" in reason


def test_unknown_intent_recommends_ai_router():
    dest, reason = evaluate(make_result(Intent.UNKNOWN, 0.0))
    assert dest is Destination.AI_ROUTER


def test_high_confidence_write_recommends_legacy_not_yet_offline():
    dest, reason = evaluate(make_result(Intent.DELETE_TASK, 1.0))
    assert dest is Destination.LEGACY
    assert "does not yet implement" in reason


def test_below_clarify_band_recommends_ai_router():
    dest, reason = evaluate(make_result(Intent.ADD_TASK, 0.4))
    assert dest is Destination.AI_ROUTER
    assert "clarify band" in reason


def test_ambiguous_middle_band_recommends_clarify():
    # 0.65 is in [0.6, 0.75) for REVERSIBLE_WRITE
    dest, reason = evaluate(make_result(Intent.ADD_TASK, 0.65))
    assert dest is Destination.CLARIFY
    assert "ambiguous band" in reason


def test_high_ambiguity_caps_at_legacy_despite_high_confidence():
    dest, reason = evaluate(make_result(Intent.DELETE_TASK, 1.0, ambiguity=0.9))
    assert dest is Destination.LEGACY
    assert "ambiguity" in reason and "safety cap" in reason


def test_read_only_threshold_is_lower_than_write_thresholds():
    # 0.65 clears READ_ONLY's 0.6 threshold (recommends Legacy directly,
    # no CLARIFY) but would fall in ADD_TASK's ambiguous band at the same
    # confidence -- proves per-intent-class thresholds are actually applied.
    dest, _ = evaluate(make_result(Intent.QUERY_TASK, 0.65))
    assert dest is Destination.LEGACY


# ── RoutingDecision shape / contract ─────────────────────────────────────

def test_clarification_required_matches_recommended_destination(router):
    decision = router.route(make_result(Intent.ADD_TASK, 0.65))
    assert decision.recommended_destination is Destination.CLARIFY
    assert decision.clarification_required is True


def test_clarification_not_required_for_direct_match(router):
    decision = router.route(make_result(Intent.DELETE_TASK, 1.0))
    assert decision.clarification_required is False


def test_fallback_reason_present_for_non_offline_recommendation(router):
    decision = router.route(make_result(Intent.ADD_TASK, 0.95))
    assert decision.fallback_reason is not None


def test_intent_result_is_carried_not_copied(router):
    ir = make_result(Intent.GREETING, 0.9)
    decision = router.route(ir)
    assert decision.intent_result is ir


def test_trace_id_is_a_valid_uuid_and_unique_per_call(router):
    ir = make_result(Intent.GREETING, 0.9)
    d1 = router.route(ir)
    d2 = router.route(ir)
    uuid.UUID(d1.trace_id)  # raises ValueError if malformed
    uuid.UUID(d2.trace_id)
    assert d1.trace_id != d2.trace_id


def test_decision_latency_is_recorded_and_small(router):
    decision = router.route(make_result(Intent.GREETING, 0.9))
    assert decision.decision_latency_ms >= 0.0
    assert decision.decision_latency_ms < 10.0


def test_route_is_pure_same_input_same_recommendation(router):
    ir = make_result(Intent.ADD_TASK, 0.4)
    a = router.route(ir)
    b = router.route(ir)
    assert a.recommended_destination == b.recommended_destination
    assert a.fallback_reason == b.fallback_reason
    assert a.destination == b.destination == Destination.LEGACY


def test_offline_engine_implemented_intents_is_currently_empty():
    from core.routing.routing_matrix import OFFLINE_ENGINE_IMPLEMENTED_INTENTS
    assert OFFLINE_ENGINE_IMPLEMENTED_INTENTS == frozenset()


def test_offline_recommendation_once_a_future_stage_implements_an_intent(monkeypatch):
    # OFFLINE is unreachable today (the set above is empty by design, Stage 2
    # hasn't started) -- this proves the mechanism itself is correct ahead of
    # that set ever being populated, per DRG-001 Section 11's "Future
    # scalability" claim that flipping a row here requires no code change.
    monkeypatch.setattr(
        "core.routing.confidence.OFFLINE_ENGINE_IMPLEMENTED_INTENTS",
        frozenset({Intent.QUERY_TASK}),
    )
    dest, reason = evaluate(make_result(Intent.QUERY_TASK, 1.0))
    assert dest is Destination.OFFLINE
    assert reason is None


# ── Integration with the real Intent Engine ──────────────────────────────

def test_end_to_end_with_real_intent_engine():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from core.intent.intent_engine import IntentEngine
    from core.intent.intent_types import ConversationContext

    ie = IntentEngine()
    router_ = RoutingLayer()
    now = datetime(2026, 3, 4, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    ctx = ConversationContext(now=now)

    ir = ie.classify("delete 5", ctx)
    decision = router_.route(ir)
    assert decision.destination is Destination.LEGACY
    assert decision.intent_result.intent is Intent.DELETE_TASK
