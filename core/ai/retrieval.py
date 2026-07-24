"""
retrieval.py -- retrieval abstraction (v15.1.0-alpha.2, FOUNDATION only).

Defines the stable interface the future AI Intelligence Layer will use to
pull relevant context (memories, notes, timeline, docs) into a prompt --
without committing to any particular backend yet. Shipping the interface now
keeps later code (RAG over SQLite FTS, an embedding store, etc.) a drop-in
`Retriever` implementation rather than a refactor.

This milestone provides the contract + a `NullRetriever` (returns nothing),
NOT a real retrieval implementation -- that is a subsequent milestone.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Document:
    """One retrieved chunk. `score` is retriever-defined relevance (higher =
    better); `metadata` carries source pointers (e.g. table + row id)."""
    id: str
    text: str
    score: float = 0.0
    metadata: dict = field(default_factory=dict)


class Retriever(ABC):
    """Turns a query into a ranked list of Documents. Implementations must be
    side-effect-free and safe to call from any layer."""

    @abstractmethod
    def retrieve(self, query: str, k: int = 5) -> list[Document]:
        ...


class NullRetriever(Retriever):
    """The default no-op retriever: always returns an empty list. Lets the
    rest of the AI layer depend on the `Retriever` contract today while real
    retrieval is built later, with no behavior change."""

    def retrieve(self, query: str, k: int = 5) -> list[Document]:
        return []
