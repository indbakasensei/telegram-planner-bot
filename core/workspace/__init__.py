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

from core.workspace.models import (  # noqa: F401
    DEFAULT_WORKSPACE_TITLE,
    Milestone,
    Note,
    Workspace,
)
from core.workspace.repository import WorkspaceRepository  # noqa: F401
from core.workspace.service import WorkspaceService  # noqa: F401
