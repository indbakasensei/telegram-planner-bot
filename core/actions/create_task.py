"""
create_task.py -- Offline Engine action: create a task (v14.3, Stage 2).

The first write operation handled by the Offline Engine. Two-phase, not
single-shot like Stage 1's read-only actions -- see
docs/adr/ADR-008-offline-write-operations.md for why: Legacy's own
execute_task_action() (main.py) always confirms before saving, with no
exception, for any task creation. Genuine behavioral equivalence means
Offline Task Creation must also confirm before writing, not save directly.

  propose(context, storage) -> ActionResult
      Parses and validates a task-creation request. Never writes.
      success=True + metadata["needs_confirmation"]=True + a pending-data
      dict means "here's what I'd create, go get confirmation" -- the
      caller (main.py) is responsible for the actual conversation_state
      transition (set_pending_action/set_state), exactly as it already
      does for Legacy, keeping this module itself free of conversation
      state mutation.

  commit(pending_data, user_id, storage) -> ActionResult
      The actual save, called by main.py's confirming-state handler
      after the user replies "yes". Mirrors main.py's
      execute_task_action() field-for-field: validation, duplicate
      check, recurrence mapping, save, deadline-marking, success message.

Recognizes exactly four verb prefixes ("add task ", "create task ",
"new task ", "todo "), checked directly against RequestContext.text --
NOT via Intent Engine classification, which currently assigns these
phrasings only weak confidence (Tier 4, ~0.4) or no match at all ("todo"
isn't recognized by any existing rule) -- both below INTENT_ENGINE.md's
approved 0.75 reversible-write threshold. Same class of dispatch-layer
stopgap ADR-007 already established for Stage 1's Intent.QUERY_TASK
coarseness; see DEBUGGING.md.

Title is the verb-prefix-stripped remainder, VERBATIM -- any trailing
date/time phrase (e.g. "buy milk tomorrow at 5pm") is NOT cleaned out of
the title. Cleaning it requires natural-language understanding, which is
explicitly out of scope (no AI). Documented, accepted limitation, not a
bug -- see CHANGELOG.md's v14.3 entry.
"""
from __future__ import annotations

from typing import Any

import date_parser
from fmt import b, code, esc
from core.offline.action_result import ActionResult
from core.offline.request_context import RequestContext
from core.storage import Storage

_CREATE_PREFIXES = ("add task ", "create task ", "new task ", "todo ")


def _match_prefix_and_title(text: str) -> str | None:
    """Returns the stripped title if text starts with a recognized verb
    prefix and has non-empty content after it; None otherwise. Left-strip
    only before the prefix check -- same reasoning as
    core/offline/registrations.py's search-matcher fix (ADR-007)."""
    left_stripped = text.lstrip()
    low = left_stripped.lower()
    for prefix in _CREATE_PREFIXES:
        if low.startswith(prefix):
            remainder = left_stripped[len(prefix):].strip()
            return remainder or None
    return None


def _map_recurrence(recurrence: dict[str, Any] | None):
    """Mirrors main.py's execute_task_action() recurrence mapping exactly
    (main.py:665-676), including monthly's day-of-month default of 1."""
    if not recurrence:
        return None, None, None
    rec_type = recurrence.get("type")
    rec_weekday = None
    rec_day = None
    if rec_type == "monthly":
        rec_day = recurrence.get("day_of_month") or 1
    elif rec_type == "weekly":
        rec_weekday = recurrence.get("weekday")
    return rec_type, rec_weekday, rec_day


def format_summary(pending_data: dict[str, Any]) -> str:
    """Shared by propose() and main.py's confirming-state re-prompt (a
    reply that's neither yes nor no) -- one place owns this wording."""
    return (
        f"📋 {b('Confirm this task')}\n\n"
        f"📌 {b(pending_data.get('title'))}\n"
        f"📅 Date: {esc(pending_data.get('date') or 'No date')}\n"
        f"⏰ Time: {esc(pending_data.get('time') or 'No time')}"
    )


