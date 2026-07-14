"""
core.routing -- BAKA v14.1B Routing Layer (decision-logging only).

Implements DRG-001_Intent_Aware_Routing.md / docs/adr/ADR-006-intent-aware-routing.md's
Sub-stage B. Every message's IntentResult is routed through
RoutingLayer.route(), which ALWAYS resolves to Destination.LEGACY --
nothing in the codebase acts on `recommended_destination` yet. See
router.py's module docstring.

Public surface: Destination, RoutingDecision, RoutingLayer, RoutingError.
Everything else in this package is an implementation detail.
"""
from core.routing.exceptions import RoutingError
from core.routing.router import RoutingLayer
from core.routing.routing_types import Destination, RoutingDecision

__all__ = ["Destination", "RoutingDecision", "RoutingLayer", "RoutingError"]
