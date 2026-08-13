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


def test_classification_ignores_tests_and_file_nodes() -> None:
    """Test scaffolding and file/import nodes are not architectural components."""
    from knowledge_builder.models import Symbol
    from knowledge_builder.passes.classify_pass import _role

    # Test helpers mention "endpoint"/"route" constantly but are not the API surface.
    assert (
        _role(
            Symbol(
                id="t",
                label="test_status_endpoint()",
                name="test_status_endpoint",
                kind="function",
                source_file="tests/unit/test_zip_upload_status.py",
            )
        )
        is None
    )
    assert (
        _role(
            Symbol(
                id="c",
                label="TestRegistryEndpoints",
                name="TestRegistryEndpoints",
                kind="class",
                source_file="tests/registry/test_registry_api.py",
            )
        )
        is None
    )
    # A file node is a location, not an endpoint.
    assert (
        _role(
            Symbol(
                id="f",
                label="api_v1/endpoints.py",
                name="endpoints",
                kind="file",
                source_file="app/router/api_v1/endpoints.py",
            )
        )
        is None
    )
    # Production routes still classify.
    assert (
        _role(
            Symbol(
                id="p",
                label="upload_route",
                name="upload_route",
                kind="function",
                source_file="app/upload/routes.py",
            )
        )
        is not None
    )


def test_module_names_ignore_references_and_private_labels() -> None:
    """A module is named for its capability, not for a label that happens to be prominent.

    graphify labels a community after a notable node, which is often an imported type
    (``Any``) or a private helper (``._execute_command``) — neither describes what the
    code does, so the package name wins.
    """
    from knowledge_builder.models import Symbol
    from knowledge_builder.parser.types import CommunityInfo
    from knowledge_builder.passes.module_pass import (
        _community_name,
        _name_from_symbols,
        _standalone_name,
    )

    def sym(name: str, kind: str, file: str) -> Symbol:
        return Symbol(id=name, label=name, name=name.lstrip("."), kind=kind, source_file=file)

    imported = [sym("Any", "import", "app/queue/base.py")]
    community = CommunityInfo(id="0", label="Any", member_ids=("Any",))
    assert _community_name(community, imported) == "Queue"

    private = sym("._execute_command", "method", "app/local_fs/cli.py")
    assert _standalone_name(private) == "LocalFs"

    # A real capability name is kept as-is.
    real = sym("ZipUploadService", "class", "app/zip_upload/service.py")
    assert _standalone_name(real) == "ZipUploadService"

    # The generic "Module" fallback is replaced by something identifying.
    assert _name_from_symbols([sym("x", "function", "scripts/obfuscate.py")]) != "Module"


def test_duplicate_module_names_are_disambiguated() -> None:
    """A dozen modules called "Collection" are unusable; widen each with path context."""
    from knowledge_builder.models import Module
    from knowledge_builder.passes.module_pass import _disambiguate_names

    modules = [
        Module(id="m1", name="Collection", source_paths=("app/collection/api.py",)),
        Module(id="m2", name="Collection", source_paths=("app/collection/models.py",)),
        Module(id="m3", name="Collection", source_paths=("tests/collection/test_doc.py",)),
        Module(id="m4", name="ZipUpload", source_paths=("app/zip_upload/service.py",)),
    ]
    result = {m.id: m.name for m in _disambiguate_names(modules, {})}

    # Same directory — only the file name can separate them.
    assert result["m1"] == "Collection Api"
    assert result["m2"] == "Collection Models"
    assert result["m3"] != result["m1"]
    assert len({result["m1"], result["m2"], result["m3"]}) == 3
    # An already-unique name is left alone.
    assert result["m4"] == "ZipUpload"


def test_widening_never_reintroduces_a_duplicate() -> None:
    """Two *different* colliding groups can widen toward the same string.

    ``FsManager`` × 2 and ``TestFsManager`` × 2 both live under ``tests/local_fs`` and
    both reach for ``LocalFs TestFsManager``. A per-group name pool lets the second group
    claim it again — reintroducing the exact duplicate the widening exists to remove.
    """
    from knowledge_builder.models import Module
    from knowledge_builder.passes.module_pass import _disambiguate_names

    modules = [
        Module(id="a1", name="FsManager", source_paths=("tests/local_fs/test_fs_manager.py",)),
        Module(id="a2", name="FsManager", source_paths=("tests/local_fs/test_cli.py",)),
        Module(id="b1", name="TestFsManager", source_paths=("tests/local_fs/test_fs_manager.py",)),
        Module(id="b2", name="TestFsManager", source_paths=("tests/local_fs/test_models.py",)),
    ]
    names = [m.name for m in _disambiguate_names(modules, {})]
    assert len(set(names)) == len(names), names


