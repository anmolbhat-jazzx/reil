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


def test_imports_are_not_expected_to_belong_to_a_module() -> None:
    """A module is a business capability; an import belongs to none by construction.

    Warning on every unassigned ``uuid``/``AsyncSession`` node buries the case that
    actually matters — a *definition* the module partition failed to cover.
    """
    from knowledge_builder.models import GraphNode, Symbol

    repo = Repository(
        metadata=Metadata(repo_path="/x", repo_name="x"),
        graph_nodes=(
            GraphNode(id="i1", label="UUID", file_type="code"),  # type: ignore[arg-type]
            GraphNode(id="d1", label="login", file_type="code"),  # type: ignore[arg-type]
        ),
        symbols=(
            Symbol(id="i1", label="UUID", name="UUID", kind="import", start_line=1),
            Symbol(id="d1", label="login", name="login", kind="function", start_line=10),
        ),
    )
    report = validate_repository(repo)
    unassigned = {i.message for i in report.warnings if "module" in i.message}

    assert not any("i1" in m for m in unassigned)
    assert any("d1" in m for m in unassigned)
    # ...and the reference must not be re-reported as a *dangling* module pointer either:
    # its ``module_id`` is absent, which is the expected state, not a broken reference.
    assert not any(i.code == "SYMBOL_BAD_MODULE" for i in report.errors)


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


def test_detects_two_symbols_claiming_one_definition() -> None:
    """``(name, source_file, start_line)`` is what external indexers join on.

    Two definitions claiming the same tuple become two rows for one entity downstream,
    so the collision has to be an error here — not a surprise in the consumer's importer.
    """
    from knowledge_builder.models import GraphNode, Symbol

    def _sym(sid: str, kind: str) -> Symbol:
        return Symbol(
            id=sid,
            label="DocumentService",
            name="DocumentService",
            kind=kind,
            source_file="src/DocumentService.java",
            start_line=9,
        )

    repo = Repository(
        metadata=Metadata(repo_path="/x", repo_name="x"),
        graph_nodes=(
            GraphNode(id="a", label="DocumentService", file_type="code"),  # type: ignore[arg-type]
            GraphNode(id="b", label="DocumentService", file_type="code"),  # type: ignore[arg-type]
        ),
        symbols=(_sym("a", "class"), _sym("b", "class")),
    )
    assert any(i.code == "DUP_SYMBOL_DEF" for i in validate_repository(repo).errors)

    # The file node that *contains* the class shares its name and line span but is a
    # reference, not a definition — it must not trip the check.
    ok = repo.model_copy(update={"symbols": (_sym("a", "class"), _sym("b", "file"))})
    assert not any(i.code == "DUP_SYMBOL_DEF" for i in validate_repository(ok).errors)


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
