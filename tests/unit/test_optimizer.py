"""Phase 6 tests: concept dedup, reference normalization, summary compression."""

from __future__ import annotations

from knowledge_builder.compiler import CompilationContext
from knowledge_builder.models import (
    Concept,
    Metadata,
    Module,
    ModuleOrigin,
    Repository,
    Summary,
)
from knowledge_builder.optimizer import (
    compress_summaries,
    deduplicate_concepts,
    normalize_references,
)


def test_concept_dedup_collapses_duplicates(optimized_context: CompilationContext) -> None:
    ir = optimized_context.require_ir()
    jwt_concepts = [c for c in ir.concepts if c.normalized_label == "jwt"]
    assert len(jwt_concepts) == 1  # concept_jwt + concept_jwt_dup merged
    # the canonical concept keeps the rationale from the node that had one
    assert jwt_concepts[0].rationale is not None
    # module references only the canonical id
    auth = ir.find_module("Authentication")
    assert auth is not None
    assert auth.concept_ids == ("concept_jwt",)


def test_dedup_merges_related_ids() -> None:
    repo = Repository(
        metadata=Metadata(repo_path="/x", repo_name="x"),
        concepts=(
            Concept(id="c_a", label="JWT", rationale="token", related_ids=("s1",)),
            Concept(id="c_b", label="jwt", related_ids=("s2",)),
        ),
        modules=(Module(id="m1", name="M", concept_ids=("c_a", "c_b")),),
    )
    out = deduplicate_concepts(repo)
    assert len(out.concepts) == 1
    canonical = out.concepts[0]
    assert canonical.id == "c_a"  # keeper has the rationale
    assert set(canonical.related_ids) == {"s1", "s2"}
    assert out.modules[0].concept_ids == ("c_a",)


def test_reference_normalizer_drops_danglers() -> None:
    repo = Repository(
        metadata=Metadata(repo_path="/x", repo_name="x"),
        modules=(
            Module(
                id="m1",
                name="M",
                symbol_ids=("ghost",),
                concept_ids=("missing",),
                summary_id="nope",
            ),
        ),
    )
    out = normalize_references(repo)
    assert out.modules[0].symbol_ids == ()
    assert out.modules[0].concept_ids == ()
    assert out.modules[0].summary_id is None


def test_summary_compressor_removes_empty() -> None:
    repo = Repository(
        metadata=Metadata(repo_path="/x", repo_name="x"),
        modules=(Module(id="m1", name="M", origin=ModuleOrigin.STANDALONE, summary_id="s1"),),
        summaries=(Summary(id="s1", module_id="m1"),),  # entirely empty
    )
    out = compress_summaries(repo)
    assert out.summaries == ()
    assert out.modules[0].summary_id is None


def test_nonempty_summaries_survive(optimized_context: CompilationContext) -> None:
    ir = optimized_context.require_ir()
    # both fixture modules have populated summaries, so none are dropped
    assert len(ir.summaries) == len(ir.modules)
