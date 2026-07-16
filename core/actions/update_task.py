"""
update_task.py -- Offline Engine action: update a task (v14.4, Stage 3).

BAKA's second Offline write operation. Unlike create_task.py (v14.3,
two-phase propose/commit with a confirm step), this action applies
DIRECTLY, with NO confirmation step -- see this module's design note and
docs/adr/ADR-009-offline-task-update.md for why: Legacy's own real
editing-state handler (main.py:1022-1055) calls update_task() immediately
on the very next message, with no yes/no step at all. A confirm step here
would be a behavioral DIVERGENCE from Legacy, not equivalence -- so this
sprint deliberately does not add one, contrary to what an earlier reading
of the task brief might suggest.

Two entry points, matching Legacy's real two-message flow exactly:

  start_editing(context, storage) -> ActionResult
      Message 1: "edit task <id>" / "rename task <id>". Verifies the task
      exists, returns metadata telling the caller to call
      conversation_state.set_editing(user_id, task_id) -- the SAME
      function Legacy's edit_task_cmd() already uses. Never writes.

  apply_change(text, task_id, user_id, storage, now) -> ActionResult
      Message 2, only reachable when conversation_state's state is
      already "editing" (checked by the caller, main.py). Recognizes a
      fixed set of deterministic change patterns -- date/time (reused
      date_parser.parse_all()), explicit priority/category/title
      patterns (new, since date_parser has no deterministic signal for
      these) -- and a "cancel"/"nevermind" case that clears editing
      state cleanly (a deliberate, narrow, documented exception: Legacy
      would otherwise hand "cancel" to the AI as an edit description,
      producing a confusing no-op; this only ever improves on that one
      input). Returns success=False, warnings=["unrecognized_change"]
      for anything else -- the caller (main.py) does NOT clear state and
      falls through to Legacy's own AI-mediated editing handler, exactly
      as if this module had never been consulted.

Deliberately NOT supported, verified absent from Legacy's real update
capability, not merely out of scope by assumption:

  - Recurrence changes. database.update_task()'s real signature has no
    recurrence parameters at all, and Legacy's editing handler doesn't
    pass any -- Legacy cannot change a task's recurrence today, despite
    an earlier reading of the task brief listing "change recurrence" as
    an example. Offline Update matches that real limitation rather than
    exceeding it. See ADR-009.
  - Duplicate detection. Legacy's editing handler never calls
    task_exists(). Adding one here would be an unequivalent enhancement,
    not a safety net -- not added.

Deliberately ADDED beyond Legacy's real behavior, one narrow case,
documented as such:

  - Date/time validation before writing (date_parser.validate_datetime()).
    Legacy's real editing handler never validates either -- this sprint's
    own Transaction Safety requirement ("validate first... if validation
    fails, no database modification") justifies this one safety-only
    addition, since it changes no user-visible flow, only rejects a
    clearly-invalid date rather than silently accepting it.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import date_parser
from fmt import b, esc
from core.offline.action_result import ActionResult
from core.storage import Storage

_ENTRY_RE = re.compile(r"^(?:edit|rename)\s+task\s+(\d+)\b", re.IGNORECASE)
_CANCEL_RE = re.compile(r"^\s*(cancel|nevermind|never mind|stop)\s*$", re.IGNORECASE)
_PRIORITY_RE = re.compile(
    r"\b(?:set|change)?\s*priority\s*(?:to\s+)?(high|medium|low)\b", re.IGNORECASE,
)
_CATEGORY_RE = re.compile(
    r"\b(?:set|change)\s+category\s+(?:to\s+)?(.+)$", re.IGNORECASE,
)
_RENAME_RE = re.compile(
    r"\b(?:rename(?:\s+to)?|set\s+title\s+to|change\s+title\s+to)\s+(.+)$",
    re.IGNORECASE,
)

VALID_PRIORITIES = {"high", "medium", "low"}


def match_entry_command(text: str) -> int | None:
    """Message 1: "edit task <id>" / "rename task <id>". Returns the
    task_id, or None if this isn't a recognized entry phrase."""
    m = _ENTRY_RE.match(text.strip())
    return int(m.group(1)) if m else None


