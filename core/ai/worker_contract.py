"""
worker_contract.py -- v15.2 M4 -- GLM-5.2 Worker: types (contract).

The Worker (core/ai/worker.py) is the bounded, tool-calling executor behind
the WORKER feature flag. It receives ONE normalized request, may call at most
MAX_TOOL_CALLS tools through a ToolRegistry (never the database, never
Telegram, never raw handlers), and produces one final user-facing reply.

Everything here is pure types -- no logic, no imports from main.py -- so the
contract is testable in isolation and the Worker stays a leaf module.

Design decisions (docs/engineering/V15_2_BAKA_BRAIN.md §M4):
  * MAX_TOOL_CALLS is a Python constant, NOT configurable through user input,
    a spec field, or an env flag -- a user cannot widen the bound.
  * WorkerAction/TerminationReason are stable strings (contract, not copy).
  * WorkerRequest carries ALREADY-GATHERED data (tasks/memory/history). The
    Worker NEVER opens a database; its caller (main.py) gathers the same
    snapshots it feeds get_baka_response today.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from core.ai.tools import ToolRegistry, ToolResult

# Strict cap on tool executions per request. Deliberately NOT a spec field,
# not in any prompt, and not env-configurable: the bounded loop is the
# Worker's safety story and the bound must not be widenable by any input.
#
# 6, not 4 (M4 remediation): the enumerated compound invariants top out at
# five ops (create A -> create B -> update A -> update B -> show B), so a
# budget of 4 physically cannot execute a valid compound command. The raise
# is safe because (a) the tool catalog is complete -- every op has a tool, so
# headroom never papers over a missing capability; (b) a malformed decision
# terminates as MALFORMED immediately regardless of budget (the loop returns
# on the first bad parse, it does not spend the budget); (c) the final
# compose call happens after the loop, so steps N+1..6 feed the composer the
# same way step 5 does. Compound COMMAND completion on budget exhaustion is
# handled separately by the step renderer (core/ai/worker_render.py), which
# executes-from-steps what the model only summarized -- budget is the
# precondition, not the fix.
MAX_TOOL_CALLS = 6

__all__ = [
    "MAX_TOOL_CALLS",
    "TerminationReason",
    "WorkerAction",
    "WorkerDecision",
    "WorkerRequest",
    "WorkerRunResult",
    "WorkerStep",
]


class WorkerAction(str, Enum):
    """The one thing a model decision may ask for. Nothing else is accepted."""
    TOOL = "tool"
    FINAL = "final"
    DECLINE = "decline"


class TerminationReason(str, Enum):
    """Why a run stopped. Every run ends in exactly one of these -- used for
    the structured log line and for honest user-visible fallbacks."""
    FINAL = "final"                      # model produced a final reply
    DECLINED = "declined"                # model declined; caller falls through
    MAX_STEPS = "max_steps"              # tool-call budget exhausted
    MODEL_TIMEOUT = "model_timeout"      # a model call exceeded its timeout
    MODEL_ERROR = "model_error"          # HTTP/API failure on a model call
    MALFORMED = "malformed"              # output did not parse to one decision
    EMPTY_REPLY = "empty_reply"          # model returned empty/whitespace
    UNKNOWN_TOOL = "unknown_tool"        # model named a tool that is not registered
    INVALID_ARGS_RECURRENT = "invalid_args_recurrent"  # two consecutive bad arg sets
    TOOL_FAILURE = "tool_failure"        # a tool failed in a non-recoverable way
    CONFIRMATION_NEEDED = "confirmation_needed"  # DESTRUCTIVE/spec-confirm gate
    REFERENCE_AMBIGUOUS = "reference_ambiguous"   # unresolved/stale reference
    CONTEXT_OVERFLOW = "context_overflow"  # defensive guard, never expected
    INTERNAL = "internal"                # unexpected exception inside the Worker


@dataclass(frozen=True, slots=True)
class WorkerRequest:
    """Everything the Worker may see. `text` is the raw user message; the
    snapshots (tasks/memory/history) are gathered by the CALLER so the Worker
    itself never touches a database. `ref_ctx` is the SHARED M1
    ReferenceContext -- the Worker never builds its own reference resolver.
    `typed_refs` is the SHARED per-kind TypedReferentStore (core/ai/
    typed_referents.py) that tool adapters note into and resolve against, so
    a referent produced by the CURRENT run can never be shadowed by a stale
    active entity from a previous turn (M4 requirement R5)."""
    user_id: int
    text: str
    registry: ToolRegistry
    ref_ctx: "ReferenceContext | None" = None
    projection: "object | None" = None      # duck-typed TelegramProjection
    workspace_id: "int | None" = None
    tasks: tuple = ()
    memory: tuple = ()
    history: tuple = ()
    now: "datetime | None" = None           # IST-aware
    typed_refs: "object | None" = None      # TypedReferentStore (or None → M1)


@dataclass(frozen=True, slots=True)
class WorkerDecision:
    """One parsed model decision. Syntactic only: tool membership, argument
    validity, risk gating and confirmation are policy in worker.py."""
    action: WorkerAction
    tool_name: "str | None" = None
    arguments: "dict | None" = None
    reply: "str | None" = None
    reason: "str | None" = None             # for decline/final provenance


@dataclass(frozen=True, slots=True)
class WorkerStep:
    """One observable loop step: a decision plus its ToolResult (None on the
    terminal step). This is the whole run's trace -- the final reply is
    composed from these, never from the model's memory."""
    number: int
    decision: WorkerDecision
    result: "ToolResult | None"
    duration_ms: int


@dataclass(frozen=True, slots=True)
class WorkerRunResult:
    """Outcome of one run. `handled=True` means `reply` is authoritative and
    the caller should send it; `handled=False` (only on DECLINED) means the
    caller falls through to its legacy path. On CONFIRMATION_NEEDED the caller
    must set a pending action from `confirmation_data` (never execute)."""
    handled: bool
    reply: str
    steps: "tuple[WorkerStep, ...]" = field(default_factory=tuple)
    termination: "TerminationReason | None" = None
    request_id: str = ""
    total_ms: int = 0
    confirmation_data: "dict | None" = None
