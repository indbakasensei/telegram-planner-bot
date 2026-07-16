"""
Tests for core/offline/registry.py + core/offline/registrations.py --
the v14.8 registry-based dispatch (ADR-012).

Two layers under test:

1. ActionRegistry as pure mechanism (registration validation, duplicate
   detection, ordered resolve, pending commits) -- exercised with
   synthetic specs, no storage, no DB.
2. build_default_registry() as the production configuration -- pinning
   the registered intents, spec names, and ORDER (registration order is
   match precedence, registry.py's docstring: order is behavior, not
   style). If a refactor reorders EDIT_TASK's complete -> lifecycle ->
   update chain or QUERY_TASK's search-first rule, these tests fail
   before any behavioral test does.
3. OfflineEngine as a thin dispatcher over an injected registry --
   execution path, exception containment, and both fallback results
   (unsupported_intent for an unregistered intent, unsupported_action
   for a registered intent where no matcher accepts the text).

Behavioral equivalence of every real action is NOT re-proven here --
that's the existing per-action suites (test_offline_engine,
test_create_task, test_update_task, test_delete_task,
test_complete_task, test_lifecycle_task), all of which run against the
default registry through the same public OfflineEngine surface as
before the refactor.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from core.intent.intent_types import Intent
from core.offline.action_result import ActionResult
from core.offline.engine import OfflineEngine
from core.offline.registrations import build_default_registry
from core.offline.registry import ActionRegistry, ActionSpec, RegistryError
from core.offline.request_context import RequestContext
from core.storage import Storage

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 3, 4, 10, 0, tzinfo=IST)
UID = 555000111


def ctx(text, intent=Intent.QUERY_TASK, entities=None):
    return RequestContext(user_id=UID, text=text, intent=intent,
                           entities=entities or {}, now=NOW)


def _ok_spec(name="spec", match=None, run=None):
    return ActionSpec(
        name=name,
        match=match or (lambda context: True),
        run=run or (lambda context, storage, m: ActionResult(success=True, message="ok")),
    )


# ── ActionRegistry: registration + resolve ────────────────────────────────

def test_register_and_resolve_preserves_order():
    registry = ActionRegistry()
    first, second = _ok_spec("first"), _ok_spec("second")
    registry.register(Intent.QUERY_TASK, first)
    registry.register(Intent.QUERY_TASK, second)
    assert registry.resolve(Intent.QUERY_TASK) == (first, second)


def test_resolve_unknown_intent_returns_empty_tuple():
    registry = ActionRegistry()
    assert registry.resolve(Intent.CHAT) == ()


def test_duplicate_name_within_intent_is_rejected():
    registry = ActionRegistry()
    registry.register(Intent.QUERY_TASK, _ok_spec("dup"))
    with pytest.raises(RegistryError):
        registry.register(Intent.QUERY_TASK, _ok_spec("dup"))


def test_same_spec_under_multiple_intents_is_allowed():
    # The real registry does exactly this: EDIT_TASK and UNKNOWN share
    # complete/lifecycle/update (ADR-009's under-classification).
    registry = ActionRegistry()
    shared = _ok_spec("shared")
    registry.register(Intent.EDIT_TASK, shared)
    registry.register(Intent.UNKNOWN, shared)
    assert registry.resolve(Intent.EDIT_TASK) == (shared,)
    assert registry.resolve(Intent.UNKNOWN) == (shared,)


@pytest.mark.parametrize("bad_spec", [
    "not a spec",
    None,
    42,
])
def test_non_actionspec_registration_is_rejected(bad_spec):
    with pytest.raises(RegistryError):
        ActionRegistry().register(Intent.QUERY_TASK, bad_spec)


def test_non_intent_key_is_rejected():
    with pytest.raises(RegistryError):
        ActionRegistry().register("QUERY_TASK", _ok_spec())


def test_empty_name_is_rejected():
    with pytest.raises(RegistryError):
        ActionRegistry().register(Intent.QUERY_TASK, _ok_spec(name=""))


def test_non_callable_match_or_run_is_rejected():
    with pytest.raises(RegistryError):
        ActionRegistry().register(
            Intent.QUERY_TASK,
            ActionSpec(name="bad", match="nope", run=lambda c, s, m: None),
        )
    with pytest.raises(RegistryError):
        ActionRegistry().register(
            Intent.QUERY_TASK,
            ActionSpec(name="bad", match=lambda c: True, run="nope"),
        )


def test_intents_introspection():
    registry = ActionRegistry()
    registry.register(Intent.QUERY_TASK, _ok_spec())
    registry.register(Intent.ADD_TASK, _ok_spec())
    assert registry.intents() == frozenset({Intent.QUERY_TASK, Intent.ADD_TASK})


# ── ActionRegistry: pending commits ───────────────────────────────────────

def test_register_and_resolve_pending():
    registry = ActionRegistry()
    commit = lambda pending, user_id, storage: ActionResult(success=True, message="")
    registry.register_pending("offline_x", commit)
    assert registry.resolve_pending("offline_x") is commit
    assert registry.pending_types() == frozenset({"offline_x"})


def test_resolve_pending_unknown_returns_none():
    assert ActionRegistry().resolve_pending("nope") is None


def test_duplicate_pending_registration_is_rejected():
    registry = ActionRegistry()
    registry.register_pending("offline_x", lambda p, u, s: None)
    with pytest.raises(RegistryError):
        registry.register_pending("offline_x", lambda p, u, s: None)


def test_invalid_pending_registration_is_rejected():
    with pytest.raises(RegistryError):
        ActionRegistry().register_pending("", lambda p, u, s: None)
    with pytest.raises(RegistryError):
        ActionRegistry().register_pending("offline_x", "not callable")


# ── build_default_registry(): production configuration pins ─────────────

def test_default_registry_intents():
    registry = build_default_registry()
    assert registry.intents() == frozenset({
        Intent.QUERY_TASK, Intent.ADD_TASK, Intent.EDIT_TASK,
        Intent.UNKNOWN, Intent.DELETE_TASK,
    })
    assert registry.pending_types() == frozenset({
        "offline_add_task", "offline_delete_task",
    })


def test_default_query_task_order_search_first():
    # Search MUST be checked before the exact-phrase sets (prefix match
    # vs whole-message match); the rest are disjoint but the order is
    # pinned anyway -- reordering should be a deliberate act.
    names = [s.name for s in build_default_registry().resolve(Intent.QUERY_TASK)]
    assert names == ["search_tasks", "today_tasks", "week_tasks",
                     "list_tasks", "paused_list"]


def test_default_edit_task_order_complete_lifecycle_update():
    registry = build_default_registry()
    names = [s.name for s in registry.resolve(Intent.EDIT_TASK)]
    assert names == ["complete_task", "lifecycle_task", "update_task"]
    # UNKNOWN shares the same spec objects, same order (ADR-009).
    assert registry.resolve(Intent.UNKNOWN) == registry.resolve(Intent.EDIT_TASK)


def test_default_delete_matcher_reads_entities_not_text():
    registry = build_default_registry()
    (spec,) = registry.resolve(Intent.DELETE_TASK)
    assert spec.match(ctx("delete task 5", Intent.DELETE_TASK, {"task_id": 5})) == 5
    assert spec.match(ctx("delete this", Intent.DELETE_TASK)) is None


def test_default_add_matcher_always_matches():
    # No text pre-filter on ADD_TASK -- create_task.propose() itself
    # rejects non-create phrasings (not_a_create_command), same as the
    # old ladder.
    registry = build_default_registry()
    (spec,) = registry.resolve(Intent.ADD_TASK)
    assert spec.match(ctx("anything at all", Intent.ADD_TASK)) is not None


# ── OfflineEngine as thin dispatcher (injected registry) ─────────────────

def test_engine_dispatches_via_injected_registry():
    registry = ActionRegistry()
    seen = {}

    def match(context):
        return ("parsed", context.text)

    def run(context, storage, match_data):
        seen["match_data"] = match_data
        return ActionResult(success=True, message="ran")

    registry.register(Intent.QUERY_TASK, ActionSpec("probe", match, run))
    engine = OfflineEngine(Storage(), registry=registry)
    result = engine.execute(ctx("hello"))
    assert result.success is True
    assert result.message == "ran"
    assert seen["match_data"] == ("parsed", "hello")


def test_engine_first_matching_spec_wins():
    registry = ActionRegistry()
    registry.register(Intent.QUERY_TASK, ActionSpec(
        "never", lambda c: None,
        lambda c, s, m: ActionResult(success=True, message="wrong")))
    registry.register(Intent.QUERY_TASK, ActionSpec(
        "always", lambda c: True,
        lambda c, s, m: ActionResult(success=True, message="right")))
    engine = OfflineEngine(Storage(), registry=registry)
    assert engine.execute(ctx("x")).message == "right"


def test_engine_unregistered_intent_is_unsupported_intent():
    engine = OfflineEngine(Storage(), registry=ActionRegistry())
    result = engine.execute(ctx("list"))
    assert result.success is False
    assert "unsupported_intent" in result.warnings


def test_engine_no_matching_spec_is_unsupported_action():
    registry = ActionRegistry()
    registry.register(Intent.QUERY_TASK, _ok_spec("never", match=lambda c: None))
    engine = OfflineEngine(Storage(), registry=registry)
    result = engine.execute(ctx("list"))
    assert result.success is False
    assert "unsupported_action" in result.warnings


def test_engine_contains_run_exceptions():
    registry = ActionRegistry()

    def boom(context, storage, match_data):
        raise RuntimeError("boom")

    registry.register(Intent.QUERY_TASK, ActionSpec("boom", lambda c: True, boom))
    engine = OfflineEngine(Storage(), registry=registry)
    result = engine.execute(ctx("x"))
    assert result.success is False
    assert "action_exception:RuntimeError" in result.warnings


def test_engine_execute_pending_via_registry():
    registry = ActionRegistry()
    registry.register_pending(
        "offline_probe",
        lambda pending, user_id, storage: ActionResult(
            success=True, message=f"{pending['k']}:{user_id}"),
    )
    engine = OfflineEngine(Storage(), registry=registry)
    result = engine.execute_pending("offline_probe", {"k": "v"}, UID)
    assert result.success is True
    assert result.message == f"v:{UID}"


def test_engine_execute_pending_unknown_type():
    engine = OfflineEngine(Storage(), registry=ActionRegistry())
    result = engine.execute_pending("nope", {}, UID)
    assert result.success is False
    assert "unknown_action_type" in result.warnings


def test_engine_defaults_to_default_registry():
    # No registry injected -> build_default_registry(); "habits" is
    # QUERY_TASK but matches no spec -> unsupported_action, identical
    # to pre-v14.8 behavior.
    engine = OfflineEngine(Storage())
    result = engine.execute(ctx("habits"))
    assert result.success is False
    assert "unsupported_action" in result.warnings
