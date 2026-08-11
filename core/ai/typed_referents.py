"""
typed_referents.py -- v15.2 M4: per-kind, recency-ordered typed referent
memory for the AI Worker.

THE PROBLEM (DEBUGGING.md, M4 live failures): tool results reached the model
only as prose step-trace text, and the M1 resolver collapsed every workspace
entity to kind="milestone" with the DB active entity as its strongest signal.
So after a Worker created an entity or goal, the NEXT step had no reliable
typed identity to refer back to: "set him to level 83" / "set its deadline"
could silently resolve to a STALE active entity from a previous user turn
("Create Bennet... " updated Hu Tao; "Set its deadline..." corrupted Xiao's
target_level).

THE FIX (requirements R2/R3/R5/R9): the Worker keeps a per-user, PER-KIND
typed referent memory. Tool adapters note referents (kind, id, name,
workspace_id) whenever they create/update/list something. Resolution is
deterministic and ORDERED:

  1. explicit id / exact name within the requested kind,
  2. a pronoun/deictic word resolves to the MOST RECENT referent of any
     kind -- but if that most-recent referent is a DIFFERENT kind than the
     tool being called, the tool REJECTS (domain conflict) instead of
     silently reaching across domains. This is what stops "set its
     deadline" (a goal op) from ever touching the active character.

M1 stays authoritative wherever there is no run-scoped typed referent: a
tool with `typed_refs=None` (or an unresolvable ref) falls through to the
existing ReferenceResolver exactly as before.

This module is pure data + deterministic resolution -- no database, no
LLM, no Telegram, so it is fully testable offline.
"""
from __future__ import annotations

from dataclasses import dataclass

MAX_REFERENTS = 20

# Pronoun/deictic tokens that trigger typed resolution. Deliberately the
# same conversational vocabulary the M1 resolver understands (it/its/he/
# him/she/her/they/them/this/that), because the Worker and the tool layer
# must agree on what "the current thing" means.
_PRONOUN_TOKENS = (
    "it", "its", "he", "him", "his", "she", "her", "hers",
    "they", "them", "their", "this", "that",
)


@dataclass(frozen=True, slots=True)
class TypedReferent:
    """A stable typed identity for something the current conversation/run
    touched. Identity is (kind, id); `name`/`workspace_id` are for
    rendering and for the tool's own fallback matching."""
    kind: str                 # "entity" | "goal" | "task" | "habit" | ...
    id: int
    name: str
    workspace_id: int | None = None


@dataclass(frozen=True, slots=True)
class ResolveOutcome:
    """Outcome of a typed resolution attempt.

    `referent` set  -> use this exact identity.
    `conflict`      -> the user's deictic word points at a MORE RECENT
                       referent of a DIFFERENT kind; the caller must reject
                       (never cross domains), with `conflict_kind`/name to
                       render a clarifying message.
    neither         -> no run-scoped typed referent applies; caller falls
                       through to the M1 resolver / name match.
    """
    referent: TypedReferent | None = None
    conflict: bool = False
    conflict_kind: str | None = None
    conflict_name: str | None = None


class TypedReferentStore:
    """Per-user, per-kind, most-recent-first typed referent memory.

    One instance is shared across Worker messages for a process (mirroring
    ReferenceContext's singleton pattern) so a goal created in one message
    is still the referent for "its" in the next. Tools consult it before
    the M1 resolver; the prompt renders it as the REFERENTS block.
    """

    def __init__(self) -> None:
        self._by_user: dict[int, list[TypedReferent]] = {}

    # ── writers ──────────────────────────────────────────────────────────
    def note(self, user_id: int, kind: str, id: int, name: str,
             workspace_id: int | None = None) -> None:
        """Record that `(kind, id)` was just the focus. A re-mention moves
        it to the front; identity is (kind, id), never a display name."""
        refs = self._by_user.setdefault(user_id, [])
        refs[:] = [r for r in refs if not (r.kind == kind and r.id == id)]
        refs.append(TypedReferent(kind, id, name, workspace_id))
        if len(refs) > MAX_REFERENTS:
            del refs[:len(refs) - MAX_REFERENTS]

    def note_list(self, user_id: int, kind: str,
                  items: list) -> None:
        """Note a whole listing (most-recent-last) so the newest item is
        the most recent referent -- e.g. list_entities then 'show the last
        one' resolves to the last listed entity."""
        for item in items:
            iid = item.get("id") or item.get("entity_id") or item.get("goal_id")
            title = item.get("title") or item.get("name")
            if iid is not None and title is not None:
                self.note(user_id, kind, int(iid), str(title))

    # ── readers ──────────────────────────────────────────────────────────
    def recent(self, user_id: int, kind: str | None = None) -> list[TypedReferent]:
        refs = self._by_user.get(user_id, [])
        if kind is None:
            return list(refs)
        return [r for r in refs if r.kind == kind]

    def resolve(self, user_id: int, text: str, kind: str) -> ResolveOutcome:
        """Resolve `text` against this user's typed referents for `kind`."""
        refs = self._by_user.get(user_id, [])
        if not refs:
            return ResolveOutcome()
        text = (text or "").strip()
        low = text.lower()

        # 1. explicit id (the REFERENTS block tells the model to pass ids).
        if low.isdigit():
            nid = int(low)
            for r in reversed(refs):
                if r.kind == kind and r.id == nid:
                    return ResolveOutcome(r)
            return ResolveOutcome()

        # 2. exact display name within the requested kind.
        for r in reversed(refs):
            if r.kind == kind and r.name.lower() == low:
                return ResolveOutcome(r)

        # 3. pronoun / deictic word.
        if any(tok in low for tok in _PRONOUN_TOKENS):
            top = refs[-1]                       # most recent of ANY kind
            if top.kind != kind:
                return ResolveOutcome(conflict=True, conflict_kind=top.kind,
                                      conflict_name=top.name)
            for r in reversed(refs):
                if r.kind == kind:
                    return ResolveOutcome(r)
        return ResolveOutcome()

    # ── prompt rendering ─────────────────────────────────────────────────
    def snapshot(self, user_id: int) -> str:
        """The REFERENTS block for the Worker prompt (empty when nothing
        has been touched yet). Renders NEWEST first."""
        refs = self._by_user.get(user_id, [])
        if not refs:
            return ""
        lines = ["KNOWN REFERENTS (typed identity from this conversation; "
                 "pass the exact id=... when a tool accepts an id, else the "
                 "exact name):"]
        for r in reversed(refs):
            ws = f" ws={r.workspace_id}" if r.workspace_id is not None else ""
            lines.append(f"  [{r.kind}] id={r.id} name={r.name!r}{ws}")
        return "\n".join(lines)
