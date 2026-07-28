"""Phase 8 tests: validation report and validate pass (clean + broken IR)."""

from __future__ import annotations

from pathlib import Path

import pytest
from knowledge_builder.compiler import CompilationContext, CompilerConfig
from knowledge_builder.models import Concept, Metadata, Module, Repository, Summary
from knowledge_builder.passes.validate_pass import VALIDATION_REPORT, ValidatePass
from knowledge_builder.utils.errors import ValidationError
from knowledge_builder.validation import validate_repository


def test_clean_repo_validates(optimized_context: CompilationContext) -> None:
    report = validate_repository(optimized_context.require_ir())
    assert report.ok, [i.message for i in report.errors]


def test_detects_dangling_module_symbol() -> None:
    repo = Repository(
        metadata=Metadata(repo_path="/x", repo_name="x"),
        modules=(Module(id="m1", name="M", symbol_ids=("ghost",)),),
    )
    report = validate_repository(repo)
    assert any(i.code == "SYMBOL_REF" for i in report.errors)


def test_detects_duplicate_concepts() -> None:
    repo = Repository(
        metadata=Metadata(repo_path="/x", repo_name="x"),
        concepts=(
            Concept(id="c1", label="JWT", related_ids=("s",)),
            Concept(id="c2", label="jwt", related_ids=("s",)),
        ),
    )
    report = validate_repository(repo)
    assert any(i.code == "DUP_CONCEPT" for i in report.errors)


def test_detects_duplicate_summaries() -> None:
    repo = Repository(
        metadata=Metadata(repo_path="/x", repo_name="x"),
        modules=(Module(id="m1", name="M"),),
        summaries=(
            Summary(id="s1", module_id="m1", purpose="a"),
            Summary(id="s2", module_id="m1", purpose="b"),
        ),
    )
    report = validate_repository(repo)
    assert any(i.code == "DUP_SUMMARY" for i in report.errors)


def test_orphan_concept_is_warning() -> None:
    repo = Repository(
        metadata=Metadata(repo_path="/x", repo_name="x"),
        concepts=(Concept(id="c1", label="Loner"),),
    )
    report = validate_repository(repo)
    assert any(i.code == "ORPHAN_CONCEPT" for i in report.warnings)
    assert report.ok  # warnings don't fail validation


def test_validate_pass_records_report(optimized_context: CompilationContext) -> None:
    ValidatePass().run(optimized_context)
    report = optimized_context.artifacts[VALIDATION_REPORT]
    assert report.ok
    assert optimized_context.stats["validation"]["errors"] == 0


def test_strict_mode_raises_on_error() -> None:
    config = CompilerConfig(repo_path=Path("/x"), strict=True)
    context = CompilationContext(config)
    context.set_ir(
        Repository(
            metadata=Metadata(repo_path="/x", repo_name="x"),
            modules=(Module(id="m1", name="M", symbol_ids=("ghost",)),),
        )
    )
    with pytest.raises(ValidationError):
        ValidatePass().run(context)