def test_widening_falls_back_to_symbol_names_when_the_path_runs_out() -> None:
    """Many one-symbol modules carved out of one file share every path segment.

    Path widening cannot separate them, and ``Collection 2``…``Collection 9`` is not a
    listing anyone can read. What differs is the code each module owns.
    """
    from knowledge_builder.models import Module, Symbol
    from knowledge_builder.passes.module_pass import _disambiguate_names

    path = ("tests/collection/test_search.py",)
    names = ("test_uuid_search", "test_name_search", "test_sql_injection_rejected")
    symbols = {
        f"s{i}": Symbol(id=f"s{i}", label=n, name=n, kind="function", source_file=path[0])
        for i, n in enumerate(names)
    }
    modules = [
        Module(id=f"m{i}", name="Collection", source_paths=path, symbol_ids=(f"s{i}",))
        for i in range(len(names))
    ]
    result = [m.name for m in _disambiguate_names(modules, symbols)]

    assert len(set(result)) == len(result), result
    # The path yields only two distinct widenings, so the third module must be named for
    # the code it holds — not "Collection 2".
    assert "TestSqlInjectionRejected" in result


def test_path_labels_are_not_capability_names() -> None:
    """``app/core/__init__.py`` says where code lives; the package says what it does.

    A bare file name is left alone — for a migration the file name *is* the description,
    and nothing we could derive from ``migrations/versions`` would beat it.
    """
    from knowledge_builder.models import Symbol
    from knowledge_builder.parser.types import CommunityInfo
    from knowledge_builder.passes.module_pass import _community_name

    members = [Symbol(id="s", label="s", name="s", kind="function", source_file="app/core/db.py")]
    located = CommunityInfo(id="0", label="app/core/__init__.py", member_ids=("s",))
    assert _community_name(located, members) == "Core"

    migration = [
        Symbol(
            id="m",
            label="upgrade",
            name="upgrade",
            kind="function",
            source_file="migrations/versions/0007_added_reasoner_runs_table.py",
        )
    ]
    named = CommunityInfo(id="1", label="0007_added_reasoner_runs_table.py", member_ids=("m",))
    assert _community_name(named, migration) == "0007_added_reasoner_runs_table.py"


def test_reference_only_clusters_are_not_modules() -> None:
    """graphify clusters imports too: ``typing.Any`` attracts a community of its users.

    Such a group defines nothing and points at no file — there is nothing to open, and
    "Any" names a type the code *depends on*, not a capability it provides.
    """
    from knowledge_builder.models import Module, Symbol
    from knowledge_builder.passes.module_pass import _is_reference_only

    symbols = {
        "i1": Symbol(id="i1", label="Any", name="Any", kind="import"),
        "i2": Symbol(id="i2", label="UUID", name="UUID", kind="import"),
        "d1": Symbol(
            id="d1", label="run", name="run", kind="function", source_file="app/worker.py"
        ),
    }
    imports_only = Module(id="m1", name="Any", symbol_ids=("i1", "i2"))
    assert _is_reference_only(imports_only, symbols) is True

    # One real definition is enough to keep the module.
    mixed = Module(id="m2", name="Worker", symbol_ids=("i1", "d1"))
    assert _is_reference_only(mixed, symbols) is False

    # So is a source path: imports that came from a real file still locate code.
    located = Module(id="m3", name="Any", symbol_ids=("i1",), source_paths=("app/deps.py",))
    assert _is_reference_only(located, symbols) is False


def test_module_name_never_degrades_to_the_word_module() -> None:
    """Graph nodes can carry no source file at all; "Module 7" names nothing."""
    from knowledge_builder.models import Symbol
    from knowledge_builder.passes.module_pass import _name_from_symbols

    orphans = [Symbol(id="s1", label="publish_event", name="publish_event", kind="function")]
    assert _name_from_symbols(orphans) == "PublishEvent"


def test_a_generic_package_falls_back_to_the_real_file_stem() -> None:
    """``app/`` is a generic root, so the directory names nothing — the file must.

    The capability lookup needs a path; handing it a synthetic ``{package}/x.py`` means
    that when every directory is generic the fallback returns the placeholder's own stem
    and the module ends up called "X".
    """
    from knowledge_builder.models import Symbol
    from knowledge_builder.passes.module_pass import _name_from_symbols

    generic = [
        Symbol(
            id="s1", label="lifespan", name="lifespan", kind="function", source_file="app/main.py"
        )
    ]
    assert _name_from_symbols(generic) == "Main"

    # A meaningful directory still wins over the file name.
    scoped = [
        Symbol(
            id="s2", label="get", name="get", kind="function", source_file="app/collection/api.py"
        )
    ]
    assert _name_from_symbols(scoped) == "Collection"


def test_dunder_and_private_names_are_not_naming_candidates() -> None:
    """``__init__`` would widen to the module "Init" — less use than the counter."""
    from knowledge_builder.models import Module, Symbol
    from knowledge_builder.passes.module_pass import _symbol_names

    symbols = {
        "d": Symbol(id="d", label="__init__", name="__init__", kind="function"),
        "p": Symbol(id="p", label="_helper", name="_helper", kind="function"),
        "r": Symbol(id="r", label="load", name="load", kind="function"),
    }
    module = Module(id="m", name="Storage", symbol_ids=("d", "p", "r"))
    assert _symbol_names(module, symbols) == ["Load"]


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
