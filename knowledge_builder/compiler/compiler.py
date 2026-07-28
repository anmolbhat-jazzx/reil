"""Compiler — the high-level orchestrator.

The compiler is constructed with an explicit list of passes (dependency injection), so
the pass set is fully pluggable and testable. The standard production pipeline is
assembled in :mod:`knowledge_builder.build`.
"""

from __future__ import annotations

from collections.abc import Sequence

from knowledge_builder.compiler.artifact import KnowledgeArtifact
from knowledge_builder.compiler.config import CompilerConfig
from knowledge_builder.compiler.context import CompilationContext
from knowledge_builder.compiler.pass_base import CompilerPass
from knowledge_builder.compiler.pipeline import CompilationPipeline, ProgressHook


class Compiler:
    """Runs a configured pipeline of passes against a repository."""

    def __init__(self, passes: Sequence[CompilerPass]) -> None:
        self._pipeline = CompilationPipeline(passes)

    @property
    def pipeline(self) -> CompilationPipeline:
        return self._pipeline

    def compile(
        self, config: CompilerConfig, progress: ProgressHook | None = None
    ) -> KnowledgeArtifact:
        """Compile the repository described by ``config`` into a KnowledgeArtifact."""
        context = CompilationContext(config)
        context.logger.info("compile.start", passes=[p.name for p in self._pipeline.passes])
        artifact = self._pipeline.run(context, progress)
        context.logger.info(
            "compile.done",
            modules=len(artifact.repository.modules),
            symbols=len(artifact.repository.symbols),
            errors=len(artifact.errors),
        )
        return artifact
