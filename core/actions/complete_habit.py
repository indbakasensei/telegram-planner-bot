"""
complete_habit.py -- Offline Engine action: habit completion (v14.11,
the final Habit-domain migration).

Replicates the habit branch of main.py's done_task() (lines 446-457)
EXACTLY, as re-verified in this sprint's Phase 0:

- One call: log_habit_completion(task_id, user_id) -- a single
  connection that INSERTs the habit_log row (UNIQUE per habit per day),
  recomputes current_streak by walking log dates backward, and UPDATEs
  tasks.current_streak/longest_streak/last_completed. Nothing else.
- **Already-logged-today is a SUCCESS reply, not an error**: the UNIQUE
  constraint trips, log_habit_completion returns (False,
  "already_logged") having written nothing, and Legacy still replies
  "✅ Habit completed!" with "(already logged today)" -- replicated,
  including the zero-write property.
- **Legacy intentionally does NOT**: write completions_log, write
  interaction_log, touch AI memory, touch scheduler state (done stays
  0; due/recurrence columns untouched -- get_due_tasks() sees no
  change), touch notification/reminder state, or call mark_done().
  Verified line by line; Offline writes exactly as much. (Contrast
  with task completion, which DOES write both learning logs --
  complete_task.py.)
- **A paused habit completes fine** in Legacy: done_task() has no
  paused check and log_habit_completion() doesn't care. Replicated --
  do not "fix".
- No confirmation, no pending/editing/gathering state -- immediate
  execution, like Legacy.

Two entry points for the two registration shapes (registrations.py):

- execute(task, ...) -- the shared-spec path (both domains enabled):
  complete_task.execute() has already fetched the row and checked
  is_habit(), exactly like Legacy's done_task() branches after ONE
  fetch; re-fetching here would break query-count equivalence.
- execute_by_id(task_id, ...) -- the habits-only-build path (its own
  registered spec): performs the same locate + is_habit sequence
  done_task() does, then either completes (habit) or declines
  (missing/non-habit -> success=False, falls through to Legacy, which
  replies/handles identically).

Storage Facade only, never database.py directly (AST-enforced).
"""
from __future__ import annotations

from fmt import b, esc, i
from core.offline.action_result import ActionResult
from core.storage import Storage


def execute(task, user_id: int, storage: Storage) -> ActionResult:
    """The habit branch of Legacy's done_task(), given the
    already-fetched task row. Direct apply (module docstring)."""
    ok, streak_or_msg = storage.habits.log_completion(task[0], user_id)
    if ok:
        streak = streak_or_msg
        streak_text = (f"\n🔥 Streak: {b(str(streak))} "
                       f"day{'s' if streak != 1 else ''}!")
        warnings = []
        metadata = {"habit_id": task[0], "streak": streak}
    else:
        streak_text = f"\n{i('(already logged today)')}"
        warnings = ["already_logged"]
        metadata = {"habit_id": task[0], "already_logged": True}
    return ActionResult(
        success=True,
        message=f"✅ {b('Habit completed!')}\n📌 {esc(task[1])}{streak_text}",
        data=task[0], warnings=warnings, metadata=metadata,
    )


def execute_by_id(task_id: int, user_id: int, storage: Storage) -> ActionResult:
    """Standalone entry for habits-only builds: replicate done_task()'s
    own locate + is_habit sequence, then complete or decline."""
    task = storage.tasks.get_by_id(task_id, user_id)
    if task is None:
        # Legacy's done_task() reply -- success=False falls through and
        # Legacy produces exactly this.
        return ActionResult(
            success=False, message=f"❌ Task [{task_id}] not found.",
            warnings=["task_not_found"],
        )
    if not storage.habits.is_habit(task_id):
        # A real task in a build where the Task domain is OFF -- not
        # ours; Legacy's done_task() owns it (mark_done + learning
        # logs), so fall through with no message of our own.
        return ActionResult(success=False, message="", warnings=["not_a_habit"])
    return execute(task, user_id, storage)
