"""CallEnrichPass (Phase 4) — add call edges graphify cannot resolve.

graphify resolves a call when the call site names its target: ``self.method()``, a bare
``function()``, or a receiver whose type is declared (which is why Java fares better than
Python here). It cannot resolve ``svc.handle()`` when ``svc`` is a local variable, because
nothing at the call site says what ``svc`` is.

This pass reads the checked-out source, infers receiver types from what the code states
outright, and emits the resulting ``calls`` edges as
:attr:`~knowledge_builder.models.base.Confidence.INFERRED` — leaving graphify's own edges
untouched and distinguishable. Runs after
:class:`~knowledge_builder.passes.symbol_enrich_pass.SymbolEnrichPass` (whose
``qualified_name`` and ``signature`` are the index this resolves against) and before
:class:`~knowledge_builder.passes.callgraph_pass.CallGraphPass`, so fan-in/fan-out degree
is computed over the completed graph.

Best-effort: any failure leaves the graph exactly as graphify produced it.
"""

from __future__ import annotations

from knowledge_builder.compiler.context import CompilationContext
from knowledge_builder.compiler.pass_base import CompilerPass
from knowledge_builder.parser.symbols.calls import call_stats, resolve_calls


class CallEnrichPass(CompilerPass):
    """Resolve local-variable receiver types into additional ``calls`` edges."""

    name = "call-enrich"

    def run(self, context: CompilationContext) -> None:
        ir = context.require_ir()
        if not ir.symbols:
            return
        try:
            added = resolve_calls(context.config.repo_path, ir.symbols, ir.relationships)
        except Exception as exc:  # noqa: BLE001 - enrichment must never fail the build
            context.warning(self.name, "call resolution failed", error=str(exc))
            return

        if added:
            context.set_ir(ir.evolve(relationships=(*ir.relationships, *added)))
        stats = call_stats(added)
        context.stats["call_enrich"] = stats
        context.info(self.name, "resolved additional call edges", **stats)
