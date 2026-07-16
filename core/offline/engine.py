"""
engine.py -- OfflineEngine: the production Offline Engine dispatcher.

v14.8 (ADR-012): execute() and execute_pending() are thin dispatchers
over an ActionRegistry (core/offline/registry.py). The if/elif intent
ladder this class grew across v14.2-v14.7 -- and all the dispatch
knowledge inside it (phrase tables, matcher precedence, argument
shapes) -- moved verbatim to core/offline/registrations.py. Adding an
Offline action no longer touches this file: register it there. The
staged history of what got added when (Stage 1 reads v14.2, creation
v14.3, update v14.4, delete v14.5, completion v14.6, lifecycle v14.7)
and WHY each entry point has the shape it does lives in
registrations.py, ADR-007..ADR-012, and CHANGELOG.md.

Dispatch semantics, byte-equivalent to the old ladder:

  registry.resolve(intent) == ()   -> "unsupported_intent" (this intent
                                      has no Offline implementation;
                                      main.py falls through to Legacy)
  specs exist, none match          -> "unsupported_action" (recognized
                                      intent, unrecognized text/entities;
                                      same Legacy fall-through)
  a spec matches                   -> its run() under exception
                                      containment; any raise becomes
                                      success=False with an
                                      action_exception:<Name> warning

Matchers run OUTSIDE the containment (pure inspection, must not raise;
if one ever does it propagates to main.py's fall-through-to-Legacy
handler, exactly where the old inline matcher calls sat -- see
ActionSpec's docstring).

continue_editing() stays a direct call, not a registry dispatch,
deliberately: it is state-gated rather than intent-gated (ADR-009) and
has exactly one possible target -- registering it would add indirection
with nothing to select between.

MUST NOT (and does not): call database.py directly (Storage Facade only,
core/storage/), call AI, call scheduler.py, import Telegram objects,
mutate conversation state, send replies, or perform any I/O beyond a
debug log line -- same constraints core/intent/ and core/routing/ already
operate under.
"""
from __future__ import annotations

import logging

from datetime import datetime

from core.actions import update_task
from core.offline.action_result import ActionResult
from core.offline.registrations import build_default_registry
from core.offline.registry import ActionRegistry
from core.offline.request_context import RequestContext
from core.storage import Storage

logger = logging.getLogger(__name__)


class OfflineEngine:
    """
    Thin dispatcher over an ActionRegistry (module docstring). Never
    raises for ordinary input, same discipline IntentEngine.classify()
    and RoutingLayer.route() already established. Tests may inject a
    custom registry; production uses build_default_registry().
    """

    def __init__(self, storage: Storage, registry: ActionRegistry | None = None):
        self._storage = storage
        self._registry = registry if registry is not None else build_default_registry()

    def execute(self, context: RequestContext) -> ActionResult:
        specs = self._registry.resolve(context.intent)
        if not specs:
            result = ActionResult(success=False, message="", warnings=["unsupported_intent"])
            self._log(context, result)
            return result

        for spec in specs:
            match_data = spec.match(context)
            if match_data is None:
                continue
            try:
                result = spec.run(context, self._storage, match_data)
            except Exception as exc:
                logger.exception("Offline Engine action execution failed")
                result = ActionResult(
                    success=False, message="",
                    warnings=[f"action_exception:{type(exc).__name__}"],
                )
            self._log(context, result)
            return result

        result = ActionResult(success=False, message="", warnings=["unsupported_action"])
        self._log(context, result)
        return result

    def continue_editing(self, text: str, task_id: int, user_id: int,
                          now: datetime) -> ActionResult:
        """
        Message 2 of the update flow: the change description, only
        called by main.py when conversation_state's state is already
        "editing" (set by a prior start_editing() result). Deliberately
        NOT routed through execute() -- Intent Engine classification of a
        bare "set time to 6pm" reply carries no reliable EDIT_TASK signal
        on its own (core/intent/rules.py has no notion of conversation
        state), so main.py checks state directly and calls this instead,
        mirroring how Legacy's own handle_message() prioritizes state
        over intent-based routing. Never raises.
        """
        try:
            result = update_task.apply_change(text, task_id, user_id, self._storage, now)
        except Exception as exc:
            logger.exception("Offline Engine update failed")
            result = ActionResult(
                success=False, message="",
                warnings=[f"update_exception:{type(exc).__name__}"],
            )
        logger.debug(
            "[Offline Update]\nUser:\n%s\nTask:\n%s\nText:\n%r\nSuccess:\n%s\nWarnings:\n%s",
            user_id, task_id, text, result.success, ", ".join(result.warnings) or "(none)",
        )
        return result

    def execute_pending(self, action_type: str, pending_data: dict, user_id: int) -> ActionResult:
        """
        Commits a previously-proposed write action after the user
        confirms (main.py's `confirming` state, "yes" reply). Separate
        from execute() deliberately: there's no fresh RequestContext at
        confirm time, just the pending_data dict main.py's integration
        point saved from a prior propose()'s ActionResult.metadata --
        see docs/adr/ADR-008-offline-write-operations.md. Never raises.
        """
        commit_fn = self._registry.resolve_pending(action_type)
        if commit_fn is None:
            return ActionResult(success=False, message="", warnings=["unknown_action_type"])
        try:
            result = commit_fn(pending_data, user_id, self._storage)
        except Exception as exc:
            logger.exception("Offline Engine commit failed")
            result = ActionResult(
                success=False, message="",
                warnings=[f"commit_exception:{type(exc).__name__}"],
            )
        logger.debug(
            "[Offline Commit]\nUser:\n%s\nAction:\n%s\nSuccess:\n%s\nWarnings:\n%s",
            user_id, action_type, result.success, ", ".join(result.warnings) or "(none)",
        )
        return result

    @staticmethod
    def _log(context: RequestContext, result: ActionResult) -> None:
        logger.debug(
            "[Offline]\nUser:\n%s\nText:\n%r\nSuccess:\n%s\nWarnings:\n%s",
            context.user_id, context.text, result.success,
            ", ".join(result.warnings) or "(none)",
        )
