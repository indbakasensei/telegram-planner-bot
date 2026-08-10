"""v15.2 M2 -- Tool Contract Foundation tests (core/ai/tools.py).

Comprehensive contract coverage, A-G plus adversarial inputs:
  A. ToolSchema     -- valid/invalid specs, duplicate names, malformed schema
  B. Argument validation -- required, types, enum, unknown, nested, null
  C. Risk behaviour -- RiskLevel classification + strict unknown-arg handling
  D. ToolResult     -- success/failure, structured data, warnings
  E. ToolError      -- stable code + human message
  F. ToolRegistry   -- register/get/has/all/names/specs/openai_tools/execute
  G. Execution contract -- valid runs, invalid never reaches run(), containment

All offline: no network, no SDK, no Telegram.
"""
import pytest

from core.ai.tools import (
    RiskLevel, Tool, ToolError, ToolErrorCode, ToolRegistry, ToolRegistryError,
    ToolResult, ToolSpec, validate_args, validate_spec,
)


# ── helpers ────────────────────────────────────────────────────────────────

_DEFAULT_PARAMS = {
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "n": {"type": "integer"},
        "status": {"type": "string", "enum": ["a", "b"]},
        "nested": {"type": "object",
                   "properties": {"x": {"type": "integer"}},
                   "required": ["x"]},
    },
    "required": ["text"],
}


def _spec(name="demo", description="A demo tool",
          parameters=None, **kw) -> ToolSpec:
    return ToolSpec(
        name=name, description=description,
        parameters=_DEFAULT_PARAMS if parameters is None else parameters,
        **kw)


class _Fake(Tool):
    """A fake tool: spec fixed at construction; records every run() call so
    tests can assert whether (and with what) a handler was reached."""

    def __init__(self, spec=None, impl=None):
        self._spec = spec or _spec(parameters=_DEFAULT_PARAMS)
        self._impl = impl or (lambda **kw: f"ran:{sorted(kw)}")
        self.calls: list[dict] = []

    @property
    def spec(self) -> ToolSpec:
        return self._spec

    def run(self, **kwargs) -> str:
        self.calls.append(kwargs)
        return self._impl(**kwargs)


def _registry(*tools) -> ToolRegistry:
    reg = ToolRegistry()
    for t in tools:
        reg.register(t)
    return reg


# ── A. ToolSchema ─────────────────────────────────────────────────────────

def test_a_valid_spec_registers_and_openai_shape():
    spec = _spec(name="echo", description="Echo text",
                 parameters={"type": "object",
                             "properties": {"text": {"type": "string"}}})
    reg = _registry(_Fake(spec))
    assert reg.has("echo")
    o = spec.to_openai()
    assert o == {"type": "function",
                 "function": {"name": "echo",
                              "description": "Echo text",
                              "parameters": {"type": "object",
                                             "properties": {"text": {"type": "string"}}}}}


def test_a_missing_name_rejected():
    with pytest.raises(ToolRegistryError):
        validate_spec(_spec(name="", description="d"))
    with pytest.raises(ToolRegistryError):
        validate_spec(_spec(name="  ", description="d"))


def test_a_empty_description_rejected():
    with pytest.raises(ToolRegistryError):
        validate_spec(_spec(description=""))


def test_a_parameters_not_a_dict_rejected():
    with pytest.raises(ToolRegistryError):
        validate_spec(_spec(parameters=["object"]))


def test_a_top_level_type_not_object_rejected():
    with pytest.raises(ToolRegistryError):
        validate_spec(_spec(parameters={"type": "array", "items": {}}))


def test_a_required_references_undefined_property_rejected():
    params = {"type": "object", "properties": {"a": {"type": "string"}},
              "required": ["ghost"]}
    with pytest.raises(ToolRegistryError):
        validate_spec(_spec(parameters=params))


