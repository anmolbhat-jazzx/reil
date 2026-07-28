"""CompilerPass — the abstract base every compilation stage implements."""

from __future__ import annotations

from abc import ABC, abstractmethod

from knowledge_builder.compiler.context import CompilationContext


class CompilerPass(ABC):
    """A single, composable stage of the compilation pipeline.

    A pass reads ``context.ir`` (and/or ``context.config``), performs one unit of work,
    and writes its result back via ``context.set_ir(...)``. Passes must be stateless
    with respect to each other — all shared state flows through the context.
    """

    #: Stable, human-readable name used in logs and diagnostics.
    name: str = "pass"

    @abstractmethod
    def run(self, context: CompilationContext) -> None:
        """Execute the pass, mutating ``context`` in place."""
        raise NotImplementedError

    def __repr__(self) -> str:
        return f"<{type(self).__name__} name={self.name!r}>"
