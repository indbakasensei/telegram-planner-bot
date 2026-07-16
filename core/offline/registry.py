"""
registry.py -- ActionRegistry: registration-based dispatch for the
Offline Engine (v14.8, ADR-012).

Replaces the if/elif intent ladder that OfflineEngine.execute() grew
across v14.2-v14.7 (flagged in RC_v14_ARCHITECTURE_VALIDATION.md's
Offline Engine Review as the one Open/Closed ceiling in core/). The
registry itself is pure mechanism: it knows nothing about Tasks, Habits,
or any concrete action -- all real registrations live in
core/offline/registrations.py (explicit, no reflection, no dynamic
imports, no import-time side-effect registration; see ADR-012 for why
a single explicit registration module was chosen over decorators).

Dispatch model -- deliberately NOT a flat `intent -> one action` map,
because the shipped Intent Engine is coarser than the action set
(QUERY_TASK covers list/today/week/search/paused and more; EDIT_TASK
covers complete/lifecycle/update; see engine.py's dispatch note):

    resolve(intent)  -> ordered tuple of ActionSpecs (O(1) dict lookup)
    spec.match(ctx)  -> match data, or None to try the next spec
    spec.run(...)    -> ActionResult

Registration order within an intent IS the match-precedence order --
identical semantics to the ladder it replaces, so registration order
in registrations.py is behavior, not style.

Registration-time validation raises RegistryError (a programming error
surfaced at startup, never per-message); dispatch-time lookups never
raise -- resolve() returns () and resolve_pending() returns None for
anything unregistered, and OfflineEngine maps those to the same
"unsupported_intent"/"unknown_action_type" ActionResults as before.

Same constraints as the rest of core/offline/: no database.py, no
Telegram, no AI, no I/O.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, TYPE_CHECKING

from core.intent.intent_types import Intent
from core.offline.action_result import ActionResult
from core.offline.request_context import RequestContext

if TYPE_CHECKING:
    from core.storage import Storage


class RegistryError(ValueError):
    """Invalid or duplicate registration -- raised at registry-build
    time (application startup / test setup), never during message
    dispatch."""


@dataclass(frozen=True, slots=True)
class ActionSpec:
    """One registerable Offline action.

    `match` inspects the RequestContext and returns the parsed match
    data (task_id int, (operation, args) tuple, or just True for
    phrase-table actions) -- or None, meaning "not mine, try the next
    spec". `run` receives that match data back, so the parse isn't
    repeated. The None-means-no-match convention requires that no
    matcher ever produces None as legitimate match data (none does:
    task ids are >= 1, tuples and True are non-None).

    match runs OUTSIDE the engine's exception containment (a matcher is
    pure string/dict inspection and must not raise; if one ever does,
    it propagates to main.py's outer fall-through-to-Legacy handler --
    exactly where the old ladder's inline matcher calls sat). run runs
    INSIDE it, converted to action_exception:<Name> warnings.
    """
    name: str
    match: Callable[[RequestContext], Any]
    run: Callable[[RequestContext, "Storage", Any], ActionResult]


@dataclass(slots=True)
class ActionRegistry:
    """The single source of Offline dispatch (ADR-012).

    Two tables, matching the engine's two dispatch entry points:
    intent specs (execute()) and pending-commit callables
    (execute_pending(), the confirm-step second half of ADR-008's
    propose/commit writes). continue_editing() stays outside the
    registry deliberately -- it is state-gated, not intent-gated
    (ADR-009), and has exactly one possible target.
    """
    _specs: dict[Intent, tuple[ActionSpec, ...]] = field(default_factory=dict)
    _pending: dict[str, Callable[[dict, int, "Storage"], ActionResult]] = field(default_factory=dict)

    def register(self, intent: Intent, spec: ActionSpec) -> None:
        """Append `spec` to `intent`'s ordered spec tuple.

        The same spec object may be registered under several intents
        (EDIT_TASK and UNKNOWN share all three of complete/lifecycle/
        update -- the under-classification pattern ADR-009 documents).
        A duplicate name within ONE intent is always a bug: it would
        silently shadow or dead-letter one of the two."""
        if not isinstance(intent, Intent):
            raise RegistryError(f"intent must be an Intent member, got {intent!r}")
        if not isinstance(spec, ActionSpec):
            raise RegistryError(f"spec must be an ActionSpec, got {type(spec).__name__}")
        if not spec.name or not isinstance(spec.name, str):
            raise RegistryError("ActionSpec.name must be a non-empty string")
        if not callable(spec.match) or not callable(spec.run):
            raise RegistryError(f"ActionSpec {spec.name!r}: match and run must be callable")
        existing = self._specs.get(intent, ())
        if any(s.name == spec.name for s in existing):
            raise RegistryError(
                f"duplicate registration: {spec.name!r} already registered for {intent.name}"
            )
        self._specs[intent] = existing + (spec,)

    def resolve(self, intent: Intent) -> tuple[ActionSpec, ...]:
        """All specs for `intent` in registration (= precedence) order;
        () if the intent has no Offline implementation. O(1): returns
        the stored tuple, no per-call construction."""
        return self._specs.get(intent, ())

    def register_pending(self, action_type: str,
                          commit: Callable[[dict, int, "Storage"], ActionResult]) -> None:
        """Register the commit half of a propose/commit write (ADR-008).
        `action_type` is the conversation-state pending-action key
        main.py stores at propose time ("offline_add_task", ...)."""
        if not action_type or not isinstance(action_type, str):
            raise RegistryError("action_type must be a non-empty string")
        if not callable(commit):
            raise RegistryError(f"pending {action_type!r}: commit must be callable")
        if action_type in self._pending:
            raise RegistryError(f"duplicate pending registration: {action_type!r}")
        self._pending[action_type] = commit

    def resolve_pending(self, action_type: str) -> Callable[[dict, int, "Storage"], ActionResult] | None:
        """The registered commit callable, or None if unknown -- the
        engine maps None to the same 'unknown_action_type' result the
        old inline check produced."""
        return self._pending.get(action_type)

    def intents(self) -> frozenset[Intent]:
        """Intents with at least one registered spec -- introspection
        for tests and, later, for populating routing_matrix.py's
        OFFLINE_ENGINE_IMPLEMENTED_INTENTS from the registry instead of
        by hand (Phase 2 of the Legacy Removal Plan)."""
        return frozenset(self._specs)

    def pending_types(self) -> frozenset[str]:
        """Registered pending-commit action_type keys (introspection)."""
        return frozenset(self._pending)
