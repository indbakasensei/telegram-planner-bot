"""
core.intent -- BAKA v14.0 Stage 1 Intent Engine (Shadow Mode).

Deterministic, rule-based message classifier per
docs/adr/ADR-002-intent-engine.md and INTENT_ENGINE.md. Runs in Shadow
Mode: main.py's handle_message() calls IntentEngine.classify() and logs
the result, but nothing in the codebase acts on that result yet -- see
main.py's integration point (search "Intent Engine (Shadow Mode)") and
DESIGN_SPEC_v14_AUTONOMOUS_CORE.md's staged rollout.

Public surface: Intent, IntentResult, ConversationContext, IntentEngine.
Everything else in this package is an implementation detail.
"""
from core.intent.intent_engine import IntentEngine
from core.intent.intent_types import ConversationContext, Intent, IntentResult

__all__ = ["Intent", "IntentResult", "ConversationContext", "IntentEngine"]
