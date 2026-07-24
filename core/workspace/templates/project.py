"""
project.py -- the Project Workspace template (v15.0-beta.5).

Fourth application of the beta.2 drop-in pattern (after Game, Knowledge,
Asset), validating the extension model against an EXECUTION-focused domain:
a project you drive to completion through a milestone pipeline. Like the
other templates, the whole thing is one drop-in module added with ZERO
Workspace-OS changes -- no edit to the Entity Engine, Orchestrator,
Timeline, Sync Engine, repositories, models, or the database schema.

This module OWNS the "project" template (moved here from builtin.py, the
same way game.py took ownership of "game" in beta.2). Its shape is
preserved exactly -- icon 🛠, the goals/milestones/tasks/materials/worklog/
files sections, the Research→Documentation default milestone pipeline, and
the `PROGRESS_MILESTONES` rollup -- so the alpha.3 `ProjectAdapter` (the v14
Project↔Workspace bridge, which creates `template='project'` workspaces)
keeps working unchanged. beta.5 adds the missing template-local pieces the
other templates already have: an entity/metadata schema, validation,
normalization, and a validating `create_project_workspace` helper for
creating a *native* execution project (milestones seeded, progress = the
milestone rollup).

  * `register(WorkspaceTemplate(...))` -- the Template registry declares the
    icon, sections, seeded pipeline, and progress model.
  * Generic entities carry the project: phases/tasks -> milestones,
    decisions/worklog -> notes, categories -> tags, history -> Timeline, and
    execution progress -> the `PROGRESS_MILESTONES` rollup (% of milestones
    done). No new tables, no new entity types.
  * Template-local schema + validation + normalization live here and are
    applied at `create_project_workspace` -- the OS stays project-agnostic.
"""
from __future__ import annotations

from dataclasses import dataclass

from core.workspace.errors import EntityValidationError
from core.workspace.templates.registry import (
    PROGRESS_MILESTONES,
    WorkspaceTemplate,
    register,
)

PROJECT_KEY = "project"

# Execution lifecycle of a project (stored in metadata['status']).
PROJECT_STATUSES = ("planning", "active", "on_hold", "completed", "cancelled")
# Priority of the work (stored in metadata['priority']).
PROJECT_PRIORITIES = ("low", "medium", "high", "critical")

# The default milestone pipeline seeded on create. FROZEN: existing tests
# and the ProjectAdapter rely on this exact tuple (see beta.5 notes).
PROJECT_DEFAULT_MILESTONES = ("Research", "Design", "Prototype", "Testing",
                              "Documentation")


# ── Entity / metadata schema ──────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class FieldSpec:
    """One template-specific metadata field. Declarative -- the validator
    and normalizer below interpret it; nothing in the OS reads it."""
    name: str
    kind: str                      # "str" | "int" | "enum"
    required: bool = False
    default: object = None
    choices: tuple = ()
    minimum: int | None = None
    maximum: int | None = None


# The Project workspace's metadata schema. Everything is optional (with
# sensible enum defaults) so a project can be started with a single line and
# enriched later; execution progress comes from the milestone rollup, not a
# metadata field.
PROJECT_METADATA_SCHEMA: tuple[FieldSpec, ...] = (
    FieldSpec("status", "enum", default="planning", choices=PROJECT_STATUSES),
    FieldSpec("priority", "enum", default="medium", choices=PROJECT_PRIORITIES),
    FieldSpec("target_date", "str"),     # free-form target/deadline string
)

_SCHEMA_BY_NAME = {f.name: f for f in PROJECT_METADATA_SCHEMA}


def default_metadata() -> dict:
    """A fresh project's metadata with every defaulted field filled in."""
    return {f.name: f.default for f in PROJECT_METADATA_SCHEMA if f.default is not None}


# ── Validation rules ──────────────────────────────────────────────────────
def validate_project_metadata(metadata: dict) -> list[str]:
    """Return a list of human-readable errors (empty == valid). Checks enum
    membership (status/priority) and string types (target_date is free-form
    and optional). Unknown keys are allowed (forward-compatible) but ignored.
    Enums are checked against the canonical lowercase values -- run
    normalize_project_metadata first to accept mixed case / whitespace."""
    errors: list[str] = []
    meta = metadata or {}
    for spec in PROJECT_METADATA_SCHEMA:
        present = spec.name in meta and meta[spec.name] is not None
        if not present:
            if spec.required:
                errors.append(f"'{spec.name}' is required")
            continue
        value = meta[spec.name]
        if spec.kind == "enum":
            if value not in spec.choices:
                errors.append(
                    f"'{spec.name}' must be one of {', '.join(spec.choices)}")
        elif spec.kind == "str":
            if not isinstance(value, str):
                errors.append(f"'{spec.name}' must be text")
    return errors


def normalize_project_metadata(metadata: dict | None) -> dict:
    """Fill enum defaults, lower/trim enum values (so 'Active' / ' HIGH '
    become 'active' / 'high'), and trim string fields, leaving a clean
    metadata dict. Meant to run BEFORE validation so user input is
    canonicalised first. Unknown keys pass through untouched."""
    meta = dict(default_metadata())
    for name, value in (metadata or {}).items():
        if value is None:
            continue
        spec = _SCHEMA_BY_NAME.get(name)
        if spec and spec.kind == "enum" and isinstance(value, str):
            meta[name] = value.strip().lower()
        elif spec and spec.kind == "str" and isinstance(value, str):
            meta[name] = value.strip()
        else:
            meta[name] = value
    return meta


# ── Template registration (the extension point) ───────────────────────────
PROJECT_TEMPLATE = WorkspaceTemplate(
    key=PROJECT_KEY,
    label="Project",
    icon="🛠",
    sections=("goals", "milestones", "tasks", "materials", "worklog", "files"),
    default_milestones=PROJECT_DEFAULT_MILESTONES,
    metadata_fields=tuple(f.name for f in PROJECT_METADATA_SCHEMA),
    progress_model=PROGRESS_MILESTONES,   # execution % = milestones done
)

register(PROJECT_TEMPLATE)


# ── Validating create helper (template-local; OS unchanged) ────────────────
def create_project_workspace(engine, user_id, title, metadata=None,
                             seed_milestones=True):
    """Create a native execution Project workspace through the generic
    Entity Engine. Metadata is NORMALIZED first (enums lowercased/trimmed,
    strings trimmed, defaults filled) and then VALIDATED, so 'Active' /
    ' high ' are accepted. By default the Research→Documentation milestone
    pipeline is seeded (execution focus); pass seed_milestones=False for an
    empty project. Raises EntityValidationError on bad metadata -- the engine
    itself stays project-agnostic. Returns the created Workspace.

    (This is the *native* project entry point. The v14 Project↔Workspace
    bridge -- goal + materials/worklog -- has its own ProjectAdapter and is
    unaffected.)"""
    clean = normalize_project_metadata(metadata)
    errors = validate_project_metadata(clean)
    if errors:
        raise EntityValidationError("; ".join(errors))
    return engine.create_workspace(
        user_id, title, template=PROJECT_KEY,
        seed_milestones=seed_milestones, metadata=clean)
