"""CompilationContext — the mutable working state threaded through the pipeline.

The context is the *only* mutable object in a compilation. It holds the immutable
Repository IR (replaced wholesale by each pass), the config, a logger, and an
append-only diagnostics log. There is no global state; a fresh context is created per
compilation.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

import structlog

from knowledge_builder.compiler.config import CompilerConfig
from knowledge_builder.models.repository import Repository
from knowledge_builder.utils.errors import CompilationError
from knowledge_builder.utils.logging import get_logger


class Severity(StrEnum):
    """Severity of a diagnostic emitted during compilation."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class Diagnostic:
    """A single diagnostic message produced by a pass."""

    __slots__ = ("severity", "pass_name", "message", "details")

    def __init__(
        self,
        severity: Severity,
        pass_name: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.severity = severity
        self.pass_name = pass_name
        self.message = message
        self.details = details or {}

    def __repr__(self) -> str:
        return f"Diagnostic({self.severity}, {self.pass_name!r}, {self.message!r})"


class CompilationContext:
    """Working state for one compilation run."""

    def __init__(
        self,
        config: CompilerConfig,
        *,
        ir: Repository | None = None,
        logger: structlog.stdlib.BoundLogger | None = None,
    ) -> None:
        self.config = config
        self._ir = ir
        self.logger = logger or get_logger("compiler", repo=str(config.repo_path))
        self.diagnostics: list[Diagnostic] = []
        self.stats: dict[str, Any] = {}
        # Scratch space for pass-to-pass data that is NOT part of the persisted IR
        # (e.g. the parsed graphify bundle, community/god metadata).
        self.artifacts: dict[str, Any] = {}

    @property
    def ir(self) -> Repository | None:
        """The current Repository IR, or ``None`` before the load pass runs."""
        return self._ir

    def set_ir(self, ir: Repository) -> None:
        """Replace the current IR (passes call this with their evolved copy)."""
        self._ir = ir

    def require_ir(self) -> Repository:
        """Return the IR or raise if no pass has produced one yet."""
        if self._ir is None:
            raise CompilationError("no Repository IR present; did the load pass run?")
        return self._ir

    # -- diagnostics --------------------------------------------------------
    def diagnose(
        self,
        severity: Severity,
        pass_name: str,
        message: str,
        **details: Any,
    ) -> None:
        self.diagnostics.append(Diagnostic(severity, pass_name, message, details or None))

    def info(self, pass_name: str, message: str, **details: Any) -> None:
        self.diagnose(Severity.INFO, pass_name, message, **details)

    def warning(self, pass_name: str, message: str, **details: Any) -> None:
        self.diagnose(Severity.WARNING, pass_name, message, **details)

    def error(self, pass_name: str, message: str, **details: Any) -> None:
        self.diagnose(Severity.ERROR, pass_name, message, **details)

    def has_errors(self) -> bool:
        return any(d.severity is Severity.ERROR for d in self.diagnostics)
