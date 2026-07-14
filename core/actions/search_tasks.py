"""
search_tasks.py -- Offline Engine action: search tasks by title keyword.

Read-only. Storage Facade only. The search keyword isn't present in
context.entities (core/intent/rules.py's Tier 0 prefix match for
"search "/"find "/"look for " only extracts a numeric id, not a general
keyword -- see core/offline/engine.py's module docstring), so this
action strips the same three prefixes from context.text directly. Kept
in sync with core/intent/rules.py's _PREFIX_COMMANDS "search "/"find "/
"look for " group by hand -- same accepted-duplication pattern already
documented for core/intent/rules.py's own mirroring of main.py.
"""
from __future__ import annotations

from fmt import esc, header, task_line
from core.offline.action_result import ActionResult
from core.offline.request_context import RequestContext
from core.storage import Storage

_SEARCH_PREFIXES = ("search ", "find ", "look for ")


def _extract_keyword(text: str) -> str:
    # Left-strip only for the prefix check -- a full .strip() would drop
    # the trailing space the prefixes themselves end in ("search "),
    # causing e.g. exactly "search " to miss the prefix match and be
    # treated as a literal keyword "search" instead of an empty query.
    # Same class of bug as core/offline/engine.py's _select_action fix.
    left_stripped = text.lstrip()
    low = left_stripped.lower()
    for prefix in _SEARCH_PREFIXES:
        if low.startswith(prefix):
            return left_stripped[len(prefix):].strip()
    return text.strip()


def execute(context: RequestContext, storage: Storage) -> ActionResult:
    keyword = _extract_keyword(context.text)
    if not keyword:
        return ActionResult(
            success=False, message="What would you like to search for?",
            warnings=["empty_keyword"],
        )

    tasks = storage.tasks.search_by_title(context.user_id, keyword)
    if not tasks:
        return ActionResult(
            success=True, message=f"No tasks found matching “{esc(keyword)}”.", data=tasks,
        )

    lines = [header(f"Search: “{keyword}” ({len(tasks)})", "🔍"), ""]
    for t in tasks:
        task_id, title = t[0], t[1]
        due_date = t[2] if len(t) > 2 else None
        due_time = t[3] if len(t) > 3 else None
        priority = t[5] if len(t) > 5 else "medium"
        recurrence = t[6] if len(t) > 6 else None
        lines.append(task_line(task_id, title, time=due_time, date=due_date,
                                priority=priority, recurrence=recurrence))
    return ActionResult(success=True, message="\n".join(lines), data=tasks,
                         metadata={"count": len(tasks), "keyword": keyword})
