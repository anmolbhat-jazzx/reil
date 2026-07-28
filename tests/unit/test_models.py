"""Phase 2 tests: IR model validation, immutability, round-trip, and helpers."""

from __future__ import annotations

import pytest
from knowledge_builder.models import (
    Concept,
    FileType,
    Metadata,
    Module,
    ModuleOrigin,
    Relationship,
    Repository,
    Service,
    Symbol,
)
from pydantic import ValidationError as PydanticValidationError


def _repo() -> Repository:
    return Repository(
        metadata=Metadata(repo_path="/tmp/demo", repo_name="demo"),
        symbols=(
            Symbol(id="a_foo", label="foo", source_file="a.py", language="python"),
            Symbol(id="b_bar", label="bar", source_file="b.py", language="python"),
        ),
        modules=(
            Module(id="m1", name="Auth", origin=ModuleOrigin.COMMUNITY, symbol_ids=("a_foo",)),
        ),
        concepts=(Concept(id="c1", label="JWT"),),
    )


def test_models_are_frozen() -> None:
    sym = Symbol(id="a_foo", label="foo")
    with pytest.raises(PydanticValidationError):
        sym.label = "bar"  # type: ignore[misc]


def test_extra_fields_forbidden() -> None:
    with pytest.raises(PydanticValidationError):
        Symbol(id="x", label="y", bogus=1)  # type: ignore[call-arg]


def test_round_trip() -> None:
    repo = _repo()
    restored = Repository.model_validate(repo.model_dump())
    assert restored == repo


def test_evolve_is_functional() -> None:
    repo = _repo()
    evolved = repo.evolve(services=(Service(id="s1", name="AuthService"),))
    assert len(repo.services) == 0  # original untouched
    assert len(evolved.services) == 1


def test_id_and_name_lookups() -> None:
    repo = _repo()
    assert repo.symbol_by_id()["a_foo"].label == "foo"
    assert repo.find_module("auth") is not None
    assert repo.find_concept("jwt") is not None
    assert repo.find_module("nope") is None


def test_relationship_id_is_deterministic() -> None:
    rid = Relationship.make_id("a_foo", "b_bar", "calls")
    assert rid == "a_foo--calls-->b_bar"


def test_relation_is_free_string() -> None:
    # graphify emits arbitrary relation names; all are preserved verbatim.
    rel = Relationship(id="e", source_id="a", target_id="b", relation="contains")
    assert rel.relation == "contains"
    assert FileType("concept") is FileType.CONCEPT
