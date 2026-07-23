"""
service.py -- Workspace Service (v15.0-alpha.1, docs/v15/WED.md §5-6).

The business-logic layer of the Workspace stack: template application,
progress rollup, and the one-shot migration/bootstrap that turns a v14
user into a v15 Workspace user without moving data. It talks only to the
Repository (never the facade or database.py directly).

    Service (here)  ->  Repository  ->  Storage Facade  ->  database.py

Feature-flag discipline: the Service reads feature_flags.WORKSPACE and
exposes `.enabled`, and `bootstrap()` is a NO-OP while the flag is OFF, so
importing or even constructing the Service never creates a workspace row
or changes v14 behaviour. Direct CRUD methods stay callable (the unit
tests exercise the infrastructure with the flag off) -- what keeps the
running bot byte-identical is simply that no v14 handler constructs this
Service yet (alpha.1 ships no handlers).
"""
from __future__ import annotations

from core import feature_flags
from core.workspace import templates
from core.workspace.models import (
    DEFAULT_WORKSPACE_TITLE,
    MS_DONE,
    Milestone,
    Workspace,
)
from core.workspace.repository import WorkspaceRepository
from core.workspace.templates.registry import (
    PROGRESS_CHAPTERS,
    PROGRESS_CHECKLIST,
    PROGRESS_MANUAL,
    PROGRESS_MILESTONES,
)


class WorkspaceService:
    """Stateless orchestrator over WorkspaceRepository."""

    def __init__(self, repo: WorkspaceRepository | None = None):
        self._repo = repo or WorkspaceRepository()

    @property
    def enabled(self) -> bool:
        """Whether the Workspace OS is switched on (feature_flags.WORKSPACE).
        The running bot gates all workspace behaviour on this; unit tests
        call the CRUD methods directly regardless."""
        return feature_flags.WORKSPACE

    # ── Creation with template application ─────────────
    def create_workspace(self, user_id, title, template="generic",
                        seed_milestones=True, metadata=None) -> Workspace:
        """Create a workspace and apply its template: adopt the template's
        default icon and, when `seed_milestones`, seed its
        `default_milestones`. Unknown template keys fall back to 'generic'
        (templates.get is total)."""
        tpl = templates.get(template)
        ws = self._repo.create_workspace(
            user_id, title=title, template=tpl.key, icon=tpl.icon,
            metadata=metadata)
        if seed_milestones and tpl.default_milestones:
            for i, ms_title in enumerate(tpl.default_milestones):
                self._repo.add_milestone(ws.id, ms_title, sort_order=i)
        return ws

    # ── Progress rollup (WED §5) ───────────────────────
    def workspace_progress(self, user_id, workspace_id) -> int:
        """Derive a workspace's 0..100 progress from its template's
        progress_model. Never hand-entered:
          - milestones/checklist: % of milestones marked done;
          - chapters: current_chapter / total_chapters from metadata;
          - manual: the workspace metadata's 'progress' value (default 0).
        Returns 0 for an unknown/empty workspace rather than raising."""
        ws = self._repo.get_workspace(workspace_id, user_id)
        if ws is None:
            return 0
        model = templates.get(ws.template).progress_model
        if model in (PROGRESS_MILESTONES, PROGRESS_CHECKLIST):
            total, done = self._repo.milestone_counts(workspace_id)
            return int(round(100 * done / total)) if total else 0
        if model == PROGRESS_CHAPTERS:
            total = _as_int(ws.metadata.get("total_chapters"))
            current = _as_int(ws.metadata.get("current_chapter"))
            return int(round(100 * current / total)) if total else 0
        if model == PROGRESS_MANUAL:
            return _clamp(_as_int(ws.metadata.get("progress")))
        return 0

    def complete_milestone(self, milestone_id) -> Milestone | None:
        """Mark a milestone done (stamps completed_at at the DB layer).
        Timeline emission (KTD) is a later phase -- kept as the single
        choke-point where it will hook in."""
        return self._repo.update_milestone(milestone_id, status=MS_DONE,
                                            progress=100)

    # ── Migration / bootstrap (MIGRATION.md) ───────────
    def bootstrap(self, user_id) -> dict:
        """Idempotently bring a user onto the Workspace model: ensure their
        Inbox exists and convert existing projects into project-workspaces.
        NO-OP while the flag is OFF (returns a skipped report), so it is
        safe to wire into startup later without affecting flag-OFF users.
        Safe to call repeatedly -- creating nothing that already exists."""
        if not self.enabled:
            return {"skipped": True, "reason": "WORKSPACE flag off"}
        inbox = self._repo.ensure_default_workspace(
            user_id, title=DEFAULT_WORKSPACE_TITLE, template="generic")
        migrated = self._repo.migrate_projects(user_id)
        return {"skipped": False, "inbox_id": inbox.id,
                "projects_migrated": migrated}

    def ensure_inbox(self, user_id) -> Workspace:
        """Return the user's Inbox workspace, creating it if absent.
        Unlike bootstrap() this is not flag-gated -- it is the primitive
        the tests and later engine use directly."""
        return self._repo.ensure_default_workspace(
            user_id, title=DEFAULT_WORKSPACE_TITLE, template="generic")


def _as_int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _clamp(value, lo=0, hi=100) -> int:
    return max(lo, min(hi, value))
