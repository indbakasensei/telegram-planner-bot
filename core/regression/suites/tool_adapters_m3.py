"""Quick Release Suite: v15.2 M3 — Real Tool Adapters.

The M3 adapter surface (core/ai/tool_adapters.py) is backend-only: no user
command routes through it yet (the AI Worker is a LATER milestone), so these
specs verify the ADAPTERS' health from the live app rather than a Telegram
walk -- each spec's steps are the offline pytest run that owns the exhaustive
coverage (tests/test_tool_adapters.py) plus a `/selftest → AI → 'AI Tool
Adapter …'` probe. They exist so a live-Telegram regression pass also
re-verifies that the real, thin, projection-preserving adapters the future
Worker will build on are still intact.
"""
from core.regression.models import (
    Priority, RegressionTest, ScenarioClass, Suite,
)
from core.regression.registry import register

_QUICK = frozenset({Suite.QUICK})
_MED = Priority.MEDIUM
_HIGH = Priority.HIGH


def _t(**kw):
    register(RegressionTest(**kw))


_t(
    test_id="TAD-001", category="AI", feature="AI Tool Adapter",
    introduced_version="v15.1.0-alpha.13", priority=_HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=10, suites=_QUICK,
    objective="build_tool_registry() registers the complete M3 surface -- the "
              "24 task/habit/goal/entity/workspace/memory adapters -- under the "
              "M2 ToolRegistry with honest risk classifications (every write "
              "tool MUTATING incl. open_workspace, delete_task DESTRUCTIVE, "
              "nothing SYSTEM).",
    preconditions="Offline (no Telegram needed).",
    steps=("Run: python -m pytest tests/test_tool_adapters.py -q "
           "(test_risk_classification, test_registry_rejects_duplicate_names)",
           "Run /selftest → AI → 'AI Tool Adapter Registry'"),
    expected=("All 24 tool names are registered exactly once",
              "Risks are honest: writes are never READ_ONLY, "
              "delete_task is DESTRUCTIVE, no SYSTEM tool",
              "The self-test probe passes"),
    failure_conditions=("A tool name is missing or duplicated",
                        "A write tool is classified READ_ONLY",
                        "A second registry / second ToolResult was introduced",
                        "The self-test probe fails"),
    notes="Same contract decisions as M2 (TLC-001): one abstraction, no second "
          "registry. open_workspace is MUTATING because it persists active "
          "state (v15.2 M3 reclassification).",
)

_t(
    test_id="TAD-002", category="AI", feature="AI Tool Adapter",
    introduced_version="v15.1.0-alpha.13", priority=_HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=10, suites=_QUICK,
    objective="Entity create/update drive the SAME alpha.13 projection "
              "contract /add and NL creation use: create_entity ensures ONE "
              "topic + initial card, update_entity appends ONE activity "
              "message to that same topic -- the adapters never bypass or "
              "duplicate the Telegram-topic mechanism.",
    preconditions="Offline; a fake Telegram client + TelegramProjection.",
    steps=("Run: python -m pytest tests/test_tool_adapters.py -q "
           "(test_end_to_end_projection_with_real_client, "
           "test_entity_create_projects_topic_via_single_contract, "
           "test_entity_update_projects_to_topic_append_only)",
           "Run /selftest → AI → 'AI Tool Adapter Round-trip'"),
    expected=("create_entity posts the real initial card into a new topic",
              "update_entity posts the real append-only change summary to the "
              "existing topic (no second topic)",
              "A topic-creation failure is reported (mirrors /add); an "
              "update-post failure is best-effort (DB stands)",
              "The self-test probe passes"),
    failure_conditions=("create_entity does not ensure a topic when a "
                        "projection is wired",
                        "update_entity creates a second topic or bypasses "
                        "post_entity_update",
                        "A projection failure corrupts the DB write",
                        "The self-test probe fails"),
    notes="alpha.13 projection path preserved intact (see docs/engineering/"
          "V15_2_BAKA_BRAIN.md §M3).",
)

