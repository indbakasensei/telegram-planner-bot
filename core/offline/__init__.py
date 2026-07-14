"""
core.offline -- the Offline Engine (v14.2, Stage 1: read-only task
commands only). Dispatches RequestContext -> Action -> ActionResult via
the Storage Facade (core/storage/); never imports database.py directly.

Public surface: RequestContext, ActionResult, OfflineEngine.
"""
from core.offline.action_result import ActionResult
from core.offline.engine import OfflineEngine
from core.offline.request_context import RequestContext

__all__ = ["RequestContext", "ActionResult", "OfflineEngine"]