def test_a_property_schema_not_a_dict_rejected():
    with pytest.raises(ToolRegistryError):
        validate_spec(_spec(parameters={"type": "object",
                                        "properties": {"p": "nope"}}))


def test_a_unsupported_property_type_rejected():
    with pytest.raises(ToolRegistryError):
        validate_spec(_spec(parameters={"type": "object",
                                        "properties": {"p": {"type": "blob"}}}))
    with pytest.raises(ToolRegistryError):
        validate_spec(_spec(parameters={"type": "object",
                                        "properties": {"p": {"type": ["string", 42]}}}))


def test_a_empty_property_type_list_rejected():
    with pytest.raises(ToolRegistryError):
        validate_spec(_spec(parameters={"type": "object",
                                        "properties": {"p": {"type": []}}}))


def test_a_enum_not_a_list_rejected():
    with pytest.raises(ToolRegistryError):
        validate_spec(_spec(parameters={"type": "object",
                                        "properties": {"p": {"type": "string",
                                                             "enum": "ab"}}}))


def test_a_nested_object_valid_and_invalid():
    good = {"type": "object",
            "properties": {"meta": {"type": "object",
                                    "properties": {"x": {"type": "integer"}},
                                    "required": ["x"]}}}
    validate_spec(_spec(parameters=good))  # no raise
    bad = {"type": "object",
           "properties": {"meta": {"type": "object",
                                   "properties": {"x": {"type": "integer"}},
                                   "required": ["ghost"]}}}
    with pytest.raises(ToolRegistryError):
        validate_spec(_spec(parameters=bad))


def test_a_risk_must_be_risklevel():
    with pytest.raises(ToolRegistryError):
        validate_spec(_spec(risk="mutating"))
    validate_spec(_spec(risk=RiskLevel.DESTRUCTIVE))  # no raise


def test_a_confirmation_message_must_be_str_or_none():
    with pytest.raises(ToolRegistryError):
        validate_spec(_spec(confirmation_message=123))
    validate_spec(_spec(confirmation_message="Really?"))


def test_a_requires_admin_must_be_bool():
    with pytest.raises(ToolRegistryError):
        validate_spec(_spec(requires_admin="yes"))
    validate_spec(_spec(requires_admin=True))


def test_a_duplicate_name_rejected_at_register():
    reg = _registry(_Fake(_spec(name="dup")))
    with pytest.raises(ToolRegistryError):
        reg.register(_Fake(_spec(name="dup")))


# ── B. Argument validation ────────────────────────────────────────────────

def test_b_valid_args_execute():
    fake = _Fake()
    r = fake.execute(text="hi", n=3)
    assert r.ok and r.output == "ran:['n', 'text']"
    assert fake.calls == [{"text": "hi", "n": 3}]


def test_b_missing_required_rejected_and_handler_not_called():
    fake = _Fake()
    r = fake.execute(n=3)
    assert not r.ok
    assert r.error_code == ToolErrorCode.INVALID_ARGS
    assert "text" in r.output
    assert fake.calls == []          # never reached run()


def test_b_wrong_type_rejected():
    fake = _Fake()
    r = fake.execute(text="hi", n="three")
    assert not r.ok and r.error_code == ToolErrorCode.INVALID_ARGS
    assert fake.calls == []


def test_b_invalid_enum_rejected():
    fake = _Fake()
    r = fake.execute(text="hi", status="zzz")
    assert not r.ok and r.error_code == ToolErrorCode.INVALID_ARGS
    assert "one of" in r.output
    assert fake.calls == []


def test_b_valid_enum_accepted():
    fake = _Fake()
    r = fake.execute(text="hi", status="b")
    assert r.ok and fake.calls == [{"text": "hi", "status": "b"}]


def test_b_unknown_arg_dropped_for_read_only():
    fake = _Fake()                              # default risk READ_ONLY
    r = fake.execute(text="hi", bogus=1)
    assert r.ok
    assert fake.calls == [{"text": "hi"}]       # unknown never reached handler


