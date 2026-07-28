"""DependencyPass (Phase 4) — derive :class:`Dependency` records from edges.

``imports`` and ``references`` edges between symbols become directed dependencies. Since
graphify only records nodes it extracted, both endpoints are in-repo; a dependency whose
target is not a known symbol is flagged ``external``.
"""

from __future__ import annotations

from typing import Literal

from knowledge_builder.compiler.context import CompilationContext
from knowledge_builder.compiler.pass_base import CompilerPass
from knowledge_builder.models.base import IMPORT_RELATIONS, REFERENCE_RELATIONS
from knowledge_builder.models.dependency import Dependency


def _kind_for(relation: str) -> Literal["import", "reference"] | None:
    if relation in IMPORT_RELATIONS:
        return "import"
    if relation in REFERENCE_RELATIONS:
        return "reference"
    return None


class DependencyPass(CompilerPass):
    """Turn import/reference edges into typed dependencies."""

    name = "dependencies"

    def run(self, context: CompilationContext) -> None:
        ir = context.require_ir()
        node_ids = {n.id for n in ir.graph_nodes}
        node_label = {n.id: n.label for n in ir.graph_nodes}

        dependencies = []
        for rel in ir.relationships:
            kind = _kind_for(rel.relation)
            if kind is None:
                continue
            external = rel.target_id not in node_ids
            dependencies.append(
                Dependency(
                    id=f"dep::{rel.id}",
                    source_id=rel.source_id,
                    target_id=None if external else rel.target_id,
                    target_name=node_label.get(rel.target_id, rel.target_id),
                    kind=kind,
                    external=external,
                )
            )

        context.set_ir(ir.evolve(dependencies=tuple(dependencies)))
        context.stats["dependencies"] = len(dependencies)
        context.info(self.name, "extracted dependencies", count=len(dependencies))
