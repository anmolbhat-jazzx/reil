"""Tests for local receiver-type inference and call-edge resolution."""

from __future__ import annotations

from pathlib import Path

import pytest
from knowledge_builder.models import Relationship, Symbol
from knowledge_builder.models.base import Confidence
from knowledge_builder.parser.symbols.calls import resolve_calls
from knowledge_builder.parser.symbols.python_calls import TypeIndex, parse_calls

TYPES = TypeIndex(
    class_names=frozenset({"Repo", "Base", "Other"}),
    return_types={"make_repo": "Repo", "load": "Repo"},
)


def _sites(source: str, types: TypeIndex = TYPES) -> dict[tuple[str, str], str | None]:
    """``(caller, callee) -> inferred receiver type`` for every call in ``source``."""
    return {(c.caller, c.callee): c.receiver_type for c in parse_calls(source, "app/svc.py", types)}


# -- receiver typing --------------------------------------------------------
def test_annotated_parameter_types_the_receiver() -> None:
    sites = _sites("def handle(repo: Repo):\n    repo.save()\n")
    assert sites[("app.svc.handle", "save")] == "Repo"


def test_constructor_assignment_types_the_receiver() -> None:
    sites = _sites("def handle():\n    r = Repo()\n    r.save()\n")
    assert sites[("app.svc.handle", "save")] == "Repo"


def test_return_annotation_propagates_through_a_call() -> None:
    """``x = f()`` where ``f`` declares ``-> Repo``. Also the ``await`` form."""
    sites = _sites(
        "async def handle():\n"
        "    r = make_repo()\n"
        "    r.save()\n"
        "    q = await load()\n"
        "    q.fetch()\n"
    )
    assert sites[("app.svc.handle", "save")] == "Repo"
    assert sites[("app.svc.handle", "fetch")] == "Repo"


def test_optional_and_union_annotations_unwrap_to_the_element_type() -> None:
    for annotation in ("Optional[Repo]", "Repo | None", '"Repo"', "Awaitable[Repo]"):
        sites = _sites(f"def handle(repo: {annotation}):\n    repo.save()\n")
        assert sites[("app.svc.handle", "save")] == "Repo", annotation


def test_self_attribute_typed_in_init() -> None:
    source = (
        "class Service:\n"
        "    def __init__(self, repo: Repo):\n"
        "        self.repo = repo\n"
        "    def run(self):\n"
        "        self.repo.save()\n"
    )
    assert _sites(source)[("app.svc.Service.run", "save")] == "Repo"


def test_self_call_resolves_to_the_enclosing_class() -> None:
    source = (
        "class Service:\n"
        "    def run(self):\n"
        "        self.helper()\n"
        "    def helper(self):\n"
        "        pass\n"
    )
    assert _sites(source)[("app.svc.Service.run", "helper")] == "Service"


def test_untyped_receiver_stays_unresolved() -> None:
    """The contract that keeps precision: no stated type means no guess."""
    sites = _sites("def handle(repo):\n    repo.save()\n")
    assert sites[("app.svc.handle", "save")] is None


def test_unknown_class_in_annotation_is_not_invented() -> None:
    sites = _sites("def handle(repo: NotARepo):\n    repo.save()\n")
    assert sites[("app.svc.handle", "save")] is None


def test_calls_inside_a_nested_def_belong_to_it() -> None:
    """Attributing a closure's calls to its parent would invent edges."""
    source = (
        "def outer(repo: Repo):\n"
        "    def inner(other: Repo):\n"
        "        other.save()\n"
        "    return inner\n"
    )
    sites = _sites(source)
    assert ("app.svc.outer.inner", "save") in sites
    assert ("app.svc.outer", "save") not in sites


def test_malformed_source_yields_nothing() -> None:
    assert parse_calls("def broken(:::", "a.py", TYPES) == []


# -- resolution to symbol ids ----------------------------------------------
def _repo_with(tmp_path: Path, source: str) -> tuple[Symbol, ...]:
    """Write ``source`` and return the symbol table a compiled repo would carry."""
    (tmp_path / "app").mkdir(parents=True, exist_ok=True)
    (tmp_path / "app" / "svc.py").write_text(source)
    return (
        Symbol(
            id="caller",
            label="handle",
            name="handle",
            kind="function",
            qualified_name="app.svc.handle",
            source_file="app/svc.py",
            start_line=1,
        ),
        Symbol(
            id="cls",
            label="Repo",
            name="Repo",
            kind="class",
            qualified_name="app.svc.Repo",
            source_file="app/svc.py",
            start_line=5,
        ),
        Symbol(
            id="save",
            label="save",
            name="save",
            kind="method",
            qualified_name="app.svc.Repo.save",
            source_file="app/svc.py",
            start_line=6,
        ),
    )