def test_b_unknown_arg_rejected_for_mutating():
    fake = _Fake(_spec(risk=RiskLevel.MUTATING))
    r = fake.execute(text="hi", bogus=1)
    assert not r.ok and r.error_code == ToolErrorCode.INVALID_ARGS
    assert "bogus" in r.output
    assert fake.calls == []


def test_b_nested_object_validated_recursively():
    fake = _Fake()
    r = fake.execute(text="hi", nested={"x": 5})
    assert r.ok and fake.calls == [{"text": "hi", "nested": {"x": 5}}]


def test_b_nested_missing_required_rejected():
    fake = _Fake()
    r = fake.execute(text="hi", nested={})
    assert not r.ok and r.error_code == ToolErrorCode.INVALID_ARGS
    assert fake.calls == []


def test_b_nested_unknown_key_rejected_for_strict():
    fake = _Fake(_spec(risk=RiskLevel.MUTATING))
    r = fake.execute(text="hi", nested={"x": 5, "junk": 1})
    assert not r.ok and r.error_code == ToolErrorCode.INVALID_ARGS
    assert "junk" in r.output
    assert fake.calls == []


def test_b_optional_argument_omitted_is_ok():
    fake = _Fake()
    r = fake.execute(text="hi")
    assert r.ok and fake.calls == [{"text": "hi"}]


def test_b_null_rejected_for_plain_string():
    fake = _Fake()
    r = fake.execute(text=None)
    assert not r.ok and r.error_code == ToolErrorCode.INVALID_ARGS
    assert "null" in r.output
    assert fake.calls == []


def test_b_null_accepted_when_schema_allows():
    spec = _spec(parameters={"type": "object",
                             "properties": {"x": {"type": ["string", "null"]}}})
    fake = _Fake(spec)
    assert fake.execute(x=None).ok
    assert fake.execute(x="hi").ok
    assert fake.calls == [{"x": None}, {"x": "hi"}]


def test_b_bool_is_not_an_integer():
    fake = _Fake()
    r = fake.execute(text="hi", n=True)
    assert not r.ok and r.error_code == ToolErrorCode.INVALID_ARGS
    assert fake.calls == []


def test_b_integer_rejects_float_number_accepts_int_and_float():
    spec = _spec(parameters={"type": "object",
                             "properties": {
                                 "i": {"type": "integer"},
                                 "f": {"type": "number"}}})
    fake = _Fake(spec)
    assert not fake.execute(i=3.5).ok
    assert fake.execute(i=3, f=3.5).ok
    assert fake.execute(i=3, f=4).ok


def test_b_min_length_enforced():
    spec = _spec(parameters={"type": "object",
                             "properties": {"p": {"type": "string",
                                                  "minLength": 3}}})
    fake = _Fake(spec)
    assert not fake.execute(p="ab").ok
    assert fake.execute(p="abc").ok


def test_b_empty_string_allowed_when_no_min_length():
    spec = _spec(parameters={"type": "object",
                             "properties": {"p": {"type": "string"}}})
    fake = _Fake(spec)
    assert fake.execute(p="").ok


def test_b_no_declared_properties_accepts_empty_read_only():
    spec = _spec(parameters={"type": "object"})
    assert validate_args(spec, {}) == {}


# ── C. Risk behaviour ─────────────────────────────────────────────────────

def test_c_default_risk_is_read_only():
    assert _spec().risk is RiskLevel.READ_ONLY


def test_c_explicit_risks_preserved():
    assert _spec(risk=RiskLevel.MUTATING).risk is RiskLevel.MUTATING
    assert _spec(risk=RiskLevel.DESTRUCTIVE).risk is RiskLevel.DESTRUCTIVE
    assert _spec(risk=RiskLevel.SYSTEM).risk is RiskLevel.SYSTEM


