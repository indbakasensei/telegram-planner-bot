"""
game.py -- the Game Workspace template (v15.0-beta.2), the REFERENCE
implementation for adding a new Workspace type.

The whole point of this file: a complete, first-class Workspace ("track a
game you're playing") is added as ONE drop-in module, without editing the
Workspace OS -- no change to the Entity Engine, Orchestrator, Timeline,
Sync Engine, repositories, or the database schema. It plugs in only through
the existing extension points:

  * `register(WorkspaceTemplate(...))` -- the Template registry (composition,
    not inheritance) declares the icon, sections, and progress model.
  * The generic entities already provided by the OS carry the game's data:
      objectives -> milestones, sessions/notes -> notes, and completion% ->
      the workspace's `metadata` (read by the engine's PROGRESS_MANUAL
      model). No new tables.
  * Template-local ENTITY SCHEMA + VALIDATION RULES live here and are
    applied at this template's own creation entry point
    (`create_game_workspace`) -- the OS never learns anything
    game-specific.

Every future template (Books, Courses, Research, Vehicles, Finance,
Personal Knowledge) follows this exact shape: a schema, validators, a
registered `WorkspaceTemplate`, and a thin validating create helper.
"""
from __future__ import annotations

from core.workspace.errors import EntityValidationError
from core.workspace.templates.registry import (
    PROGRESS_MANUAL,
    FieldSpec,
    WorkspaceTemplate,
    register,
)

GAME_KEY = "game"

# A game's lifecycle/status (stored in metadata['status']).
GAME_STATUSES = ("backlog", "playing", "on_hold", "completed", "dropped")


# ── Entity / metadata schema ──────────────────────────────────────────────
# v15.1.0-alpha.9: `FieldSpec` imported from the registry (consolidated).
# GAME_METADATA_SCHEMA defines workspace-level metadata fields; entity-level
# fields for individual entities/milestones live in GAME_ENTITY_FIELDS.

# The Game workspace's metadata schema (its "entity schema"): the fields a
# game carries beyond the generic workspace title/status.
GAME_METADATA_SCHEMA: tuple[FieldSpec, ...] = (
    FieldSpec("platform", "str"),
    FieldSpec("status", "enum", default="backlog", choices=GAME_STATUSES),
    FieldSpec("hours_played", "int", default=0, minimum=0),
    FieldSpec("progress", "int", default=0, minimum=0, maximum=100),  # completion %
)

_SCHEMA_BY_NAME = {f.name: f for f in GAME_METADATA_SCHEMA}


# ── Entity-level structured fields (v15.1.0-alpha.9) ─────────────────────
# Per-character/milestone fields for the game template. These drive the
# "who to farm today" analysis use case for Genshin-like games.
GAME_ENTITY_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("level", "int", default=1, minimum=1, maximum=100),
    FieldSpec("element", "str"),              # "Pyro", "Hydro", "Anemo", ...
    FieldSpec("weapon_type", "str"),           # "Sword", "Catalyst", "Bow", ...
    FieldSpec("weapon", "str"),               # specific weapon name, e.g. "Fleuve Cendre Ferryman"
    FieldSpec("talent_domain", "str"),         # day/named domain for talent materials
    FieldSpec("materials", "json"),            # list/dict of needed materials
    FieldSpec("ascension_phase", "int", default=0, minimum=0, maximum=6),
    FieldSpec("target_level", "int", default=90, minimum=1, maximum=100),
    FieldSpec("priority", "enum", default="medium",
              choices=("low", "medium", "high")),
)


def default_metadata() -> dict:
    """A fresh game's metadata with every defaulted field filled in."""
    return {f.name: f.default for f in GAME_METADATA_SCHEMA if f.default is not None}


# ── Validation rules ──────────────────────────────────────────────────────
def validate_game_metadata(metadata: dict) -> list[str]:
    """Return a list of human-readable errors (empty == valid). Checks
    required fields, types, enum membership, and numeric ranges. Unknown
    keys are allowed (forward-compatible) but ignored."""
    errors: list[str] = []
    meta = metadata or {}
    for spec in GAME_METADATA_SCHEMA:
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
        elif spec.kind == "int":
            if isinstance(value, bool) or not _is_intlike(value):
                errors.append(f"'{spec.name}' must be a whole number")
                continue
            ivalue = int(value)
            if spec.minimum is not None and ivalue < spec.minimum:
                errors.append(f"'{spec.name}' must be >= {spec.minimum}")
            if spec.maximum is not None and ivalue > spec.maximum:
                errors.append(f"'{spec.name}' must be <= {spec.maximum}")
        elif spec.kind == "str":
            if not isinstance(value, str):
                errors.append(f"'{spec.name}' must be text")
    return errors


def normalize_game_metadata(metadata: dict | None) -> dict:
    """Fill defaults and coerce ints, leaving a clean metadata dict ready to
    store. Assumes the input already passed validate_game_metadata (ints
    are coerced defensively)."""
    meta = dict(default_metadata())
    for name, value in (metadata or {}).items():
        if value is None:
            continue
        spec = _SCHEMA_BY_NAME.get(name)
        if spec and spec.kind == "int" and _is_intlike(value) and not isinstance(value, bool):
            meta[name] = int(value)
        else:
            meta[name] = value
    return meta


def _is_intlike(value) -> bool:
    try:
        int(value)
        return True
    except (TypeError, ValueError):
        return False


# ── Template registration (the extension point) ───────────────────────────
GAME_TEMPLATE = WorkspaceTemplate(
    key=GAME_KEY,
    label="Game",
    icon="🎮",
    sections=("objectives", "sessions", "notes", "progress"),
    metadata_fields=tuple(f.name for f in GAME_METADATA_SCHEMA),
    progress_model=PROGRESS_MANUAL,   # completion% lives in metadata['progress']
    entity_fields=GAME_ENTITY_FIELDS, # v15.1.0-alpha.9
)

register(GAME_TEMPLATE)


# ── Validating create helper (template-local; OS unchanged) ────────────────
def create_game_workspace(engine, user_id, title, metadata=None,
                          seed_milestones=False):
    """Create a Game workspace through the generic Entity Engine, applying
    this template's validation first. Raises EntityValidationError (the
    OS's own validation error type) on bad metadata -- the engine itself
    stays game-agnostic. Returns the created Workspace.

    This is the pattern every template follows: validate with your rules,
    then call the unchanged `engine.create_workspace(..., template=<key>)`."""
    errors = validate_game_metadata(metadata or {})
    if errors:
        raise EntityValidationError("; ".join(errors))
    clean = normalize_game_metadata(metadata)
    return engine.create_workspace(
        user_id, title, template=GAME_KEY,
        seed_milestones=seed_milestones, metadata=clean)
