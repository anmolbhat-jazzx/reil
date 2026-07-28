"""CompilationPipeline — runs an ordered list of passes over a context."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence

from knowledge_builder.compiler.artifact import KnowledgeArtifact
from knowledge_builder.compiler.context import CompilationContext
from knowledge_builder.compiler.pass_base import CompilerPass
from knowledge_builder.utils.errors import CompilationError, KnowledgeBuilderError

ProgressHook = Callable[[CompilerPass], None]


class CompilationPipeline:
    """An ordered, immutable sequence of compiler passes."""

    def __init__(self, passes: Sequence[CompilerPass]) -> None:
        if not passes:
            raise CompilationError("a pipeline needs at least one pass")
        self._passes: tuple[CompilerPass, ...] = tuple(passes)

    @property
    def passes(self) -> tuple[CompilerPass, ...]:
        return self._passes

    def run(
        self, context: CompilationContext, progress: ProgressHook | None = None
    ) -> KnowledgeArtifact:
        """Run every pass in order, then build the resulting artifact.

        A :class:`KnowledgeBuilderError` from a pass is wrapped in a
        :class:`CompilationError` tagged with the failing pass name and re-raised — never
        swallowed. ``progress`` (if given) is called with each pass before it runs.
        """
        for stage in self._passes:
            if progress is not None:
                progress(stage)
            started = time.perf_counter()
            context.logger.info("pass.start", pass_name=stage.name)
            try:
                stage.run(context)
            except CompilationError:
                raise
            except KnowledgeBuilderError as exc:
                raise CompilationError(str(exc), pass_name=stage.name) from exc
            except Exception as exc:  # noqa: BLE001 - re-raised as typed error, not swallowed
                raise CompilationError(f"unexpected error: {exc}", pass_name=stage.name) from exc
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            context.stats.setdefault("pass_timings_ms", {})[stage.name] = round(elapsed_ms, 2)
            context.logger.info("pass.done", pass_name=stage.name, elapsed_ms=round(elapsed_ms, 2))

        repository = context.require_ir()
        return KnowledgeArtifact(
            repository=repository,
            diagnostics=tuple(context.diagnostics),
            stats=dict(context.stats),
        )
