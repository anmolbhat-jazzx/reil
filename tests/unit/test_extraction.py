"""Phase 4 tests: symbols, call graph, dependencies, classification, modules."""

from __future__ import annotations

from pathlib import Path

import pytest
from knowledge_builder.compiler import CompilationContext, CompilerConfig
from knowledge_builder.models import ModuleOrigin
from knowledge_builder.passes import (
    CallGraphPass,
    ClassifyPass,
    DependencyPass,
    LoadPass,
    ModulePass,
    SymbolPass,
)
from knowledge_builder.passes.callgraph_pass import CALL_DEGREE


def _extract(config: CompilerConfig) -> CompilationContext:
    context = CompilationContext(config)
    for pass_ in (
        LoadPass(),
        SymbolPass(),
        CallGraphPass(),
        DependencyPass(),
        ClassifyPass(),
        ModulePass(),
    ):
        pass_.run(context)
    return context


@pytest.fixture
def extracted(sample_config: CompilerConfig) -> CompilationContext:
    return _extract(sample_config)


def test_indirect_call_and_re_exports_counted() -> None:
    from knowledge_builder.compiler import CompilationContext, CompilerConfig
    from knowledge_builder.models import GraphNode, Metadata, Relationship, Repository, Symbol
    from knowledge_builder.passes import CallGraphPass, DependencyPass
    from knowledge_builder.passes.callgraph_pass import CALL_DEGREE

    ir = Repository(
        metadata=Metadata(repo_path="/x", repo_name="x"),
        graph_nodes=(
            GraphNode(id="a", label="a", file_type="code"),  # type: ignore[arg-type]
            GraphNode(id="b", label="b", file_type="code"),  # type: ignore[arg-type]
        ),
        symbols=(Symbol(id="a", label="a"), Symbol(id="b", label="b")),
        relationships=(
            Relationship(id="e1", source_id="a", target_id="b", relation="indirect_call"),
            Relationship(id="e2", source_id="a", target_id="b", relation="re_exports"),
        ),
    )
    ctx = CompilationContext(CompilerConfig(repo_path=Path("/x")))
    ctx.set_ir(ir)
    CallGraphPass().run(ctx)
    DependencyPass().run(ctx)

    # indirect_call now contributes to call-graph degree
    assert ctx.artifacts[CALL_DEGREE]["a"]["out"] == 1
    # re_exports now surfaces as an import dependency
    deps = ctx.require_ir().dependencies
    assert any(d.kind == "import" for d in deps)


def test_symbols_extracted_from_code_nodes(extracted: CompilationContext) -> None:
    ir = extracted.require_ir()
    labels = {s.label for s in ir.symbols}
    assert labels == {"login", "validate_token", "handle_login", "upload", "upload_route"}
    assert all(s.language == "python" for s in ir.symbols)


def test_callgraph_degree(extracted: CompilationContext) -> None:
    degree = extracted.artifacts[CALL_DEGREE]
    assert degree["src_auth_service_login"]["in"] == 1  # called by handle_login
    assert degree["src_auth_service_login"]["out"] == 1  # calls validate_token


def test_dependencies(extracted: CompilationContext) -> None:
    ir = extracted.require_ir()
    kinds = sorted(d.kind for d in ir.dependencies)
    assert kinds == ["import", "reference"]
    assert all(not d.external for d in ir.dependencies)


def test_classification(extracted: CompilationContext) -> None:
    ir = extracted.require_ir()
    service_names = {s.name for s in ir.services}
    assert service_names == {"AuthService", "UploadService"}
    assert {c.name for c in ir.controllers} == {"AuthController"}
    assert {a.name for a in ir.apis} == {"upload_route"}


def test_modules_hybrid(extracted: CompilationContext) -> None:
    ir = extracted.require_ir()
    modules = {m.name: m for m in ir.modules}
    assert set(modules) == {"Authentication", "Upload Pipeline"}

    auth = modules["Authentication"]
    assert auth.origin is ModuleOrigin.COMMUNITY
    assert auth.cohesion == pytest.approx(0.82)
    assert len(auth.symbol_ids) == 3
    assert any(sid.startswith("service::") for sid in auth.service_ids)
    assert any(cid.startswith("controller::") for cid in auth.controller_ids)

    upload = modules["Upload Pipeline"]
    assert any(aid.startswith("api::") for aid in upload.api_ids)


def test_symbol_module_assignment(extracted: CompilationContext) -> None:
    ir = extracted.require_ir()
    by_id = ir.symbol_by_id()
    assert by_id["src_auth_service_login"].module_id == "module::community::0"


def test_module_split_on_low_cohesion(sample_config: CompilerConfig) -> None:
    # Force a split: any community below this cohesion is partitioned by package.
    strict_cfg = sample_config.model_copy(update={"min_cohesion": 0.6})
    ir = _extract(strict_cfg).require_ir()
    # Community 1 (cohesion 0.55) is now split by package; its members share one
    # package (src/upload) so the split yields a single PACKAGE-origin module.
    upload_modules = [m for m in ir.modules if m.community_id == "1"]
    assert len(upload_modules) == 1
    assert upload_modules[0].origin is ModuleOrigin.PACKAGE
    # Community 0 (cohesion 0.82) stays a single COMMUNITY module.
    auth_modules = [m for m in ir.modules if m.community_id == "0"]
    assert len(auth_modules) == 1
    assert auth_modules[0].origin is ModuleOrigin.COMMUNITY
