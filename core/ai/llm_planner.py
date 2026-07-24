"""
llm_planner.py -- the LLM-backed Planner for the Cognitive Engine
(v15.1.0-alpha.3).

Wraps the app's AI (baka_brain) to choose WHICH grounded Workspace tool best
answers a question. Critically, the model only emits a tool + args as JSON --
it never writes the factual answer, so it cannot hallucinate Workspace data
(the facts come from the tool, in cognition.py). Any AI failure, malformed
output, or unknown tool falls back to the deterministic `RuleBasedPlanner`,
so the Cognitive Engine always produces a plan.

The AI call is injected (`ai_call`) so this is offline-testable; the default
lazily resolves baka_brain's fast chat function at call time (no import-time
dependency, no live call in tests).
"""
from __future__ import annotations

import json
import re

from core.ai.cognition import Plan, PlanStep, Planner, RuleBasedPlanner

# The fixed tool catalogue the model may choose from.
KNOWN_TOOLS = {
    "list_workspaces", "workspace_overview", "list_entities",
    "recent_notes", "open_workspace", "recall",
}

_SYSTEM_PROMPT = """You route a user's question about their Workspaces to ONE tool.
You do NOT answer with facts -- you only pick a tool; the tool returns the real data.

Tools:
- list_workspaces()                       list all workspaces
- workspace_overview(workspace?)          progress + entity counts
- list_entities(workspace?, status?)      entities/components; status: todo|in_progress|done|blocked
- recent_notes(workspace?)                latest progress notes
- open_workspace(workspace)               set the active workspace
- recall(query)                           SEARCH everything stored (entities, notes) for related info

Rules:
- Omit "workspace" to use the active one (from context).
- For broad/open questions ("what do I know about X", "tell me about X"), use recall with the user's question as query.
- Reply with ONLY JSON: {"tool": "<name>", "args": {...}}
- If unsure, use recall with the question as query.
"""


def _extract_json(text: str) -> dict | None:
    if not text:
        return None
    if "```" in text:
        text = text.split("```")[1] if text.count("```") >= 2 else text
        text = text.replace("json", "", 1) if text.lstrip().startswith("json") else text
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except (ValueError, TypeError):
        return None


class LLMPlanner(Planner):
    def __init__(self, ai_call=None, fallback: Planner | None = None):
        self._ai_call = ai_call
        self._fallback = fallback or RuleBasedPlanner()

    def _ai(self, prompt: str) -> str:
        if self._ai_call is not None:
            return self._ai_call(prompt)
        # Lazy: resolve the app's fast chat function only when actually used.
        import baka_brain
        fn = getattr(baka_brain, "call_fast", None) or getattr(baka_brain, "call_nvidia")
        return fn([{"role": "system", "content": _SYSTEM_PROMPT},
                   {"role": "user", "content": prompt}])

    def plan(self, query, context) -> Plan:
        try:
            ctx = (f"Active workspace id: {context.active_workspace_id}. "
                   f"Workspaces: {', '.join(context.workspace_titles) or '(none)'}.")
            raw = self._ai(f"{ctx}\nQuestion: {query}")
            data = _extract_json(raw)
            if data:
                tool = str(data.get("tool", "")).strip()
                args = data.get("args") or {}
                if tool in KNOWN_TOOLS and isinstance(args, dict):
                    return Plan((PlanStep(tool, args),), intent="llm")
        except Exception:
            pass
        return self._fallback.plan(query, context)
