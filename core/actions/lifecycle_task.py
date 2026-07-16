"""
lifecycle_task.py -- Offline Engine actions: task lifecycle operations
(v14.7, Stage 6 -- the final Task-domain migration sprint).

One module for six operations, deliberately, rather than the per-file
split the task brief offered as an example (pause_task.py, resume_task.py,
...): five of the six share an identical locate -> single-UPDATE -> reply
skeleton, and separate files would duplicate that boilerplate five times
-- the brief's own "Do NOT duplicate logic" instruction outranks its
illustrative file names. Each operation is still its own named function
with its own tests.

Phase 0 inventory, verified directly against main.py/database.py (per
the brief's "do NOT assume any feature exists"):

  VERIFIED TO EXIST, migrated here:
  - Pause      (pause_cmd, main.py:2296)  -> pause_task():  UPDATE paused=1
  - Resume     (resume_cmd, main.py:2315) -> resume_task(): UPDATE paused=0
  - Paused view (paused_cmd, main.py:2334) -> get_paused_tasks()
  - Snooze     (snooze_cmd, main.py:2617) -> snooze_task(): UPDATE
    snooze_until = now + minutes; validates 1-1440 minutes; learning-log
    side effects (log_snooze + log_interaction("task_snooze"), both
    exception-swallowed -- replicated verbatim, including the swallow)
  - Stop reminders (stopreminder_cmd, main.py:2504) -> stop_reminders():
    UPDATE due_time=NULL, snooze_until=NULL
  - Carry forward (carryforward_cmd, main.py:2363) ->
    carry_forward_overdue(): bulk UPDATE due_date=today for overdue,
    non-paused, non-recurring tasks (the WHERE clause's paused/recurrence
    exclusions live in database.py and are shared by construction)

  VERIFIED TO EXIST but NOT migrated here, with reasons:
  - Delreminder (delreminder_cmd, main.py:2536) -- a pure delete alias
    (calls delete_task()); "delete reminder <id>" already classifies
    DELETE_TASK, so v14.5's offline delete path (ADR-010, with its
    deliberate confirm step) already covers it. Nothing to add.
  - Postpone (postpone_task()) -- only reachable via reminder callback
    buttons (handle_callback, main.py:2089), not the text-message path
    this Offline Engine integrates with. Out of scope.
  - clear_snooze() -- internal scheduler plumbing, no user-facing command.

  VERIFIED TO NOT EXIST in Legacy (zero matches in main.py -- documented
  per the brief, not invented): Archive, Restore, Hide, Unhide, Unsnooze.

None of these operations confirm before acting in Legacy (all verified
immediate), and none is irreversible (pause<->resume are inverses,
snooze/stop-reminders/carry-forward are all correctable by editing the
task) -- so per ADR-010's policy, all apply directly, no confirm step.

Scheduler equivalence is by construction: `paused` and `snooze_until`
ARE the scheduler's state (scheduler.py's get_due_tasks() filters on
them), and both paths write them through the same database.py functions.

One Legacy wording quirk replicated, not fixed: stopreminder's reply
says "Use /resume <id> to turn back on", but resume_task() only flips
`paused` -- it does NOT restore the due_time stop_reminders() cleared,
so resuming after stopreminder doesn't actually bring the pings back.
Misleading text, faithfully mirrored (the brief allows improvements only
for genuine bugs/safety; a wording quibble is neither) -- documented in
DEBUGGING.md.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from fmt import b, esc
from core.offline.action_result import ActionResult
from core.offline.request_context import RequestContext
from core.storage import Storage

# Entry patterns mirror main.py's slashless prefix groups verbatim
# (core/intent/rules.py's Tier 0 maps all of these to EDIT_TASK except
# the paused-view phrases, which are QUERY_TASK exact matches).
_PAUSE_RE = re.compile(r"^pause\s+(\d+)\b", re.IGNORECASE)
_RESUME_RE = re.compile(r"^resume\s+(\d+)\b", re.IGNORECASE)
_SNOOZE_RE = re.compile(r"^snooze\s+(\d+)\s+(\d+)\b", re.IGNORECASE)
_STOPREM_RE = re.compile(
    r"^(?:stopreminder|stop\s+reminders?(?:\s+for)?)\s+(\d+)\b", re.IGNORECASE,
)
_CARRYFORWARD_PHRASES = ("carryforward", "carry forward", "move overdue to today")
PAUSED_VIEW_PHRASES = ("paused", "show paused", "paused tasks")

SNOOZE_MIN, SNOOZE_MAX = 1, 1440  # mirrors main.py:2631's 1-1440 bound


def match_entry(text: str) -> tuple[str, dict] | None:
    """Returns (operation, args) for a recognized lifecycle phrase, or
    None (graceful fallthrough to Legacy). Id-less phrasings ("pause",
    "snooze 5") deliberately don't match -- Legacy's usage/pick-list
    replies stay Legacy's job."""
    stripped = text.strip()
    low = stripped.lower()

    if low in _CARRYFORWARD_PHRASES:
        return "carry_forward", {}
    m = _SNOOZE_RE.match(stripped)
    if m:
        return "snooze", {"task_id": int(m.group(1)), "minutes": int(m.group(2))}
    m = _PAUSE_RE.match(stripped)
    if m:
        return "pause", {"task_id": int(m.group(1))}
    m = _RESUME_RE.match(stripped)
    if m:
        return "resume", {"task_id": int(m.group(1))}
    m = _STOPREM_RE.match(stripped)
    if m:
        return "stop_reminders", {"task_id": int(m.group(1))}
    return None


