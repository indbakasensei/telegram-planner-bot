"""
core.actions -- Offline Engine action implementations (v14.2).

Each module exposes exactly one function, `execute(context: RequestContext,
storage: Storage) -> ActionResult`, matching the signature
core/offline/engine.py's dispatch table expects. Stage 1 of the Offline
Engine (this sprint): four read-only task actions only. See OUT OF SCOPE
in CHANGELOG.md's v14.2 entry for what these deliberately do not cover.
"""
from core.actions import list_tasks, search_tasks, today_tasks, week_tasks

__all__ = ["list_tasks", "today_tasks", "week_tasks", "search_tasks"]
