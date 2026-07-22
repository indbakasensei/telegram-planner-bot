"""Self-tests: intent + routing sanity (category Routing).

Deterministic, no I/O -- exercises the Intent Engine and Routing Layer
end to end and confirms they produce a well-formed decision.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from core.selftest.models import SelfTestFail
from core.selftest.registry import selftest

_IST = ZoneInfo("Asia/Kolkata")


@selftest(name="Intent + Routing", category="Routing")
def check_intent_routing():
    from core.intent import IntentEngine, ConversationContext
    from core.routing import RoutingLayer

    ctx = ConversationContext(state="idle", partial_data={},
                              now=datetime.now(_IST))
    intent = IntentEngine().classify(text="list", context=ctx)
    if intent is None or intent.intent is None:
        raise SelfTestFail("intent engine returned no classification")
    decision = RoutingLayer().route(intent)
    if decision is None or decision.recommended_destination is None:
        raise SelfTestFail("routing layer returned no decision")
    return (f"'list' -> {intent.intent.name} -> "
            f"{decision.recommended_destination.name}")