SOURCE = (
    "def handle(repo: Repo):\n    repo.save()\n\n\nclass Repo:\n    def save(self):\n        pass\n"
)


def test_resolves_a_typed_receiver_to_the_method_symbol(tmp_path: Path) -> None:
    edges = resolve_calls(tmp_path, _repo_with(tmp_path, SOURCE), ())
    assert [(e.source_id, e.target_id) for e in edges] == [("caller", "save")]
    assert edges[0].relation == "calls"
    # Distinguishable from graphify's own edges, so consumers can filter.
    assert edges[0].confidence is Confidence.INFERRED


def test_does_not_duplicate_an_edge_graphify_already_found(tmp_path: Path) -> None:
    symbols = _repo_with(tmp_path, SOURCE)
    existing = (
        Relationship(
            id=Relationship.make_id("caller", "save", "calls"),
            source_id="caller",
            target_id="save",
            relation="calls",
        ),
    )
    assert resolve_calls(tmp_path, symbols, existing) == ()


def test_inherited_method_resolves_through_an_inherits_edge(tmp_path: Path) -> None:
    source = (
        "def handle(repo: Repo):\n"
        "    repo.save()\n"
        "\n"
        "\n"
        "class Base:\n"
        "    def save(self):\n"
        "        pass\n"
        "\n"
        "\n"
        "class Repo(Base):\n"
        "    pass\n"
    )
    (tmp_path / "app").mkdir(parents=True, exist_ok=True)
    (tmp_path / "app" / "svc.py").write_text(source)
    symbols = (
        Symbol(
            id="caller",
            label="handle",
            name="handle",
            kind="function",
            qualified_name="app.svc.handle",
            source_file="app/svc.py",
            start_line=1,
        ),
        Symbol(
            id="base",
            label="Base",
            name="Base",
            kind="class",
            qualified_name="app.svc.Base",
            source_file="app/svc.py",
            start_line=5,
        ),
        Symbol(
            id="save",
            label="save",
            name="save",
            kind="method",
            qualified_name="app.svc.Base.save",
            source_file="app/svc.py",
            start_line=6,
        ),
        Symbol(
            id="repo",
            label="Repo",
            name="Repo",
            kind="class",
            qualified_name="app.svc.Repo",
            source_file="app/svc.py",
            start_line=10,
        ),
    )
    inherits = (Relationship(id="i1", source_id="repo", target_id="base", relation="inherits"),)
    edges = resolve_calls(tmp_path, symbols, inherits)
    assert [(e.source_id, e.target_id) for e in edges] == [("caller", "save")]


def test_two_classes_sharing_a_name_resolve_to_neither(tmp_path: Path) -> None:
    """Ambiguity must cost recall, never precision — a wrong call edge is worse."""
    symbols = (
        *_repo_with(tmp_path, SOURCE),
        Symbol(
            id="cls2",
            label="Repo",
            name="Repo",
            kind="class",
            qualified_name="other.mod.Repo",
            source_file="other/mod.py",
            start_line=1,
        ),
        Symbol(
            id="save2",
            label="save",
            name="save",
            kind="method",
            qualified_name="other.mod.Repo.save",
            source_file="other/mod.py",
            start_line=2,
        ),
    )
    assert resolve_calls(tmp_path, symbols, ()) == ()


def test_missing_source_file_is_not_an_error(tmp_path: Path) -> None:
    symbols = (
        Symbol(
            id="caller",
            label="handle",
            name="handle",
            kind="function",
            qualified_name="app.svc.handle",
            source_file="app/gone.py",
            start_line=1,
        ),
    )
    assert resolve_calls(tmp_path, symbols, ()) == ()


@pytest.mark.parametrize(
    ("signature", "expected"),
    [
        ("(a: int) -> Repo", "Repo"),
        ("(a: int) -> Optional[Repo]", "Repo"),
        ("(a: int) -> Awaitable[Optional[Repo]]", "Repo"),
        ("(a: int) -> Repo | None", "Repo"),
        ("(a: int)", None),
        ("(a: int) -> dict[str, int]", "str"),  # not a repo class → dropped downstream
    ],
)
def test_return_type_parsing(signature: str, expected: str | None) -> None:
    from knowledge_builder.parser.symbols.calls import _return_type

    assert _return_type(signature) == expected
