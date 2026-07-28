"""Typed exception hierarchy for the knowledge builder.

Every error raised by the package derives from :class:`KnowledgeBuilderError` so
callers can catch the whole family with a single ``except``. Exceptions are never
swallowed internally; passes let them propagate to the pipeline, which turns them
into a structured, actionable message.
"""

from __future__ import annotations


class KnowledgeBuilderError(Exception):
    """Base class for all errors raised by :mod:`knowledge_builder`."""


class LoaderError(KnowledgeBuilderError):
    """Raised when the graphify output for a repository cannot be located."""


class ParseError(KnowledgeBuilderError):
    """Raised when a graphify artifact is present but malformed."""


class CompilationError(KnowledgeBuilderError):
    """Raised when a compiler pass fails to run."""

    def __init__(self, message: str, *, pass_name: str | None = None) -> None:
        self.pass_name = pass_name
        prefix = f"[{pass_name}] " if pass_name else ""
        super().__init__(f"{prefix}{message}")


class SerializationError(KnowledgeBuilderError):
    """Raised when writing or reading a ``knowledge.kb`` artifact fails."""


class ValidationError(KnowledgeBuilderError):
    """Raised when a strict validation run finds integrity errors."""


class QueryError(KnowledgeBuilderError):
    """Raised when a runtime query against ``knowledge.kb`` cannot be answered."""
