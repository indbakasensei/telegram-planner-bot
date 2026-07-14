"""
today_tasks.py -- Offline Engine action: today's tasks.

Read-only. Storage Facade only. Requires context.now (IST-aware) to
compute "today" -- never reads the system clock itself, same discipline
core/intent/ and core/routing/ already established.
"""
from __future__ import annotations

from fmt import header, task_line
from core.offline.action_result import ActionResult
from core.offline.request_context import RequestContext
from core.storage import Storage


def execute(context: RequestContext, storage: Storage) -> ActionResult:
    if context.now is None:
        return ActionResult(
            success=False, message="Internal error: no clock supplied.",
            warnings=["missing_now"],
        )

    today_str = context.now.strftime("%Y-%m-%d")
    tasks = storage.tasks.get_by_date(context.user_id, today_str)
    if not tasks:
        return ActionResult(success=True, message="✅ No tasks for today!", data=tasks)

    lines = [header(f"Today ({today_str})", "📅"), ""]
    for t in tasks:
        task_id, title = t[0], t[1]
        due_time = t[3] if len(t) > 3 else None
        priority = t[5] if len(t) > 5 else "medium"
        recurrence = t[6] if len(t) > 6 else None
        lines.append(task_line(task_id, title, time=due_time,
                                priority=priority, recurrence=recurrence))
    return ActionResult(success=True, message="\n".join(lines), data=tasks,
                         metadata={"count": len(tasks), "date": today_str})
