"""
worker.py -- v15.2 M4 -- GLM-5.2 Worker: the bounded, tool-calling executor.

The Worker is dormant behind feature_flags.WORKER and the owner-only canary
(main.py). When it runs, it converts ONE user message into at most
MAX_TOOL_CALLS tool calls through a ToolRegistry -- NEVER the database,
NEVER Telegram, NEVER raw handlers -- then one final reply. Its single entry
point is `Worker.run(request)`; the whole surface is the M2/M3 contract
(core/ai/tools.py + core/ai/tool_adapters.py).

Safety properties (docs/engineering/V15_2_BAKA_BRAIN.md §M4):
  * Bounded loop: MAX_TOOL_CALLS=4 is a Python constant, not widenable by
    any input; one model attempt per step (no retry storms).
  * Fail-closed execution: only ToolRegistry.execute runs tools; unknown
    names and invalid arguments terminate or feed back, never execute.
  * Confirmation gate is MECHANICAL, before execute: DESTRUCTIVE tools (and
    any tool with a confirmation_message) never run silently -- the run ends
    with CONFIRMATION_NEEDED and the caller routes through the EXISTING
    conversation_state.py machine (no second confirmation system).
  * Honesty: the final reply is guarded so success is never claimed without
    a backing ok=True ToolResult ("never fabricate success").
  * References: the Worker has NO resolver of its own; entity tools resolve
    via the shared M1 ReferenceContext. Dates: date_parser is authoritative
    (worker_prompt injects its result; the model must use it verbatim).
  * Observability: one structured log line per run with NO raw user text and
    secret-redacted arguments.
"""
from __future__ import annotations

import logging
import re
import time
from uuid import uuid4

from openai import APITimeoutError

from core.ai.tools import RiskLevel, ToolErrorCode
from core.ai.worker_contract import (
    MAX_TOOL_CALLS,
    TerminationReason,
    WorkerAction,
    WorkerDecision,
    WorkerRequest,
    WorkerRunResult,
    WorkerStep,
)
from core.ai.worker_parser import WorkerParseError, parse_decision
from core.ai.worker_prompt import build_messages

__all__ = ["Worker"]

logger = logging.getLogger("baka.worker")

# Keys that must never reach a log line, whatever a tool returns.
_SECRET_RE = re.compile(
    r"token|key|secret|password|credential|authorization|api_key|bearer",
    re.IGNORECASE)


def _redact(args: dict | None) -> dict | None:
    if not args:
        return args
    out = {}
    for k, v in args.items():
        out[k] = "[REDACTED]" if _SECRET_RE.search(str(k)) else v
    return out


# Per-termination graceful fallbacks (sent only when handled=True; main.py
# falls through to Legacy when handled=False).
_GRACEFUL = {
    TerminationReason.MODEL_TIMEOUT:
        "I couldn't finish processing that right now — try again in a moment.",
    TerminationReason.MODEL_ERROR:
        "The AI service didn't respond — try again in a moment.",
    TerminationReason.MALFORMED:
        "I didn't understand the response I got. Try rephrasing.",
    TerminationReason.EMPTY_REPLY:
        "I didn't get a response. Try again.",
    TerminationReason.UNKNOWN_TOOL:
        "I don't have that action. Could you rephrase?",
    TerminationReason.INVALID_ARGS_RECURRENT:
        "I couldn't sort out the details for that. Could you rephrase?",
    TerminationReason.TOOL_FAILURE:
        "That action didn't work. Try again or rephrase.",
    TerminationReason.REFERENCE_AMBIGUOUS:
        "I couldn't tell which one you meant. Could you clarify?",
    TerminationReason.CONTEXT_OVERFLOW:
        "That was too much for me at once — try again.",
    TerminationReason.INTERNAL:
        "Something went wrong on my side. Try again in a moment.",
}


def _graceful(term: TerminationReason) -> str:
    return _GRACEFUL.get(term, "I couldn't do that. Try again.")


# Success-claim tokens the honesty guard watches for. "done"/"ok" are too
# generic (they appear in ordinary prose) and are deliberately excluded.
_SUCCESS_CLAIMS = re.compile(
    r"\b(created|deleted|updated|saved|added|removed|completed|remembered|"
    r"forgotten|renamed|reset|started)\b", re.IGNORECASE)


