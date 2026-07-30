"""
knowledge.py -- the Knowledge Workspace template (v15.0-beta.3).

Second proof of the beta.2 thesis: an entire educational/knowledge domain
("learn a subject, capture what you know, track your mastery") is added as
ONE drop-in module, without editing the Workspace OS -- no change to the
Entity Engine, Orchestrator, Timeline, Sync Engine, repositories, or the
database schema. It plugs in only through the existing extension points,
exactly like the Game reference template (game.py):

  * `register(WorkspaceTemplate(...))` -- the Template registry declares the
    icon, sections, and progress model (composition, not inheritance).
  * The generic entities already provided by the OS carry the knowledge:
      concepts/topics -> milestones, sources/notes -> notes, and mastery% ->
      the workspace's `metadata` (read by the engine's PROGRESS_MANUAL
      model). No new tables, no new entity types.
  * Template-local ENTITY SCHEMA + VALIDATION RULES live here and are
    applied at this template's own creation entry point
    (`create_knowledge_workspace`) -- the OS never learns anything
    knowledge-specific.

This is the same shape every future template (Vehicles, Finance, Personal
Knowledge, ...) follows: a schema, validators, a registered
`WorkspaceTemplate`, and a thin validating create helper.
"""
from __future__ import annotations

from core.workspace.errors import EntityValidationError
from core.workspace.templates.registry import (
    PROGRESS_MANUAL,
    FieldSpec,
    WorkspaceTemplate,
    register,
)

KNOWLEDGE_KEY = "knowledge"

# A knowledge workspace's learning lifecycle (stored in metadata['status']).
KNOWLEDGE_STATUSES = ("exploring", "learning", "reviewing", "mastered", "archived")


# ── Entity / metadata schema ──────────────────────────────────────────────
# v15.1.0-alpha.9: `FieldSpec` imported from the registry (consolidated).
# KNOWLEDGE_METADATA_SCHEMA defines workspace-level metadata fields; entity-
# level fields for individual concepts/topics live in KNOWLEDGE_ENTITY_FIELDS.

# The Knowledge workspace's metadata schema (its "entity schema"): the
# fields a knowledge area carries beyond the generic workspace title/status.
KNOWLEDGE_METADATA_SCHEMA: tuple[FieldSpec, ...] = (
    FieldSpec("domain", "str"),                       # subject area
    FieldSpec("source", "str"),                       # book / course / paper / ...
    FieldSpec("status", "enum", default="exploring", choices=KNOWLEDGE_STATUSES),
    FieldSpec("items_reviewed", "int", default=0, minimum=0),  # concepts/cards reviewed
    FieldSpec("progress", "int", default=0, minimum=0, maximum=100),  # mastery %
)

_SCHEMA_BY_NAME = {f.name: f for f in KNOWLEDGE_METADATA_SCHEMA}


# ── Entity-level structured fields (v15.1.0-alpha.9) ─────────────────────
# Per-concept/milestone fields. These track individual topics within a
# knowledge area (e.g. a flashcard deck, a chapter in a textbook).
KNOWLEDGE_ENTITY_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("difficulty", "enum", default="medium",
              choices=("easy", "medium", "hard")),
    FieldSpec("review_count", "int", default=0, minimum=0),
    FieldSpec("mastery_level", "int", default=0, minimum=0, maximum=100),
    FieldSpec("source_type", "str"),           # "book", "article", "video", ...
    FieldSpec("key_concepts", "json"),         # list of key concepts
    FieldSpec("next_review", "str"),           # date string for spaced repetition
)


def default_metadata() -> dict:
    """A fresh knowledge workspace's metadata with every defaulted field
    filled in."""
    return {f.name: f.default for f in KNOWLEDGE_METADATA_SCHEMA if f.default is not None}


# ── Validation rules ──────────────────────────────────────────────────────
def validate_knowledge_metadata(metadata: dict) -> list[str]:
    """Return a list of human-readable errors (empty == valid). Checks
    required fields, types, enum membership, and numeric ranges. Unknown
    keys are allowed (forward-compatible) but ignored."""
    errors: list[str] = []
    meta = metadata or {}
    for spec in KNOWLEDGE_METADATA_SCHEMA:
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


def normalize_knowledge_metadata(metadata: dict | None) -> dict:
    """Fill defaults and coerce ints, leaving a clean metadata dict ready to
    store. Assumes the input already passed validate_knowledge_metadata
    (ints are coerced defensively)."""
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
KNOWLEDGE_TEMPLATE = WorkspaceTemplate(
    key=KNOWLEDGE_KEY,
    label="Knowledge",
    icon="🧠",
    sections=("concepts", "sources", "notes", "reviews", "progress"),
    metadata_fields=tuple(f.name for f in KNOWLEDGE_METADATA_SCHEMA),
    progress_model=PROGRESS_MANUAL,   # mastery% lives in metadata['progress']
    entity_fields=KNOWLEDGE_ENTITY_FIELDS,  # v15.1.0-alpha.9
)

register(KNOWLEDGE_TEMPLATE)


# ── Validating create helper (template-local; OS unchanged) ────────────────
def create_knowledge_workspace(engine, user_id, title, metadata=None,
                               seed_milestones=False):
    """Create a Knowledge workspace through the generic Entity Engine,
    applying this template's validation first. Raises EntityValidationError
    (the OS's own validation error type) on bad metadata -- the engine
    itself stays knowledge-agnostic. Returns the created Workspace.

    Same pattern as create_game_workspace: validate with your rules, then
    call the unchanged `engine.create_workspace(..., template=<key>)`."""
    errors = validate_knowledge_metadata(metadata or {})
    if errors:
        raise EntityValidationError("; ".join(errors))
    clean = normalize_knowledge_metadata(metadata)
    return engine.create_workspace(
        user_id, title, template=KNOWLEDGE_KEY,
        seed_milestones=seed_milestones, metadata=clean)
