"""Tests for the language-agnostic tree-sitter symbol provider."""

from __future__ import annotations

from pathlib import Path

import pytest
from knowledge_builder.parser.symbols import enrich_symbols
from knowledge_builder.parser.symbols import treesitter_provider as ts

JAVA_REPO = Path(__file__).parent.parent / "fixtures" / "java_repo"
JAVA_FILE = "src/main/java/com/jazzx/docs/DocumentService.java"


def _defs(source: str, path: str) -> dict[str, ts.DefInfo]:
    return {d.qualified_name: d for d in ts.parse_file(source, path)}


# -- registry ---------------------------------------------------------------
def test_rules_resolve_by_extension() -> None:
    assert ts.rules_for("A.java") is not None
    assert ts.rules_for("a.go") is not None
    assert ts.rules_for("a.ts") is not None
    assert ts.rules_for("a.unknownext") is None


# -- java -------------------------------------------------------------------
def test_java_extracts_full_detail() -> None:
    source = (JAVA_REPO / JAVA_FILE).read_text()
    defs = _defs(source, JAVA_FILE)

    cls = defs["com.jazzx.docs.DocumentService"]
    assert cls.kind == "class"
    assert cls.docstring == "Service for documents."  # javadoc
    assert cls.decorators == ("Service",)
    assert cls.visibility == "public"
    # package declaration drives the qualified name, not the file path
    assert cls.qualified_name.startswith("com.jazzx.docs")

    method = defs["com.jazzx.docs.DocumentService.findById"]
    assert method.kind == "method"
    assert method.signature == "(String id, int depth) -> Document"
    assert method.docstring == "Finds a document by id."
    assert method.is_static is True
    assert method.decorators == ("Override",)


def test_java_start_line_excludes_annotations() -> None:
    """The join key must be the declaration line, not the ``@Annotation`` above it."""
    source = (JAVA_REPO / JAVA_FILE).read_text()
    lines = source.splitlines()
    method = _defs(source, JAVA_FILE)["com.jazzx.docs.DocumentService.findById"]
    assert "findById" in lines[method.start_line - 1]
    assert "@Override" in lines[method.start_line - 2]


# -- other languages, same engine -------------------------------------------
def test_go_function_and_doc() -> None:
    src = (
        "package main\n\n// Upload sends a blob.\nfunc Upload(b []byte) error {\n\treturn nil\n}\n"
    )
    d = _defs(src, "cmd/app/main.go")["cmd.app.main.Upload"]
    assert d.kind == "function"
    assert d.docstring == "Upload sends a blob."
    assert d.signature == "(b []byte)"


def test_typescript_class_and_async_method() -> None:
    src = (
        "/** Renders a chunk. */\n"
        "export class ChunkView {\n"
        "  /** Loads it. */\n"
        "  async load(id: string): Promise<void> {}\n"
        "}\n"
    )
    defs = _defs(src, "src/ChunkView.ts")
    assert defs["src.ChunkView.ChunkView"].docstring == "Renders a chunk."
    method = defs["src.ChunkView.ChunkView.load"]
    assert method.is_async is True
    assert method.signature == "(id: string) -> Promise<void>"


# -- graceful degradation ---------------------------------------------------
def test_unsupported_language_returns_nothing() -> None:
    assert ts.parse_file("whatever", "a.unknownext") == []


def test_malformed_source_does_not_raise() -> None:
    # tree-sitter is error-tolerant; the contract is simply "never raise".
    ts.parse_file("public class {{{ broken", "Broken.java")


# -- router dispatches by language ------------------------------------------
def test_router_enriches_java_symbols() -> None:
    from knowledge_builder.models import Symbol

    symbols = (
        Symbol(id="s1", label="findById", name="findById", source_file=JAVA_FILE, start_line=13),
    )
    updates = enrich_symbols(JAVA_REPO, symbols)
    assert updates["s1"]["kind"] == "method"
    assert updates["s1"]["docstring"] == "Finds a document by id."


def test_file_node_is_not_enriched_into_its_public_class() -> None:
    """A Java file node shares its stem with the class inside — it must not absorb it.

    ``DocumentService.java`` cleans to the name ``DocumentService``, the only definition
    of that name in the file. Matching on the name alone would turn the file node into a
    duplicate of the class node — one per Java file across a whole repository.
    """
    from knowledge_builder.models import Symbol

    file_node = Symbol(
        id="file",
        label="DocumentService.java",
        name="DocumentService",
        kind="file",
        source_file=JAVA_FILE,
        start_line=1,
    )
    class_node = Symbol(
        id="cls",
        label="DocumentService",
        name="DocumentService",
        kind="class",
        source_file=JAVA_FILE,
        start_line=8,
    )
    updates = enrich_symbols(JAVA_REPO, (file_node, class_node))

    assert "file" not in updates  # stays a file, keeps its L1 baseline
    assert updates["cls"]["kind"] == "class"
    assert updates["cls"]["start_line"] == 9  # snapped to the `class` keyword line


@pytest.mark.parametrize("path", ["a.py", "a.java", "a.go", "a.ts"])
def test_provider_selected_for_supported_languages(path: str) -> None:
    from knowledge_builder.parser.symbols.enrich import _provider_for

    assert _provider_for(path) is not None
