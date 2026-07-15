"""
complete_task.py -- Offline Engine action: complete a task (v14.6, Stage 5).

BAKA's fourth Offline write operation. Applies DIRECTLY, no confirm step
-- matching Legacy's real, verified behavior (main.py's done_task(),
lines 428-482: mark_done() is called immediately on `/done <id>`, no
yes/no step), and consistent with ADR-010's policy: completion preserves
the task row (done=1, nothing destroyed), so it doesn't meet the
irreversibility bar that justified Delete's added confirmation.

Phase 0 findings this implementation is built on, all verified directly
against main.py/database.py rather than assumed:

- **No undo capability exists in Legacy.** No undone/uncomplete/undo
  command anywhere in main.py. A completed task's row survives (done=1),
  but no user-facing path flips it back. Per this sprint's Reversibility
  Review instruction: documented, not invented -- Offline adds no undo
  either.
- **Habits branch away before mark_done().** Legacy's done_task() checks
  is_habit() FIRST: a habit gets log_habit_completion() + streak display
  and never touches mark_done(). Habits are out of this sprint's scope,
  so execute() returns warnings=["habit_not_supported"] for them --
  main.py falls through to Legacy, which handles the streak logic
  exactly as today. Zero habit behavior change in either flag state.
- **Completion has learning-log side effects.** Legacy logs to
  completions_log (log_completion(), with a computed minutes-late delay)
  and interaction_log (log_interaction(user_id, "task_done")), both
  wrapped in a bare try/except: pass. Replicated here field-for-field --
  including the exception-swallowing, because a learning-log failure not
  blocking the completion is itself Legacy behavior worth preserving --
  via the Storage Facade's new LearningStorage domain (v14.6).
- **Recurrence handling is identical by construction.** mark_done() is a
  plain `UPDATE tasks SET done=1` with no recurrence special-casing, and
  both paths call that same function. (database.py's get_recurring_tasks()
  is dead code -- defined, never called anywhere.)
- **Re-completing an already-done task succeeds silently in Legacy**
  (get_task_by_id() has no done-flag filter; mark_done()'s UPDATE is
  idempotent). Matched, not "fixed" -- see tests.
"""
from __future__ import annotations

import re
from datetime import datetime

from fmt import b, esc
from core.offline.action_result import ActionResult
from core.storage import Storage

# Mirrors main.py's _starts_with_handlers entry for done_task verbatim:
# (["done ", "complete task ", "finish task ", "mark done "], done_task).
# Offline additionally requires a numeric id: Legacy's bare "done" (no
# args) shows a pick-list, which stays Legacy's job -- no id means no
# match here, graceful fallthrough.
_ENTRY_RE = re.compile(
    r"^(?:done|complete\s+task|finish\s+task|mark\s+done)\s+(\d+)\b",
    re.IGNORECASE,
)


def match_entry_command(text: str) -> int | None:
    """Returns the task_id, or None if this isn't a recognized
    completion phrase (including phrases without a numeric id, e.g.
    "mark task complete" -- Legacy-only, needs its pick-list UX)."""
    m = _ENTRY_RE.match(text.strip())
    return int(m.group(1)) if m else None


def _compute_delay_minutes(due_time: str | None, now: datetime) -> int:
    """Minutes-late computation, replicating main.py's done_task()
    (lines 462-471) exactly, including its silent fallback to 0 on any
    parse failure."""
    if not due_time:
        return 0
    try:
        sh, sm = map(int, due_time.split(":"))
        scheduled_dt = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
        return max(0, int((now - scheduled_dt).total_seconds() / 60))
    except (ValueError, AttributeError):
        return 0


def execute(task_id: int, user_id: int, storage: Storage,
             now: datetime | None) -> ActionResult:
    """Locate, branch away habits, mark done, replicate learning-log
    side effects, reply. Direct apply -- see module docstring."""
    task = storage.tasks.get_by_id(task_id, user_id)
    if task is None:
        return ActionResult(
            success=False, message=f"❌ Task [{task_id}] not found.",
            warnings=["task_not_found"],
        )

    if storage.habits.is_habit(task_id):
        # Out of scope: Legacy's streak logic owns habit completion.
        # main.py falls through to Legacy's done_task() on this signal.
        return ActionResult(success=False, message="", warnings=["habit_not_supported"])

    if now is None:
        return ActionResult(
            success=False, message="Internal error: no clock supplied.",
            warnings=["missing_now"],
        )

    storage.tasks.mark_done(task_id, user_id)

    # Learning-log side effects, replicating main.py:460-476 verbatim --
    # including the bare exception swallow: a learning-log failure must
    # not un-succeed the completion, exactly as in Legacy.
    try:
        due_time = task[3]
        storage.learning.log_completion(
            user_id, task_id, task[1], task[4] or "General",
            due_time or "00:00", now.strftime("%Y-%m-%d %H:%M:%S"),
            _compute_delay_minutes(due_time, now),
        )
        storage.learning.log_interaction(user_id, "task_done")
    except Exception:
        pass

    return ActionResult(
        success=True,
        message=f"✅ {b('Done!')} Great job:\n📌 {esc(task[1])}",
        data=task_id,
        metadata={"task_id": task_id, "completed_title": task[1]},
    )
