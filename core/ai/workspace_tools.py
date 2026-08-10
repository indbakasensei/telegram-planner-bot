"""
workspace_tools.py -- grounded Workspace tools for the Cognitive Engine
(v15.1.0-alpha.3, Phase 1).

Each tool is a thin, read-mostly wrapper over an existing Workspace API
(the Entity Engine / Storage Facade). The tools are the ONLY way the
Cognitive Engine touches Workspace data, which is exactly how the design
principle "the AI is never the database / never the business logic" is
enforced structurally: the model chooses *which* tool to call, but every
fact in the answer comes from real Workspace state. A tool never invents
data -- when nothing exists it says so plainly (Safety, PART 8).

Tools are built per request and bound to (engine, user_id, active
workspace) so `user_id` is never a model-facing argument. The model only
supplies domain args like a workspace name or a status.
"""
from __future__ import annotations

from core.ai.tools import RiskLevel, Tool, ToolRegistry, ToolSpec
from core.storage import Storage
from core.workspace.engine import EntityEngine

ENTITY_TYPE = "milestone"   # a workspace "entity"/"component" is a milestone


class _WSTool(Tool):
    """Base: resolves a workspace from a name/#id arg, else the active one,
    else the sole workspace if there's exactly one."""

    def __init__(self, engine: EntityEngine, user_id: int,
                 active_ws_id: int | None = None, storage: Storage | None = None):
        self._eng = engine
        self._uid = user_id
        self._active = active_ws_id
        self._s = storage or Storage()

    def _workspaces(self):
        return self._eng.list_workspaces(self._uid, status=None)

    def _resolve_ws(self, ref=None):
        wss = self._workspaces()
        if ref:
            r = str(ref).strip().lower()
            if r.isdigit():
                return next((w for w in wss if w.id == int(r)), None)
            exact = [w for w in wss if w.title.lower() == r]
            if exact:
                return exact[0]
            partial = [w for w in wss if r in w.title.lower()]
            return partial[0] if len(partial) == 1 else None
        if self._active is not None:
            return next((w for w in wss if w.id == self._active), None)
        return wss[0] if len(wss) == 1 else None


class ListWorkspacesTool(_WSTool):
    @property
    def spec(self):
        return ToolSpec("list_workspaces",
                        "List the user's workspaces (projects/games/goals).")

    def run(self, **kwargs):
        wss = self._workspaces()
        if not wss:
            return "You have no workspaces yet."
        return "Workspaces: " + "; ".join(
            f"{w.title} ({w.template}, #{w.id})" for w in wss)


class WorkspaceOverviewTool(_WSTool):
    @property
    def spec(self):
        return ToolSpec(
            "workspace_overview",
            "Progress and entity counts for one workspace.",
            {"type": "object", "properties": {
                "workspace": {"type": "string",
                              "description": "workspace name or #id; omit for the active one"}}})

    def run(self, workspace=None, **kwargs):
        ws = self._resolve_ws(workspace)
        if ws is None:
            return self._which(workspace)
        prog = self._eng.workspace_progress(self._uid, ws.id)
        ms = self._eng.list_milestones(self._uid, ws.id)
        done = sum(1 for m in ms if m.status == "done")
        blocked = sum(1 for m in ms if m.status == "blocked")
        extra = f", {blocked} blocked" if blocked else ""
        return (f"{ws.title}: {prog}% complete · {len(ms)} entities "
                f"({done} done{extra}).")

    def _which(self, ref):
        if ref:
            return f"I couldn't find a workspace matching '{ref}'."
        return "Which workspace? Open one first (e.g. 'open Drone')."


class ListEntitiesTool(_WSTool):
    @property
    def spec(self):
        return ToolSpec(
            "list_entities",
            "List a workspace's entities (components/characters/milestones), "
            "optionally filtered by status (todo/in_progress/done/blocked).",
            {"type": "object", "properties": {
                "workspace": {"type": "string"},
                "status": {"type": "string",
                           "enum": ["todo", "in_progress", "done", "blocked"]}}})

    def run(self, workspace=None, status=None, **kwargs):
        ws = self._resolve_ws(workspace)
        if ws is None:
            return WorkspaceOverviewTool._which(self, workspace)
        ms = self._eng.list_milestones(self._uid, ws.id)
        if status:
            s = str(status).strip().lower()
            hit = [m for m in ms if m.status == s]
            if not hit:
                return f"No {s} entities in {ws.title}."
            return f"{s.replace('_', ' ').title()} in {ws.title}: " + \
                   ", ".join(m.title for m in hit)
        if not ms:
            return f"{ws.title} has no entities yet."
        return f"Entities in {ws.title}: " + \
               ", ".join(f"{m.title} [{m.status}]" for m in ms)


class RecentNotesTool(_WSTool):
    @property
    def spec(self):
        return ToolSpec(
            "recent_notes",
            "The most recent progress notes for a workspace.",
            {"type": "object", "properties": {
                "workspace": {"type": "string"},
                "limit": {"type": "integer"}}})

    def run(self, workspace=None, limit=5, **kwargs):
        ws = self._resolve_ws(workspace)
        if ws is None:
            return WorkspaceOverviewTool._which(self, workspace)
        notes = self._eng.list_notes(self._uid, ws.id)
        if not notes:
            return f"No notes logged in {ws.title} yet."
        try:
            n = max(1, int(limit))
        except (TypeError, ValueError):
            n = 5
        recent = notes[-n:]
        return f"Recent in {ws.title}: " + " | ".join(x.content for x in recent)


class OpenWorkspaceTool(_WSTool):
    """Sets the active workspace -- the conversation-context write that makes
    later questions resolve without naming the workspace again (PART 7).

    v15.2 M3: reclassified READ_ONLY → MUTATING. open_workspace persists the
    active-workspace context (tg_bindings.set_active); it changes state, so
    the default READ_ONLY risk was dishonest. The /ws engine calls run()
    directly (never Tool.execute), so /ws behavior is unchanged."""

    @property
    def spec(self):
        return ToolSpec(
            "open_workspace",
            "Make a workspace the active one for this conversation.",
            {"type": "object", "properties": {"workspace": {"type": "string"}}},
            risk=RiskLevel.MUTATING)

    def run(self, workspace=None, **kwargs):
        ws = self._resolve_ws(workspace)
        if ws is None:
            return f"I couldn't find a workspace matching '{workspace}'."
        self._s.tg_bindings.set_active(self._uid, ws.id)
        return f"Opened {ws.title}. It's now the active workspace."


def build_workspace_registry(engine, user_id, active_ws_id=None,
                             storage=None) -> ToolRegistry:
    """A per-request registry of grounded Workspace tools bound to this user
    and active workspace. Includes the retrieval-backed `recall` tool for
    broad questions (v15.1.0-alpha.8)."""
    reg = ToolRegistry()
    for cls in (ListWorkspacesTool, WorkspaceOverviewTool, ListEntitiesTool,
                RecentNotesTool, OpenWorkspaceTool):
        reg.register(cls(engine, user_id, active_ws_id, storage))
    # Real retrieval across all stored workspace data.
    from core.ai.workspace_retriever import RecallTool, WorkspaceRetriever
    reg.register(RecallTool(WorkspaceRetriever(user_id, engine, storage)))
    return reg
