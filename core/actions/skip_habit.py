"""
skip_habit.py -- Offline Engine action: intentional streak reset
(v14.10, Habit domain Stage 2).

Replicates main.py's skiphabit_cmd() exactly (v14.10 Phase 0):
locate -> is_habit guard -> reset_streak() -> reply. Direct apply,
**no confirmation** -- Legacy has none, and the operation fails
ADR-010's irreversibility test twice over: `longest_streak` is
untouched, and `current_streak` is derived data that the next
log_habit_completion() recomputes from the full habit_log history
anyway (the "self-healing reset" documented in DEBUGGING.md's v14.9
habit findings). No learning logs, no analytics, no scheduler columns
touched (`current_streak` is display data; get_due_tasks() never reads
it). Legacy's UPDATE is guardless, so repeating the command repeats
the reply -- idempotent by construction, replicated.

Id-less phrasings ("skiphabit", "skip habit") fall through to Legacy's
usage replies, same as every other entry command.

Storage Facade only, never database.py directly.
"""
from __future__ import annotations

import re

from fmt import b
from core.offline.action_result import ActionResult
from core.offline.request_context import RequestContext
from core.storage import Storage

# Mirrors main.py's / core/intent/rules.py's slashless prefix group
# (["skiphabit ", "skip habit ", "reset streak "] -> EDIT_TASK),
# verbatim. \s+ between words matches the style of every other entry
# regex (complete_task, lifecycle_task, habit_views).
_ENTRY_RE = re.compile(
    r"^(?:skiphabit|skip\s+habit|reset\s+streak)\s+(\d+)\b", re.IGNORECASE,
)


def match_entry_command(text: str) -> int | None:
    """Returns the habit_id, or None if this isn't a recognized
    skip-habit phrase."""
    m = _ENTRY_RE.match(text.strip())
    return int(m.group(1)) if m else None


def execute(habit_id: int, context: RequestContext,
             storage: Storage) -> ActionResult:
    """Locate, guard, reset, reply -- skiphabit_cmd()'s exact sequence."""
    task = storage.tasks.get_by_id(habit_id, context.user_id)
    if not task or not storage.habits.is_habit(habit_id):
        # Legacy replies "That's not a habit." -- success=False falls
        # through to Legacy, which produces exactly that.
        return ActionResult(
            success=False, message="That's not a habit.",
            warnings=["not_a_habit"],
        )
    storage.habits.reset_streak(habit_id)
    return ActionResult(
        success=True,
        message=(f"🔄 Streak reset for {b(task[1])}. "
                 "No worries — start fresh tomorrow!"),
        data=[habit_id],
        metadata={"habit_id": habit_id, "operation": "skip_habit"},
    )
