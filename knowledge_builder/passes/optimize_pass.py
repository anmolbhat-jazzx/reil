"""OptimizePass (Phase 6) — apply compiler-style optimizations to the IR.

Runs the optimizer functions in order: deduplicate concepts (shared-concept
extraction), normalize references (drop danglers), then compress summaries. Each step is
a pure IR→IR transform.
"""

from __future__ import annotations

from knowledge_builder.compiler.context import CompilationContext
from knowledge_builder.compiler.pass_base import CompilerPass
from knowledge_builder.optimizer import (
    compress_summaries,
    deduplicate_concepts,
    normalize_references,
)


class OptimizePass(CompilerPass):
    """Deduplicate, normalize, and compress the IR."""

    name = "optimize"

    def run(self, context: CompilationContext) -> None:
        ir = context.require_ir()
        before = {"concepts": len(ir.concepts), "summaries": len(ir.summaries)}

        ir = deduplicate_concepts(ir)
        ir = normalize_references(ir)
        ir = compress_summaries(ir)

        after = {"concepts": len(ir.concepts), "summaries": len(ir.summaries)}
        context.set_ir(ir)
        context.stats["optimize"] = {"before": before, "after": after}
        context.info(
            self.name,
            "optimized IR",
            concepts_removed=before["concepts"] - after["concepts"],
            summaries_removed=before["summaries"] - after["summaries"],
        )
