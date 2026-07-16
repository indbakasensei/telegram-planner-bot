"""
core.offline -- the Offline Engine. Dispatches RequestContext -> Action
-> ActionResult via the Storage Facade (core/storage/); never imports
database.py directly. v14.8 (ADR-012): dispatch is registry-based --
actions are registered in registrations.py, resolved through
ActionRegistry, and OfflineEngine is a thin dispatcher.

Public surface: RequestContext, ActionResult, OfflineEngine, plus the
registration machinery future domains (Habits, Goals, Projects) extend:
ActionRegistry, ActionSpec, RegistryError, build_default_registry.
"""
from core.offline.action_result import ActionResult
from core.offline.engine import OfflineEngine
from core.offline.registrations import build_default_registry
from core.offline.registry import ActionRegistry, ActionSpec, RegistryError
from core.offline.request_context import RequestContext

__all__ = [
    "RequestContext", "ActionResult", "OfflineEngine",
    "ActionRegistry", "ActionSpec", "RegistryError", "build_default_registry",
]
