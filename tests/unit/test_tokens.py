"""Tests for the real tokenizer and KB context/token accounting."""

from __future__ import annotations

from pathlib import Path

import pytest
from knowledge_builder.compiler import CompilationContext
from knowledge_builder.query import KnowledgeBase
from knowledge_builder.serializer import KnowledgeWriter
from knowledge_builder.utils.tokens import count_tokens, tokenizer_name


def test_tokenizer_counts_are_real() -> None:
    assert count_tokens("") == 0
    # A real BPE splits this into multiple tokens; chars/4 would be ~9.
    n = count_tokens("zip upload archive extraction service")
    assert 5 <= n <= 12
    assert tokenizer_name() == "cl100k_base"


@pytest.fixture
def kb(optimized_context: CompilationContext, tmp_path: Path) -> KnowledgeBase:
    path = KnowledgeWriter().write(optimized_context.require_ir(), tmp_path / "knowledge.kb")
    with KnowledgeBase(path) as base:
        yield base


def test_build_context_reports_tokens(kb: KnowledgeBase) -> None:
    result = kb.build_context("explain the upload workflow")
    assert result.tokens > 0
    assert result.tokens == count_tokens(result.text)
    assert result.tokenizer == "cl100k_base"
    assert result.hits
    assert "Question:" in result.text


def test_empty_query_has_minimal_context(kb: KnowledgeBase) -> None:
    result = kb.build_context("")
    assert result.hits == ()
