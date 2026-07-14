"""
exceptions.py -- Routing Layer exception hierarchy.

Currently unused internally: router.py's route() never raises for
ordinary input (mirrors core/intent/intent_engine.py's IntentEngine.classify()
"never raises for ordinary input" property) -- confidence.py's evaluate()
is a total function over IntentResult, with no input that leaves any
branch unhandled. Defined now, ahead of any actual raise site, so future
Routing Layer work (e.g. a Sub-stage C failure path, DRG-001 Section 8)
has a normalized exception type to raise instead of inventing one ad hoc
under time pressure -- the same normalization discipline AI_ROUTER.md's
Provider Interface already establishes for provider adapters.
"""
from __future__ import annotations


class RoutingError(RuntimeError):
    """Base class for Routing Layer failures. Not raised by v14.1B."""
