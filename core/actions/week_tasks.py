"""
week_tasks.py -- Offline Engine action: this week's tasks.

Read-only. Storage Facade only. Requires context.now. Range matches
main.py's existing week_tasks() handler exactly (today through +7 days,
not a Monday-Sunday calendar week) -- CHANGELOG.md's v14.2 entry notes
this deliberate behavioral parity with Legacy.
"""
from __future__ import annotations

from datetime import timedelta

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

    start_str = context.now.strftime("%Y-%m-%d")
    end_str = (context.now + timedelta(days=7)).strftime("%Y-%m-%d")
    tasks = storage.tasks.get_by_week(context.user_id, start_str, end_str)
    if not tasks:
        return ActionResult(success=True, message="✅ No tasks this week!", data=tasks)

    lines = [header("This Week", "🗓"), ""]
    for t in tasks:
        task_id, title = t[0], t[1]
        due_date = t[2] if len(t) > 2 else None
        due_time = t[3] if len(t) > 3 else None
        priority = t[5] if len(t) > 5 else "medium"
        recurrence = t[6] if len(t) > 6 else None
        lines.append(task_line(task_id, title, time=due_time, date=due_date,
                                priority=priority, recurrence=recurrence))
    return ActionResult(success=True, message="\n".join(lines), data=tasks,
                         metadata={"count": len(tasks), "start": start_str, "end": end_str})
