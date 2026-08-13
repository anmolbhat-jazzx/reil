"""SymbolPass (Phase 4) — project ``code`` nodes into typed :class:`Symbol` records.

Baseline projection from graphify data only: a clean ``name`` (from ``label``), integer
``start_line``/``end_line`` (from ``source_location``), and a best-effort ``kind``. These
are always present, even for languages the source-enrichment pass cannot parse. The
richer fields (docstring, signature, exact ranges, flags) are filled afterwards by
:class:`~knowledge_builder.passes.symbol_enrich_pass.SymbolEnrichPass`.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from knowledge_builder.compiler.context import CompilationContext
from knowledge_builder.compiler.pass_base import CompilerPass
from knowledge_builder.models.base import FileType
from knowledge_builder.models.graph import GraphNode
from knowledge_builder.models.symbol import Symbol
from knowledge_builder.utils.languages import language_for_path

_LOC = re.compile(r"L?(\d+)(?:\s*-\s*L?(\d+))?")
_CODE_EXTENSIONS = (".py", ".java", ".kt", ".ts", ".tsx", ".js", ".jsx", ".go", ".rb", ".cs")


class SymbolPass(CompilerPass):
    """Create a :class:`Symbol` for every code node in the graph."""

    name = "symbols"

    def run(self, context: CompilationContext) -> None:
        ir = context.require_ir()
        symbols = tuple(
            self._project(node) for node in ir.graph_nodes if node.file_type is FileType.CODE
        )
        context.set_ir(ir.evolve(symbols=symbols))
        context.stats["symbols"] = len(symbols)
        context.info(self.name, "extracted symbols", count=len(symbols))

    def _project(self, node: GraphNode) -> Symbol:
        label = node.label
        start_line, end_line = _parse_lines(node.source_location)
        return Symbol(
            id=node.id,
            label=label,
            name=_clean_name(label),
            kind=_baseline_kind(label, node.source_file),
            source_file=node.source_file,
            source_location=node.source_location,
            start_line=start_line,
            end_line=end_line,
            language=language_for_path(node.source_file),
            rationale=node.rationale,
        )


def _parse_lines(location: str | None) -> tuple[int | None, int | None]:
    """``L10-L30`` → (10, 30); ``L7`` → (7, None); unparseable → (None, None)."""
    if not location:
        return None, None
    match = _LOC.search(location)
    if not match:
        return None, None
    start = int(match.group(1))
    end = int(match.group(2)) if match.group(2) else None
    return start, end


def _clean_name(label: str) -> str:
    """Reduce a graphify label to a bare identifier.

    ``clean_revision()`` → ``clean_revision``; ``.test_foo()`` → ``test_foo``;
    ``api_v2/endpoints.py`` → ``endpoints``; ``Class.method`` → ``method``.
    """
    text = (label or "").strip()
    if not text:
        return ""
    if _looks_like_path(text):
        return PurePosixPath(text).stem
    if "(" in text:
        text = text[: text.index("(")]
    text = text.strip().lstrip(".")
    # Keep only the final dotted segment as the bare name.
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return text.strip()


def _baseline_kind(label: str, source_file: str | None) -> str | None:
    """Best-effort kind from the label alone (refined later by source enrichment)."""
    text = (label or "").strip()
    if _looks_like_path(text):
        return "file"
    if "(" in text:
        return "function"  # may be refined to "method" by the enrichment pass
    if text[:1].isupper() and text.isidentifier():
        return "class"
    return None


def _looks_like_path(text: str) -> bool:
    return "/" in text or text.endswith(_CODE_EXTENSIONS)
