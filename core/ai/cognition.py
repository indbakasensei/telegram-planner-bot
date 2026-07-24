"""
cognition.py -- the Cognitive Engine, Phase 1 (v15.1.0-alpha.3):
Planner + Executor over grounded Workspace tools.

Separation of responsibilities (design principle):
  * the Planner reasons   -- decides WHICH tools to call for a question;
  * the Executor executes -- runs those tools against the Workspace APIs;
  * the tools ground      -- every fact comes from real Workspace state.

Because the answer is composed ONLY from tool outputs, the model can never
fabricate Workspace data: it routes, it does not write facts. Conversation
context (the active workspace, persisted in `tg_active_context`) lets later
questions resolve without repeating the workspace name (PART 7). When no
grounded fact exists, the engine says so rather than inventing (PART 8).

The AI model is injected as a `Planner` (the LLM-backed one lives in
llm_planner.py); a deterministic `RuleBasedPlanner` is the default and the
offline test double -- this module never calls a live LLM.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from core.ai.workspace_tools import build_workspace_registry
from core.storage import Storage
from core.workspace.engine import EntityEngine


# ── Plan / result value objects ───────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class PlanStep:
    tool: str
    args: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Plan:
    steps: tuple[PlanStep, ...]
    intent: str = ""
    note: str = ""          # optional AI *suggestion* -- never a fact


@dataclass(frozen=True, slots=True)
class CognitiveContext:
    user_id: int
    active_workspace_id: int | None
    workspace_titles: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ToolResult:
    tool: str
    output: str
    ok: bool = True


@dataclass(frozen=True, slots=True)
class CognitiveResult:
    answer: str
    facts: tuple[str, ...]          # grounded, from tools
    plan: Plan
    results: tuple[ToolResult, ...]
    suggestion: str = ""            # AI-generated, clearly separate from facts

    @property
    def grounded(self) -> bool:
        return bool(self.facts)


# ── Planner contract + deterministic default ──────────────────────────────
class Planner(ABC):
    @abstractmethod
    def plan(self, query: str, context: CognitiveContext) -> Plan:
        ...


class RuleBasedPlanner(Planner):
    """Deterministic keyword router -- the default and the test double. Maps a
    question to one grounded tool call; resolves a workspace name mentioned in
    the query, else relies on the active workspace (conversation context)."""

    def plan(self, query, context):
        text = (query or "").strip()
        low = text.lower()
        ref = self._extract_ref(low, context.workspace_titles)

        if any(k in low for k in ("open ", "switch to", "go to", "use ")) and ref:
            return Plan((PlanStep("open_workspace", {"workspace": ref}),), "open")
        if "blocked" in low or "stuck" in low:
            return Plan((PlanStep("list_entities",
                                  {"workspace": ref, "status": "blocked"}),), "blocked")
        if any(k in low for k in ("progress", "how far", "complete", "% ", "how much")):
            return Plan((PlanStep("workspace_overview", {"workspace": ref}),), "overview")
        if any(k in low for k in ("recent", "activity", "last", "latest", "update", "note")):
            return Plan((PlanStep("recent_notes", {"workspace": ref}),), "notes")
        if (any(k in low for k in ("workspace", "project", "game", "goal")) and
                any(k in low for k in ("list", "what", "which", "my", "all", "show"))):
            return Plan((PlanStep("list_workspaces", {}),), "list")
        if any(k in low for k in ("component", "entit", "character", "milestone",
                                  "what's in", "whats in", "what is in", "parts")):
            return Plan((PlanStep("list_entities", {"workspace": ref}),), "entities")
        # default: an overview of the referenced/active workspace
        return Plan((PlanStep("workspace_overview", {"workspace": ref}),), "overview")

    @staticmethod
    def _extract_ref(low, titles):
        # longest matching workspace title mentioned in the query wins
        best = None
        for t in titles:
            if t and t.lower() in low and (best is None or len(t) > len(best)):
                best = t
        return best


# ── Executor ──────────────────────────────────────────────────────────────
def execute(plan: Plan, registry) -> list[ToolResult]:
    """Run each plan step against the tool registry. A missing/erroring tool
    is recorded as a non-ok result, never raised -- the engine degrades
    gracefully rather than crashing a conversation."""
    out: list[ToolResult] = []
    for step in plan.steps:
        tool = registry.get(step.tool)
        if tool is None:
            out.append(ToolResult(step.tool, f"(no such tool: {step.tool})", ok=False))
            continue
        try:
            out.append(ToolResult(step.tool, tool.run(**(step.args or {})), ok=True))
        except Exception as e:   # pragma: no cover - defensive
            out.append(ToolResult(step.tool, f"(tool error: {e})", ok=False))
    return out


# ── The Cognitive Engine ──────────────────────────────────────────────────
class CognitiveEngine:
    """Answers questions about the Workspace by planning tool calls and
    grounding the answer in their output. Stateless beyond injected deps."""

    NO_INFO = "I don't have that information yet."

    def __init__(self, engine: EntityEngine | None = None,
                 planner: Planner | None = None, storage: Storage | None = None):
        self._eng = engine or EntityEngine()
        self._planner = planner or RuleBasedPlanner()
        self._s = storage or Storage()

    def handle(self, user_id, query) -> CognitiveResult:
        active = self._s.tg_bindings.get_active(user_id)
        active_ws = active[0] if active else None
        titles = tuple(w.title for w in self._eng.list_workspaces(user_id, status=None))
        ctx = CognitiveContext(user_id, active_ws, titles)

        plan = self._planner.plan(query, ctx)
        registry = build_workspace_registry(self._eng, user_id, active_ws, self._s)
        results = execute(plan, registry)

        facts = tuple(r.output for r in results if r.ok)
        answer = "  ".join(facts) if facts else self.NO_INFO
        return CognitiveResult(answer=answer, facts=facts, plan=plan,
                               results=tuple(results), suggestion=plan.note)
