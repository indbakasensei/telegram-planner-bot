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
# v15.0-beta.2: the Game reference template registers itself on import
# (a full new Workspace added as one drop-in module, no OS change).
from core.workspace.templates import game  # noqa: E402,F401
# v15.0-beta.3: the Knowledge template -- second drop-in module, same
# pattern, proving educational/knowledge domains need no OS change either.
from core.workspace.templates import knowledge  # noqa: E402,F401
# v15.0-beta.4: the Asset template -- one reusable module for ANY physical
# asset (vehicle/computer/drone/...), still zero OS change.
from core.workspace.templates import asset  # noqa: E402,F401
# v15.0-beta.5: the Project template -- execution-focused domain; owns the
# "project" template (moved out of builtin.py), preserving its shape so the
# ProjectAdapter bridge is unaffected. Still zero OS change.
from core.workspace.templates import project  # noqa: E402,F401
