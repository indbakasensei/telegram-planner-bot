"""
orchestrator.py -- the AI Workspace Orchestrator (v15.0-alpha.7,
docs/v15/AWOD.md).

The GENERIC layer that turns a natural-language utterance into a validated
Entity Engine operation. It sits ABOVE the engine and runs the AWOD
resolver pipeline: interpret -> select workspace -> resolve entity -> plan
-> safety gate -> apply. It is deliberately template-AGNOSTIC: a fixed set
of generic actions (create/rename/archive/complete workspace; add/complete/
archive/delete milestone; add note) mapped to generic engine calls. There
is NO book/game/project logic here -- every future template reuses this
same orchestration unchanged.

"AI proposes, the engine disposes": the AI's job is only to produce a
`Proposal`; this orchestrator re-resolves and re-validates everything
against real data and applies it through the Entity Engine (which enforces
ownership, lifecycle, and emits events). The AI model itself is injected as
an `Interpreter` -- this module never calls the live LLM/NIM, so it stays
offline-testable. A deterministic `RuleBasedInterpreter` ships as the
default; an LLM-backed interpreter plugs into the same contract later (a
user-facing wiring step, out of scope here).

Nothing here is wired into the running bot and no user-facing controls are
added; with `WORKSPACE` OFF nothing constructs it, so behaviour is
byte-identical.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from core.workspace.engine import EntityEngine
from core.workspace.errors import EntityError, EntityValidationError


# ── Generic actions (no template specifics) ───────────────────────────────
class Action:
    CREATE_WORKSPACE = "create_workspace"
    RENAME_WORKSPACE = "rename_workspace"
    ARCHIVE_WORKSPACE = "archive_workspace"
    COMPLETE_WORKSPACE = "complete_workspace"
    ADD_MILESTONE = "add_milestone"
    COMPLETE_MILESTONE = "complete_milestone"
    ARCHIVE_MILESTONE = "archive_milestone"
    DELETE_MILESTONE = "delete_milestone"
    ADD_NOTE = "add_note"
    UNKNOWN = "unknown"


# Actions whose target is an existing milestone (need entity resolution).
_MILESTONE_TARGET = frozenset({
    Action.COMPLETE_MILESTONE, Action.ARCHIVE_MILESTONE, Action.DELETE_MILESTONE,
})
# Irreversible-ish actions that require explicit confirmation (AWOD §4.1).
_IRREVERSIBLE = frozenset({
    Action.ARCHIVE_WORKSPACE, Action.ARCHIVE_MILESTONE, Action.DELETE_MILESTONE,
})


class Status:
    APPLIED = "applied"
    NEEDS_CONFIRMATION = "needs_confirmation"
    NEEDS_CLARIFICATION = "needs_clarification"
    REJECTED = "rejected"        # understood but invalid input
    FAILED = "failed"            # engine refused (e.g. illegal transition)


@dataclass(frozen=True, slots=True)
class OrchestratorContext:
    user_id: int
    active_workspace_id: int | None = None


@dataclass(frozen=True, slots=True)
class Proposal:
    """What the interpreter (AI or rule-based) proposes. Just a proposal --
    the orchestrator re-validates everything before applying."""
    action: str
    workspace_ref: str | None = None   # a workspace title the user named
    entity_ref: str | None = None      # a milestone title the user named
    params: dict = field(default_factory=dict)
    confidence: float = 1.0


@dataclass(frozen=True, slots=True)
class OrchestratorResult:
    status: str
    message: str
    workspace: object | None = None
    entity: object | None = None
    proposal: Proposal | None = None
    options: tuple = ()
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == Status.APPLIED


# ── Interpreter contract ──────────────────────────────────────────────────
class Interpreter(ABC):
    """Turns an utterance into a Proposal. The AI model implements this;
    the orchestrator depends only on the contract, never the model."""

    @abstractmethod
    def interpret(self, utterance: str, context: OrchestratorContext) -> Proposal:
        ...


class RuleBasedInterpreter(Interpreter):
    """A deterministic, offline, GENERIC interpreter -- the default and the
    test double. Maps leading verbs to actions; no template-specific
    knowledge. An LLM-backed interpreter implements the same contract
    later without touching the orchestrator."""

    def interpret(self, utterance: str, context: OrchestratorContext) -> Proposal:
        text = (utterance or "").strip()
        if not text:
            return Proposal(Action.UNKNOWN, confidence=0.0)

        workspace_ref = None
        # Optional "in <workspace>, <rest>" / "in <workspace>: <rest>" prefix.
        m = re.match(r"(?i)^in\s+(.+?)\s*[,:]\s*(.+)$", text)
        if m:
            workspace_ref, text = m.group(1).strip(), m.group(2).strip()

        low = text.lower()

        def after(*keywords):
            for kw in keywords:
                mm = re.match(rf"(?i)^{kw}\b[:\s]*(.+)$", text)
                if mm:
                    return mm.group(1).strip().strip("'\"")
            return None

        # Notes.
        note = after("note", "add note", "add a note")
        if note is not None:
            return Proposal(Action.ADD_NOTE, workspace_ref, params={"content": note})

        # Workspace-level.
        title = after("create workspace", "new workspace", "create a workspace")
        if title is not None:
            return Proposal(Action.CREATE_WORKSPACE, params={"title": title})
        rename = after("rename to", "rename workspace to", "rename this to")
        if rename is not None:
            return Proposal(Action.RENAME_WORKSPACE, workspace_ref,
                            params={"title": rename})
        if re.search(r"(?i)\barchive (this |the )?workspace\b", low):
            return Proposal(Action.ARCHIVE_WORKSPACE, workspace_ref)
        if re.search(r"(?i)\b(complete|finish|close) (this |the )?workspace\b", low):
            return Proposal(Action.COMPLETE_WORKSPACE, workspace_ref)

        # Milestones.
        ms = after("add milestone", "add step", "new milestone")
        if ms is not None:
            return Proposal(Action.ADD_MILESTONE, workspace_ref, params={"title": ms})
        target = after("delete milestone", "remove milestone")
        if target is not None:
            return Proposal(Action.DELETE_MILESTONE, workspace_ref, entity_ref=target)
        target = after("archive milestone")
        if target is not None:
            return Proposal(Action.ARCHIVE_MILESTONE, workspace_ref, entity_ref=target)
        target = after("complete milestone", "finish milestone", "finished",
                       "completed", "done with", "complete")
        if target is not None:
            return Proposal(Action.COMPLETE_MILESTONE, workspace_ref, entity_ref=target)

        return Proposal(Action.UNKNOWN, workspace_ref, confidence=0.0)


# ── The orchestrator ──────────────────────────────────────────────────────
class WorkspaceOrchestrator:
    """Runs the AWOD resolver pipeline over an injected interpreter and the
    Entity Engine. Stateless."""

    def __init__(self, engine: EntityEngine | None = None,
                 interpreter: Interpreter | None = None,
                 min_confidence: float = 0.5):
        self._engine = engine or EntityEngine()
        self._interpreter = interpreter or RuleBasedInterpreter()
        self._min_confidence = min_confidence

    def handle(self, user_id, utterance, active_workspace_id=None,
               confirm=False) -> OrchestratorResult:
        ctx = OrchestratorContext(user_id, active_workspace_id)

        # 1. Intent recognition.
        proposal = self._interpreter.interpret(utterance, ctx)
        if (proposal.action == Action.UNKNOWN
                or proposal.confidence < self._min_confidence):
            return OrchestratorResult(
                Status.NEEDS_CLARIFICATION,
                "I didn't understand that — could you rephrase?",
                proposal=proposal)

        # create needs no existing workspace.
        if proposal.action == Action.CREATE_WORKSPACE:
            return self._apply_create(user_id, proposal)

        # 2. Workspace selection.
        ws, clar = self._select_workspace(user_id, proposal, ctx)
        if clar is not None:
            return clar

        # 3. Entity resolution (milestone-target actions only).
        milestone = None
        if proposal.action in _MILESTONE_TARGET:
            milestone, clar = self._resolve_milestone(user_id, ws, proposal)
            if clar is not None:
                return clar

        # 4-5. Safety gate: irreversible actions need explicit confirmation.
        if proposal.action in _IRREVERSIBLE and not confirm:
            return OrchestratorResult(
                Status.NEEDS_CONFIRMATION,
                self._confirm_prompt(proposal, ws, milestone),
                workspace=ws, entity=milestone, proposal=proposal)

        # 6. Apply + cascade (engine emits events -> Timeline/Sync if wired).
        return self._apply(user_id, ws, proposal, milestone)

    # ── resolvers ──────────────────────────────────────
    def _select_workspace(self, user_id, proposal, ctx):
        if proposal.workspace_ref:
            matches = self._match_workspaces(user_id, proposal.workspace_ref)
            if not matches:
                return None, OrchestratorResult(
                    Status.NEEDS_CLARIFICATION,
                    f"I couldn't find a workspace matching "
                    f"'{proposal.workspace_ref}'.")
            if len(matches) > 1:
                return None, OrchestratorResult(
                    Status.NEEDS_CLARIFICATION,
                    "Which workspace did you mean?",
                    options=tuple(w.title for w in matches))
            return matches[0], None
        if ctx.active_workspace_id is not None:
            ws = self._engine.get_workspace_or_none(user_id, ctx.active_workspace_id)
            if ws is not None:
                return ws, None
        return None, OrchestratorResult(
            Status.NEEDS_CLARIFICATION, "Which workspace should I use?")

    def _match_workspaces(self, user_id, ref):
        ref_l = ref.lower().strip()
        active = self._engine.list_workspaces(user_id, status=None)
        exact = [w for w in active if w.title.lower() == ref_l]
        if exact:
            return exact
        return [w for w in active if ref_l in w.title.lower()]

    def _resolve_milestone(self, user_id, ws, proposal):
        ref = (proposal.entity_ref or "").lower().strip()
        milestones = self._engine.list_milestones(user_id, ws.id)
        if not ref:
            return None, OrchestratorResult(
                Status.NEEDS_CLARIFICATION, "Which milestone?",
                options=tuple(m.title for m in milestones))
        exact = [m for m in milestones if m.title.lower() == ref]
        matches = exact or [m for m in milestones if ref in m.title.lower()]
        if not matches:
            return None, OrchestratorResult(
                Status.NEEDS_CLARIFICATION,
                f"I couldn't find a milestone matching '{proposal.entity_ref}' "
                f"in '{ws.title}'.",
                options=tuple(m.title for m in milestones))
        if len(matches) > 1:
            return None, OrchestratorResult(
                Status.NEEDS_CLARIFICATION, "Which milestone did you mean?",
                options=tuple(m.title for m in matches))
        return matches[0], None

    # ── apply ──────────────────────────────────────────
    def _apply_create(self, user_id, proposal):
        title = (proposal.params.get("title") or "").strip()
        if not title:
            return OrchestratorResult(
                Status.NEEDS_CLARIFICATION, "What should the workspace be called?")
        try:
            ws = self._engine.create_workspace(
                user_id, title,
                template=proposal.params.get("template", "generic"))
        except EntityValidationError as e:
            return OrchestratorResult(Status.REJECTED, str(e), error=str(e))
        return OrchestratorResult(
            Status.APPLIED, f"Created workspace '{ws.title}'.", workspace=ws)

    def _apply(self, user_id, ws, proposal, milestone):
        a = proposal.action
        p = proposal.params
        try:
            if a == Action.RENAME_WORKSPACE:
                w = self._engine.rename_workspace(user_id, ws.id, p.get("title", ""))
                return OrchestratorResult(
                    Status.APPLIED, f"Renamed workspace to '{w.title}'.", workspace=w)
            if a == Action.ARCHIVE_WORKSPACE:
                w = self._engine.archive_workspace(user_id, ws.id)
                return OrchestratorResult(
                    Status.APPLIED, f"Archived workspace '{w.title}'.", workspace=w)
            if a == Action.COMPLETE_WORKSPACE:
                w = self._engine.complete_workspace(user_id, ws.id)
                return OrchestratorResult(
                    Status.APPLIED, f"Marked workspace '{w.title}' done.", workspace=w)
            if a == Action.ADD_MILESTONE:
                m = self._engine.add_milestone(user_id, ws.id, p.get("title", ""))
                return OrchestratorResult(
                    Status.APPLIED, f"Added milestone '{m.title}'.",
                    workspace=ws, entity=m)
            if a == Action.ADD_NOTE:
                n = self._engine.add_note(user_id, ws.id, p.get("content", ""))
                return OrchestratorResult(
                    Status.APPLIED, "Note added.", workspace=ws, entity=n)
            if a == Action.COMPLETE_MILESTONE:
                m = self._engine.complete_milestone(user_id, milestone.id)
                return OrchestratorResult(
                    Status.APPLIED, f"Completed milestone '{m.title}'.",
                    workspace=ws, entity=m)
            if a == Action.ARCHIVE_MILESTONE:
                m = self._engine.archive_milestone(user_id, milestone.id)
                return OrchestratorResult(
                    Status.APPLIED, f"Archived milestone '{m.title}'.",
                    workspace=ws, entity=m)
            if a == Action.DELETE_MILESTONE:
                m = self._engine.delete_milestone(user_id, milestone.id)
                return OrchestratorResult(
                    Status.APPLIED, f"Deleted milestone '{m.title}'.",
                    workspace=ws, entity=m)
        except EntityValidationError as e:
            return OrchestratorResult(Status.REJECTED, str(e), error=str(e))
        except EntityError as e:
            return OrchestratorResult(Status.FAILED, str(e), error=str(e))
        return OrchestratorResult(
            Status.FAILED, f"Unsupported action: {a}", error="unsupported")

    def _confirm_prompt(self, proposal, ws, milestone):
        if proposal.action == Action.ARCHIVE_WORKSPACE:
            return f"Archive workspace '{ws.title}'? This hides it from active views."
        if proposal.action == Action.ARCHIVE_MILESTONE:
            return f"Archive milestone '{milestone.title}'?"
        if proposal.action == Action.DELETE_MILESTONE:
            return f"Delete milestone '{milestone.title}'? (it can be recovered)"
        return "Confirm this action?"
