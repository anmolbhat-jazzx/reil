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


def test_stats(kb: KnowledgeBase) -> None:
    stats = kb.stats()
    assert stats["repo_name"] == "sample_repo"
    assert stats["counts"]["modules"] == 2
