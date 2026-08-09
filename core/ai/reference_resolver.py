"""
reference_resolver.py -- deterministic conversational reference resolution (M1).

Resolves pronouns, conversational references ("this one", "that one",
"the current one") and ordinals ("first one", "last one") against context
already established in this conversation:

  1. the DB-backed *active entity* (tg_active_context) -- strongest signal,
  2. the per-user recent-mention stack + last ordered list (ReferenceContext).

The resolver NEVER mutates the database and NEVER invokes the LLM. It only
resolves a referent (or reports ambiguity) so the caller can act through
its existing handlers. An unresolvable reference resolves to kind="none"
and the caller falls through to the normal pipeline -- never a guess,
never a crash, never an invented entity.

Identity is by (kind, workspace_id, id); display titles are only for
rendering and clarification. No gender or domain assumptions: "he"/"she"/
"it" all resolve deictically against the same metadata, and a bare
Genshin-style template is in no way assumed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from core.ai.reference_context import Referent, ReferenceContext
from core.storage import Storage
from core.workspace.engine import EntityEngine

# Workspace entities are milestones under the hood (matches
# core/workspace/groups_app.py ENTITY_TYPE).
ENTITY_TYPE = "milestone"

# Strong reference signals -- gendered/plural pronouns.
_PRONOUNS = frozenset({
    "he", "him", "his", "she", "her", "hers", "they", "them", "their",
})

# Strong conversational deictic phrases.
_CONVERSATIONAL_PHRASES = (
    "this one", "that one", "the current one",
    "the current character", "the current entity", "the one",
)

# Weak deictic tokens -- only treated as references when the message also
# carries an entity-intent signal (avoids hijacking e.g. "what time is it?").
_WEAK = frozenset({"it", "its", "this", "that"})

# Ordinal reference phrases: "the first one", "second one", ... "last one".
_ORDINAL_RE = re.compile(
    r"(?:the\s+)?(first|second|third|fourth|fifth|last)\s+one\b")
_ORDINAL_INDEX = {
    "first": 0, "second": 1, "third": 2, "fourth": 3, "fifth": 4, "last": -1,
}

# Entity-intent signals (mirrors EntityManager's keyword pre-check).
_ENTITY_SIGNALS = (
    "create", "add ", "new ", "make ", "character", "entity", "level",
    "priority", "element", "weapon", "upgrade", "update", "change ", "set ",
    "status", "current", "show", "find ", "who ", "which ", "what ", "list ",
    "all ", "how many", "need ", "done", "complete", "is now", "reached",
    "got", "finally", "just", "finished", "completed", "increased",
)

# Leading retrieve verbs that may introduce a bare reference ("show her").
_RETRIEVE_VERBS = ("show", "display", "view", "see", "get")


def _tokens(text: str) -> set[str]:
    """Lowercased alphabetic word tokens (so "her" never matches "there")."""
    return set(re.findall(r"[a-z]+", text.lower()))


def is_ordinal_phrase(text: str) -> bool:
    return _ORDINAL_RE.search(text.lower()) is not None


def ordinal_index(text: str) -> int | None:
    m = _ORDINAL_RE.search(text.lower())
    if not m:
        return None
    return _ORDINAL_INDEX[m.group(1)]


@dataclass(frozen=True, slots=True)
class Resolution:
    """Outcome of a reference-resolution attempt.

    kind == "entity"   → `entity`/`referent` is the resolved target.
    ambiguous == True  → `candidates` are the plausible referents; the
                         caller should ask for clarification, never guess.
    kind == "none"     → no reference, or a reference that cannot be
                         resolved from available context. Caller falls
                         through; `had_reference` distinguishes "no token
                         present" from "token present but unresolvable".
    """
    kind: str = "none"
    had_reference: bool = False
    has_signal: bool = False
    entity: object | None = None        # resolved Milestone when kind=="entity"
    referent: Referent | None = None
    ambiguous: bool = False
    candidates: tuple = ()              # tuple[Referent, ...] when ambiguous
    stale_active: bool = False          # active-entity id no longer exists


class ReferenceResolver:
    """Resolves references against active-entity + recent/ordered context.

    Injected `storage`/`engine`/`context` for offline testability; defaults
    match EntityManager's own. Never mutates the DB (a dangling active
    entity is reported via `stale_active` for the caller to clear).
    """

    def __init__(self, storage: Storage | None = None,
                 engine: EntityEngine | None = None,
                 context: ReferenceContext | None = None):
        self._s = storage or Storage()
        self._eng = engine or EntityEngine()
        self._ctx = context or ReferenceContext()

    # ── public ───────────────────────────────────────────────────────────
    def resolve(self, user_id: int, text: str, workspace_id: int,
                entities: list) -> Resolution:
        """Detect and resolve a reference in `text` for the given workspace.

        `entities` must be the fresh, non-deleted milestone list for
        `workspace_id` (already loaded by the caller). Soft-deleted rows are
        excluded by list_milestones, so a reference can never resolve to a
        deleted entity.
        """
        text = (text or "").strip()
        if not text:
            return Resolution(kind="none")
        low = text.lower()
        tokens = _tokens(low)

        has_signal = any(k in low for k in _ENTITY_SIGNALS)
        has_strong = bool(tokens & _PRONOUNS) or any(
            p in low for p in _CONVERSATIONAL_PHRASES) or is_ordinal_phrase(low)
        has_weak = bool(tokens & _WEAK)

        if not (has_strong or (has_weak and has_signal)):
            return Resolution(kind="none", has_signal=has_signal)

        # 1. Ordinal references need the last ordered list shown.
        if is_ordinal_phrase(low):
            ordered = [r for r in self._ctx.ordered(user_id)
                       if r.workspace_id == workspace_id]
            idx = ordinal_index(low)
            if ordered and idx is not None and abs(idx) < len(ordered):
                ent = self._find_by_referent(entities, ordered[idx])
                if ent is not None:
                    return Resolution(
                        kind="entity", had_reference=True, has_signal=has_signal,
                        entity=ent, referent=ordered[idx])
            # No ordered context, or index out of range → leave unresolved.
            return Resolution(kind="none", had_reference=True,
                              has_signal=has_signal)

        # 2. Active entity is the strongest deictic signal.
        active = self._s.tg_bindings.get_active(user_id)
        if active and active[0] is not None and active[2] is not None:
            ent = self._find_by_id(entities, active[2])
            if ent is not None:
                return Resolution(
                    kind="entity", had_reference=True, has_signal=has_signal,
                    entity=ent,
                    referent=Referent(kind=ENTITY_TYPE, id=ent.id,
                                      title=ent.title,
                                      workspace_id=workspace_id))
            # Active entity no longer exists (deleted/archived) — report so
            # the caller can clear the dangling pointer. Never resolve to it.
            return Resolution(kind="none", had_reference=True,
                              has_signal=has_signal, stale_active=True)

        # 3. No active entity → recent mentions in this workspace.
        distinct: list[Referent] = []
        seen: set[tuple[str, int]] = set()
        for r in reversed(self._ctx.recent(user_id)):       # most recent first
            if r.workspace_id != workspace_id:
                continue
            key = (r.kind, r.id)
            if key not in seen:
                seen.add(key)
                distinct.append(r)

        if len(distinct) == 1:
            ent = self._find_by_referent(entities, distinct[0])
            if ent is not None:
                return Resolution(
                    kind="entity", had_reference=True, has_signal=has_signal,
                    entity=ent, referent=distinct[0])
            return Resolution(kind="none", had_reference=True,
                              has_signal=has_signal)
        if len(distinct) > 1:
            # Genuinely ambiguous — caller must clarify, never guess.
            return Resolution(kind="none", had_reference=True,
                              has_signal=has_signal, ambiguous=True,
                              candidates=tuple(distinct))

        return Resolution(kind="none", had_reference=True, has_signal=has_signal)

    # ── helpers ──────────────────────────────────────────────────────────
    @staticmethod
    def _find_by_id(entities: list, entity_id: int) -> object | None:
        for m in entities:
            if m.id == entity_id:
                return m
        return None

    @staticmethod
    def _find_by_referent(entities: list, ref: Referent) -> object | None:
        for m in entities:
            if m.id == ref.id and (ref.workspace_id is None
                                   or m.workspace_id == ref.workspace_id):
                return m
        return None
