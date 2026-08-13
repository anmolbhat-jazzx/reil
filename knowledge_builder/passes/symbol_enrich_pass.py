"""SymbolEnrichPass (Phase 4) — fill source-derived symbol detail.

Runs after :class:`~knowledge_builder.passes.symbol_pass.SymbolPass`, reading the checked-out
source to add the fields graphify cannot provide: ``kind``, ``qualified_name``,
``signature``, ``docstring``, exact ``start_line``/``end_line`` (+ columns), and the
modifier flags. Independent of the graph, best-effort, and never fails the build — any
error leaves symbols at their graphify-only baseline.

Placed before :class:`~knowledge_builder.passes.module_pass.ModulePass`, which only
``model_copy``-updates ``module_id`` and so preserves everything set here.
"""

from __future__ import annotations

from typing import Any

from knowledge_builder.compiler.context import CompilationContext
from knowledge_builder.compiler.pass_base import CompilerPass
from knowledge_builder.models.symbol import Symbol
from knowledge_builder.parser.symbols import enrich_symbols

#: Kind for a symbol with no definition site in this repository — an imported or
#: otherwise external name (``AsyncSession``, ``UUID``, ``pytest.fixture``, builtins).
#: graphify emits these as nodes without a source location; they are references, not
#: definitions, so they are excluded from retrieval and never warned about.
IMPORT_KIND = "import"


def _apply(symbol: Symbol, update: dict[str, Any] | None) -> Symbol:
    """Apply an enrichment update, or mark the symbol as an external reference."""
    if update is not None:
        return symbol.model_copy(update=update)
    if symbol.start_line is None:
        # No graphify line and no definition found by any provider → not defined here.
        return symbol.model_copy(update={"kind": IMPORT_KIND})
    return symbol


class SymbolEnrichPass(CompilerPass):
    """Enrich symbols with source-derived detail (docstrings, signatures, kinds, …)."""

    name = "symbol-enrich"

    def run(self, context: CompilationContext) -> None:
        ir = context.require_ir()
        if not ir.symbols:
            return
        try:
            updates = enrich_symbols(context.config.repo_path, ir.symbols)
        except Exception as exc:  # noqa: BLE001 - enrichment must never fail the build
            context.warning(self.name, "symbol enrichment failed", error=str(exc))
            return

        symbols = tuple(_apply(sym, updates.get(sym.id)) for sym in ir.symbols)
        imported = sum(1 for s in symbols if s.kind == IMPORT_KIND)
        context.set_ir(ir.evolve(symbols=symbols))
        context.stats["symbol_enrich"] = {
            "enriched": len(updates),
            "imported": imported,
            "total": len(ir.symbols),
        }
        context.info(
            self.name,
            "enriched symbols",
            enriched=len(updates),
            imported=imported,
            total=len(ir.symbols),
        )
