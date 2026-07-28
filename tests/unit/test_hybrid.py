"""Tests for hybrid context: KB map + exact source slices, with token breakdown."""

from __future__ import annotations

from pathlib import Path

import pytest
from knowledge_builder.compiler import CompilationContext
from knowledge_builder.query import KnowledgeBase
from knowledge_builder.query.snippets import SnippetReader, parse_location
from knowledge_builder.serializer import KnowledgeWriter


def test_parse_location_variants() -> None:
    assert parse_location("L107") == (107, None)
    assert parse_location("L10-L30") == (10, 30)
    assert parse_location("42") == (42, None)
    assert parse_location(None) is None
    assert parse_location("") is None


@pytest.fixture
def kb(optimized_context: CompilationContext, tmp_path: Path) -> KnowledgeBase:
    path = KnowledgeWriter().write(optimized_context.require_ir(), tmp_path / "knowledge.kb")
    with KnowledgeBase(path) as base:
        yield base


def test_hybrid_reads_exact_lines(kb: KnowledgeBase, sample_repo: Path) -> None:
    result = kb.build_hybrid_context("explain the login authentication flow", sample_repo)
    assert result.snippets  # real code was read
    # the login function body (line 10 of the fixture) is in the context
    assert "def login(user):" in result.text


def test_graph_expansion_reaches_callee(kb: KnowledgeBase, sample_repo: Path) -> None:
    # "upload" seeds upload_route; a 1-hop `calls` expansion should also reach upload().
    result = kb.build_hybrid_context("upload", sample_repo, hops=1)
    symbols = {s.symbol for s in result.snippets}
    assert "upload_route" in symbols
    assert "upload" in symbols  # reached via graph edge, not keyword
    # token breakdown is consistent and split into map + code
    assert result.kb_tokens > 0
    assert result.code_tokens > 0
    assert result.tokens >= result.kb_tokens + result.code_tokens - 5
    assert result.tokenizer == "cl100k_base"


def test_hybrid_respects_code_budget(kb: KnowledgeBase, sample_repo: Path) -> None:
    tiny = kb.build_hybrid_context("authentication upload", sample_repo, code_token_budget=1)
    # budget of 1 admits at most a single snippet (the loop keeps the first, then stops)
    assert len(tiny.snippets) <= 1


def test_hybrid_missing_repo_yields_map_only(kb: KnowledgeBase, tmp_path: Path) -> None:
    empty = tmp_path / "no_repo"
    empty.mkdir()
    result = kb.build_hybrid_context("login", empty)
    assert result.snippets == ()  # nothing to read
    assert result.code_tokens == 0
    assert result.kb_tokens > 0


def test_snippet_reader_slices_to_next_symbol(sample_repo: Path) -> None:
    from knowledge_builder.models import Symbol

    a = Symbol(id="a", label="login", source_file="src/auth/service.py", source_location="L10")
    b = Symbol(
        id="b", label="validate_token", source_file="src/auth/service.py", source_location="L32"
    )
    snippets = SnippetReader(sample_repo, max_lines=60).read_for_symbols([a], (a, b))
    assert len(snippets) == 1
    # start-line-only symbol 'a' slices from L10 up to just before L32
    assert snippets[0].start == 10
    assert snippets[0].end == 31
    assert "def login(user):" in snippets[0].code
