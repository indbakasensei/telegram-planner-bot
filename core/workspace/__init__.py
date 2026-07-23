"""
core.workspace -- the Workspace Foundation (v15.0-alpha.1, docs/v15/).

Infrastructure only: the schema (in database.py), the Storage-Facade
domains, the typed models, the Repository, the Service, and the Template
registry that later v15 phases (Telegram sync, Knowledge Timeline, AI
Orchestrator) build upon. Nothing here runs while feature_flags.WORKSPACE
is OFF -- the bot behaves byte-identically to v14.26.

    Service  ->  Repository  ->  Storage Facade  ->  database.py
"""
from __future__ import annotations

from core.workspace.engine import EntityEngine  # noqa: F401
from core.workspace.errors import (  # noqa: F401
    EntityError,
    EntityNotFound,
    EntityValidationError,
    InvalidTransition,
)
from core.workspace.events import EntityEvent  # noqa: F401
from core.workspace.timeline import (  # noqa: F401
    TimelineEngine,
    TimelineEvent,
    TimelineRepository,
)
from core.workspace.sync import (  # noqa: F401
    SyncAdapter,
    SyncEngine,
    SyncItem,
    SyncOutboxRepository,
    SyncResult,
)
from core.workspace.adapters import TelegramAdapter  # noqa: F401
from core.workspace.orchestrator import (  # noqa: F401
    Action,
    Interpreter,
    OrchestratorResult,
    Proposal,
    RuleBasedInterpreter,
    Status,
    WorkspaceOrchestrator,
)
from core.workspace.llm_interpreter import LLMInterpreter  # noqa: F401
from core.workspace.models import (  # noqa: F401
    DEFAULT_WORKSPACE_TITLE,
    Milestone,
    Note,
    Workspace,
)
from core.workspace.project_adapter import (  # noqa: F401
    ProjectAdapter,
    ProjectView,
    use_workspace_projects,
)
from core.workspace.repository import WorkspaceRepository  # noqa: F401
from core.workspace.service import WorkspaceService  # noqa: F401