@pytest.mark.parametrize("risk", [RiskLevel.MUTATING, RiskLevel.DESTRUCTIVE,
                                  RiskLevel.SYSTEM])
def test_c_unknown_args_rejected_for_all_strict_risks(risk):
    fake = _Fake(_spec(risk=risk))
    r = fake.execute(text="hi", bogus=1)
    assert not r.ok and r.error_code == ToolErrorCode.INVALID_ARGS
    assert fake.calls == []


def test_c_read_only_drops_unknown_but_mutating_rejects():
    read_fake = _Fake(_spec(risk=RiskLevel.READ_ONLY))
    mut_fake = _Fake(_spec(risk=RiskLevel.MUTATING))
    assert read_fake.execute(text="hi", extra=1).ok
    assert not mut_fake.execute(text="hi", extra=1).ok
    assert read_fake.calls == [{"text": "hi"}]
    assert mut_fake.calls == []


def test_c_confirmation_and_admin_metadata_survive():
    spec = _spec(risk=RiskLevel.DESTRUCTIVE,
                 confirmation_message="Delete everything?",
                 requires_admin=True)
    assert spec.confirmation_message == "Delete everything?"
    assert spec.requires_admin is True


# ── D. ToolResult ─────────────────────────────────────────────────────────

def test_d_success_result():
    r = ToolResult(tool="demo", ok=True, output="done")
    assert r.ok and r.output == "done" and r.error_code is None
    assert r.data is None and r.warnings == ()


def test_d_failure_result_carries_stable_code():
    r = ToolResult(tool="demo", ok=False, output="nope",
                   error_code=ToolErrorCode.INVALID_ARGS)
    assert not r.ok and r.error_code == "invalid_args"


def test_d_structured_data_passthrough():
    class _DataTool(_Fake):
        def run(self, **kwargs):
            return ToolResult(tool="demo", ok=True, output="done",
                              data={"id": 7, "name": "x"})

    r = _DataTool().execute(text="hi")
    assert r.ok and r.data == {"id": 7, "name": "x"}
    assert r.output == "done"


def test_d_warnings_preserved():
    class _WarnTool(_Fake):
        def run(self, **kwargs):
            return ToolResult(tool="demo", ok=True, output="done",
                              warnings=("stale",))

    r = _WarnTool().execute(text="hi")
    assert r.warnings == ("stale",)


def test_d_tool_error_contained_not_raised():
    class _FailTool(_Fake):
        def run(self, **kwargs):
            raise ToolError(ToolErrorCode.PERMISSION_DENIED, "no access")

    r = _FailTool().execute(text="hi")
    assert not r.ok and r.error_code == ToolErrorCode.PERMISSION_DENIED
    assert r.output == "no access"


# ── E. ToolError ──────────────────────────────────────────────────────────

def test_e_code_and_message_attributes():
    e = ToolError("boom", "Something broke")
    assert e.code == "boom"
    assert e.message == "Something broke"


def test_e_str_is_human_message():
    e = ToolError("boom", "Something broke")
    assert str(e) == "Something broke"
    assert repr(e).startswith("ToolError")


def test_e_codes_are_stable_constants():
    assert ToolErrorCode.INVALID_ARGS == "invalid_args"
    assert ToolErrorCode.UNKNOWN_TOOL == "unknown_tool"
    assert ToolErrorCode.INTERNAL == "internal"


def test_e_raise_and_catch_roundtrip():
    try:
        raise ToolError(ToolErrorCode.INVALID_ARGS, "bad")
    except ToolError as e:
        assert e.code == "invalid_args" and e.message == "bad"


def test_e_tool_error_is_caught_by_exception_hierarchy():
    assert issubclass(ToolError, Exception)
    assert issubclass(ToolRegistryError, ValueError)


# ── F. ToolRegistry ───────────────────────────────────────────────────────