def _default_timeout() -> float:
    from baka_brain import TIMEOUT_NORMAL_REASONING
    return TIMEOUT_NORMAL_REASONING


def _honest_summary(steps: tuple) -> str:
    lines = ["Here's what actually happened:"]
    for s in steps:
        r = s.result
        if r is None:
            continue
        status = "ok" if r.ok else f"failed ({r.error_code or 'tool_error'})"
        lines.append(f"  • {s.decision.tool_name} → {status}: {r.output[:160]}")
    return "\n".join(lines) if len(lines) > 1 else _graceful(TerminationReason.MAX_STEPS)


class Worker:
    """One bounded execution engine. `model_fn(messages, timeout) -> str` is
    injected so tests run on deterministic fakes; production wires
    baka_brain.call_worker_single (MODEL_MAIN, single attempt, no fallback)."""

    def __init__(self, model_fn, timeout: "float | None" = None,
                 log: "logging.Logger | None" = None):
        if model_fn is None:
            raise TypeError("Worker needs a model_fn (callable) injected")
        self._model_fn = model_fn
        self._timeout = timeout
        self._log = log or logger

    # ── public entry ───────────────────────────────────────────────────────
    def run(self, request: WorkerRequest) -> WorkerRunResult:
        start = time.perf_counter()
        request_id = uuid4().hex[:12]
        steps: list[WorkerStep] = []
        confirmation_data = None
        try:
            term, reply, confirmation_data, model_calls = self._loop(
                request, steps)
        except Exception:  # noqa: BLE001 -- the Worker must never crash the bot
            self._log.exception("[worker %s] internal failure", request_id)
            term = TerminationReason.INTERNAL
            reply = _graceful(term)
            model_calls = -1
        total_ms = int((time.perf_counter() - start) * 1000)
        self._log_structured(request_id, request, steps, term, total_ms,
                             model_calls, len(reply))
        handled = term in (TerminationReason.FINAL,
                           TerminationReason.MAX_STEPS,
                           TerminationReason.CONFIRMATION_NEEDED)
        return WorkerRunResult(
            handled=handled, reply=reply, steps=tuple(steps),
            termination=term, request_id=request_id, total_ms=total_ms,
            confirmation_data=confirmation_data)

    # ── the bounded loop ───────────────────────────────────────────────────
    def _loop(self, request: WorkerRequest,
              steps: list[WorkerStep]) -> "tuple[TerminationReason, str, dict | None, int]":
        model_calls = 0
        timeout = self._timeout if self._timeout is not None else _default_timeout()

        for n in range(1, MAX_TOOL_CALLS + 1):
            messages = build_messages(request, tuple(steps), final=False)
            model_calls += 1
            decision, err = self._one_decision(messages, timeout)
            if err is not None:
                return err, _graceful(err), None, model_calls

            if decision.action is WorkerAction.DECLINE:
                return TerminationReason.DECLINED, "", None, model_calls
            if decision.action is WorkerAction.FINAL:
                if not (decision.reply or "").strip():
                    return (TerminationReason.EMPTY_REPLY,
                            _graceful(TerminationReason.EMPTY_REPLY),
                            None, model_calls)
                return (TerminationReason.FINAL,
                        self._fabricate_guard(decision.reply, tuple(steps)),
                        None, model_calls)

            # TOOL decision.
            name = decision.tool_name
            if not request.registry.has(name):
                return (TerminationReason.UNKNOWN_TOOL,
                        _graceful(TerminationReason.UNKNOWN_TOOL), None,
                        model_calls)
            spec = request.registry.get(name).spec
            # Mechanical gate, BEFORE execute. Never "the LLM decides".
            if spec.risk is RiskLevel.DESTRUCTIVE or spec.confirmation_message is not None:
                msg = (spec.confirmation_message
                       or f"Shall I run {name} with {decision.arguments or {}}?")
                return (TerminationReason.CONFIRMATION_NEEDED, msg,
                        {"tool": name,
                         "arguments": decision.arguments or {},
                         "message": msg},
                        model_calls)

            t1 = time.perf_counter()
            result = request.registry.execute(name, decision.arguments or {})
            steps.append(WorkerStep(n, decision, result,
                                    int((time.perf_counter() - t1) * 1000)))
            if result.ok:
                continue  # feed the ok result into the next decision
            # Failure policy (docs ... §M4): recoverable failures feed back;
            # terminal ones stop now.
            if result.error_code in (ToolErrorCode.UNKNOWN_TOOL,
                                     ToolErrorCode.INTERNAL):
                return (TerminationReason.TOOL_FAILURE,
                        _graceful(TerminationReason.TOOL_FAILURE), None,
                        model_calls)
            if result.error_code == ToolErrorCode.INVALID_ARGS:
                if self._consecutive_invalid_args(steps) >= 2:
                    return (TerminationReason.INVALID_ARGS_RECURRENT,
                            _graceful(TerminationReason.INVALID_ARGS_RECURRENT),
                            None, model_calls)
            # else: loop continues; the step trace (incl. this failure) is fed
            # to the next model call so it can correct the arguments.

        # Budget exhausted: ONE final composition call, then an honest summary.
        messages = build_messages(request, tuple(steps), final=True)
        model_calls += 1
        decision, err = self._one_decision(messages, timeout)
        if err is not None:
            return (TerminationReason.MAX_STEPS,
                    _honest_summary(tuple(steps)) or _graceful(
                        TerminationReason.MAX_STEPS),
                    None, model_calls)
        if decision.action is WorkerAction.FINAL and (decision.reply or "").strip():
            return (TerminationReason.MAX_STEPS,
                    self._fabricate_guard(decision.reply, tuple(steps)),
                    None, model_calls)
        return (TerminationReason.MAX_STEPS,
                _honest_summary(tuple(steps)) or _graceful(
                    TerminationReason.MAX_STEPS),
                None, model_calls)

    def _one_decision(self, messages: list[dict], timeout: float
                      ) -> "tuple[WorkerDecision | None, TerminationReason | None]":
        """One model call → (decision, None) or (None, termination reason).
        Exactly one attempt: no retry, no fallback model."""
        try:
            text = self._model_fn(messages, timeout)
        except APITimeoutError:
            return None, TerminationReason.MODEL_TIMEOUT
        except Exception:  # noqa: BLE001 -- any API/transport failure
            return None, TerminationReason.MODEL_ERROR
        if not text or not text.strip():
            return None, TerminationReason.EMPTY_REPLY
        try:
            return parse_decision(text), None
        except WorkerParseError:
            return None, TerminationReason.MALFORMED

    # ── honesty guard ──────────────────────────────────────────────────────
    def _fabricate_guard(self, reply: str, steps: tuple) -> str:
        """Deterministic guard, not an LLM check: if the reply claims a
        success action but NO tool in the trace succeeded, rewrite it to an
        honest statement. Prevents 'Xiao created successfully' with no backing
        result."""
        if _SUCCESS_CLAIMS.search(reply) and not any(
                s.result is not None and s.result.ok for s in steps):
            base = "I couldn't complete that — nothing actually succeeded."
            summary = _honest_summary(steps) if steps else ""
            return f"{base}\n{summary}" if summary else base
        return reply

    @staticmethod
    def _consecutive_invalid_args(steps: list) -> int:
        count = 0
        for s in reversed(steps):
            r = s.result
            if (r is not None and not r.ok
                    and r.error_code == ToolErrorCode.INVALID_ARGS):
                count += 1
            else:
                break
        return count

    # ── observability (NO raw user text, secrets redacted) ─────────────────
    def _log_structured(self, request_id, request, steps, term, total_ms,
                        model_calls, reply_len) -> None:
        step_log = []
        for s in steps:
            r = s.result
            step_log.append({
                "step": s.number,
                "action": s.decision.action.value,
                "tool": s.decision.tool_name,
                "args": _redact(s.decision.arguments),
                "ok": bool(r.ok) if r else None,
                "error_code": r.error_code if r else None,
                "duration_ms": s.duration_ms,
            })
        # user text is intentionally absent from this line.
        self._log.info(
            "[worker %s] user=%s workspace=%s termination=%s total_ms=%s "
            "model_calls=%s steps=%s reply_len=%s",
            request_id, request.user_id, request.workspace_id, term.value,
            total_ms, model_calls, step_log, reply_len)
