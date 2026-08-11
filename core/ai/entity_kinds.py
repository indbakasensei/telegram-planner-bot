"""
entity_kinds.py -- v15.2 M4 -- generic, template-agnostic entity-kind
classification for the AI Worker.

WHY (live-matrix findings, M4): "Create Artifact Blizzard Slayer",
"Show all artifacts", "Staff of Homa", "Xiao", "Read Book" all require the
system to know an entity's KIND (artifact / weapon / character / goal / …)
without a giant hardcoded per-game name list. This module owns that
classification so the Worker can resolve a kind from the user's words,
existing data, and template metadata -- and, when genuinely necessary, an
optional cached web lookup -- instead of the caller maintaining template
knowledge by hand.

RESOLUTION PRIORITY (owner directive, M4 remediation item 1/15):

  1. existing DB entity type / typed workspace data,
  2. explicit user-provided type ("create artifact X", "a weapon called Y"),
  3. template metadata / known aliases (generic classifiers, NOT per-game),
  4. Worker semantic reasoning (the model sets entity_type on the tool),
  5. optional web/entity-knowledge lookup ONLY when genuinely necessary
     (behind a flag, cached, never the default),
  6. web results cached so a classification is never re-requested.

TEMPLATE-AGNOSTIC (item 14): there is deliberately NO GenshinClassifier /
GenshinEntityResolver / hardcoded name list here. The heuristics below are
generic English classifiers (weapon nouns, role nouns, relic nouns) that apply
to ANY workspace; a 'book' template resolves "Bow of Truth" to a weapon the
same way a 'game' template does. A web resolver (optional) is also generic.
Everything is expressed as an EntityKind string; the tool schemas and the
projection stay kind-agnostic.

THIS MODULE IS OFFLINE + DETERMINISTIC (no database, no LLM, no network by
default): the "known DB type" priority is fed IN by the caller (the create
adapter passes the existing rows), and a web lookup is an explicit opt-in
behind feature_flags -- so the system is fully usable with no internet.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# ── the kind vocabulary ────────────────────────────────────────────────────
# Workspace-entity kinds (stored in milestones.entity_type).
KIND_ENTITY = "entity"
KIND_CHARACTER = "character"
KIND_WEAPON = "weapon"
KIND_ARTIFACT = "artifact"

# Cross-domain kinds (NOT workspace entities -- separate storage, used by
# the typed-list surface list_entities(kind=…)).
KIND_GOAL = "goal"
KIND_TASK = "task"
KIND_HABIT = "habit"

# All kinds the typed-list surface can enumerate. "all" is the union flag.
ENTITY_KINDS = (KIND_ENTITY, KIND_CHARACTER, KIND_WEAPON, KIND_ARTIFACT)
ALL_KINDS = ENTITY_KINDS + (KIND_GOAL, KIND_TASK, KIND_HABIT)
LIST_ALL = "all"

# Source of a classification (priority level, roughly).
SOURCE_EXPLICIT = "explicit"   # priority 2 -- "create artifact X"
SOURCE_DB = "db"               # priority 1 -- an existing row says the kind
SOURCE_TEMPLATE = "template"   # priority 3 -- template/alias metadata
SOURCE_MODEL = "model"         # priority 4 -- the Worker's own reasoning
SOURCE_WEB = "web"             # priority 5 -- optional cached web lookup


@dataclass(frozen=True, slots=True)
class KindResult:
    """One kind classification: the kind, a 0..1 confidence, and where it
    came from. Used by the create adapter to enrich entity_type and by the
    typed-list surface to pick the right domain."""
    kind: str
    confidence: float
    source: str


# ── generic classifier words (aliases, priority 3) ─────────────────────────
# Universal English classifiers, deliberately NOT per-game. A word is a
# WEAK hint (a name containing "staff" is likely a weapon) unless it appears
# as an explicit type declaration ("a staff called X"), which is priority 2.
_WEAK_KIND_HINTS: dict[str, tuple[str, ...]] = {
    KIND_CHARACTER: (
        "character", "char", "hero", "heroine", "persona", "unit",
        "champion", "summoner", "protagonist",
    ),
    KIND_WEAPON: (
        "weapon", "arms", "sword", "greatsword", "blade", "bow", "catalyst",
        "polearm", "staff", "spear", "lance", "hammer", "axe", "dagger",
        "claymore", "gun", "rifle", "cannon", "whip", "scythe",
    ),
    KIND_ARTIFACT: (
        "artifact", "artifacts", "relic", "relics", "trinket", "amulet",
        "talisman", "ornament",
    ),
}

# Words that, when they DIRECTLY follow "create/a/an/the" or precede
# "called/named", declare the entity's kind (priority 2, high confidence).
_STRONG_KIND_WORDS: dict[str, str] = {
    "character": KIND_CHARACTER, "char": KIND_CHARACTER, "hero": KIND_CHARACTER,
    "heroine": KIND_CHARACTER, "persona": KIND_CHARACTER,
    "weapon": KIND_WEAPON, "blade": KIND_WEAPON, "sword": KIND_WEAPON,
    "bow": KIND_WEAPON, "catalyst": KIND_WEAPON, "polearm": KIND_WEAPON,
    "staff": KIND_WEAPON, "spear": KIND_WEAPON, "gun": KIND_WEAPON,
    "artifact": KIND_ARTIFACT, "relic": KIND_ARTIFACT, "trinket": KIND_ARTIFACT,
    "goal": KIND_GOAL, "task": KIND_TASK, "habit": KIND_HABIT,
}

# The classifier nouns that can introduce a kind without the generic ones
# being ambiguous inside a name ("a weapon", "a character", "an artifact").
_EXPLICIT_PREFIX_RE = re.compile(
    r"\b(?:create|add|make|new|another|a|an|the)\s+"
    r"(artifact|artifacts|relic|relics|weapon|weapons|blade|sword|bow|catalyst|"
    r"polearm|staff|spear|gun|character|char|hero|heroine|persona|goal|task|"
    r"habit)\b",
    re.IGNORECASE,
)
# "…called X" / "…named X" / "X the <kind>" (kind right before "called").
_CALLED_KIND_RE = re.compile(
    r"\b(artifact|weapon|character|relic|goal|task|habit)s?\s+"
    r"(?:called|named)\b",
    re.IGNORECASE,
)


def _strong_kind_in(text: str) -> str | None:
    m = _EXPLICIT_PREFIX_RE.search(text or "")
    if m:
        return _STRONG_KIND_WORDS.get(m.group(1).lower())
    m = _CALLED_KIND_RE.search(text or "")
    if m:
        return _STRONG_KIND_WORDS.get(m.group(1).lower())
    return None


def _weak_kind_in(text: str) -> str | None:
    """First weak hint found in a name. Conservative: the hint must be a
    whole word, and a bare 'staff'/'bow' inside a longer name is accepted as
    a weak signal but never overrides an explicit or DB classification."""
    low = (text or "").lower()
    for kind, words in _WEAK_KIND_HINTS.items():
        for w in words:
            if re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", low):
                return kind
    return None


class EntityKindResolver:
    """Deterministic kind resolution. Stateless; callers feed in context.

    ``resolve(text, name, existing_kind=None)``:
      * existing_kind (the entity's current stored entity_type, from the DB
        row for this name) wins -- priority 1;
      * an explicit type declaration in text or name -- priority 2;
      * a weak generic classifier inside the name -- priority 3;
      * otherwise None -- the Worker/model reasons (priority 4), and an
        optional web lookup (priority 5) is a separate, opt-in, cached step.

    ``resolve_for_create(text, name, existing_rows)`` is the create-tool
    helper: it first looks up an existing row for ``name`` (across any kind,
    so a legacy untyped row adopts the typed identity), then falls back to
    the deterministic signals above.
    """

    def resolve(self, text: str | None = None, name: str | None = None,
                existing_kind: str | None = None) -> KindResult | None:
        if existing_kind and existing_kind != KIND_ENTITY:
            return KindResult(existing_kind, 1.0, SOURCE_DB)
        explicit = _strong_kind_in(text) or _strong_kind_in(name)
        if explicit:
            return KindResult(explicit, 0.97, SOURCE_EXPLICIT)
        weak = _weak_kind_in(name) or _weak_kind_in(text)
        if weak and weak != KIND_ENTITY:
            return KindResult(weak, 0.6, SOURCE_TEMPLATE)
        return None

    def resolve_for_create(self, text: str | None, name: str | None,
                           existing_rows) -> KindResult | None:
        """The create-adapter entry point. ``existing_rows`` is an iterable
        of workspace milestones (any entity_type); a row whose normalized
        title matches ``name`` supplies priority 1."""
        if existing_rows:
            for row in existing_rows:
                if row.title and row.title.lower() == (name or "").lower():
                    if getattr(row, "entity_type", KIND_ENTITY) not in (None, KIND_ENTITY):
                        return KindResult(
                            getattr(row, "entity_type", KIND_ENTITY), 1.0, SOURCE_DB)
        return self.resolve(text=text, name=name)