def propose(context: RequestContext, storage: Storage) -> ActionResult:
    """Parse + validate only. Never writes."""
    title = _match_prefix_and_title(context.text)
    if title is None:
        return ActionResult(success=False, message="", warnings=["unsupported_action"])

    if context.now is None:
        return ActionResult(
            success=False, message="Internal error: no clock supplied.",
            warnings=["missing_now"],
        )

    parsed = date_parser.parse_all(title, context.now)
    date_str = parsed.get("date")
    time_str = parsed.get("time")

    errors = date_parser.validate_datetime(date_str, time_str, context.now)
    if errors:
        return ActionResult(
            success=False,
            message="  ".join(errors) + "\n\nPlease correct and try again.",
            warnings=["validation_failed"],
        )

    if storage.tasks.exists(context.user_id, title, date_str):
        matches = storage.tasks.search_by_title(context.user_id, title or "")
        existing_id = matches[0][0] if matches else "?"
        return ActionResult(
            success=True,
            message=f"Task {b(title)} is already saved as [{existing_id}]. "
                    f"Use /done {existing_id} when complete!",
            metadata={"duplicate": True, "existing_id": existing_id},
        )

    rec_type, rec_weekday, rec_day = _map_recurrence(parsed.get("recurrence"))
    pending_data = {
        "title": title,
        "date": date_str,
        "time": time_str,
        "category": "General",
        "priority": parsed.get("priority", "medium"),
        "recurrence_type": rec_type,
        "recurrence_weekday": rec_weekday,
        "recurrence_day": rec_day,
        "is_deadline": bool(parsed.get("is_deadline")),
    }

    return ActionResult(
        success=True, message=format_summary(pending_data),
        metadata={"needs_confirmation": True, "pending_data": pending_data},
    )


def commit(pending_data: dict[str, Any], user_id: int, storage: Storage) -> ActionResult:
    """The actual save, called after the user confirms. Mirrors main.py's
    execute_task_action() field-for-field (main.py:636-719)."""
    title = pending_data.get("title")
    date_str = pending_data.get("date")
    time_str = pending_data.get("time")

    if not title:
        return ActionResult(
            success=False, message="❌ No task title. Please try again.",
            warnings=["missing_title"],
        )

    errors = date_parser.validate_datetime(date_str, time_str)
    if errors:
        return ActionResult(
            success=False,
            message="  ".join(errors) + "\n\nPlease correct and try again.",
            warnings=["validation_failed"],
        )

    if storage.tasks.exists(user_id, title, date_str):
        matches = storage.tasks.search_by_title(user_id, title or "")
        existing_id = matches[0][0] if matches else "?"
        return ActionResult(
            success=True,
            message=f"Task {b(title)} is already saved as [{existing_id}]. "
                    f"Use /done {existing_id} when complete!",
            metadata={"duplicate": True, "existing_id": existing_id},
        )

    task_id = storage.tasks.add(
        user_id, title, date_str, time_str,
        pending_data.get("category", "General"),
        pending_data.get("priority", "medium"),
        pending_data.get("recurrence_type"),
        pending_data.get("recurrence_weekday"),
        pending_data.get("recurrence_day"),
    )

    if bool(pending_data.get("is_deadline")):
        try:
            storage.tasks.mark_as_deadline(task_id, user_id, True)
        except Exception:
            pass

    rec_type = pending_data.get("recurrence_type")
    rec_msg = f"\n🔁 Repeats: {esc(rec_type)}" if rec_type else ""

    message = (
        f"✅ {b('Saved!')}\n\n"
        f"📌 {b(title)}\n"
        f"<i>📅 {esc(date_str or 'No date')} · ⏰ {esc(time_str or 'No time')} · "
        f"🏷 {esc(pending_data.get('category', 'General'))}</i>"
        f"{rec_msg}\n\n"
        f"Use {code('/done ' + str(task_id))} when complete!"
    )
    return ActionResult(success=True, message=message, data=task_id,
                         metadata={"task_id": task_id})