def test_f_register_get_has_all_names_specs():
    reg = _registry(_Fake(_spec(name="one")), _Fake(_spec(name="two")))
    assert reg.has("one") and reg.has("two") and not reg.has("three")
    assert reg.get("one").spec.name == "one"
    assert reg.get("three") is None
    assert {t.spec.name for t in reg.all()} == {"one", "two"}
    assert reg.names() == ("one", "two")
    assert [s.name for s in reg.specs()] == ["one", "two"]


def test_f_openai_tools_shape():
    reg = _registry(_Fake(_spec(name="one", description="First",
                                parameters={"type": "object",
                                            "properties": {"a": {"type": "integer"}}})))
    o = reg.openai_tools()
    assert len(o) == 1
    assert o[0] == {"type": "function",
                    "function": {"name": "one", "description": "First",
                                 "parameters": {"type": "object",
                                                "properties": {"a": {"type": "integer"}}}}}


def test_f_duplicate_name_rejected():
    reg = _registry(_Fake(_spec(name="dup")))
    with pytest.raises(ToolRegistryError):
        reg.register(_Fake(_spec(name="dup")))
    assert len(reg.all()) == 1


def test_f_colliding_names_rejected_across_classes():
    class _Other(Tool):
        @property
        def spec(self):
            return _spec(name="dup")
        def run(self, **kwargs):
            return "other"

    reg = _registry(_Fake(_spec(name="dup")))
    with pytest.raises(ToolRegistryError):
        reg.register(_Other())
    assert reg.get("dup").run() == "ran:[]"     # first registration survives


def test_f_register_rejects_non_tool():
    with pytest.raises(TypeError):
        ToolRegistry().register(object())


def test_f_malformed_spec_rejected_at_register():
    reg = ToolRegistry()
    with pytest.raises(ToolRegistryError):
        reg.register(_Fake(_spec(parameters={"type": "object",
                                             "properties": {"p": {"type": "blob"}}})))
    assert len(reg.all()) == 0         # nothing was added


def test_f_clear():
    reg = _registry(_Fake(_spec(name="one")))
    reg.clear()
    assert not reg.has("one") and reg.names() == ()


def test_f_execute_unknown_tool():
    reg = _registry()
    r = reg.execute("ghost", {})
    assert not r.ok and r.error_code == ToolErrorCode.UNKNOWN_TOOL
    assert "ghost" in r.output


def test_f_execute_non_object_args():
    fake = _Fake()
    reg = _registry(fake)
    r = reg.execute("demo", ["text"])
    assert not r.ok and r.error_code == ToolErrorCode.INVALID_ARGS
    assert fake.calls == []


def test_f_execute_valid_round_trip():
    fake = _Fake()
    reg = _registry(fake)
    r = reg.execute("demo", {"text": "hi", "n": 2})
    assert r.ok and fake.calls == [{"text": "hi", "n": 2}]


# ── G. Execution contract ─────────────────────────────────────────────────

def test_g_valid_args_execute_fake_tool():
    fake = _Fake()
    r = fake.execute(text="hello")
    assert r.ok and fake.calls == [{"text": "hello"}]


def test_g_invalid_args_never_execute_fake_tool():
    fake = _Fake()
    r = fake.execute(text=123)          # wrong type
    assert not r.ok
    assert fake.calls == []             # handler NOT reached


def test_g_tool_returning_toolresult_passes_through():
    marker = ToolResult(tool="demo", ok=False, output="custom",
                        error_code="custom_code")
    class _Passthrough(_Fake):
        def run(self, **kwargs):
            return marker
    r = _Passthrough().execute(text="hi")
    assert r is marker                 # NOT re-wrapped


def test_g_str_return_wrapped_ok():
    fake = _Fake()
    r = fake.execute(text="hi")
    assert r.ok and r.output.startswith("ran:") and r.error_code is None


def test_g_none_return_becomes_empty_output():
    class _NoneTool(_Fake):
        def run(self, **kwargs):
            return None
    r = _NoneTool().execute(text="hi")
    assert r.ok and r.output == ""