def _locate(task_id: int, user_id: int, storage: Storage):
    """The shared locate step every per-task operation starts with,
    mirroring Legacy's identical get_task_by_id-or-not-found preamble."""
    task = storage.tasks.get_by_id(task_id, user_id)
    if task is None:
        return None, ActionResult(
            success=False, message=f"❌ Task [{task_id}] not found.",
            warnings=["task_not_found"],
        )
    return task, None


def pause(task_id: int, user_id: int, storage: Storage) -> ActionResult:
    task, err = _locate(task_id, user_id, storage)
    if err:
        return err
    storage.tasks.pause(task_id, user_id)
    return ActionResult(
        success=True,
        message=f"⏸ Paused: {b(task[1])}\nReminders stopped. "
                f"Use /resume {task_id} to turn back on.",
        metadata={"operation": "pause", "task_id": task_id},
    )


def resume(task_id: int, user_id: int, storage: Storage) -> ActionResult:
    task, err = _locate(task_id, user_id, storage)
    if err:
        return err
    storage.tasks.resume(task_id, user_id)
    return ActionResult(
        success=True,
        message=f"▶️ Resumed: {b(task[1])}\nReminders are back on.",
        metadata={"operation": "resume", "task_id": task_id},
    )


def snooze(task_id: int, minutes: int, user_id: int, storage: Storage,
            now: datetime | None) -> ActionResult:
    if not (SNOOZE_MIN <= minutes <= SNOOZE_MAX):
        return ActionResult(
            success=False,
            message="Snooze duration must be 1-1440 minutes (24 hours max).",
            warnings=["invalid_duration"],
        )
    task, err = _locate(task_id, user_id, storage)
    if err:
        return err
    if now is None:
        return ActionResult(
            success=False, message="Internal error: no clock supplied.",
            warnings=["missing_now"],
        )

    snooze_until = (now + timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M")
    storage.tasks.snooze(task_id, user_id, snooze_until)

    # Learning-log side effects, mirroring main.py:2642-2646 verbatim,
    # including the bare exception swallow.
    try:
        storage.learning.log_snooze(user_id, task_id, task[1],
                                     task[4] or "General", minutes)
        storage.learning.log_interaction(user_id, "task_snooze")
    except Exception:
        pass

    h, m = minutes // 60, minutes % 60
    label = f"{h}h {m}m" if h else f"{m}m"
    return ActionResult(
        success=True,
        message=f"⏰ Snoozed {b(task[1])} for {esc(label)}.\n"
                f"I'll remind you at {esc(snooze_until.split()[1])}.",
        metadata={"operation": "snooze", "task_id": task_id,
                  "snooze_until": snooze_until},
    )


def stop_reminders(task_id: int, user_id: int, storage: Storage) -> ActionResult:
    task, err = _locate(task_id, user_id, storage)
    if err:
        return err
    storage.tasks.stop_reminders(task_id, user_id)
    return ActionResult(
        success=True,
        message=f"🔕 Reminders stopped for {b(task[1])}\n"
                f"Task still exists. Use /resume {task_id} to turn back on.",
        metadata={"operation": "stop_reminders", "task_id": task_id},
    )


def carry_forward(user_id: int, storage: Storage,
                   now: datetime | None) -> ActionResult:
    if now is None:
        return ActionResult(
            success=False, message="Internal error: no clock supplied.",
            warnings=["missing_now"],
        )
    today = now.strftime("%Y-%m-%d")
    count = storage.tasks.carry_forward_overdue(user_id, today)
    if count > 0:
        message = f"📅 Moved {count} overdue task(s) to today ({esc(today)})."
    else:
        message = "✅ No overdue tasks to carry forward!"
    return ActionResult(
        success=True, message=message,
        metadata={"operation": "carry_forward", "count": count},
    )


def paused_list(context: RequestContext, storage: Storage) -> ActionResult:
    """Read-only paused-tasks view -- signature matches the Stage 1
    read-only actions so the registry's QUERY_TASK specs
    (core/offline/registrations.py) can dispatch it the same way."""
    tasks = storage.tasks.get_paused(context.user_id)
    if not tasks:
        return ActionResult(success=True, message="No paused tasks.", data=tasks)
    lines = [f"⏸ {b('Paused Tasks:')}", ""]
    for t in tasks:
        lines.append(f"{b('[' + str(t[0]) + ']')} {esc(t[1])} — 📅 {esc(t[2] or 'No date')}")
    lines.append("")
    lines.append("Use /resume <id> to reactivate.")
    return ActionResult(success=True, message="\n".join(lines), data=tasks,
                         metadata={"operation": "paused_list", "count": len(tasks)})


def execute_entry(operation: str, args: dict, context: RequestContext,
                   storage: Storage) -> ActionResult:
    """Single dispatch point the engine calls with match_entry()'s output."""
    if operation == "pause":
        return pause(args["task_id"], context.user_id, storage)
    if operation == "resume":
        return resume(args["task_id"], context.user_id, storage)
    if operation == "snooze":
        return snooze(args["task_id"], args["minutes"], context.user_id,
                       storage, context.now)
    if operation == "stop_reminders":
        return stop_reminders(args["task_id"], context.user_id, storage)
    if operation == "carry_forward":
        return carry_forward(context.user_id, storage, context.now)
    return ActionResult(success=False, message="", warnings=["unknown_operation"])
