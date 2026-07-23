"""
service.py -- Workspace Service (v15.0-alpha.1, refactored onto the
Entity Engine in v15.0-alpha.2).

The use-case / orchestration layer of the Workspace stack. As of alpha.2
it no longer performs entity mutations directly -- it composes an
`EntityEngine` (the reusable core) and delegates create/progress/
lifecycle to it, keeping only the higher-level concerns that aren't a
single entity operation: the flag-gated migration bootstrap and the
Inbox primitive.

    Service (use-cases)  ->  EntityEngine (validation + lifecycle + events)
                         ->  Repository  ->  Storage Facade  ->  database.py

Feature-flag discipline is unchanged: `.enabled` reads feature_flags.
WORKSPACE and `bootstrap()` is a NO-OP while the flag is OFF, so nothing
here creates a workspace row or alters v14 behaviour on a flag-OFF start.
The engine's methods stay callable regardless (the unit tests exercise the
infrastructure with the flag off); what keeps the running bot byte-
identical is that no v14 handler constructs this Service yet.
"""
from __future__ import annotations

from core import feature_flags
from core.workspace.engine import EntityEngine
from core.workspace.models import DEFAULT_WORKSPACE_TITLE, Milestone, Workspace
from core.workspace.repository import WorkspaceRepository


class WorkspaceService:
    """Stateless orchestrator. Owns a Repository (for the migration
    passthroughs) and an EntityEngine (for validated entity ops)."""

    def __init__(self, repo: WorkspaceRepository | None = None,
                 engine: EntityEngine | None = None):
        self._repo = repo or WorkspaceRepository()
        self._engine = engine or EntityEngine(repo=self._repo)

    @property
    def enabled(self) -> bool:
        """Whether the Workspace OS is switched on (feature_flags.WORKSPACE)."""
        return feature_flags.WORKSPACE

    # ── Entity operations (delegated to the engine) ────
    def create_workspace(self, user_id, title, template="generic",
                        seed_milestones=True, metadata=None) -> Workspace:
        return self._engine.create_workspace(
            user_id, title, template=template,
            seed_milestones=seed_milestones, metadata=metadata)

    def workspace_progress(self, user_id, workspace_id) -> int:
        return self._engine.workspace_progress(user_id, workspace_id)

    def complete_milestone(self, user_id, milestone_id) -> Milestone:
        """Mark a milestone done via the engine (lifecycle-validated,
        stamps completed_at, drives progress to 100, emits an event)."""
        return self._engine.complete_milestone(user_id, milestone_id)

    # ── Migration / bootstrap (MIGRATION.md) ───────────
    def bootstrap(self, user_id) -> dict:
        """Idempotently bring a user onto the Workspace model: ensure their
        Inbox exists and convert existing projects into project-workspaces.
        NO-OP while the flag is OFF (returns a skipped report). Safe to
        call repeatedly."""
        if not self.enabled:
            return {"skipped": True, "reason": "WORKSPACE flag off"}
        inbox = self._repo.ensure_default_workspace(
            user_id, title=DEFAULT_WORKSPACE_TITLE, template="generic")
        migrated = self._repo.migrate_projects(user_id)
        return {"skipped": False, "inbox_id": inbox.id,
                "projects_migrated": migrated}

    def ensure_inbox(self, user_id) -> Workspace:
        """Return the user's Inbox workspace, creating it if absent. Not
        flag-gated -- the primitive the tests and later engine use."""
        return self._repo.ensure_default_workspace(
            user_id, title=DEFAULT_WORKSPACE_TITLE, template="generic")
