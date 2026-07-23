"""
llm_interpreter.py -- the production Interpreter (v15.0-beta.1).

Implements the orchestrator's `Interpreter` contract using the existing AI
provider abstraction (baka_brain). It asks the model to convert one user
utterance into a single generic workspace Proposal (JSON), parses it, and
returns a Proposal. It does NOT touch the engine, never writes anything,
and cannot bypass validation -- producing a Proposal is all it does; the
orchestrator re-resolves and re-validates everything (AWOD §4.4).

Fail-safe by construction: any AI error (timeout, 429, malformed JSON, an
unknown action) falls back to the deterministic RuleBasedInterpreter, so
the pipeline degrades gracefully instead of breaking (beta.1 requirement).
baka_brain is imported lazily inside the default AI call, so importing this
module (and therefore core.workspace) triggers no provider/network setup --
keeping the WORKSPACE-off path byte-identical.
"""
from __future__ import annotations

import json
import re

from core.workspace.orchestrator import (
    Action,
    Interpreter,
    OrchestratorContext,
    Proposal,
    RuleBasedInterpreter,
)

_VALID_ACTIONS = frozenset({
    Action.CREATE_WORKSPACE, Action.RENAME_WORKSPACE, Action.ARCHIVE_WORKSPACE,
    Action.COMPLETE_WORKSPACE, Action.ADD_MILESTONE, Action.COMPLETE_MILESTONE,
    Action.ARCHIVE_MILESTONE, Action.DELETE_MILESTONE, Action.ADD_NOTE,
})

_SYSTEM_PROMPT = (
    "You convert a user's message into ONE workspace operation, as JSON.\n"
    "Valid actions: create_workspace, rename_workspace, archive_workspace, "
    "complete_workspace, add_milestone, complete_milestone, archive_milestone, "
    "delete_milestone, add_note, unknown.\n"
    "Return ONLY JSON of the form:\n"
    '{"action": "<action>", "workspace_ref": <title or null>, '
    '"entity_ref": <milestone title or null>, '
    '"params": {"title": <str?>, "content": <str?>}, "confidence": <0..1>}\n'
    "workspace_ref is a workspace the user named; entity_ref is a milestone "
    "they named. Use action 'unknown' with low confidence if the message is "
    "not a workspace operation. Do not invent data."
)


def _default_ai_call(messages):
    """Lazily use baka_brain's fast model. Imported here so nothing loads
    the AI provider until an utterance is actually interpreted."""
    import baka_brain
    return baka_brain.call_fast(messages, temperature=0.0, max_tokens=200)


def _extract_json(text: str) -> dict:
    """Parse a JSON object out of a model reply, tolerating ```json fences
    and surrounding prose."""
    if not text:
        raise ValueError("empty AI reply")
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(),
                     flags=re.MULTILINE).strip()
    try:
        obj = json.loads(cleaned)
    except (ValueError, TypeError):
        m = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not m:
            raise ValueError("no JSON object in AI reply")
        obj = json.loads(m.group(0))
    if not isinstance(obj, dict):
        raise ValueError("AI reply is not a JSON object")
    return obj


class LLMInterpreter(Interpreter):
    """AI-backed Interpreter with a deterministic fallback."""

    def __init__(self, ai_call=None, fallback: Interpreter | None = None,
                 min_confidence: float = 0.35):
        self._ai_call = ai_call or _default_ai_call
        self._fallback = fallback or RuleBasedInterpreter()
        self._min_confidence = min_confidence

    def interpret(self, utterance: str, context: OrchestratorContext) -> Proposal:
        try:
            reply = self._ai_call([
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": utterance or ""},
            ])
            proposal = self._parse(reply)
        except Exception:
            # Any AI/parse failure -> deterministic fallback (never break).
            return self._fallback.interpret(utterance, context)
        if proposal is None:
            return self._fallback.interpret(utterance, context)
        return proposal

    def _parse(self, reply) -> Proposal | None:
        obj = _extract_json(reply)
        action = str(obj.get("action") or "").strip().lower()
        if action not in _VALID_ACTIONS:
            return None  # unknown/invalid -> caller falls back
        params = obj.get("params") or {}
        if not isinstance(params, dict):
            params = {}
        try:
            confidence = float(obj.get("confidence", 1.0))
        except (TypeError, ValueError):
            confidence = 1.0
        if confidence < self._min_confidence:
            return None
        return Proposal(
            action=action,
            workspace_ref=obj.get("workspace_ref") or None,
            entity_ref=obj.get("entity_ref") or None,
            params={k: v for k, v in params.items() if v is not None},
            confidence=confidence,
        )
