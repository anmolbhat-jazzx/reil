"""Tests for symbol projection + source enrichment (federation identity fields)."""

from __future__ import annotations

from pathlib import Path

import pytest
from knowledge_builder.compiler import CompilationContext, CompilerConfig
from knowledge_builder.models import Metadata, Repository, Symbol
from knowledge_builder.parser.symbols import enrich_symbols, python_ast
from knowledge_builder.passes import LoadPass, SymbolEnrichPass, SymbolPass
from knowledge_builder.passes.symbol_pass import _baseline_kind, _clean_name, _parse_lines
from knowledge_builder.serializer import KnowledgeReader, KnowledgeWriter
from knowledge_builder.validation import validate_repository


# -- baseline projection (graphify-only) ------------------------------------
@pytest.mark.parametrize(
    "label,expected",
    [
        ("clean_revision()", "clean_revision"),
        (".test_foo()", "test_foo"),
        ("api_v2/endpoints.py", "endpoints"),
        ("Class.method", "method"),
        ("plain_name", "plain_name"),
    ],
)
def test_clean_name(label: str, expected: str) -> None:
    assert _clean_name(label) == expected


def test_parse_lines() -> None:
    assert _parse_lines("L10-L30") == (10, 30)
    assert _parse_lines("L7") == (7, None)
    assert _parse_lines(None) == (None, None)
    assert _parse_lines("nonsense") == (None, None)


def test_baseline_kind() -> None:
    assert _baseline_kind("pkg/mod.py", "pkg/mod.py") == "file"
    assert _baseline_kind("do_thing()", "x.py") == "function"
    assert _baseline_kind("MyClass", "x.py") == "class"


# -- python ast provider ----------------------------------------------------
_SRC = '''
import abc


def clean_revision(rev: str, *, force: bool = False) -> str:
    """Normalize a revision id."""
    return rev.strip()


class Chunk(abc.ABC):
    """A chunk."""

    @staticmethod
    def make(x):
        ...

    @abc.abstractmethod
    async def persist(self, db) -> None:
        """Persist it."""
        ...

    def _hidden(self):
        ...
'''


def test_python_ast_extracts_all_fields() -> None:
    defs = {d.qualified_name: d for d in python_ast.parse_file(_SRC, "app/collection/models.py")}

    fn = defs["app.collection.models.clean_revision"]
    assert fn.kind == "function"
    assert fn.signature == "(rev: str, *, force: bool=False) -> str"
    assert fn.docstring == "Normalize a revision id."
    assert fn.start_line == 5  # the `def` line, not the blank lines above

    cls = defs["app.collection.models.Chunk"]
    assert cls.kind == "class"
    assert cls.signature == "(abc.ABC)"

    make = defs["app.collection.models.Chunk.make"]
    assert make.kind == "method"
    assert make.is_static is True

    persist = defs["app.collection.models.Chunk.persist"]
    assert persist.is_async is True
    assert persist.is_abstract is True
    assert persist.docstring == "Persist it."

    assert defs["app.collection.models.Chunk._hidden"].visibility == "protected"


def test_python_parse_is_silent_on_bad_escape(recwarn: pytest.WarningsRecorder) -> None:
    """A stray ``\\L`` escape in someone's source must not print during a build."""
    source = 'def f():\n    """doc with \\L bad escape"""\n    return 1\n'
    defs = python_ast.parse_file(source, "app/x.py")
    assert [d.name for d in defs] == ["f"]  # still parsed
    assert not [w for w in recwarn if issubclass(w.category, SyntaxWarning)]


# -- end-to-end through the pipeline ----------------------------------------
def _ir(sample_repo: Path, *, enrich: bool) -> Repository:
    config = CompilerConfig(
        repo_path=sample_repo, workspace=sample_repo / "graphify-out", build_graph=False
    )
    context = CompilationContext(config)
    passes = [LoadPass(), SymbolPass()]
    if enrich:
        passes.append(SymbolEnrichPass())
    for p in passes:
        p.run(context)
    return context.require_ir()


def test_symbol_pass_baseline(sample_repo: Path) -> None:
    symbols = {s.name: s for s in _ir(sample_repo, enrich=False).symbols}
    login = symbols["login"]
    assert login.name == "login"
    assert login.start_line == 10  # from source_location "L10-L30"
    assert login.end_line == 30


def test_symbol_enrich_fills_detail(sample_repo: Path) -> None:
    symbols = {s.name: s for s in _ir(sample_repo, enrich=True).symbols}
    upload = symbols["upload"]
    assert upload.kind == "function"
    assert upload.signature == "(blob)"
    assert upload.docstring is not None and upload.docstring.startswith("Upload")
    assert upload.qualified_name == "src.upload.service.upload"
    assert upload.start_line == 1  # authoritative def line (join key)
    assert upload.end_line is not None and upload.end_line >= 3


def test_symbol_enrich_skips_unparseable_source(sample_repo: Path) -> None:
    # auth/service.py is deliberately malformed Python; enrichment must degrade
    # gracefully (baseline name/line kept, semantic fields left None) — never crash.
    symbols = {s.name: s for s in _ir(sample_repo, enrich=True).symbols}
    login = symbols["login"]
    assert login.name == "login" and login.start_line == 10  # baseline preserved
    assert login.signature is None and login.docstring is None  # not guessed


def test_unresolvable_symbols_marked_as_imports(sample_repo: Path) -> None:
    """graphify emits imported/external names with no location; they are not definitions."""
    from knowledge_builder.passes.symbol_enrich_pass import IMPORT_KIND

    config = CompilerConfig(
        repo_path=sample_repo, workspace=sample_repo / "graphify-out", build_graph=False
    )
    context = CompilationContext(config)
    context.set_ir(
        Repository(
            metadata=Metadata(repo_path=str(sample_repo), repo_name="s"),
            # No source_location → an imported name such as ``AsyncSession``.
            symbols=(Symbol(id="ext", label="AsyncSession", name="AsyncSession"),),
        )
    )
    SymbolEnrichPass().run(context)
    symbol = context.require_ir().symbols[0]
    assert symbol.kind == IMPORT_KIND
    # …and it must not raise a validation warning, since it is expected.
    report = validate_repository(context.require_ir())
    assert not [i for i in report.warnings if i.code == "SYMBOL_NO_START_LINE"]


def test_enrich_symbols_router_directly(sample_repo: Path) -> None:
    ir = _ir(sample_repo, enrich=False)
    updates = enrich_symbols(sample_repo, ir.symbols)
    # Every python symbol in the sample repo resolves to a def.
    assert updates
    for update in updates.values():
        assert update["name"]
        assert update["start_line"] is not None


def test_symbol_fields_round_trip(sample_repo: Path, tmp_path: Path) -> None:
    ir = _ir(sample_repo, enrich=True)
    kb = KnowledgeWriter().write(ir, tmp_path / "knowledge.kb")
    with KnowledgeReader(kb) as reader:
        upload = next(s for s in reader.symbols() if s.name == "upload")
    assert upload.kind == "function"
    assert upload.qualified_name == "src.upload.service.upload"
    assert upload.start_line == 1
    assert upload.signature == "(blob)"
