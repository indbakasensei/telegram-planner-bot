"""
entities.py -- entity-extraction helpers for the Intent Engine.

Pure functions only: text or an already-parsed dict in, a plain dict
out. No I/O. These do not reimplement date/time parsing -- they adapt
date_parser.py's existing output shape into IntentResult.entities, and
extract the small pieces of structure (like a trailing numeric task id)
that date_parser.py doesn't already cover.
"""
from __future__ import annotations

import re
from typing import Any

_LEADING_INT_RE = re.compile(r'(?<!\d)(\d+)')


def extract_numeric_id(text: str) -> int | None:
    """
    First integer literal in `text`, e.g. the "5" in "5" / "5 30" /
    "task 5 tomorrow". Used for Tier 0 command matches like
    "done 5", "delete 5", "snooze 5 30" where main.py's real handlers
    (done_task, delete_task_cmd, snooze_cmd, ...) parse the id out of
    context.args themselves -- this is a read-only echo of that same
    convention for observational entity logging, not a reimplementation
    of what those handlers do with it.
    """
    m = _LEADING_INT_RE.search(text)
    return int(m.group(1)) if m else None


def entities_from_parsed_date(parsed: dict[str, Any]) -> dict[str, Any]:
    """
    Adapt date_parser.parse_all()'s return shape into a lean entities
    dict: only keys with a meaningful (truthy, non-default) value are
    included, so a classification's logged entities line stays short and
    every key present is actually informative.
    """
    entities: dict[str, Any] = {}
    if parsed.get("date"):
        entities["date"] = parsed["date"]
    if parsed.get("time"):
        entities["time"] = parsed["time"]
        if parsed.get("time_ambiguous"):
            entities["time_ambiguous"] = True
    if parsed.get("recurrence"):
        entities["recurrence"] = parsed["recurrence"]["type"]
    if parsed.get("priority") and parsed["priority"] != "medium":
        entities["priority"] = parsed["priority"]
    if parsed.get("is_deadline"):
        entities["is_deadline"] = True
    if parsed.get("multiple_tasks"):
        entities["multiple_tasks"] = True
    return entities