def test_g_int_return_stringified():
    class _IntTool(_Fake):
        def run(self, **kwargs):
            return 42
    r = _IntTool().execute(text="hi")
    assert r.ok and r.output == "42"


def test_g_generic_exception_contained_internal():
    class _CrashTool(_Fake):
        def run(self, **kwargs):
            raise RuntimeError("kaboom")
    r = _CrashTool().execute(text="hi")
    assert not r.ok and r.error_code == ToolErrorCode.INTERNAL
    assert "RuntimeError" in r.output


def test_g_registry_execute_never_raises_on_input_matrix():
    fake = _Fake()
    reg = _registry(fake)
    cases = [("demo", {}), ("demo", {"text": 1}), ("demo", None),
             ("demo", "str"), ("demo", {"text": "ok", "boom": 1}),
             ("missing", {}), (None, {})]
    for name, args in cases:
        r = reg.execute(name, args)     # must never raise
        assert isinstance(r, ToolResult)


def test_g_execute_returns_ok_for_valid_args_never_raises():
    fake = _Fake()
    for kwargs in [{"text": "a"}, {"text": "b", "n": 1},
                   {"text": "c", "nested": {"x": 2}}]:
        r = fake.execute(**kwargs)
        assert isinstance(r, ToolResult)


# ── Adversarial ───────────────────────────────────────────────────────────

def test_adv_malformed_schema_properties_as_list():
    with pytest.raises(ToolRegistryError):
        validate_spec(_spec(parameters={"type": "object", "properties": []}))


def test_adv_schema_with_junk_top_level_keys_still_validates_content():
    # unexpected *top-level* keys are ignored, but the declared parts must
    # still be coherent -- a bad declared property is still rejected.
    with pytest.raises(ToolRegistryError):
        validate_spec(_spec(parameters={"type": "object", "bogus": 1,
                                        "properties": {"p": {"type": "nope"}}}))


def test_adv_empty_name_and_description():
    with pytest.raises(ToolRegistryError):
        validate_spec(_spec(name="", description="x"))
    with pytest.raises(ToolRegistryError):
        validate_spec(_spec(name="x", description=""))


def test_adv_none_args_to_validate_args():
    spec = _spec()
    with pytest.raises(ToolError) as ei:
        validate_args(spec, None)
    assert ei.value.code == ToolErrorCode.INVALID_ARGS


def test_adv_validate_spec_rejects_non_toolspec():
    with pytest.raises(ToolRegistryError):
        validate_spec("echo")


def test_adv_tool_execute_with_none_kwarg_rejected_when_not_allowed():
    fake = _Fake()
    r = fake.execute(text=None)
    assert not r.ok and r.error_code == ToolErrorCode.INVALID_ARGS
    assert fake.calls == []


def test_adv_dangerous_metadata_string_risk():
    with pytest.raises(ToolRegistryError):
        validate_spec(_spec(risk="HIGH"))
    with pytest.raises(ToolRegistryError):
        validate_spec(_spec(risk=3))


def test_adv_dangerous_metadata_bad_confirmation():
    with pytest.raises(ToolRegistryError):
        validate_spec(_spec(confirmation_message=[]))


def test_adv_invalid_openai_schema_cannot_register():
    reg = ToolRegistry()
    with pytest.raises(ToolRegistryError):
        reg.register(_Fake(_spec(parameters={"type": "array", "items": {}})))
    # therefore openai_tools() output is always structurally valid
    reg.register(_Fake(_spec(name="ok", description="fine")))
    for o in reg.openai_tools():
        assert o["type"] == "function"
        assert o["function"]["parameters"]["type"] == "object"


def test_adv_duplicate_registration_after_clear_allowed():
    reg = _registry(_Fake(_spec(name="again")))
    reg.clear()
    reg.register(_Fake(_spec(name="again")))   # no raise after clear
    assert reg.has("again")
