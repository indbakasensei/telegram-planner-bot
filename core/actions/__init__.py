"""
core.actions -- Offline Engine action implementations.

Stage 1 (v14.2) read-only actions each expose exactly one function,
`execute(context: RequestContext, storage: Storage) -> ActionResult`.
Stage 2 (v14.3) adds the first write action, `create_task`, which is
two-phase (`propose()`/`commit()`) instead -- see create_task.py's module
docstring and docs/adr/ADR-008-offline-write-operations.md for why.
"""
from core.actions import create_task, list_tasks, search_tasks, today_tasks, week_tasks

__all__ = ["list_tasks", "today_tasks", "week_tasks", "search_tasks", "create_task"]
