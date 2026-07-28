"""ConceptPass (Phase 5) — harvest concepts from graphify's semantic nodes.

Deterministic: no LLM is called. Nodes graphify already tagged ``concept`` or
``rationale`` become :class:`Concept` records, linked to the symbols/nodes they relate
to via semantic edges. Concepts are then attached to the modules whose symbols they
touch.
"""

from __future__ import annotations

from collections import defaultdict

from knowledge_builder.compiler.context import CompilationContext
from knowledge_builder.compiler.pass_base import CompilerPass
from knowledge_builder.models.base import SEMANTIC_RELATIONS, FileType
from knowledge_builder.models.concept import Concept
from knowledge_builder.models.module import Module
from knowledge_builder.models.symbol import Symbol

_CONCEPT_TYPES = frozenset({FileType.CONCEPT, FileType.RATIONALE})


class ConceptPass(CompilerPass):
    """Project concept/rationale nodes into :class:`Concept` records."""

    name = "concepts"

    def run(self, context: CompilationContext) -> None:
        ir = context.require_ir()
        concept_nodes = {n.id: n for n in ir.graph_nodes if n.file_type in _CONCEPT_TYPES}

        related: dict[str, set[str]] = defaultdict(set)
        for rel in ir.relationships:
            if rel.relation not in SEMANTIC_RELATIONS:
                continue
            if rel.source_id in concept_nodes:
                related[rel.source_id].add(rel.target_id)
            if rel.target_id in concept_nodes:
                related[rel.target_id].add(rel.source_id)

        concepts = tuple(
            Concept(
                id=node.id,
                label=node.label,
                file_type=node.file_type,
                rationale=node.rationale,
                source_file=node.source_file,
                source_location=node.source_location,
                related_ids=tuple(sorted(related.get(node.id, set()))),
            )
            for node in concept_nodes.values()
        )

        modules = _attach_concepts_to_modules(ir.modules, concepts, ir.symbol_by_id())

        context.set_ir(ir.evolve(concepts=concepts, modules=modules))
        context.stats["concepts"] = len(concepts)
        context.info(self.name, "harvested concepts", count=len(concepts))


def _attach_concepts_to_modules(
    modules: tuple[Module, ...],
    concepts: tuple[Concept, ...],
    symbols_by_id: dict[str, Symbol],
) -> tuple[Module, ...]:
    module_concepts: dict[str, set[str]] = defaultdict(set)
    for concept in concepts:
        for related_id in concept.related_ids:
            symbol = symbols_by_id.get(related_id)
            if symbol and symbol.module_id:
                module_concepts[symbol.module_id].add(concept.id)
    return tuple(
        module.model_copy(
            update={
                "concept_ids": tuple(
                    sorted(set(module.concept_ids) | module_concepts.get(module.id, set()))
                )
            }
        )
        for module in modules
    )
