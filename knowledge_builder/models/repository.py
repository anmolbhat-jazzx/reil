"""Repository: the root container of the Repository IR.

Every compiler pass reads and returns a ``Repository``. It is immutable; passes produce
an updated copy via :meth:`Repository.evolve`. Collections are tuples so the whole tree
is hashable and cheap to copy structurally.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from knowledge_builder.models.api import Api
from knowledge_builder.models.base import IRModel
from knowledge_builder.models.concept import Concept
from knowledge_builder.models.controller import Controller
from knowledge_builder.models.dependency import Dependency
from knowledge_builder.models.graph import GraphNode, Relationship
from knowledge_builder.models.metadata import Metadata
from knowledge_builder.models.module import Module
from knowledge_builder.models.service import Service
from knowledge_builder.models.summary import Summary
from knowledge_builder.models.symbol import Symbol
from knowledge_builder.models.workflow import Workflow

if TYPE_CHECKING:
    from typing import Any


class Repository(IRModel):
    """The complete intermediate representation of one repository."""

    metadata: Metadata

    # Raw graph layer (faithful to graphify's graph.json).
    graph_nodes: tuple[GraphNode, ...] = ()
    relationships: tuple[Relationship, ...] = ()

    # Typed projections built by the deterministic + semantic passes.
    symbols: tuple[Symbol, ...] = ()
    modules: tuple[Module, ...] = ()
    services: tuple[Service, ...] = ()
    controllers: tuple[Controller, ...] = ()
    apis: tuple[Api, ...] = ()
    workflows: tuple[Workflow, ...] = ()
    concepts: tuple[Concept, ...] = ()
    dependencies: tuple[Dependency, ...] = ()
    summaries: tuple[Summary, ...] = ()

    def evolve(self, **changes: Any) -> Repository:
        """Return a copy of this repository with ``changes`` applied."""
        return self.model_copy(update=changes)

    # -- id lookups ---------------------------------------------------------
    def node_by_id(self) -> dict[str, GraphNode]:
        return {n.id: n for n in self.graph_nodes}

    def symbol_by_id(self) -> dict[str, Symbol]:
        return {s.id: s for s in self.symbols}

    def module_by_id(self) -> dict[str, Module]:
        return {m.id: m for m in self.modules}

    def concept_by_id(self) -> dict[str, Concept]:
        return {c.id: c for c in self.concepts}

    def summary_by_id(self) -> dict[str, Summary]:
        return {s.id: s for s in self.summaries}

    # -- name lookups (case-insensitive) ------------------------------------
    def find_module(self, name: str) -> Module | None:
        return _find_by_name(self.modules, name)

    def find_service(self, name: str) -> Service | None:
        return _find_by_name(self.services, name)

    def find_concept(self, name: str) -> Concept | None:
        key = name.strip().lower()
        for concept in self.concepts:
            if concept.label.strip().lower() == key:
                return concept
        return None


def _find_by_name(items: tuple[Any, ...], name: str) -> Any | None:
    key = name.strip().lower()
    for item in items:
        if item.name.strip().lower() == key:
            return item
    return None
