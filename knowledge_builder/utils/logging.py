"""Structured logging setup.

The package emits structured logs via :mod:`structlog`. No ``print`` statements are
used anywhere in library code; the CLI layer is responsible for any human-facing
console output (via ``rich``). Call :func:`configure_logging` once at process start
(the CLI does this); library code just calls :func:`get_logger`.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

_CONFIGURED = False


def configure_logging(*, level: int = logging.INFO, json_output: bool = False) -> None:
    """Configure structlog + stdlib logging.

    Args:
        level: Minimum log level to emit.
        json_output: When ``True`` render logs as JSON lines (useful for CI /
            machine consumption); otherwise use a human-readable console renderer.
    """
    global _CONFIGURED

    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )
    _CONFIGURED = True


def get_logger(name: str | None = None, **initial_values: Any) -> structlog.stdlib.BoundLogger:
    """Return a bound structured logger, configuring defaults on first use."""
    if not _CONFIGURED:
        configure_logging()
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name or "knowledge_builder")
    if initial_values:
        logger = logger.bind(**initial_values)
    return logger
