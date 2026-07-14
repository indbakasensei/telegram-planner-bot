"""
list_tasks.py -- Offline Engine action: list all pending tasks.

Read-only. Storage Facade only (core/storage/), never database.py
directly -- see core/offline/engine.py's module docstring for why.
"""
from __future__ import annotations

from fmt import header, task_line
from core.offline.action_result import ActionResult
from core.offline.request_context import RequestContext
from core.storage import Storage


def execute(context: RequestContext, storage: Storage) -> ActionResult:
    tasks = storage.tasks.get_all(context.user_id, done=0)
    if not tasks:
        return ActionResult(success=True, message="✅ No pending tasks!", data=tasks)

    lines = [header(f"Your Tasks ({len(tasks)})", "📋"), ""]
    for t in tasks:
        task_id, title = t[0], t[1]
        due_date = t[2] if len(t) > 2 else None
        due_time = t[3] if len(t) > 3 else None
        priority = t[5] if len(t) > 5 else "medium"
        recurrence = t[6] if len(t) > 6 else None
        lines.append(task_line(task_id, title, time=due_time, date=due_date,
                                priority=priority, recurrence=recurrence))
    return ActionResult(success=True, message="\n".join(lines), data=tasks,
                         metadata={"count": len(tasks)})
