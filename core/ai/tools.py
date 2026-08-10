"""
tools.py -- tool contract foundation (v15.1.0-alpha.2 foundation; extended
by v15.2 M2 — Tool Contract Foundation).

Defines what an AI-callable "tool" is and how it is registered, described,
validated, and executed — the single contract the future AI Worker (v15.2)
routes through. Everything lives in this one module so there is exactly ONE
tool abstraction in the codebase: `Tool` + `ToolSpec` + `ToolRegistry`, plus
`RiskLevel` (what a tool may do), `ToolError` (stable machine-readable
failures), `ToolResult` (structured outcomes), and fail-closed argument
validation (`validate_spec` / `validate_args`).

This module deliberately still does NOT implement the AI Worker, an agent
loop, or any concrete task/entity/reminder tools — those come in later
v15.2 milestones. `ToolSpec.to_openai()` renders the JSON shape an
OpenAI-compatible `tools=[...]` argument expects, so the foundation is ready
to plug in without reshaping later.

M2 contract decisions (see docs/engineering/V15_2_BAKA_BRAIN.md):
  * RiskLevel classifies tools READ_ONLY / MUTATING / DESTRUCTIVE / SYSTEM.
  * Argument validation is fail-closed: invalid arguments NEVER reach a
    tool's run(). Unknown arguments are REJECTED for write/delete/system
    tools and silently dropped for READ_ONLY tools.
  * `Tool.execute()` is the single sanctioned run path: it validates,
    contains every failure into a non-ok `ToolResult`, and never raises for
    ordinary input. `ToolRegistry.execute()` is the dispatcher the Worker
    will call.
  * A malformed ToolSpec or a duplicate name is rejected loudly at
    register() time (ToolRegistryError).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum

__all__ = [
    "RiskLevel",
    "Tool",
    "ToolError",
    "ToolErrorCode",
    "ToolRegistry",
    "ToolRegistryError",
    "ToolResult",
    "ToolSpec",
    "validate_args",
    "validate_spec",
]


# ── Risk ──────────────────────────────────────────────────────────────────
class RiskLevel(Enum):
    """What a tool may do. READ_ONLY is the default; anything that writes,
    deletes, or touches system/admin surface must declare it explicitly so
    the future Worker can gate confirmation and permissions on it."""
    READ_ONLY = "read_only"
    MUTATING = "mutating"
    DESTRUCTIVE = "destructive"
    SYSTEM = "system"


# Unknown arguments are only tolerated on pure reads.
_STRICT_RISKS = frozenset({RiskLevel.MUTATING, RiskLevel.DESTRUCTIVE,
                           RiskLevel.SYSTEM})


# ── Errors ────────────────────────────────────────────────────────────────
class ToolErrorCode:
    """Stable machine-readable error codes. The future Worker keys on these
    strings — they are contract, not copy. A code must never be reworded;
    add a new code rather than changing an existing one.

    CONFIRMATION_REQUIRED / PERMISSION_DENIED are RESERVED for later
    milestones (M5+ confirmation flow) — the contract does not raise them
    yet, but the codes are fixed now so nothing changes shape later."""
    INVALID_ARGS = "invalid_args"        # schema validation failed
    UNKNOWN_TOOL = "unknown_tool"        # no such registered tool
    INTERNAL = "internal"                # unexpected exception inside run()
    CONFIRMATION_REQUIRED = "confirmation_required"
    PERMISSION_DENIED = "permission_denied"


class ToolError(Exception):
    """A tool failure with a stable machine-readable `code` and a
    human-readable `message`. Raised BY tools (and by argument validation);
    `Tool.execute`/`ToolRegistry.execute` convert it into a non-ok ToolResult
    so it never escapes to a caller."""
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

    def __str__(self) -> str:
        return self.message


class ToolRegistryError(ValueError):
    """Registration-time failure: a malformed ToolSpec, or a duplicate tool
    name. Raised at register() time so a bad tool is rejected loudly."""


# ── ToolResult ────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class ToolResult:
    """The outcome of one tool execution. `ok=False` results carry a stable
    `error_code` (a ToolErrorCode string) so callers can branch on the
    failure class without string-matching the message. `data` holds an
    optional structured (JSON-compatible) payload for the Worker to inspect."""
    tool: str
    ok: bool = True
    output: str = ""
    data: "dict | None" = None
    warnings: "tuple[str, ...]" = ()
    error_code: "str | None" = None


# ── ToolSpec ──────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class ToolSpec:
    """Describes a tool for the model and for validation. `parameters` is a
    JSON-Schema object (as OpenAI tool-calling expects); default is an empty
    object. `risk` classifies what the tool may do; `confirmation_message`
    (if set) is shown before a MUTATING/DESTRUCTIVE tool runs; `requires_admin`
    marks owner-only tools."""
    name: str
    description: str
    parameters: dict = field(default_factory=lambda: {"type": "object", "properties": {}})
    risk: RiskLevel = RiskLevel.READ_ONLY
    confirmation_message: "str | None" = None
    requires_admin: bool = False

    def to_openai(self) -> dict:
        """The `{"type":"function","function":{...}}` shape for an
        OpenAI-compatible `tools=[...]` request."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


