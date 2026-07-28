"""Phase 0 smoke tests: package imports, version, logging, and typed errors."""

from __future__ import annotations

import knowledge_builder
import pytest
from knowledge_builder.utils import (
    CompilationError,
    KnowledgeBuilderError,
    get_logger,
)


def test_version_is_exposed() -> None:
    assert knowledge_builder.__version__ == "0.1.0"


def test_error_hierarchy() -> None:
    assert issubclass(CompilationError, KnowledgeBuilderError)
    err = CompilationError("boom", pass_name="symbol_pass")
    assert "symbol_pass" in str(err)
    assert "boom" in str(err)


def test_error_family_is_catchable() -> None:
    with pytest.raises(KnowledgeBuilderError):
        raise CompilationError("x")


def test_logger_is_bound() -> None:
    logger = get_logger("test", phase=0)
    # structlog bound loggers expose info(); calling it must not raise.
    logger.info("hello", answer=42)
