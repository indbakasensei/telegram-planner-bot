"""Quick Release Suite: v15.2 M2 — AI Tool Contract Foundation.

The tool contract (core/ai/tools.py) is backend-only: no user command routes
through it yet (the AI Worker is a LATER milestone), so these specs verify the
CONTRACT's health from the live app rather than a Telegram walk — each spec's
steps are the offline pytest run that owns the exhaustive coverage
(tests/test_tool_contract.py) plus a `/selftest → AI → 'AI Tool Contract'`
probe. They exist so a live-Telegram regression pass also re-verifies that the
contract the Worker will build on is still intact.
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
    test_id="TLC-001", category="AI", feature="AI Tool Contract",
    introduced_version="v15.1.0-alpha.13", priority=_HIGH,
    scenario=ScenarioClass.INVALID, estimated_seconds=10, suites=_QUICK,
    objective="Registration validates specs and rejects duplicates — a "
              "malformed ToolSpec or a second tool with the same name is "
              "refused loudly, never silently replacing.",
    preconditions="Offline (no Telegram needed); repo on the v15.2 M2 branch.",
    steps=("Run: python -m pytest tests/test_tool_contract.py -q "
           "(A + F sections)",
           "Run /selftest → AI → 'AI Tool Contract'"),
    expected=("The offline suite reports the malformed-schema and "
              "duplicate-name rejection tests green",
              "The self-test probe passes (register → validate → execute → "
              "contain OK)"),
    failure_conditions=("A malformed spec is registered silently",
                        "A duplicate name replaces the existing tool",
                        "The self-test probe fails"),
    notes="Duplicate-name detection supersedes the pre-M2 idempotent-replace "
          "semantics (intentional contract change).",
)

_t(
    test_id="TLC-002", category="AI", feature="AI Tool Contract",
    introduced_version="v15.1.0-alpha.13", priority=_HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=10, suites=_QUICK,
    objective="A registered tool executes through the registry with valid "
              "arguments and returns an ok ToolResult.",
    preconditions="Offline.",
    steps=("Run: python -m pytest tests/test_tool_contract.py -q "
           "(B1/B13, F8, G1)",
           "Run /selftest → AI → 'AI Tool Contract'"),
    expected=("Valid args reach run() and the result is ok=True",
              "The registry.execute round-trip passes"),
    failure_conditions=("Valid args are rejected",
                        "execute() raises instead of returning a ToolResult"),
)

_t(
    test_id="TLC-003", category="AI", feature="AI Tool Contract",
    introduced_version="v15.1.0-alpha.13", priority=_HIGH,
    scenario=ScenarioClass.INVALID, estimated_seconds=10, suites=_QUICK,
    objective="Invalid arguments never reach a handler — wrong types, missing "
              "required args, bad enums, and unknown args on write tools are "
              "all refused before run().",
    preconditions="Offline.",
    steps=("Run: python -m pytest tests/test_tool_contract.py -q "
           "(B2–B9/B11/B12/B14/B15, G2)"),
    expected=("Every invalid-args case returns ok=False with the stable "
              "error_code 'invalid_args'",
              "The fake tool's run() is never invoked on an invalid call"),
    failure_conditions=("run() is reached with invalid arguments",
                        "A tool returns ok=True for schema-invalid input"),
)

_t(
    test_id="TLC-004", category="AI", feature="AI Tool Contract",
    introduced_version="v15.1.0-alpha.13", priority=_MED,
    scenario=ScenarioClass.RECOVERY, estimated_seconds=10, suites=_QUICK,
    objective="Tool failures are contained — a ToolError keeps its stable "
              "code and message; any other exception becomes an 'internal' "
              "result; nothing escapes to a caller.",
    preconditions="Offline.",
    steps=("Run: python -m pytest tests/test_tool_contract.py -q (D2/D5/E, "
           "G6/G7)"),
    expected=("A ToolError from run() is returned as ok=False with its code",
              "A RuntimeError is contained as error_code 'internal'",
              "registry.execute never raises on an ordinary input matrix"),
    failure_conditions=("An exception escapes execute()",
                        "A failure is reported as ok=True"),
)