# ── The Tool contract ─────────────────────────────────────────────────────
class Tool(ABC):
    """An AI-callable tool: a `spec` describing it to the model, and a `run`
    that executes it. `execute(**kwargs)` is the single sanctioned way to run
    a tool: it validates arguments against the spec, contains every failure
    in a ToolResult, and normalizes the `run()` return value."""

    @property
    @abstractmethod
    def spec(self) -> ToolSpec:
        ...

    @abstractmethod
    def run(self, **kwargs) -> "str | ToolResult":
        """Execute with VALIDATED keyword arguments (unknowns already
        filtered/validated by execute). May return a plain string or a
        ToolResult; may raise ToolError for expected failures. Any other
        exception is contained by execute() into an internal-error result."""
        ...

    def execute(self, **kwargs) -> ToolResult:
        """Validate, run, contain. Never raises for ordinary input: malformed
        arguments and tool failures all come back as non-ok ToolResults."""
        name = self.spec.name
        try:
            validated = validate_args(self.spec, kwargs)
        except ToolError as e:
            return ToolResult(tool=name, ok=False, output=e.message,
                              error_code=e.code)
        try:
            result = self.run(**validated)
        except ToolError as e:
            return ToolResult(tool=name, ok=False, output=e.message,
                              error_code=e.code)
        except Exception as e:  # noqa: BLE001 -- containment is the point
            return ToolResult(tool=name, ok=False,
                              output=f"Tool '{name}' failed: {type(e).__name__}",
                              error_code=ToolErrorCode.INTERNAL)
        if isinstance(result, ToolResult):
            return result
        if result is None:
            return ToolResult(tool=name, ok=True, output="")
        return ToolResult(tool=name, ok=True, output=str(result))


