"""
tools.py -- tool interface foundation (v15.1.0-alpha.2, FOUNDATION only).

Defines what an AI-callable "tool" is (`Tool` + `ToolSpec`) and a
registration-based `ToolRegistry`, so future tool orchestration can discover
and describe tools uniformly -- the same edit-nothing-central,
registration-based philosophy as the Offline Engine's ActionRegistry
(ADR-012) and the Self-Test/regression registries.

Scope: the CONTRACT + registry only. This milestone deliberately does NOT
implement a planner, an execution/orchestration loop, or any concrete tools
-- those come in later AI-layer milestones. `ToolSpec.to_openai()` renders
the JSON shape an OpenAI-compatible `tools=[...]` argument expects, so the
foundation is ready to plug in without reshaping later.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """Describes a tool for the model. `parameters` is a JSON-Schema object
    (as OpenAI tool-calling expects); default is an empty object."""
    name: str
    description: str
    parameters: dict = field(default_factory=lambda: {"type": "object", "properties": {}})

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


class Tool(ABC):
    """An AI-callable tool: a `spec` describing it to the model, and a `run`
    that executes it. Implementations must validate their own inputs and
    return a string result the model can read."""

    @property
    @abstractmethod
    def spec(self) -> ToolSpec:
        ...

    @abstractmethod
    def run(self, **kwargs) -> str:
        ...


class ToolRegistry:
    """A registry of tools, keyed by name. Registration is idempotent by
    name (re-registering replaces). The future orchestrator asks the registry
    for `specs()` to advertise tools and `get(name)` to execute a call."""

    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if not isinstance(tool, Tool):
            raise TypeError("register() expects a Tool instance")
        name = tool.spec.name
        if not name or not isinstance(name, str):
            raise ValueError("tool spec.name must be a non-empty string")
        self._tools[name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def has(self, name: str) -> bool:
        return name in self._tools

    def all(self) -> tuple[Tool, ...]:
        return tuple(self._tools.values())

    def specs(self) -> list[ToolSpec]:
        return [t.spec for t in self._tools.values()]

    def openai_tools(self) -> list[dict]:
        """All specs rendered for an OpenAI-compatible `tools=[...]` arg."""
        return [t.spec.to_openai() for t in self._tools.values()]

    def clear(self) -> None:
        self._tools.clear()
