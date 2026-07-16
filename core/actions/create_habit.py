"""
create_habit.py -- Offline Engine action: habit creation (v14.10,
Habit domain Stage 2 -- the domain's first write operation).

Replicates main.py's addhabit_cmd() exactly, as verified in v14.9's and
v14.10's Phase 0 audits. The load-bearing findings, each pinned by a
test:

- **Direct apply, NO confirmation.** Legacy's /addhabit writes
  immediately; only the AI-driven HABIT flow confirms. Per ADR-010
  (confirm when Legacy confirms OR the operation is irreversible),
  creation is reversible by delete and Legacy doesn't confirm, so
  neither do we -- unlike task creation (v14.3), where Legacy's own
  flow confirms. Different answer, same policy.
- **NO duplicate detection.** addhabit_cmd() never calls task_exists()
  or any equivalent -- creating "Run" twice yields two habits, in
  Legacy and here alike.
- **Title stripping is quirky and replicated verbatim**: Legacy strips
  only `at HH:MM` (colon form) and the literal words
  daily/every day/every week/weekly/monthly. "gym every monday at
  7 AM" keeps "every monday at 7 AM" in the title even though
  parse_all() extracts the weekly recurrence and 07:00 from it --
  faithful, documented, not fixed.
- **No scheduler code involved**: the created row's recurrence columns
  are the scheduler integration (get_due_tasks() reads them), identical
  by construction since both paths insert through database.add_habit()
  (which also stamps habit_start_date from the real clock -- Legacy
  behavior, unchanged).
- **No learning logs, no analytics writes** -- Legacy writes none for
  habit creation.

Empty remainders/titles fall through to Legacy's own usage replies
("Tell me what the habit is." / the /addhabit usage card), the same
id-less-phrase discipline as v14.7/v14.9.

Storage Facade only, never database.py directly.
"""
from __future__ import annotations

import re

from fmt import b, esc
from core.offline.action_result import ActionResult
from core.offline.request_context import RequestContext
from core.storage import Storage

import date_parser

# Mirrors main.py's / core/intent/rules.py's slashless prefix group
# (["addhabit ", "add habit ", "new habit "] -> ADD_TASK), verbatim.
# Disjoint from create_task._CREATE_PREFIXES by inspection -- the
# ADD_TASK registry bucket relies on that (registrations.py).
_CREATE_PREFIXES = ("addhabit ", "add habit ", "new habit ")

# Legacy's exact title-stripping regex, addhabit_cmd() (main.py:3038).
_STRIP_RE = re.compile(
    r"\b(at\s+\d{1,2}:\d{2})\b|\b(daily|every day|every week|weekly|monthly)\b",
    re.IGNORECASE,
)


def match_entry_command(text: str) -> str | None:
    """Returns the whitespace-collapsed remainder after a recognized
    create-habit prefix (mirroring main.py's args_str.split()/join
    round-trip), or None if the prefix is missing or the remainder is
    empty (bare "add habit " -> Legacy's usage reply)."""
    left_stripped = text.lstrip()
    low = left_stripped.lower()
    for prefix in _CREATE_PREFIXES:
        if low.startswith(prefix):
            remainder = " ".join(left_stripped[len(prefix):].split())
            return remainder or None
    return None


def execute(description: str, context: RequestContext,
             storage: Storage) -> ActionResult:
    """Parse time/recurrence, strip title, insert -- addhabit_cmd()'s
    exact pipeline. Direct apply (module docstring)."""
    if context.now is None:
        return ActionResult(success=False, message="", warnings=["missing_now"])

    parsed = date_parser.parse_all(description, context.now)
    time_val = parsed.get("time")
    recurrence = parsed.get("recurrence")
    rec_type = recurrence["type"] if recurrence else "daily"
    rec_weekday = recurrence.get("weekday") if recurrence else None

    title = _STRIP_RE.sub("", description).strip()
    title = re.sub(r"\s+", " ", title)
    if not title:
        # Legacy replies "Tell me what the habit is." -- success=False
        # here falls through to Legacy, which produces exactly that.
        return ActionResult(
            success=False, message="Tell me what the habit is.",
            warnings=["empty_title"],
        )

    habit_id = storage.habits.add(
        context.user_id, title, time=time_val,
        recurrence=rec_type, recurrence_weekday=rec_weekday,
    )

    day_suffix = f" (day {rec_weekday})" if rec_weekday is not None else ""
    message = (
        f"🌱 {b('Habit created!')}\n\n"
        f"📌 {b(title)}\n"
        f"🔄 {esc(rec_type)}{esc(day_suffix)}\n"
        f"⏰ {esc(time_val or 'flexible')}\n\n"
        "Mark it done every time you do it — I'll track your streak!\n"
        "Use /habits to see all habits."
    )
    return ActionResult(
        success=True, message=message, data=[habit_id],
        metadata={"habit_id": habit_id, "title": title,
                  "recurrence": rec_type, "time": time_val},
    )
