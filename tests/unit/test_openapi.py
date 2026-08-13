"""Tests for OpenAPI contract ingestion and handler binding."""

from __future__ import annotations

from pathlib import Path

from knowledge_builder.compiler import CompilationContext, CompilerConfig
from knowledge_builder.models import Api, Metadata, Repository, Symbol
from knowledge_builder.parser.openapi import (
    Operation,
    bind,
    discover_specs,
    normalize_path,
    parse_operations,
)
from knowledge_builder.passes import OpenApiPass

REPO = Path(__file__).parent.parent / "fixtures" / "openapi_repo"


def _operations() -> list:
    return [op for rel, doc in discover_specs(REPO) for op in parse_operations(rel, doc)]


# -- discovery + parsing ----------------------------------------------------
def test_discovers_yaml_spec() -> None:
    specs = discover_specs(REPO)
    assert len(specs) == 1
    rel, doc = specs[0]
    assert rel == "openapi.yaml"
    assert "paths" in doc


def test_parses_operations_with_contract_detail() -> None:
    ops = {(o.method, o.path): o for o in _operations()}
    get = ops[("GET", "/documents/{id}")]
    assert get.operation_id == "getDocument"
    assert get.summary == "Fetch a document."
    assert get.tags == ("documents",)
    assert set(get.response_codes) == {"200", "404"}
    assert "id" in get.parameters  # inherited from the path-item level

    post = ops[("POST", "/documents")]
    assert post.request_schema == "DocumentCreate"
    assert post.response_codes == ("201",)