# ── ToolRegistry ──────────────────────────────────────────────────────────
class ToolRegistry:
    """A registry of tools, keyed by name. Registration validates the spec
    (rejecting malformed schemas) and rejects duplicate names. `execute()`
    is the single execution entry point the future Worker will call."""

    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if not isinstance(tool, Tool):
            raise TypeError("register() expects a Tool instance")
        name = tool.spec.name
        if not name or not isinstance(name, str):
            raise ValueError("tool spec.name must be a non-empty string")
        validate_spec(tool.spec)                  # fail closed on malformed schemas
        if name in self._tools:
            raise ToolRegistryError(
                f"tool already registered: {name!r} (a name may be registered "
                f"only once)")
        self._tools[name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def has(self, name: str) -> bool:
        return name in self._tools

    def all(self) -> tuple[Tool, ...]:
        return tuple(self._tools.values())

    def names(self) -> tuple[str, ...]:
        return tuple(self._tools)

    def specs(self) -> list[ToolSpec]:
        return [t.spec for t in self._tools.values()]

    def openai_tools(self) -> list[dict]:
        """All specs rendered for an OpenAI-compatible `tools=[...]` arg."""
        return [t.spec.to_openai() for t in self._tools.values()]

    def execute(self, name: str, args: dict) -> ToolResult:
        """Execute a tool by name with validated arguments. Never raises for
        ordinary input: unknown tools, non-object argument payloads, and
        validation failures all come back as non-ok ToolResults."""
        tool = self.get(name)
        if tool is None:
            return ToolResult(tool=name, ok=False,
                              output=f"Unknown tool: {name}",
                              error_code=ToolErrorCode.UNKNOWN_TOOL)
        if not isinstance(args, dict):
            return ToolResult(tool=name, ok=False,
                              output=f"Tool '{name}' arguments must be a JSON object.",
                              error_code=ToolErrorCode.INVALID_ARGS)
        return tool.execute(**args)

    def clear(self) -> None:
        self._tools.clear()


# ── Schema validation ─────────────────────────────────────────────────────
_JSON_TYPES = frozenset({
    "string", "integer", "number", "boolean", "object", "array", "null",
})


def validate_spec(spec: ToolSpec) -> None:
    """Reject a malformed ToolSpec loudly (raises ToolRegistryError). Called
    at registration time so a bad tool never enters the registry, and
    defensively by validate_args so execution always fails closed."""
    if not isinstance(spec, ToolSpec):
        raise ToolRegistryError(
            f"expected a ToolSpec, got {type(spec).__name__}")
    name = spec.name
    if not isinstance(name, str) or not name.strip():
        raise ToolRegistryError(
            f"tool name must be a non-empty string, got {name!r}")
    if not isinstance(spec.description, str) or not spec.description.strip():
        raise ToolRegistryError(
            f"tool {name!r}: description must be a non-empty string")
    params = spec.parameters
    if not isinstance(params, dict):
        raise ToolRegistryError(
            f"tool {name!r}: parameters must be a JSON-Schema dict, "
            f"got {type(params).__name__}")
    ptype = params.get("type")
    if ptype is not None and ptype != "object":
        raise ToolRegistryError(
            f"tool {name!r}: top-level JSON-Schema type must be 'object', "
            f"got {ptype!r}")
    props = params.get("properties", {})
    if not isinstance(props, dict):
        raise ToolRegistryError(
            f"tool {name!r}: properties must be a dict, "
            f"got {type(props).__name__}")
    for pname, psch in props.items():
        if not isinstance(pname, str) or not pname:
            raise ToolRegistryError(
                f"tool {name!r}: property names must be non-empty strings")
        _check_prop_schema(name, pname, psch)
    req = params.get("required", [])
    if not isinstance(req, list) or not all(isinstance(r, str) for r in req):
        raise ToolRegistryError(
            f"tool {name!r}: required must be a list of property names")
    undefined = [r for r in req if r not in props]
    if undefined:
        raise ToolRegistryError(
            f"tool {name!r}: required references undefined properties: {undefined}")
    if not isinstance(spec.risk, RiskLevel):
        raise ToolRegistryError(
            f"tool {name!r}: risk must be a RiskLevel, got {spec.risk!r}")
    if spec.confirmation_message is not None and not isinstance(spec.confirmation_message, str):
        raise ToolRegistryError(
            f"tool {name!r}: confirmation_message must be a string or None")
    if not isinstance(spec.requires_admin, bool):
        raise ToolRegistryError(
            f"tool {name!r}: requires_admin must be a bool, "
            f"got {spec.requires_admin!r}")


def _check_prop_schema(tool: str, path: str, psch) -> None:
    """Validate one property's JSON-Schema fragment (recursively for
    nested objects)."""
    if not isinstance(psch, dict):
        raise ToolRegistryError(
            f"tool {tool!r}: property {path!r} schema must be a dict, "
            f"got {type(psch).__name__}")
    ptype = psch.get("type")
    if ptype is not None:
        types = ptype if isinstance(ptype, list) else [ptype]
        if not types:
            raise ToolRegistryError(
                f"tool {tool!r}: property {path!r} type list is empty")
        for t in types:
            if not isinstance(t, str) or t not in _JSON_TYPES:
                raise ToolRegistryError(
                    f"tool {tool!r}: property {path!r} has unsupported type {t!r}")
    enum = psch.get("enum")
    if enum is not None and not isinstance(enum, list):
        raise ToolRegistryError(
            f"tool {tool!r}: property {path!r} enum must be a list")
    if ptype == "object" or (isinstance(ptype, list) and "object" in ptype):
        sub = psch.get("properties")
        if sub is not None:
            if not isinstance(sub, dict):
                raise ToolRegistryError(
                    f"tool {tool!r}: property {path!r} nested properties must be "
                    f"a dict, got {type(sub).__name__}")
            for sp, ssch in sub.items():
                if not isinstance(sp, str) or not sp:
                    raise ToolRegistryError(
                        f"tool {tool!r}: nested property names must be "
                        f"non-empty strings")
                _check_prop_schema(tool, f"{path}.{sp}", ssch)
        sreq = psch.get("required")
        if sreq is not None:
            if not isinstance(sreq, list) or not all(isinstance(r, str) for r in sreq):
                raise ToolRegistryError(
                    f"tool {tool!r}: property {path!r} required must be a list "
                    f"of property names")
            undefined = [r for r in sreq if r not in (sub or {})]
            if undefined:
                raise ToolRegistryError(
                    f"tool {tool!r}: property {path!r} required references "
                    f"undefined nested properties: {undefined}")


def validate_args(spec: ToolSpec, args: dict) -> dict:
    """Validate `args` against `spec.parameters` and return the (possibly
    filtered) arguments to execute. Raises ToolError("invalid_args", ...) on
    any violation — invalid arguments NEVER reach a tool's run().

    Unknown arguments are REJECTED for MUTATING/DESTRUCTIVE/SYSTEM tools (a
    write tool must never be fed a key it does not declare) and silently
    DROPPED for READ_ONLY tools (a read may be asked for more than it knows)."""
    if not isinstance(args, dict):
        raise ToolError(ToolErrorCode.INVALID_ARGS,
                        f"Tool '{spec.name}' arguments must be a JSON object.")
    try:
        validate_spec(spec)
    except ToolRegistryError as e:
        # Fail closed: without a valid schema we cannot validate arguments.
        raise ToolError(ToolErrorCode.INVALID_ARGS,
                        f"Tool '{spec.name}' has a malformed schema: {e}")
    props = spec.parameters.get("properties", {})
    strict = spec.risk in _STRICT_RISKS
    unknown = [k for k in args if k not in props]
    if unknown:
        if strict:
            raise ToolError(ToolErrorCode.INVALID_ARGS,
                            f"Tool '{spec.name}' got unknown argument(s): "
                            f"{', '.join(sorted(unknown))}.")
        args = {k: v for k, v in args.items() if k in props}
    for req in spec.parameters.get("required", []):
        if req not in args:
            raise ToolError(ToolErrorCode.INVALID_ARGS,
                            f"Tool '{spec.name}' missing required argument '{req}'.")
    for k, v in args.items():
        _check_value(spec.name, k, v, props.get(k, {}), strict)
    return args


def _type_name(v) -> str:
    return "null" if v is None else type(v).__name__


def _type_ok(t: str, v) -> bool:
    """JSON-type check. Note: bool is NOT an integer, and None is only ever a
    JSON `null`."""
    if t == "string":
        return isinstance(v, str)
    if t == "integer":
        return isinstance(v, int) and not isinstance(v, bool)
    if t == "number":
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    if t == "boolean":
        return isinstance(v, bool)
    if t == "object":
        return isinstance(v, dict)
    if t == "array":
        return isinstance(v, list)
    if t == "null":
        return v is None
    return False  # unsupported type -- validate_spec rejects these anyway


def _human(types: list) -> str:
    return " or ".join(types)


def _check_value(tool: str, path: str, value, prop: dict, strict: bool) -> None:
    """Validate one argument value against its property schema. Nested
    objects are validated recursively; unknown nested keys are rejected on
    strict tools and dropped on read-only ones."""
    ptype = prop.get("type")
    types = ptype if isinstance(ptype, list) else ([ptype] if ptype is not None else None)

    if value is None:
        if types is not None and "null" not in types:
            raise ToolError(ToolErrorCode.INVALID_ARGS,
                            f"Tool '{tool}' argument '{path}' does not accept null.")
    elif types is not None and not any(_type_ok(t, value) for t in types):
        raise ToolError(ToolErrorCode.INVALID_ARGS,
                        f"Tool '{tool}' argument '{path}' has wrong type "
                        f"(expected {_human(types)}, got {_type_name(value)}).")

    enum = prop.get("enum")
    if enum is not None and value not in enum:
        raise ToolError(ToolErrorCode.INVALID_ARGS,
                        f"Tool '{tool}' argument '{path}' must be one of: "
                        f"{', '.join(repr(e) for e in enum)}.")

    if isinstance(value, str):
        min_len = prop.get("minLength")
        if min_len is not None and len(value) < min_len:
            raise ToolError(ToolErrorCode.INVALID_ARGS,
                            f"Tool '{tool}' argument '{path}' must be at least "
                            f"{min_len} character(s) long.")

    if isinstance(value, dict) and (types is None or "object" in types):
        sub = prop.get("properties", {})
        if sub:
            nested_unknown = [k for k in value if k not in sub]
            if nested_unknown and strict:
                raise ToolError(ToolErrorCode.INVALID_ARGS,
                                f"Tool '{tool}' argument '{path}' got unknown "
                                f"nested argument(s): "
                                f"{', '.join(sorted(nested_unknown))}.")
            if nested_unknown:
                value = {k: v for k, v in value.items() if k in sub}
            for r in prop.get("required", []):
                if r not in value:
                    raise ToolError(ToolErrorCode.INVALID_ARGS,
                                    f"Tool '{tool}' argument '{path}' missing "
                                    f"required nested argument '{r}'.")
            for k, v in value.items():
                _check_value(tool, f"{path}.{k}", v, sub.get(k, {}), strict)
