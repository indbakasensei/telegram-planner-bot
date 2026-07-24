"""
builtin.py -- the templates that ship with v15.0-alpha.1
(docs/v15/WED.md §6).

Each is a plain config object registered at import. Adding a new kind of
workspace later means appending one `register(...)` here (or a new module
that calls it) -- the Workspace Engine never changes. Registration runs
when `core.workspace.templates` is imported (its __init__ imports this).
"""
from __future__ import annotations

from core.workspace.templates.registry import (
    PROGRESS_CHAPTERS,
    PROGRESS_CHECKLIST,
    PROGRESS_MANUAL,
    PROGRESS_MILESTONES,
    WorkspaceTemplate,
    register,
)

# generic -- the fallback every unclassified workspace (and Inbox) gets.
register(WorkspaceTemplate(
    key="generic", label="Workspace", icon="📁",
    sections=("tasks", "notes"),
    progress_model=PROGRESS_MILESTONES,
))

# project -- the v14 "project" (goal + materials + worklog) as a workspace.
register(WorkspaceTemplate(
    key="project", label="Project", icon="🛠",
    sections=("goals", "milestones", "tasks", "materials", "worklog", "files"),
    default_milestones=("Research", "Design", "Prototype", "Testing", "Documentation"),
    metadata_fields=("status", "target_date"),
    progress_model=PROGRESS_MILESTONES,
))

# book -- reading tracker.
register(WorkspaceTemplate(
    key="book", label="Book", icon="📖",
    sections=("chapters", "notes", "quotes", "summary"),
    metadata_fields=("author", "total_chapters", "current_chapter"),
    progress_model=PROGRESS_CHAPTERS,
))

# course / study.
register(WorkspaceTemplate(
    key="course", label="Course", icon="🎓",
    sections=("modules", "notes", "deadlines"),
    metadata_fields=("provider", "total_modules", "current_module"),
    progress_model=PROGRESS_CHECKLIST,
))

# research.
register(WorkspaceTemplate(
    key="research", label="Research", icon="🔬",
    sections=("questions", "sources", "notes", "findings"),
    progress_model=PROGRESS_MANUAL,
))

# game -- the reference template (v15.0-beta.2) lives in its own
# self-contained module (game.py) with an entity/metadata schema and
# validation rules, registered from there. It is NOT declared here, to
# demonstrate that a full new Workspace is added as one drop-in file
# without editing anything else.
