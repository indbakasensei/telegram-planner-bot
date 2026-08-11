"""
Tests for v15.2 M4 -- the Worker's robust structured-output parser
(core/ai/worker_parser.py).

The parser exists because the legacy extractor (baka_brain.clean_json) uses a
greedy `find("{") / rfind("}")` slice that silently corrupts output with more
than one JSON object -- the F1 failure class. These tests lock the fail-closed
contract: exactly ONE well-formed top-level object is accepted; zero, a bare
array, or MULTIPLE objects is an error, never a guess. No test here calls a
model, a registry, or a database.
"""
import pytest

from core.ai.worker_parser import WorkerParseError, extract_single_object, parse_decision
from core.ai.worker_contract import WorkerAction


# ── extraction: the one-object contract ───────────────────────────────────
def test_extract_bare_object():
    assert extract_single_object('{"action":"final","reply":"ok"}') == {
        "action": "final", "reply": "ok"}


def test_extract_json_fence():
    text = "```json\n{\"action\":\"final\",\"reply\":\"hi\"}\n```"
    assert extract_single_object(text)["action"] == "final"


def test_extract_plain_fence():
    text = "```\n{\"action\":\"tool\",\"tool\":\"list_tasks\"}\n```"
    assert extract_single_object(text)["action"] == "tool"


def test_extract_prose_wrapped():
    text = ("Here is my decision for you:\n"
            "{\"action\":\"final\",\"reply\":\"done\"}\n\n"
            "Regards, the assistant.")
    assert extract_single_object(text)["reply"] == "done"


def test_extract_nested_braces_in_values():
    text = '{"action":"tool","tool":"create_task","arguments":{"title":"a {b} c"}}'
    obj = extract_single_object(text)
    assert obj["arguments"]["title"] == "a {b} c"


def test_extract_escaped_quotes_in_values():
    text = r'{"action":"final","reply":"say \"hi\" to {x}"}'
    assert extract_single_object(text)["reply"] == 'say "hi" to {x}'


def test_extract_multiple_objects_is_error():
    # The F1 regression: two JSON objects MUST be rejected, never merged and
    # never "last one wins".
    text = '{"action":"tool","tool":"create_task"}{"action":"final","reply":"x"}'
    with pytest.raises(WorkerParseError, match="[Aa]mbiguous"):
        extract_single_object(text)


def test_extract_no_object_is_error():
    with pytest.raises(WorkerParseError):
        extract_single_object("the model just said hello")


def test_extract_top_level_array_is_error():
    with pytest.raises(WorkerParseError):
        extract_single_object('[{"action":"final","reply":"x"}]')


def test_extract_unbalanced_is_error():
    with pytest.raises(WorkerParseError):
        extract_single_object('{"action":"final","reply":"x"')  # missing close


def test_extract_empty_is_error():
    for bad in ("", "   ", "\n\t"):
        with pytest.raises(WorkerParseError):
            extract_single_object(bad)


# ── decision parsing: action ──────────────────────────────────────────────
def test_tool_decision_roundtrip():
    d = parse_decision('{"action":"tool","tool":"list_tasks","arguments":{}}')
    assert d.action is WorkerAction.TOOL
    assert d.tool_name == "list_tasks"
    assert d.arguments == {}


def test_tool_decision_without_arguments_defaults_empty():
    d = parse_decision('{"action":"tool","tool":"list_tasks"}')
    assert d.arguments == {}


def test_tool_decision_null_arguments_defaults_empty():
    d = parse_decision('{"action":"tool","tool":"list_tasks","arguments":null}')
    assert d.arguments == {}


def test_tool_decision_missing_tool_name_is_error():
    with pytest.raises(WorkerParseError):
        parse_decision('{"action":"tool","arguments":{}}')


def test_tool_decision_non_dict_arguments_is_error():
    with pytest.raises(WorkerParseError):
        parse_decision('{"action":"tool","tool":"list_tasks","arguments":[]}')


def test_final_decision_roundtrip():
    d = parse_decision('{"action":"final","reply":"Your tasks are listed."}')
    assert d.action is WorkerAction.FINAL
    assert d.reply == "Your tasks are listed."


def test_final_decision_non_string_reply_is_error():
    with pytest.raises(WorkerParseError):
        parse_decision('{"action":"final","reply":42}')


def test_decline_decision_roundtrip():
    d = parse_decision('{"action":"decline","reason":"chat"}')
    assert d.action is WorkerAction.DECLINE
    assert d.reason == "chat"


def test_decline_without_reason_ok():
    d = parse_decision('{"action":"decline"}')
    assert d.action is WorkerAction.DECLINE and d.reason is None


def test_missing_action_is_error():
    with pytest.raises(WorkerParseError):
        parse_decision('{"tool":"list_tasks"}')


def test_non_string_action_is_error():
    with pytest.raises(WorkerParseError):
        parse_decision('{"action":123}')


def test_unknown_action_is_error():
    with pytest.raises(WorkerParseError):
        parse_decision('{"action":"hack"}')


def test_action_case_insensitive():
    d = parse_decision('{"action":"FINAL","reply":"ok"}')
    assert d.action is WorkerAction.FINAL


# ── injection resistance ──────────────────────────────────────────────────
def test_tool_name_injection_inside_arguments_is_data():
    """A nested 'tool' key inside arguments must never shadow the decision's
    own tool name -- it is data the registry will validate, not a redirect."""
    text = ('{"action":"tool","tool":"list_tasks",'
            '"arguments":{"tool":"delete_everything","nested":{"action":"final"}}}')
    d = parse_decision(text)
    assert d.action is WorkerAction.TOOL
    assert d.tool_name == "list_tasks"          # the TOP-LEVEL tool wins
    assert d.arguments["tool"] == "delete_everything"  # and stays data


def test_embedded_instructions_are_not_decisions():
    """Instructions smuggled inside the JSON body ('ignore rules') are just
    an unknown top-level key -- ignored, not acted on."""
    d = parse_decision('{"action":"final","reply":"ok","ignore rules":true}')
    assert d.action is WorkerAction.FINAL and d.reply == "ok"
