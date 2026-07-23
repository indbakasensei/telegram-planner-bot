"""
project_adapter.py -- Project <-> Workspace integration (v15.0-alpha.3).

Proves that the Workspace architecture can transparently REPLACE the v14
Project backend. A v14 "project" is a goal that has materials/worklog; v15
routes it through the Workspace layer by making a template='project'
workspace its container, linked to the goal via `goals.workspace_id`. The
project's data (materials, worklog, progress) is NOT moved -- this adapter
reads/writes it through the existing project functions (via the Storage
Facade), keyed by the goal the workspace resolves to. Same data, new lens
(WED §8, MIGRATION.md §3).

Scope guardrails for this milestone:
  - NO milestones (projects create their workspace with seed_milestones=
    False; project progress stays the v14 materials/worklog computation,
    not a milestone rollup).
  - NO timeline, Telegram, or AI -- those are later phases.
  - Flag OFF: this adapter is never constructed by the running bot, so the
    legacy /projects path is byte-identical. Flag ON: the same operations
    can be served through the workspace layer with identical results.
"""
from __future__ import annotations

from dataclasses import dataclass

from core import feature_flags
from core.storage import Storage
from core.workspace.engine import EntityEngine
from core.workspace.errors import EntityNotFound
from core.workspace.models import Workspace
from core.workspace.repository import WorkspaceRepository

PROJECT_TEMPLATE = "project"


def use_workspace_projects() -> bool:
    """Whether the running bot should route projects through the Workspace
    layer. The later user-facing phase gates its handler swap on this; with
    the flag OFF the legacy path is used and this adapter is dormant."""
    return feature_flags.WORKSPACE


@dataclass(frozen=True, slots=True)
class ProjectView:
    """A project seen through the Workspace layer: the workspace container
    plus the backing goal's project data (assembled from the v14 overview,
    unchanged)."""
    workspace: Workspace
    goal_id: int
    title: str
    deadline: str | None
    progress: int
    materials_acquired: int
    materials_total: int
    work_state: str


class ProjectAdapter:
    """Serves project operations through the Workspace layer, delegating
    project data to the existing project functions via the facade."""

    def __init__(self, storage: Storage | None = None,
                 engine: EntityEngine | None = None):
        self._s = storage or Storage()
        self._repo = WorkspaceRepository(self._s)
        self._engine = engine or EntityEngine(repo=self._repo)

    @property
    def enabled(self) -> bool:
        return feature_flags.WORKSPACE

    # ── Creation & lookup ──────────────────────────────
    def create_project(self, user_id, title, deadline=None) -> ProjectView:
        """Create a project AS a workspace: a backing goal + a
        template='project' workspace (no milestones), linked. Returns the
        assembled ProjectView."""
        goal_id = self._s.goals.add(user_id, title, deadline)
        ws = self._engine.create_workspace(
            user_id, title, template=PROJECT_TEMPLATE, seed_milestones=False)
        self._repo.link_goal_to_workspace(user_id, goal_id, ws.id)
        return self._view(user_id, ws, goal_id)

    def get_project(self, user_id, workspace_id) -> ProjectView | None:
        goal_id = self._repo.goal_id_for_workspace(user_id, workspace_id)
        ws = self._engine.get_workspace_or_none(user_id, workspace_id)
        if goal_id is None or ws is None:
            return None
        return self._view(user_id, ws, goal_id)

    def list_projects(self, user_id) -> list[ProjectView]:
        """Every project-template workspace, as ProjectViews."""
        out = []
        for ws in self._engine.list_workspaces(user_id, status=None):
            if ws.template != PROJECT_TEMPLATE:
                continue
            goal_id = self._repo.goal_id_for_workspace(user_id, ws.id)
            if goal_id is not None:
                out.append(self._view(user_id, ws, goal_id))
        return out

    def goal_id(self, user_id, workspace_id) -> int:
        """Resolve the backing goal for a project workspace, or raise
        EntityNotFound (not a project workspace / not owned)."""
        gid = self._repo.goal_id_for_workspace(user_id, workspace_id)
        if gid is None:
            raise EntityNotFound(f"project workspace {workspace_id}")
        return gid

    # ── Project data, addressed by workspace (delegates to v14) ──
    def add_materials(self, user_id, workspace_id, names, quantity=1):
        return self._s.projects.add_materials(
            user_id, self.goal_id(user_id, workspace_id), names, quantity)

    def get_materials(self, user_id, workspace_id):
        return self._s.projects.get_materials(
            user_id, self.goal_id(user_id, workspace_id))

    def add_worklog(self, user_id, workspace_id, entry, kind="note"):
        return self._s.projects.add_worklog(
            user_id, self.goal_id(user_id, workspace_id), entry, kind)

    def get_worklog(self, user_id, workspace_id, limit=20):
        return self._s.projects.get_worklog(
            user_id, self.goal_id(user_id, workspace_id), limit)

    def progress(self, user_id, workspace_id) -> int:
        """Project progress: the v14 materials/worklog computation (NOT a
        milestone rollup), so it matches the legacy /projects value."""
        return self._s.projects.compute_progress(
            user_id, self.goal_id(user_id, workspace_id))[0]

    def overview(self, user_id, workspace_id) -> dict | None:
        """The v14 project overview dict, annotated with workspace_id."""
        goal_id = self._repo.goal_id_for_workspace(user_id, workspace_id)
        if goal_id is None:
            return None
        ov = self._s.projects.get_overview(user_id, goal_id)
        if ov is not None:
            ov = dict(ov)
            ov["workspace_id"] = workspace_id
        return ov

    # ── Migration ──────────────────────────────────────
    def migrate(self, user_id) -> int:
        """Convert this user's legacy projects into project workspaces
        (idempotent). Returns the number created this call."""
        return self._repo.migrate_projects(user_id)

    def verify_migration(self, user_id) -> dict:
        """Integrity report: no unmigrated projects, no orphan project
        workspaces (report['ok'] is the transparent-replacement proof)."""
        return self._repo.verify_project_migration(user_id)

    # ── internal ───────────────────────────────────────
    def _view(self, user_id, ws: Workspace, goal_id: int) -> ProjectView:
        ov = self._s.projects.get_overview(user_id, goal_id) or {}
        return ProjectView(
            workspace=ws,
            goal_id=goal_id,
            title=ov.get("title", ws.title),
            deadline=ov.get("deadline"),
            progress=ov.get("progress", 0),
            materials_acquired=ov.get("materials_acquired", 0),
            materials_total=ov.get("materials_total", 0),
            work_state=ov.get("work_state", "not started"),
        )
