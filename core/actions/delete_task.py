"""
delete_task.py -- Offline Engine action: delete a task (v14.5, Stage 4).

BAKA's third Offline write operation, and the first destructive one.
Two-phase (propose/commit), like create_task.py -- but unlike Update
(ADR-009, which matched Legacy's real no-confirm behavior), Delete
DELIBERATELY diverges from Legacy: main.py's real delete_task_cmd()
(verified directly, main.py:483-504) deletes immediately with NO
confirmation at all. Offline Delete adds one anyway. See
docs/adr/ADR-010-destructive-operations-policy.md for the full reasoning
-- summarized: irreversibility, INTENT_ENGINE.md's own already-approved
"destructive writes always confirm" principle (whose premise about
Legacy's current behavior turns out to be wrong, but whose intent is
sound), and this sprint's own explicit Locate-Preview-Confirm-Delete-
Verify-Return safety specification.

  propose(context, storage) -> ActionResult
      Locate + Preview. Verifies the task exists, returns a preview and
      metadata={"needs_confirmation": True, "pending_data": {"task_id": ...}}.
      Never deletes.

  commit(pending_data, user_id, storage) -> ActionResult
      Confirm + Delete + Verify + Return, called after the user confirms.
      Idempotent: re-checks existence first -- if the task is already
      gone (a repeated confirmation, or a concurrent delete from another
      path), reports that gracefully instead of attempting a redundant
      delete or raising. After deleting, re-fetches to VERIFY the row is
      actually gone before reporting success -- if it's somehow still
      present, reports a failure rather than a false-positive success.

Database interaction: storage.tasks.delete() (Storage Facade, already
existed from Stage 1 -- no extension needed). database.delete_task() is
a plain single-table `DELETE FROM tasks WHERE id=? AND user_id=?`, no
cascading cleanup of other tables, verified by reading it directly. No
scheduler interaction needed either: scheduler.py polls the tasks table
for due rows; a deleted row simply stops appearing on the next poll,
nothing to explicitly cancel.
"""
from __future__ import annotations

from typing import Any

from fmt import b, esc
from core.offline.action_result import ActionResult
from core.storage import Storage


def format_preview(task: tuple) -> str:
    """Shared by propose() and main.py's confirming-state re-prompt (a
    reply that's neither yes nor no) -- one place owns this wording,
    same pattern as create_task.format_summary()."""
    return (
        f"🗑 {b('Delete this task?')}\n\n"
        f"📌 {b(task[1])}\n"
        f"📅 {esc(task[2] or 'No date')}  ⏰ {esc(task[3] or 'No time')}"
    )


def propose(task_id: int, user_id: int, storage: Storage) -> ActionResult:
    """Locate + Preview. Never deletes."""
    task = storage.tasks.get_by_id(task_id, user_id)
    if task is None:
        return ActionResult(
            success=False, message=f"❌ Task [{task_id}] not found.",
            warnings=["task_not_found"],
        )
    return ActionResult(
        success=True, message=format_preview(task),
        metadata={"needs_confirmation": True, "pending_data": {"task_id": task_id}},
    )


def commit(pending_data: dict[str, Any], user_id: int, storage: Storage) -> ActionResult:
    """Confirm + Delete + Verify + Return. Idempotent."""
    task_id = pending_data.get("task_id")
    if task_id is None:
        return ActionResult(
            success=False, message="❌ Nothing to delete.",
            warnings=["missing_task_id"],
        )

    task = storage.tasks.get_by_id(task_id, user_id)
    if task is None:
        # Idempotency: already gone (repeated confirmation, or a
        # concurrent delete via another path) -- the end state the user
        # wanted (task not present) already holds. Report success, not
        # an error, but flag it distinctly so callers/logs can tell the
        # difference from a fresh delete.
        return ActionResult(
            success=True, message=f"🗑 Task [{task_id}] was already deleted.",
            metadata={"already_deleted": True, "task_id": task_id},
        )

    title = task[1]
    storage.tasks.delete(task_id, user_id)

    # Verify: re-fetch and confirm the row is actually gone before
    # reporting success -- never claim success on faith.
    still_present = storage.tasks.get_by_id(task_id, user_id)
    if still_present is not None:
        return ActionResult(
            success=False, message="❌ Delete failed -- task still present. Please try again.",
            warnings=["delete_not_verified"],
        )

    return ActionResult(
        success=True, message=f"🗑 Deleted: {b(title)}",
        metadata={"task_id": task_id, "deleted_title": title},
    )