def test_non_spec_files_ignored(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name": "x", "paths": 1}')
    assert discover_specs(tmp_path) == []


def test_normalize_path_ignores_param_names() -> None:
    assert normalize_path("/docs/{id}") == normalize_path("/docs/<doc_id>")


# -- binding ----------------------------------------------------------------
def _symbol(sid: str, name: str, decorators: tuple[str, ...] = ()) -> Symbol:
    return Symbol(id=sid, label=name, name=name, decorators=decorators, source_file="app/routes.py")


def test_binds_by_route_decorator() -> None:
    symbols = (
        _symbol("s1", "get_document", ('router.get("/documents/{id}")',)),
        _symbol("s2", "create_document", ('router.post("/documents")',)),
    )
    bound = bind(_operations(), symbols)
    assert bound[("GET", "/documents/{id}")] == "s1"
    assert bound[("POST", "/documents")] == "s2"


def test_binds_by_operation_id_when_no_decorator() -> None:
    symbols = (_symbol("s1", "getDocument"),)
    bound = bind(_operations(), symbols)
    assert bound[("GET", "/documents/{id}")] == "s1"


def test_binds_by_derived_name() -> None:
    symbols = (_symbol("s1", "get_documents_id"),)
    bound = bind(_operations(), symbols)
    assert bound[("GET", "/documents/{id}")] == "s1"


def test_binds_when_decorator_omits_router_prefix() -> None:
    """FastAPI/Spring handlers declare a path relative to their router's mount point."""
    symbols = (_symbol("s1", "get_document", ('router.get("/{id}")',)),)
    bound = bind(_operations(), symbols)
    assert bound[("GET", "/documents/{id}")] == "s1"


def test_suffix_match_requires_whole_segments() -> None:
    """``/ments/{id}`` must not match ``/documents/{id}`` — segments, not characters."""
    symbols = (_symbol("s1", "bogus", ('router.get("/ments/{id}")',)),)
    assert bind(_operations(), symbols) == {}


def test_ambiguous_suffix_stays_unbound() -> None:
    symbols = (
        _symbol("s1", "a", ('router.get("/{id}")',)),
        _symbol("s2", "b", ('router.get("/{id}")',)),
    )
    assert bind(_operations(), symbols) == {}


def test_binds_by_fastapi_generated_operation_id() -> None:
    """FastAPI auto-ids look like ``<function>_<path>_<method>``."""
    ops = [
        Operation(
            method="GET",
            path="/api/v1/things/{id}",
            spec_file="s.json",
            operation_id="read_thing_api_v1_things__id__get",
        )
    ]
    assert bind(ops, (_symbol("s1", "read_thing"),)) == {("GET", "/api/v1/things/{id}"): "s1"}


def test_prefix_inference_resolves_ambiguous_bare_routes() -> None:
    """Bare ``/{id}`` routes are identical across routers until the mount prefix is known.

    One unambiguous binding per file reveals that prefix, which then disambiguates the
    rest — without it these all collide and none can bind.
    """
    ops = [
        Operation(method="GET", path="/api/v1/collections/by-name/{n}", spec_file="s"),
        Operation(method="GET", path="/api/v1/collections", spec_file="s"),
        Operation(method="GET", path="/api/v1/collections/{collection_id}", spec_file="s"),
        Operation(method="POST", path="/api/v1/global-config/seed", spec_file="s"),
        Operation(method="GET", path="/api/v1/global-config/{config_id}", spec_file="s"),
    ]

    def sym(sid: str, name: str, file: str, dec: str) -> Symbol:
        return Symbol(id=sid, label=name, name=name, source_file=file, decorators=(dec,))

    symbols = (
        sym("c0", "by_name", "app/collection/api.py", 'router.get("/by-name/{n}")'),
        sym("c1", "list_collections", "app/collection/api.py", 'router.get("")'),
        sym("c2", "get_collection", "app/collection/api.py", 'router.get("/{collection_id}")'),
        sym("g0", "seed", "app/configuration/api.py", 'router.post("/seed")'),
        # Same bare shape as c2 but a different router — must not cross-bind.
        sym("g1", "get_cfg", "app/configuration/api.py", 'router.get("/{config_id}")'),
    )
    bound = bind(ops, symbols)
    assert bound[("GET", "/api/v1/collections")] == "c1"
    assert bound[("GET", "/api/v1/collections/{collection_id}")] == "c2"
    assert bound[("GET", "/api/v1/global-config/{config_id}")] == "g1"
    assert len(bound) == len(ops)


def test_multiple_routers_in_one_file_are_scoped_separately() -> None:
    """One module often mounts several routers at different prefixes.

    Keying the learned prefix on the *router variable*, not just the file, keeps
    ``router`` and ``ontology_router`` from making each other look ambiguous.
    """
    ops = [
        Operation(method="GET", path="/api/v1/registry/jtbd/draft", spec_file="s"),
        Operation(method="GET", path="/api/v1/registry/jtbd/{registry_id}", spec_file="s"),
        Operation(method="GET", path="/api/v1/registry/ontology/resolve", spec_file="s"),
        Operation(method="GET", path="/api/v1/registry/ontology/{registry_id}", spec_file="s"),
    ]
    file = "app/registry/api.py"

    def sym(sid: str, name: str, dec: str) -> Symbol:
        return Symbol(id=sid, label=name, name=name, source_file=file, decorators=(dec,))

    symbols = (
        sym("j0", "draft", 'router.get("/draft")'),
        sym("j1", "get_jtbd", 'router.get("/{registry_id}")'),
        sym("o0", "resolve", 'ontology_router.get("/resolve")'),
        sym("o1", "get_ontology", 'ontology_router.get("/{registry_id}")'),
    )
    bound = bind(ops, symbols)
    assert bound[("GET", "/api/v1/registry/jtbd/{registry_id}")] == "j1"
    assert bound[("GET", "/api/v1/registry/ontology/{registry_id}")] == "o1"


def test_path_affinity_breaks_v1_v2_tie() -> None:
    """Two versions declaring the same tail resolve by which file echoes the path."""
    ops = [Operation(method="GET", path="/api/v2/reasoning/entities/minimal", spec_file="s")]
    symbols = (
        Symbol(
            id="v1",
            label="m",
            name="m",
            source_file="app/reasoning/api.py",
            decorators=('router.get("/minimal")',),
        ),
        Symbol(
            id="v2",
            label="m",
            name="m",
            source_file="app/router/api_v2/reasoning.py",
            decorators=('router.get("/minimal")',),
        ),
    )
    assert bind(ops, symbols)[("GET", "/api/v2/reasoning/entities/minimal")] == "v2"


def test_route_path_read_from_first_positional_argument() -> None:
    """Keyword strings must never be mistaken for the route path."""
    from knowledge_builder.parser.openapi.binder import _route_of

    # The real FastAPI shape that previously mis-parsed ``response_model`` as the path.
    assert _route_of('router.get("", response_model=list[Collection])') == ("GET", "/")
    assert _route_of("router.get('', summary='List collections')") == ("GET", "/")
    assert _route_of('router.get("/{id}", response_model=X)') == ("GET", "/{id}")
    assert _route_of("router.get(response_model=X)") == ("GET", "/")
    # A positional string that is not a path is not a route at all.
    assert _route_of('pytest.mark.parametrize("value", [1, 2])') == ("", None)


def test_binds_bare_collection_root_routes() -> None:
    """``@router.get("", …)`` mounts at the router root and must still bind."""
    ops = [
        Operation(method="GET", path="/api/v1/things/{id}", spec_file="s"),
        Operation(method="GET", path="/api/v1/things", spec_file="s"),
    ]
    file = "app/things/api.py"
    symbols = (
        Symbol(
            id="s1",
            label="get_thing",
            name="get_thing",
            source_file=file,
            decorators=('router.get("/{id}", response_model=Thing)',),
        ),
        Symbol(
            id="s2",
            label="list_things",
            name="list_things",
            source_file=file,
            decorators=('router.get("", response_model=list[Thing])',),
        ),
    )
    bound = bind(ops, symbols)
    assert bound[("GET", "/api/v1/things")] == "s2"


def test_unmatched_operation_stays_unbound() -> None:
    assert bind(_operations(), (_symbol("s1", "unrelated"),)) == {}


def test_binds_spring_annotation() -> None:
    symbols = (_symbol("s1", "findById", ('GetMapping("/documents/{id}")',)),)
    bound = bind(_operations(), symbols)
    assert bound[("GET", "/documents/{id}")] == "s1"


# -- pass -------------------------------------------------------------------
def _run_pass(apis: tuple[Api, ...] = (), symbols: tuple[Symbol, ...] = ()) -> Repository:
    context = CompilationContext(CompilerConfig(repo_path=REPO, build_graph=False))
    context.set_ir(
        Repository(
            metadata=Metadata(repo_path=str(REPO), repo_name="openapi_repo"),
            apis=apis,
            symbols=symbols,
        )
    )
    OpenApiPass().run(context)
    return context.require_ir()


def test_pass_creates_authoritative_apis() -> None:
    ir = _run_pass(symbols=(_symbol("s1", "get_document", ('router.get("/documents/{id}")',)),))
    by_route = {(a.method, a.path): a for a in ir.apis}
    get = by_route[("GET", "/documents/{id}")]
    assert get.origin == "openapi"
    assert get.operation_id == "getDocument"
    assert get.handler_symbol_id == "s1"
    assert get.spec_file == "openapi.yaml"
    assert get.source_file == "app/routes.py"


def test_one_route_declared_by_several_specs_is_one_api() -> None:
    """A repo shipping the same spec as .json and .yaml still has one endpoint.

    Keying ``Api.id`` on the spec declaration rather than the route made ``apis.id``
    collide, and the artifact could not be written at all — a real multi-module Java repo
    shipped five specs sharing 239 of 424 routes and the build died on the UNIQUE
    constraint. Federation would also have received the same endpoint counted three times.
    """
    from knowledge_builder.passes.openapi_pass import _routes

    ops = [
        Operation(method="GET", path="/orders", spec_file="api.yaml", operation_id="listOrders"),
        Operation(method="GET", path="/orders", spec_file="api.json", operation_id="listOrders"),
        Operation(method="POST", path="/orders", spec_file="api.json"),
    ]
    routes = _routes(ops)

    assert set(routes) == {("GET", "/orders"), ("POST", "/orders")}
    assert len({f"api::{m}::{p}" for m, p in routes}) == 2


def test_richest_declaration_wins_and_is_deterministic() -> None:
    """Pick the declaration carrying the most contract detail, ties broken stably."""
    from knowledge_builder.passes.openapi_pass import _richest

    bare = Operation(method="GET", path="/orders", spec_file="b.yaml")
    detailed = Operation(
        method="GET",
        path="/orders",
        spec_file="a.json",
        operation_id="listOrders",
        summary="List orders",
        response_codes=("200",),
    )
    assert _richest([bare, detailed]) is detailed
    assert _richest([detailed, bare]) is detailed  # order of discovery must not matter


def test_drifted_specs_are_flagged_not_averaged() -> None:
    """Identical copies are not a conflict; differing contracts are, and must surface.

    ``flowable-api-spec.json`` (169 paths) and ``.yaml`` (166) had drifted apart. Silently
    picking one hides a defect the repo owner needs to see.
    """
    from knowledge_builder.passes.openapi_pass import _disagree

    same = [
        Operation(method="GET", path="/o", spec_file="a.yaml", response_codes=("200",)),
        Operation(method="GET", path="/o", spec_file="a.json", response_codes=("200",)),
    ]
    drifted = [
        Operation(method="GET", path="/o", spec_file="a.yaml", response_codes=("200",)),
        Operation(method="GET", path="/o", spec_file="a.json", response_codes=("200", "404")),
    ]
    assert _disagree(same) is False
    assert _disagree(drifted) is True
    assert _disagree(same[:1]) is False


def test_pass_replaces_heuristic_api_for_same_route() -> None:
    heuristic = Api(id="api::guess", name="guess", method="GET", path="/documents/{id}")
    ir = _run_pass(apis=(heuristic,))
    matching = [a for a in ir.apis if normalize_path(a.path or "") == "/documents/{}"]
    assert all(a.origin == "openapi" for a in matching)
    assert "api::guess" not in {a.id for a in ir.apis}


def test_pass_keeps_heuristic_api_not_in_spec() -> None:
    other = Api(id="api::other", name="other", method="GET", path="/health")
    ir = _run_pass(apis=(other,))
    assert "api::other" in {a.id for a in ir.apis}


def test_pass_drops_heuristic_guesses_without_a_route() -> None:
    """With an authoritative spec, a guess lacking method+path is noise, not an endpoint."""
    noise = Api(id="api::noise", name="profile_endpoint()", source_file="app/mw/profiler.py")
    ir = _run_pass(apis=(noise,))
    assert "api::noise" not in {a.id for a in ir.apis}


def test_pass_noop_without_spec(tmp_path: Path) -> None:
    context = CompilationContext(CompilerConfig(repo_path=tmp_path, build_graph=False))
    heuristic = Api(id="api::guess", name="guess", method="GET", path="/x")
    context.set_ir(Repository(metadata=Metadata(repo_path="x", repo_name="x"), apis=(heuristic,)))
    OpenApiPass().run(context)
    assert context.require_ir().apis == (heuristic,)  # untouched
