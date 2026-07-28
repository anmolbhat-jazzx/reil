"""SerializePass (Phase 7 wiring) — write the compiled IR to ``knowledge.kb``.

Placed near the end of the pipeline (before validation) so the Definition-of-Done
ordering — "Writing knowledge.kb…" then "Validating artifact…" — holds.
"""

from __future__ import annotations

from knowledge_builder.compiler.context import CompilationContext
from knowledge_builder.compiler.pass_base import CompilerPass
from knowledge_builder.serializer.writer import KnowledgeWriter

ARTIFACT_PATH = "artifact_path"


class SerializePass(CompilerPass):
    """Serialize the IR to the configured output path."""

    name = "serialize"

    def __init__(self, writer: KnowledgeWriter | None = None) -> None:
        self._writer = writer or KnowledgeWriter()

    def run(self, context: CompilationContext) -> None:
        ir = context.require_ir()
        output_path = context.config.resolved_output_path
        written = self._writer.write(ir, output_path)
        context.artifacts[ARTIFACT_PATH] = written
        context.stats["artifact_path"] = str(written)
        context.info(self.name, "wrote knowledge artifact", path=str(written))
