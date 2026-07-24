"""
asset.py -- the Asset Workspace template (v15.0-beta.4).

Third application of the beta.2 drop-in pattern (after Game and Knowledge),
and the broadest: ONE reusable template that represents ANY owned physical
asset -- vehicles, computers, drones, cameras, robots, manufacturing
equipment, electronics, appliances, tools. There is deliberately no
per-asset-type template and no hardcoded vehicle/drone/laptop logic; the
asset *kind* is just `metadata['asset_type']`.

Like game.py / knowledge.py, the whole template is one drop-in module added
with ZERO Workspace-OS changes -- no edit to the Entity Engine,
Orchestrator, Timeline, Sync Engine, repositories, models, or the database
schema. It plugs in only through the existing extension points:

  * `register(WorkspaceTemplate(...))` -- the Template registry declares the
    icon, sections, and progress model (composition, not inheritance).
  * The generic entities already provided by the OS carry the asset's data:
      maintenance / inspections / repairs / upgrades -> milestones,
      service records / observations / issues / config -> notes,
      categories / components -> tags, ownership + maintenance history ->
      the append-only Timeline, and maintenance/lifecycle completion ->
      the `PROGRESS_MILESTONES` rollup. No new tables, no new entity types.
  * Template-local ENTITY SCHEMA + VALIDATION + NORMALIZATION live here and
    are applied at this template's own creation entry point
    (`create_asset_workspace`) -- the OS never learns anything
    asset-specific.

Every future template (Finance, Personal Knowledge, ...) follows this exact
shape: a schema, validators, a registered `WorkspaceTemplate`, and a thin
validating create helper.
"""
from __future__ import annotations

from dataclasses import dataclass

from core.workspace.errors import EntityValidationError
from core.workspace.templates.registry import (
    PROGRESS_MILESTONES,
    WorkspaceTemplate,
    register,
)

ASSET_KEY = "asset"

# One generic template covers every physical asset; the kind is metadata.
ASSET_TYPES = ("vehicle", "computer", "drone", "robot", "equipment",
               "electronics", "appliance", "tool", "other")
# Operational lifecycle of the asset (stored in metadata['status']).
ASSET_STATUSES = ("active", "maintenance", "stored", "retired", "sold")
# Physical condition (stored in metadata['condition']).
ASSET_CONDITIONS = ("excellent", "good", "fair", "poor")


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


# The Asset workspace's metadata schema (its "entity schema"): the fields an
# asset carries beyond the generic workspace title. Asset type is required;
# everything else is optional (with sensible enum defaults) so any physical
# thing can be logged with a single line and enriched later.
ASSET_METADATA_SCHEMA: tuple[FieldSpec, ...] = (
    FieldSpec("asset_type", "enum", required=True, choices=ASSET_TYPES),
    FieldSpec("status", "enum", default="active", choices=ASSET_STATUSES),
    FieldSpec("condition", "enum", default="good", choices=ASSET_CONDITIONS),
    FieldSpec("manufacturer", "str"),
    FieldSpec("model", "str"),
    FieldSpec("serial_number", "str"),
    FieldSpec("purchase_date", "str"),      # free-form date string (optional)
    FieldSpec("warranty_expiry", "str"),    # free-form date string (optional)
    FieldSpec("location", "str"),
)

_SCHEMA_BY_NAME = {f.name: f for f in ASSET_METADATA_SCHEMA}
_ENUM_FIELDS = frozenset(f.name for f in ASSET_METADATA_SCHEMA if f.kind == "enum")


def default_metadata() -> dict:
    """A fresh asset's metadata with every defaulted field filled in
    (asset_type has no default -- it is required)."""
    return {f.name: f.default for f in ASSET_METADATA_SCHEMA if f.default is not None}


# ── Validation rules ──────────────────────────────────────────────────────
def validate_asset_metadata(metadata: dict) -> list[str]:
    """Return a list of human-readable errors (empty == valid). Checks the
    required asset_type, enum membership (status/condition/asset_type), and
    string types. Dates are free-form optional strings. Unknown keys are
    allowed (forward-compatible) but ignored. Enums are checked against the
    canonical lowercase values -- run normalize_asset_metadata first to
    accept mixed case / surrounding whitespace."""
    errors: list[str] = []
    meta = metadata or {}
    for spec in ASSET_METADATA_SCHEMA:
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


def normalize_asset_metadata(metadata: dict | None) -> dict:
    """Fill enum defaults, trim every string field, and lower/trim enum
    values (so 'Vehicle' / ' active ' become 'vehicle' / 'active'), leaving
    a clean metadata dict. Meant to run BEFORE validation so user input is
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
ASSET_TEMPLATE = WorkspaceTemplate(
    key=ASSET_KEY,
    label="Asset",
    icon="📦",
    sections=("maintenance", "service_records", "notes", "components", "history"),
    metadata_fields=tuple(f.name for f in ASSET_METADATA_SCHEMA),
    # Maintenance/lifecycle completion is the share of maintenance milestones
    # done -- reuses the generic milestone rollup, no asset-specific code.
    progress_model=PROGRESS_MILESTONES,
)

register(ASSET_TEMPLATE)


# ── Validating create helper (template-local; OS unchanged) ────────────────
def create_asset_workspace(engine, user_id, title, metadata=None,
                           seed_milestones=False):
    """Create an Asset workspace through the generic Entity Engine. Metadata
    is NORMALIZED first (enums lowercased/trimmed, strings trimmed, defaults
    filled) and then VALIDATED, so 'Vehicle' / ' DJI ' are accepted. Raises
    EntityValidationError (the OS's own validation error type) on bad
    metadata -- the engine itself stays asset-agnostic. Returns the created
    Workspace.

    Same pattern as create_game_workspace / create_knowledge_workspace, just
    normalize-then-validate because assets accept human-entered enums."""
    clean = normalize_asset_metadata(metadata)
    errors = validate_asset_metadata(clean)
    if errors:
        raise EntityValidationError("; ".join(errors))
    return engine.create_workspace(
        user_id, title, template=ASSET_KEY,
        seed_milestones=seed_milestones, metadata=clean)
