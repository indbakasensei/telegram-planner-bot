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
class FieldSpec:
    """One template-specific structured field for an entity (milestone) or
    workspace metadata. Declarative -- the validator below interprets it;
    nothing in the OS reads it beyond what the template defines.

    v15.1.0-alpha.9: consolidated into the registry from duplicate copies
    in each template file (game.py, knowledge.py, asset.py, project.py)."""
    name: str
    kind: str                      # "str" | "int" | "enum" | "json"
    required: bool = False
    default: object = None
    choices: tuple = ()
    minimum: int | None = None
    maximum: int | None = None


@dataclass(frozen=True, slots=True)
class WorkspaceTemplate:
    """Immutable description of one kind of workspace. `sections` names the
    read-models a UI would render for it; `default_milestones` are seeded
    on create; `metadata_fields` are the template-specific keys stored in
    the workspace's JSON metadata; `progress_model` selects the rollup;
    `entity_fields` declares structured per-entity fields for milestones
    (v15.1.0-alpha.9)."""
    key: str
    label: str
    icon: str
    sections: tuple[str, ...] = ()
    default_milestones: tuple[str, ...] = ()
    metadata_fields: tuple[str, ...] = ()
    progress_model: str = PROGRESS_MILESTONES
    entity_fields: tuple[FieldSpec, ...] = ()   # v15.1.0-alpha.9


# ── Entity field validation (v15.1.0-alpha.9) ──────────────────────────

def entity_field_specs(template_key: str) -> tuple[FieldSpec, ...]:
    """Return the entity field definitions for a template, falling back to
    empty (no structured fields)."""
    tpl = get(template_key)
    return tpl.entity_fields if tpl else ()


def validate_entity_fields(template_key: str, fields: dict) -> list[str]:
    """Validate fields dict against a template's entity field schema.
    Returns a list of error messages (empty = valid). Unknown keys are
    allowed for forward compatibility. Same type/enum/range rules as the
    per-template metadata validators."""
    errors: list[str] = []
    specs = {s.name: s for s in entity_field_specs(template_key)}
    if not specs or not fields:
        return errors
    for spec_name, spec in specs.items():
        present = spec_name in fields and fields[spec_name] is not None
        if not present:
            if spec.required:
                errors.append(f"'{spec_name}' is required")
            continue
        value = fields[spec_name]
        if spec.kind == "enum":
            if value not in spec.choices:
                errors.append(
                    f"'{spec_name}' must be one of {', '.join(spec.choices)}")
        elif spec.kind == "int":
            if isinstance(value, bool) or not _is_intlike(value):
                errors.append(f"'{spec_name}' must be a whole number")
                continue
            ivalue = int(value)
            if spec.minimum is not None and ivalue < spec.minimum:
                errors.append(f"'{spec_name}' must be >= {spec.minimum}")
            if spec.maximum is not None and ivalue > spec.maximum:
                errors.append(f"'{spec_name}' must be <= {spec.maximum}")
        elif spec.kind == "str":
            if not isinstance(value, str):
                errors.append(f"'{spec_name}' must be text")
        elif spec.kind == "json":
            # Accept dicts, lists, or JSON strings.
            if not isinstance(value, (dict, list, str)):
                errors.append(f"'{spec_name}' must be a JSON object, array, or string")
    return errors


def normalize_entity_fields(template_key: str, fields: dict | None) -> dict:
    """Fill defaults and coerce ints, leaving a clean fields dict ready to
    store. Unknown keys pass through untouched for forward compatibility."""
    specs = {s.name: s for s in entity_field_specs(template_key)}
    result = {}
    # Apply defaults from the schema first.
    for s in specs.values():
        if s.default is not None:
            result[s.name] = s.default
    # Merge in provided values.
    for name, value in (fields or {}).items():
        if value is None:
            continue
        spec = specs.get(name)
        if spec and spec.kind == "int" and _is_intlike(value) and not isinstance(value, bool):
            result[name] = int(value)
        else:
            result[name] = value
    return result


def _is_intlike(value) -> bool:
    try:
        int(value)
        return True
    except (TypeError, ValueError):
        return False


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