def start_editing(task_id: int, user_id: int, storage: Storage) -> ActionResult:
    """Verifies the task exists. Never writes. Caller is responsible for
    the actual conversation_state.set_editing() call -- kept out of this
    module to preserve the "no conversation state mutation" constraint
    every Offline Engine component operates under."""
    task = storage.tasks.get_by_id(task_id, user_id)
    if task is None:
        return ActionResult(
            success=False, message=f"❌ Task [{task_id}] not found.",
            warnings=["task_not_found"],
        )
    return ActionResult(
        success=True,
        message=(
            f"✏️ Editing [{task_id}]: {esc(task[1])}\n\n"
            f"📅 {esc(task[2] or 'No date')}  ⏰ {esc(task[3] or 'No time')}  "
            f"🏷 {esc(task[4])}\n\n"
            f"Tell me what to change (date, time, priority, category, or title)."
        ),
        metadata={"start_editing": True, "task_id": task_id},
    )


def _match_change(text: str, now: datetime) -> tuple[dict[str, Any], str] | None:
    """Returns (fields_to_update, human_description) for the first
    recognized pattern, checked most-specific-first (explicit patterns
    before date_parser's general date/time detection, same "specificity
    wins" discipline core/offline/registrations.py's search-matcher fix
    already established) -- or None if nothing deterministic matched."""
    stripped = text.strip()

    m = _PRIORITY_RE.search(stripped)
    if m:
        level = m.group(1).lower()
        if level in VALID_PRIORITIES:
            return {"priority": level}, f"priority: {level}"

    m = _CATEGORY_RE.search(stripped)
    if m:
        category = m.group(1).strip()
        if category:
            return {"category": category}, f"category: {category}"

    m = _RENAME_RE.search(stripped)
    if m:
        title = m.group(1).strip()
        if title:
            return {"title": title}, f"title: {title}"

    parsed = date_parser.parse_all(stripped, now)
    date_str, time_str = parsed.get("date"), parsed.get("time")
    if date_str or time_str:
        fields: dict[str, Any] = {}
        if date_str:
            fields["due_date"] = date_str
        if time_str:
            fields["due_time"] = time_str
        desc = " · ".join(f"{k}: {v}" for k, v in
                           (("date", date_str), ("time", time_str)) if v)
        return fields, desc

    return None


def apply_change(text: str, task_id: int, user_id: int, storage: Storage,
                  now: datetime) -> ActionResult:
    """Message 2. See module docstring for the full state machine."""
    if _CANCEL_RE.match(text):
        return ActionResult(success=True, message="❌ Cancelled!", metadata={"cancelled": True})

    match = _match_change(text, now)
    if match is None:
        return ActionResult(success=False, message="", warnings=["unrecognized_change"])
    fields, description = match

    # Transaction safety: validate first, no database modification if
    # validation fails (deliberate addition beyond Legacy -- see module
    # docstring).
    if "due_date" in fields or "due_time" in fields:
        errors = date_parser.validate_datetime(
            fields.get("due_date"), fields.get("due_time"), now,
        )
        if errors:
            return ActionResult(
                success=False,
                message="  ".join(errors) + "\n\nPlease correct and try again.",
                warnings=["validation_failed"],
            )

    task = storage.tasks.get_by_id(task_id, user_id)
    if task is None:
        return ActionResult(
            success=False, message=f"❌ Task [{task_id}] not found.",
            warnings=["task_not_found"],
        )

    # Prepare, then commit once -- a single Storage Facade call, matching
    # database.update_task()'s own single-statement-per-field semantics
    # (never partially applied across multiple separate calls).
    storage.tasks.update(task_id, user_id, **fields)

    updated = storage.tasks.get_by_id(task_id, user_id)
    message = (
        f"✅ {b('Updated!')}\n\n"
        f"📌 {b(updated[1])}\n"
        f"📅 {esc(updated[2] or 'No date')}  ⏰ {esc(updated[3] or 'No time')}  "
        f"🏷 {esc(updated[4])}"
    )
    return ActionResult(success=True, message=message, data=updated,
                         metadata={"changed": description})