_t(
    test_id="TAD-003", category="AI", feature="AI Tool Adapter",
    introduced_version="v15.1.0-alpha.13", priority=_HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=10, suites=_QUICK,
    objective="Task + habit + goal read/write round-trips return structured "
              "data (ids, fields, statuses, the reminder surface = "
              "due_date/due_time) and mirror the live handlers: duplicate "
              "tasks rejected, invalid datetimes rejected, complete "
              "takes the habit branch for habit ids, goal progress clamps and "
              "reports completion.",
    preconditions="Offline.",
    steps=("Run: python -m pytest tests/test_tool_adapters.py -q "
           "(test_task_* test_habit_* test_goal_* sections)",
           "Run /selftest → AI → 'AI Tool Adapter Round-trip'"),
    expected=("create/list/find/update/complete/delete_task each return "
              "structured ToolResults",
              "The reminder surface is exposed as due_date/due_time on task "
              "data",
              "complete_task on a habit id logs the habit (streak) -- the "
              "same branch /done takes",
              "The self-test probe passes"),
    failure_conditions=("A task write returns formatted text with no "
                        "machine-readable data",
                        "complete_task does not branch to habit completion",
                        "A duplicate task is created instead of rejected",
                        "The self-test probe passes false-negative"),
    notes="No separate reminders tool: reminders ARE task due-times. No "
          "update_habit tool (database.py has none).",
)

_t(
    test_id="TAD-004", category="AI", feature="AI Tool Adapter",
    introduced_version="v15.1.0-alpha.13", priority=_MED,
    scenario=ScenarioClass.NORMAL, estimated_seconds=10, suites=_QUICK,
    objective="Entity reference resolution REUSES the M1 ReferenceResolver "
              "(a pronoun resolves to the active entity, never reimplemented), "
              "and memory/recall reads are grounded in stored data.",
    preconditions="Offline.",
    steps=("Run: python -m pytest tests/test_tool_adapters.py -q "
           "(test_entity_conversational_reference_resolves, test_memory_reads, "
           "test_recall_grounded_in_stored_data, test_entity_find_by_keyword)"),
    expected=("A conversational reference like 'her' resolves to the active "
              "entity via the M1 resolver",
              "get_memories / search_memories / recall return real stored "
              "values, and a miss returns an empty result, not an error",
              "A READ_ONLY get_entity does not move the persisted active "
              "entity"),
    failure_conditions=("Reference resolution was reimplemented instead of "
                        "reused",
                        "A read tool mutates active state",
                        "recall invents data that is not stored"),
    notes="M1 resolver/context are shared, not copied (no duplicate resolver "
          "logic).",
)

_t(
    test_id="TAD-005", category="AI", feature="AI Tool Adapter",
    introduced_version="v15.1.0-alpha.13", priority=_HIGH,
    scenario=ScenarioClass.INVALID, estimated_seconds=10, suites=_QUICK,
    objective="Adversarial robustness: invalid arguments are rejected before "
              "a handler runs (unknown args on write tools, missing targets, "
              "empty update sets, bad field values), execute() never raises on "
              "an ordinary input matrix, and read tools silently drop unknown "
              "args.",
    preconditions="Offline.",
    steps=("Run: python -m pytest tests/test_tool_adapters.py -q "
           "(test_mutating_tool_rejects_unknown_arg, "
           "test_readonly_tool_drops_unknown_arg, test_missing_targets*, "
           "test_entity_invalid_field_value_rejected, "
           "test_registry_execute_never_raises, test_delete_task_carries_*)"),
    expected=("Every invalid call returns ok=False with the stable "
              "error_code 'invalid_args' (or 'internal' for an unexpected "
              "exception)",
              "delete_task carries a confirmation_message",
              "registry.execute never raises on the adversarial matrix",
              "A read's unknown arg is dropped, not rejected"),
    failure_conditions=("An invalid call reaches a handler's run()",
                        "execute() raises instead of returning a ToolResult",
                        "A failure is reported as ok=True"),
    notes="Not-found targets classify as invalid_args (M2's code set has no "
          "separate not_found code yet).",
)
