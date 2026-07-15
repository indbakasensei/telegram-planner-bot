"""
core.actions -- Offline Engine action implementations.

Stage 1 (v14.2) read-only actions each expose exactly one function,
`execute(context: RequestContext, storage: Storage) -> ActionResult`.
Stage 2 (v14.3) adds the first write action, `create_task`, which is
two-phase (`propose()`/`commit()`) instead -- see create_task.py's module
docstring and docs/adr/ADR-008-offline-write-operations.md for why.
Stage 3 (v14.4) adds `update_task`, which applies directly with no
confirm step (`start_editing()`/`apply_change()`) -- see update_task.py's
module docstring and docs/adr/ADR-009-offline-task-update.md for why.
Stage 4 (v14.5) adds `delete_task`, two-phase like create_task
(`propose()`/`commit()`) but for a different reason -- see
delete_task.py's module docstring and
docs/adr/ADR-010-destructive-operations-policy.md.
"""
from core.actions import create_task, delete_task, list_tasks, search_tasks, today_tasks, update_task, week_tasks

__all__ = [
    "list_tasks", "today_tasks", "week_tasks", "search_tasks",
    "create_task", "update_task", "delete_task",
]
