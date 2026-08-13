"""Phase 9 tests: the KnowledgeBase runtime SDK."""

from __future__ import annotations

from pathlib import Path

import knowledge_builder
import pytest
from knowledge_builder.compiler import CompilationContext
from knowledge_builder.query import KnowledgeBase
from knowledge_builder.serializer import KnowledgeWriter


@pytest.fixture
def kb(optimized_context: CompilationContext, tmp_path: Path) -> KnowledgeBase:
    path = KnowledgeWriter().write(optimized_context.require_ir(), tmp_path / "knowledge.kb")
    with KnowledgeBase(path) as base:
        yield base


def test_knowledge_base_is_public() -> None:
    assert knowledge_builder.KnowledgeBase is KnowledgeBase


def test_get_module(kb: KnowledgeBase) -> None:
    module = kb.get_module("Authentication")
    assert module is not None
    assert module.name == "Authentication"


def test_get_service_and_concept(kb: KnowledgeBase) -> None:
    assert kb.get_service("AuthService") is not None
    assert kb.get_concept("JWT") is not None
    assert kb.get_workflow("Login Flow") is not None
    assert kb.get_module("does-not-exist") is None


def test_query_ranks_relevant_entities(kb: KnowledgeBase) -> None:
    results = kb.query("upload workflow")
    assert results
    kinds_names = {(r.kind, r.name) for r in results}
    # the Upload Pipeline module should surface for "upload"
    assert ("module", "Upload Pipeline") in kinds_names
    # results are sorted by descending score
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)


def test_query_empty_text(kb: KnowledgeBase) -> None:
    assert kb.query("") == []


def test_context_renders_symbol_detail() -> None:
    """A bare name teaches a model nothing — signature and docstring must come along."""
    from knowledge_builder.models import Symbol
    from knowledge_builder.query.knowledge_base import _render_symbol

    lines = _render_symbol(
        Symbol(
            id="s",
            label="upload",
            name="upload",
            kind="function",
            qualified_name="src.upload.service.upload",
            signature="(blob)",
            docstring="Upload a blob to object storage.",
            source_file="src/upload/service.py",
            start_line=10,
        )
    )
    rendered = "\n".join(lines)
    assert "src.upload.service.upload(blob)" in rendered
    assert "src/upload/service.py:L10" in rendered
    assert "Upload a blob to object storage." in rendered


def test_is_test_detection() -> None:
    from knowledge_builder.query.knowledge_base import _is_test

    assert _is_test("tests/unit/test_zip_upload.py")
    assert _is_test("app/zip_upload/test_helpers.py")
    assert not _is_test("app/zip_upload/service.py")


def test_production_outranks_tests_unless_asked_for(tmp_path: Path) -> None:
    """``test_zip_upload_processing`` matches more query words than the feature itself.

    A tie-break is therefore too weak — it needs a score penalty — but the penalty must
    lift when the question is explicitly about tests.
    """
    from knowledge_builder.models import Metadata, Module, Repository

    repo = Repository(
        metadata=Metadata(repo_path=".", repo_name="r"),
        modules=(
            Module(
                id="m1",
                name="test_zip_upload_processing.py",
                source_paths=("tests/unit/test_zip_upload_processing.py",),
            ),
            Module(
                id="m2",
                name="zip_upload/service.py",
                source_paths=("app/zip_upload/service.py",),
            ),
        ),
    )
    path = KnowledgeWriter().write(repo, tmp_path / "rank.kb")
    with KnowledgeBase(path) as base:
        feature_first = base.query("how does zip upload processing work")
        assert feature_first[0].name == "zip_upload/service.py"
        tests_first = base.query("zip upload tests")
        assert tests_first[0].name == "test_zip_upload_processing.py"


def test_stats(kb: KnowledgeBase) -> None:
    stats = kb.stats()
    assert stats["repo_name"] == "sample_repo"
    assert stats["counts"]["modules"] == 2
