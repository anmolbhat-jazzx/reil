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


# -- graph retriever: shared tokenization + noise exclusion -------------------
def _retriever_symbols():
    from knowledge_builder.models import Symbol

    def sym(i, name, file, kind, doc=None):
        return Symbol(
            id=i,
            label=name,
            name=name,
            source_file=file,
            source_location="L10",
            kind=kind,
            docstring=doc,
        )

    return (
        sym(
            "s1",
            "split_document",
            "app/split/splitter.py",
            "function",
            "Split a document into chunks for indexing.",
        ),
        sym(
            "s2",
            "embed_chunks",
            "app/embedding/vector.py",
            "method",
            "Create embedding vectors for each chunk.",
        ),
        sym(
            "s3",
            "enrich_span",
            "common/utils/telemetry.py",
            "function",
            "Set attributes on the current span.",
        ),
        sym("s4", "collection/api.py", "app/collection/api.py", "file"),
        sym(
            "s5",
            "test_embedding_skipped",
            "tests/unit/test_embedding.py",
            "function",
            "Test embedding is skipped.",
        ),
    )


def _retrieve(query: str):
    from knowledge_builder.models import GraphNode
    from knowledge_builder.query.retrieval import GraphRetriever

    symbols = _retriever_symbols()
    nodes = tuple(
        GraphNode(id=s.id, label=s.label, file_type="code", source_file=s.source_file)
        for s in symbols
    )
    return GraphRetriever(symbols, nodes, ()).retrieve(query, hops=0, max_candidates=10)


def test_retriever_matches_stemmed_words_in_docstrings() -> None:
    """``chunked``/``embedded`` must reach ``chunk``/``embedding`` — via docstrings.

    Order between two equally-relevant answers is arbitrary; what matters is that both
    outrank unrelated code that merely shares the word "document".
    """
    names = [s.name for s in _retrieve("how are documents chunked and embedded")]
    assert set(names[:2]) == {"embed_chunks", "split_document"}
    assert "enrich_span" not in names  # telemetry shares no stemmed word


def test_retriever_excludes_file_nodes() -> None:
    """A file node slices from line 1 — the import block, never an answer."""
    names = [s.name for s in _retrieve("collection api documents")]
    assert "collection/api.py" not in names


def test_retriever_demotes_tests() -> None:
    results = _retrieve("how are documents chunked and embedded")
    names = [s.name for s in results]
    if "test_embedding_skipped" in names:
        assert names.index("test_embedding_skipped") == len(names) - 1
