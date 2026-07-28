"""SymbolPass (Phase 4) — project ``code`` nodes into typed :class:`Symbol` records."""

from __future__ import annotations

from knowledge_builder.compiler.context import CompilationContext
from knowledge_builder.compiler.pass_base import CompilerPass
from knowledge_builder.models.base import FileType
from knowledge_builder.models.symbol import Symbol
from knowledge_builder.utils.languages import language_for_path


class SymbolPass(CompilerPass):
    """Create a :class:`Symbol` for every code node in the graph."""

    name = "symbols"

    def run(self, context: CompilationContext) -> None:
        ir = context.require_ir()
        symbols = tuple(
            Symbol(
                id=node.id,
                label=node.label,
                source_file=node.source_file,
                source_location=node.source_location,
                language=language_for_path(node.source_file),
                rationale=node.rationale,
            )
            for node in ir.graph_nodes
            if node.file_type is FileType.CODE
        )
        context.set_ir(ir.evolve(symbols=symbols))
        context.stats["symbols"] = len(symbols)
        context.info(self.name, "extracted symbols", count=len(symbols))
