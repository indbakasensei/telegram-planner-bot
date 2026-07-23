"""
core.workspace.templates -- Workspace Template registry + built-ins
(v15.0-alpha.1).

Importing this package registers every built-in template (side effect of
importing .builtin) and re-exports the registry's public surface, so
callers do:

    from core.workspace import templates
    tpl = templates.get("book")
"""
from __future__ import annotations

from core.workspace.templates.registry import (  # noqa: F401
    PROGRESS_CHAPTERS,
    PROGRESS_CHECKLIST,
    PROGRESS_MANUAL,
    PROGRESS_MILESTONES,
    WorkspaceTemplate,
    all_templates,
    exists,
    get,
    keys,
    register,
)

# Register the built-ins (side effect on import).
from core.workspace.templates import builtin  # noqa: E402,F401
