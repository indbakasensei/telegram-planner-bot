"""
engine.py -- OfflineEngine (v14.2): the first production Offline Engine
path. Dispatches RequestContext -> read-only task Action -> ActionResult.

MUST NOT (and does not): call database.py directly (Storage Facade only,
core/storage/), call AI, call scheduler.py, import Telegram objects,
mutate conversation state, send replies, or perform any I/O beyond a
debug log line -- same constraints core/intent/ and core/routing/ already
operate under.

Action dispatch note (Phase 0 finding, see CHANGELOG.md's v14.2 entry):
Intent.QUERY_TASK is deliberately coarser than the four actions this
Stage covers -- it also covers /habits, /goals, /dashboard, /settings,
etc. (DRG-001 Section 7's Routing Matrix), none of which this Offline
Engine implements. Distinguishing "list" from "today" from "week" from
"search" therefore can't be done from `intent` alone; `entities` doesn't
carry a distinguishing hint either (Tier 0's exact-phrase matches produce
empty entities -- core/intent/rules.py). This module's dispatch table
below is a narrow, explicitly-scoped stopgap: a small, hand-maintained
mirror of core/intent/rules.py's own Tier 0 phrase groups for exactly
these four actions, checked against RequestContext.text directly. This
is accepted, documented duplication (the same kind already accepted for
core/intent/rules.py's own mirroring of main.py's command tables,
DEBUGGING.md), one level deeper. The real fix -- giving IntentResult.entities
a structured action/command hint at classification time -- is future
work, not done here; see DEBUGGING.md's "Offline Engine action dispatch
is text-pattern-based, not Intent-based" entry.

Any message that IS classified QUERY_TASK but doesn't match one of these
four known patterns (e.g. "/habits") returns a graceful
ActionResult(success=False, warnings=["unsupported_action"]) --
main.py's integration point falls through to Legacy on that signal,
exactly as if the Offline Engine had never been consulted.
"""
from __future__ import annotations

import logging

from core.actions import list_tasks, search_tasks, today_tasks, week_tasks
from core.intent.intent_types import Intent
from core.offline.action_result import ActionResult
from core.offline.request_context import RequestContext
from core.storage import Storage

logger = logging.getLogger(__name__)

# Mirrors core/intent/rules.py's _EXACT_COMMANDS "list"/"today"/"week"
# groups and _PREFIX_COMMANDS "search "/"find "/"look for " group,
# verbatim, for exactly the phrases these four actions must recognize.
_TODAY_PHRASES = (
    "today", "today's tasks", "show today", "what's today",
    "what do i have today", "schedule today",
)
_WEEK_PHRASES = ("week", "this week", "weekly", "show week", "what's this week")
_LIST_PHRASES = ("list", "my tasks", "show tasks", "all tasks", "show all")
_SEARCH_PREFIXES = ("search ", "find ", "look for ")


def _select_action(text: str):
    # Prefix check uses only a left-strip: the prefixes themselves end in
    # a space ("search "), so a full .strip() would remove that trailing
    # space from an input that's exactly "search " (prefix, no query
    # yet) and cause it to wrongly miss the match -- found by
    # tests/test_offline_engine.py's empty-keyword case.
    left_stripped = text.lstrip().lower()
    for prefix in _SEARCH_PREFIXES:
        if left_stripped.startswith(prefix):
            return search_tasks.execute

    low = text.strip().lower()
    if low in _TODAY_PHRASES:
        return today_tasks.execute
    if low in _WEEK_PHRASES:
        return week_tasks.execute
    if low in _LIST_PHRASES:
        return list_tasks.execute
    return None


class OfflineEngine:
    """
    Stage 1: dispatches only to the four read-only task actions
    (core/actions/{list,today,week,search}_tasks.py). Anything else
    returns a graceful "unsupported" ActionResult -- never raises for
    ordinary input, same discipline IntentEngine.classify() and
    RoutingLayer.route() already established.
    """

    def __init__(self, storage: Storage):
        self._storage = storage

    def execute(self, context: RequestContext) -> ActionResult:
        if context.intent is not Intent.QUERY_TASK:
            result = ActionResult(
                success=False, message="", warnings=["unsupported_intent"],
            )
            self._log(context, result)
            return result

        action = _select_action(context.text)
        if action is None:
            result = ActionResult(
                success=False, message="", warnings=["unsupported_action"],
            )
            self._log(context, result)
            return result

        try:
            result = action(context, self._storage)
        except Exception as exc:
            logger.exception("Offline Engine action execution failed")
            result = ActionResult(
                success=False, message="",
                warnings=[f"action_exception:{type(exc).__name__}"],
            )
        self._log(context, result)
        return result

    @staticmethod
    def _log(context: RequestContext, result: ActionResult) -> None:
        logger.debug(
            "[Offline]\nUser:\n%s\nText:\n%r\nSuccess:\n%s\nWarnings:\n%s",
            context.user_id, context.text, result.success,
            ", ".join(result.warnings) or "(none)",
        )
