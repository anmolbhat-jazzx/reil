"""Phase 7 integration tests: write IR → knowledge.kb → read it back losslessly."""

from __future__ import annotations

from pathlib import Path

import pytest
from knowledge_builder.compiler import CompilationContext
from knowledge_builder.serializer import SCHEMA_VERSION, KnowledgeReader, KnowledgeWriter
from knowledge_builder.utils.errors import QueryError


@pytest.fixture
def kb_path(optimized_context: CompilationContext, tmp_path: Path) -> Path:
    repo = optimized_context.require_ir()
    return KnowledgeWriter().write(repo, tmp_path / "knowledge.kb")


def test_written_file_exists_with_schema_version(kb_path: Path) -> None:
    assert kb_path.is_file()
    with KnowledgeReader(kb_path) as reader:
        assert reader.schema_version() == SCHEMA_VERSION


def test_round_trip_collections(optimized_context: CompilationContext, kb_path: Path) -> None:
    repo = optimized_context.require_ir()
    with KnowledgeReader(kb_path) as reader:
        assert set(reader.symbols()) == set(repo.symbols)
        assert set(reader.modules()) == set(repo.modules)
        assert set(reader.services()) == set(repo.services)
        assert set(reader.controllers()) == set(repo.controllers)
        assert set(reader.apis()) == set(repo.apis)
        assert set(reader.concepts()) == set(repo.concepts)
        assert set(reader.workflows()) == set(repo.workflows)
        assert set(reader.dependencies()) == set(repo.dependencies)
        assert set(reader.graph_nodes()) == set(repo.graph_nodes)
        assert set(reader.relationships()) == set(repo.relationships)
        assert set(reader.summaries()) == set(repo.summaries)


def test_round_trip_metadata(optimized_context: CompilationContext, kb_path: Path) -> None:
    repo = optimized_context.require_ir()
    with KnowledgeReader(kb_path) as reader:
        assert reader.metadata() == repo.metadata


def test_load_repository_reconstructs(optimized_context: CompilationContext, kb_path: Path) -> None:
    repo = optimized_context.require_ir()
    with KnowledgeReader(kb_path) as reader:
        restored = reader.load_repository()
    assert set(restored.modules) == set(repo.modules)
    assert restored.metadata == repo.metadata


def test_lookups(kb_path: Path) -> None:
    with KnowledgeReader(kb_path) as reader:
        assert reader.module_by_name("Authentication") is not None
        assert reader.module_by_name("authentication") is not None  # case-insensitive
        assert reader.concept_by_label("JWT") is not None
        assert reader.service_by_name("AuthService") is not None
        assert reader.counts()["modules"] == 2


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(QueryError):
        KnowledgeReader(tmp_path / "nope.kb")


def test_writer_overwrites(optimized_context: CompilationContext, tmp_path: Path) -> None:
    repo = optimized_context.require_ir()
    target = tmp_path / "knowledge.kb"
    KnowledgeWriter().write(repo, target)
    first_size = target.stat().st_size
    # Writing again must not append/duplicate rows.
    KnowledgeWriter().write(repo, target)
    with KnowledgeReader(target) as reader:
        assert reader.counts()["modules"] == 2
    assert target.stat().st_size == first_size
