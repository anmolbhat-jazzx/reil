"""KnowledgeArtifact — the in-memory result of a compilation.

Wraps the final Repository IR together with the diagnostics and per-pass stats gathered
during compilation. The serializer turns the IR into ``knowledge.kb``; the artifact is
what the ``Compiler`` returns to callers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from knowledge_builder.compiler.context import Diagnostic, Severity
from knowledge_builder.models.repository import Repository


@dataclass(frozen=True)
class KnowledgeArtifact:
    """The compiled result held in memory."""

    repository: Repository
    diagnostics: tuple[Diagnostic, ...] = ()
    stats: dict[str, Any] = field(default_factory=dict)

    @property
    def errors(self) -> tuple[Diagnostic, ...]:
        return tuple(d for d in self.diagnostics if d.severity is Severity.ERROR)

    @property
    def warnings(self) -> tuple[Diagnostic, ...]:
        return tuple(d for d in self.diagnostics if d.severity is Severity.WARNING)

    def has_errors(self) -> bool:
        return bool(self.errors)
