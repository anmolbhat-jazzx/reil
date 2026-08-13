"""Tests for router mount discovery (prefixes declared away from the handler)."""

from __future__ import annotations

from pathlib import Path

from knowledge_builder.models import Symbol
from knowledge_builder.parser.openapi import bind, discover_mounts
from knowledge_builder.parser.openapi.spec import Operation

REPO = Path(__file__).parent.parent / "fixtures" / "mount_repo"
CONFIG = "app/configuration/api.py"
WIDGET = "app/widget/api.py"


def test_composes_nested_mount_prefixes() -> None:
    """``app`` → ``api_v1`` (/api/v1) → config router (/global-config) composes."""
    mounts = discover_mounts(REPO)
    assert mounts[(CONFIG, "router")] == ("api", "v1", "global-config")
    assert mounts[(WIDGET, "router")] == ("api", "v1", "widgets")
    assert mounts[("app/router/api_v1/endpoints.py", "api_v1")] == ("api", "v1")


def test_resolves_import_aliases() -> None:
    """The mount site names the router ``global_config_router``; its file calls it ``router``."""
    mounts = discover_mounts(REPO)
    # Keyed by the *defining* file and variable — what the handler's decorator uses.
    assert (CONFIG, "router") in mounts
    assert (CONFIG, "global_config_router") not in mounts


def test_resolves_module_qualified_include(tmp_path: Path) -> None:
    """``include_router(module.router)`` after ``from pkg import module``."""
    (tmp_path / "app" / "cfg").mkdir(parents=True)
    (tmp_path / "app" / "cfg" / "api.py").write_text(
        "from fastapi import APIRouter\nrouter = APIRouter()\n"
    )
    (tmp_path / "app" / "main.py").write_text(
        "from fastapi import FastAPI\n"
        "from app.cfg import api as cfg_api\n"
        "app = FastAPI()\n"
        'app.include_router(cfg_api.router, prefix="/api/v1/cfg")\n'
    )
    mounts = discover_mounts(tmp_path)
    assert mounts[("app/cfg/api.py", "router")] == ("api", "v1", "cfg")


def test_root_mount_keeps_empty_prefix(tmp_path: Path) -> None:
    """A router mounted at the root needs an explicit empty-prefix entry to compose."""
    (tmp_path / "main.py").write_text(
        "from fastapi import FastAPI, APIRouter\n"
        "app = FastAPI()\n"
        "sub = APIRouter()\n"
        "app.include_router(sub)\n"
    )
    assert discover_mounts(tmp_path)[("main.py", "sub")] == ()


def test_repo_without_routers_yields_nothing(tmp_path: Path) -> None:
    (tmp_path / "main.py").write_text("print('hi')\n")
    assert discover_mounts(tmp_path) == {}


def test_mounts_disambiguate_otherwise_unbindable_routes() -> None:
    """Two routers both declaring a bare ``/{id}`` are ambiguous until prefixes are known.

    Neither router has a distinctive route to infer a prefix from, so this is exactly the
    case decorator analysis alone cannot solve.
    """
    ops = [
        Operation(method="GET", path="/api/v1/global-config/{config_id}", spec_file="s"),
        Operation(method="GET", path="/api/v1/widgets/{widget_id}", spec_file="s"),
    ]
    symbols = (
        Symbol(
            id="g",
            label="get_config",
            name="get_config",
            source_file=CONFIG,
            decorators=('router.get("/{config_id}")',),
        ),
        Symbol(
            id="w",
            label="get_widget",
            name="get_widget",
            source_file=WIDGET,
            decorators=('router.get("/{widget_id}")',),
        ),
    )
    assert bind(ops, symbols) == {}  # unbindable without mount information
    bound = bind(ops, symbols, discover_mounts(REPO))
    assert bound[("GET", "/api/v1/global-config/{config_id}")] == "g"
    assert bound[("GET", "/api/v1/widgets/{widget_id}")] == "w"


def test_wrong_mount_prefix_does_not_destroy_a_correct_inference() -> None:
    """Mount and inferred prefixes are candidates, not overrides.

    Regression: making mounts authoritative meant a router whose mount site resolved
    wrongly lost bindings that inference had already gotten right. A candidate that does
    not reconstruct the operation path must simply lose, costing nothing.
    """
    file = "app/registry/api.py"
    ops = [
        Operation(method="GET", path="/api/v1/registry/jtbd/draft", spec_file="s"),
        Operation(method="GET", path="/api/v1/registry/jtbd/{registry_id}", spec_file="s"),
    ]
    symbols = (
        Symbol(
            id="j0",
            label="draft",
            name="draft",
            source_file=file,
            decorators=('router.get("/draft")',),
        ),
        Symbol(
            id="j1",
            label="get_j",
            name="get_j",
            source_file=file,
            decorators=('router.get("/{registry_id}")',),
        ),
    )
    expected = {
        ("GET", "/api/v1/registry/jtbd/draft"): "j0",
        ("GET", "/api/v1/registry/jtbd/{registry_id}"): "j1",
    }

    assert bind(ops, symbols) == expected  # inference alone
    correct = {(file, "router"): ("api", "v1", "registry", "jtbd")}
    assert bind(ops, symbols, correct) == expected
    wrong = {(file, "router"): ("api", "v1", "registry", "ontology")}
    assert bind(ops, symbols, wrong) == expected  # must not regress


def test_constructor_prefix_is_included() -> None:
    """``APIRouter(prefix="/x")`` composes with the prefix given at the mount site."""
    from knowledge_builder.parser.openapi.mounts import _parse_file

    info = _parse_file('r = APIRouter(prefix="/inner")\n', "a.py")
    assert info is not None
    assert info.routers["r"] == ("inner",)
