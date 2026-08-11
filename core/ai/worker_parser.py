"""
worker_parser.py -- v15.2 M4 -- GLM-5.2 Worker: robust structured-output parser.

Parses the model's decision output into ONE WorkerDecision. This module
exists specifically because baka_brain.clean_json() (the legacy extractor)
uses a greedy `find("{") / rfind("}")` slice that silently corrupts any
output containing more than one JSON object (the F1 failure class documented
in docs/engineering/AI_WORKER_AUDIT.md). This parser is deterministic and
fail-closed instead:

  * Fenced (```json / ```), bare, prose-wrapped, and multi-JSON output are
    all handled WITHOUT greedy regex.
  * Exactly one well-formed top-level JSON object is accepted.
  * Zero objects, a top-level array, unbalanced/malformed text, or MORE THAN
    ONE object is an error -- never a guess. A duplicated or ambiguous
    decision is exactly the bug we refuse to reintroduce, so "last one wins"
    is deliberately not a policy.
  * Syntactic validation only: action/tool/arguments shapes. Tool NAME
    membership and argument schema validity are policy in worker.py (so
    UNKNOWN_TOOL stays distinct from MALFORMED), and argument values are
    validated fail-closed by the ToolRegistry on execute.
  * A nested key named "tool" or "action" inside `arguments` is DATA, never
    the decision -- tool-name injection cannot redirect execution.
"""
from __future__ import annotations

import json
import re

from core.ai.worker_contract import WorkerAction, WorkerDecision

__all__ = ["WorkerParseError", "extract_single_object", "parse_decision"]

_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*$")   # ``` or ```json opening line


class WorkerParseError(ValueError):
    """The model output did not parse to exactly one valid decision."""


# ── JSON run extraction (no greedy regex) ─────────────────────────────────
def _scan_json_runs(text: str) -> list[tuple[int, int]]:
    """Find every well-formed top-level JSON run by tracking a nesting stack
    through strings and escape sequences. Returns (start, end) exclusive-end
    spans. Prose between/around runs is ignored; a mismatched close resets
    the current candidate (the run is malformed)."""
    runs: list[tuple[int, int]] = []
    stack: list[str] = []
    start: int | None = None
    in_string = False
    escaped = False
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch in "{[":
                if not stack:
                    start = i
                stack.append(ch)
            elif ch in "}]":
                if stack:
                    expected = "}" if stack[-1] == "{" else "]"
                    if ch == expected:
                        stack.pop()
                        if not stack and start is not None:
                            runs.append((start, i + 1))
                            start = None
                    else:
                        stack.clear()
                        start = None
        i += 1
    return runs


def _strip_fences(text: str) -> str:
    """Remove a single ```json / ``` fence wrapper if present so the fast
    json.loads path works on the common clean-output case. The scanner below
    would find the object inside the fences anyway; this only optimizes it."""
    t = text.strip()
    if t.startswith("```"):
        end = t.rfind("```")
        if end > 0:
            body = t[3:end]
            nl = body.find("\n")
            first = body[:nl].strip() if nl >= 0 else body.strip()
            if first.lower() in ("", "json", "text"):
                return body[nl + 1:].strip() if nl >= 0 else ""
    return t


def extract_single_object(text: str) -> dict:
    """The ONE well-formed top-level JSON object in `text`, or raise
    WorkerParseError. Fail-closed: zero runs, a top-level array, or multiple
    objects are all errors."""
    if not text or not text.strip():
        raise WorkerParseError("empty model output")
    cleaned = _strip_fences(text)

    try:  # fast path: the whole cleaned text is one object
        obj = json.loads(cleaned)
        if isinstance(obj, dict):
            return obj
        if isinstance(obj, list):
            raise WorkerParseError("top-level array is not a decision")
    except json.JSONDecodeError:
        pass

    objects: list[tuple[int, dict]] = []
    for s, e in _scan_json_runs(cleaned):
        chunk = cleaned[s:e]
        try:
            obj = json.loads(chunk)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            objects.append((s, obj))

    if not objects:
        raise WorkerParseError("no well-formed JSON object found")
    if len(objects) > 1:
        raise WorkerParseError(
            f"{len(objects)} top-level JSON objects (ambiguous; refusing to guess)")
    return objects[0][1]


# ── Decision parsing ──────────────────────────────────────────────────────
def parse_decision(text: str) -> WorkerDecision:
    """Parse model output into a WorkerDecision. Raises WorkerParseError on
    any syntactic violation (missing/invalid action, non-object arguments,
    non-string tool/reply). Tool membership is NOT checked here -- worker.py
    turns an unknown name into TerminationReason.UNKNOWN_TOOL."""
    obj = extract_single_object(text)

    action = obj.get("action")
    if not isinstance(action, str) or not action.strip():
        raise WorkerParseError("missing or non-string 'action'")
    action = action.strip().lower()
    try:
        act = WorkerAction(action)
    except ValueError:
        raise WorkerParseError(f"unknown action {action!r}")

    if act is WorkerAction.TOOL:
        tool = obj.get("tool")
        if not isinstance(tool, str) or not tool.strip():
            raise WorkerParseError("tool decision without a tool name")
        args = obj.get("arguments")
        if args is None:
            args = {}
        if not isinstance(args, dict):
            raise WorkerParseError("tool decision with non-object 'arguments'")
        return WorkerDecision(action=act, tool_name=tool.strip(), arguments=args)

    if act is WorkerAction.FINAL:
        reply = obj.get("reply")
        if not isinstance(reply, str):
            raise WorkerParseError("final decision without a string 'reply'")
        return WorkerDecision(action=act, reply=reply)

    # DECLINE: reason is optional provenance only
    reason = obj.get("reason")
    return WorkerDecision(action=act, reason=reason if isinstance(reason, str) else None)
