"""
workspace_retriever.py -- real retrieval over stored Workspace data
(v15.1.0-alpha.8): the first concrete `Retriever` (alpha.2 shipped only the
interface + NullRetriever).

Instead of answering only from a single precise tool, the Cognitive Engine
can now gather *related* context from everything the user has stored in a
Workspace -- entity titles + statuses and every progress note -- and ground
its answer in that. This is what lets natural questions ("what do I know
about Hu Tao?", "anything on the drone build?") work without a
feature-specific command per question.

Retrieval is deterministic keyword scoring over SQLite content (token
overlap with type weights), not embeddings -- no model, no network, fully
offline-testable. A vector/FTS backend can later replace `retrieve()`
without touching callers, because they depend only on the `Retriever`
contract. Every returned Document is real stored data (grounding: the AI
never invents Workspace facts).
"""
from __future__ import annotations

import re

from core.ai.retrieval import Document, Retriever
from core.ai.tools import Tool, ToolSpec
from core.storage import Storage
from core.workspace.engine import EntityEngine

# Words too common to help matching (question words, articles, pronouns).
_STOP = frozenset(
    "a an the of to in on for and or is are was were be been what when where "
    "who which why how do does did my your me i you it its this that about "
    "tell show find search have has had can could would should any anything "
    "know with at as".split())


def _tokens(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", (text or "").lower())
            if len(w) > 2 and w not in _STOP]


class WorkspaceRetriever(Retriever):
    """Ranked keyword retrieval across a user's workspaces, entities, and
    notes. Bound to one user (the Retriever contract is `retrieve(query,k)`)."""

    # relevance weight per source type (titles matter more than note bodies)
    _WEIGHT = {"workspace": 2.0, "entity": 2.0, "note": 1.0}

    def __init__(self, user_id, engine: EntityEngine | None = None,
                 storage: Storage | None = None):
        self._uid = user_id
        self._eng = engine or EntityEngine()
        self._s = storage or Storage()

    def _candidates(self):
        """(kind, id, text, metadata) for everything stored in the user's
        workspaces -- the corpus retrieval scores against."""
        out = []
        for w in self._eng.list_workspaces(self._uid, status=None):
            out.append(("workspace", f"workspace:{w.id}",
                        f"{w.title} ({w.template})", {"workspace": w.title}))
            for m in self._eng.list_milestones(self._uid, w.id):
                out.append(("entity", f"milestone:{m.id}",
                            f"{m.title} [{m.status}] in {w.title}",
                            {"workspace": w.title, "status": m.status,
                             "entity": m.title}))
            for n in self._eng.list_notes(self._uid, w.id):
                out.append(("note", f"note:{n.id}",
                            f"{n.content} (in {w.title})", {"workspace": w.title}))
        return out

    def retrieve(self, query: str, k: int = 5) -> list[Document]:
        q = set(_tokens(query))
        if not q:
            return []
        scored = []
        for kind, doc_id, text, meta in self._candidates():
            toks = set(_tokens(text))
            overlap = q & toks
            if not overlap:
                continue
            score = len(overlap) * self._WEIGHT.get(kind, 1.0)
            meta = {**meta, "kind": kind}
            scored.append(Document(id=doc_id, text=text, score=score, metadata=meta))
        scored.sort(key=lambda d: d.score, reverse=True)
        return scored[:k]


class RecallTool(Tool):
    """The retrieval tool the planner routes broad/recall questions to:
    'what do I know about X', 'tell me about X', 'anything on X'. Grounds the
    answer in real stored data; says so plainly when nothing matches."""

    def __init__(self, retriever: WorkspaceRetriever):
        self._r = retriever

    @property
    def spec(self):
        return ToolSpec(
            "recall",
            "Search everything stored across the user's workspaces (entities, "
            "statuses, notes) for anything related to the question. Use for "
            "broad/open questions rather than a single specific field.",
            {"type": "object", "properties": {
                "query": {"type": "string",
                          "description": "the user's question or topic keywords"}}})

    def run(self, query=None, **kwargs):
        docs = self._r.retrieve(query or "", k=6)
        if not docs:
            return "I couldn't find anything about that in your saved data."
        lines = "\n".join(f"• {d.text}" for d in docs)
        return f"Here's what I found in your workspaces:\n{lines}"
