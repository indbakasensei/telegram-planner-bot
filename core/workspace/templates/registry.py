"""
registry.py -- the Workspace Template registry (v15.0-alpha.1,
docs/v15/WED.md §6).

A Template is a registered *config object*, not a Workspace subclass
(composition over inheritance -- one of the load-bearing v15 decisions).
The engine stores only a template KEY on each workspace and asks this
registry for the config when it needs to seed defaults or render a view;
adding a template is one `register(...)` call and the engine never
changes (Open/Closed).

Same registration-based, edit-nothing-central philosophy as the Offline
Engine's ActionRegistry (ADR-012) and the Self-Test registry. Registration
is deduplicated by key so importing the builtin module twice registers
each template once.
"""
from __future__ import annotations

from dataclasses import dataclass, field


# Progress models a template can declare (how a workspace's % is derived).
PROGRESS_MILESTONES = "milestones"   # % of milestones done
PROGRESS_CHECKLIST = "checklist"     # % of child tasks done
PROGRESS_CHAPTERS = "chapters"       # current_chapter / total_chapters
PROGRESS_MANUAL = "manual"           # user/AI sets it explicitly


@dataclass(frozen=True, slots=True)
class WorkspaceTemplate:
    """Immutable description of one kind of workspace. `sections` names the
    read-models a UI would render for it; `default_milestones` are seeded
    on create; `metadata_fields` are the template-specific keys stored in
    the workspace's JSON metadata; `progress_model` selects the rollup."""
    key: str
    label: str
    icon: str
    sections: tuple[str, ...] = ()
    default_milestones: tuple[str, ...] = ()
    metadata_fields: tuple[str, ...] = ()
    progress_model: str = PROGRESS_MILESTONES


_REGISTRY: dict[str, WorkspaceTemplate] = {}


def register(template: WorkspaceTemplate) -> None:
    """Register (or replace, by key) a template. Idempotent by key so a
    reloaded builtin module never double-registers."""
    if not isinstance(template, WorkspaceTemplate):
        raise TypeError("register() expects a WorkspaceTemplate")
    if not template.key or not isinstance(template.key, str):
        raise ValueError("template key must be a non-empty string")
    _REGISTRY[template.key] = template


def get(key: str) -> WorkspaceTemplate:
    """Return the template for `key`, falling back to the 'generic'
    template for any unknown key (so a workspace created with a
    typo'd/removed template still renders). Never raises."""
    if key in _REGISTRY:
        return _REGISTRY[key]
    return _REGISTRY.get("generic", _GENERIC_FALLBACK)


def exists(key: str) -> bool:
    return key in _REGISTRY


def all_templates() -> tuple[WorkspaceTemplate, ...]:
    """Every registered template, in registration order."""
    return tuple(_REGISTRY.values())


def keys() -> tuple[str, ...]:
    return tuple(_REGISTRY.keys())


def clear() -> None:
    """Empty the registry -- used only by unit tests that build a
    synthetic registry in isolation."""
    _REGISTRY.clear()


# Last-resort fallback if even 'generic' was never registered (e.g. a test
# called clear()). Keeps get() total.
_GENERIC_FALLBACK = WorkspaceTemplate(
    key="generic", label="Workspace", icon="📁",
    sections=("tasks", "notes"), progress_model=PROGRESS_MILESTONES,
)
