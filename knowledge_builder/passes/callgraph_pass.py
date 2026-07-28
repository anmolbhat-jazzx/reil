"""CallGraphPass (Phase 4) — analyze the ``calls`` sub-graph over symbols.

The call graph itself lives in ``repository.relationships`` (edges with relation
``calls``). This pass computes per-symbol fan-in/fan-out degree and surfaces the busiest
symbols. The metrics are stashed in ``context.artifacts`` for the module-summary step and
summarized in ``context.stats``.
"""

from __future__ import annotations

from collections import defaultdict

from knowledge_builder.compiler.context import CompilationContext
from knowledge_builder.compiler.pass_base import CompilerPass
from knowledge_builder.models.base import CALL_RELATIONS

CALL_DEGREE = "call_degree"


class CallGraphPass(CompilerPass):
    """Derive call-graph degree metrics from ``calls`` edges."""

    name = "callgraph"

    def run(self, context: CompilationContext) -> None:
        ir = context.require_ir()
        symbol_ids = {s.id for s in ir.symbols}

        fan_out: dict[str, int] = defaultdict(int)
        fan_in: dict[str, int] = defaultdict(int)
        call_edges = 0
        for rel in ir.relationships:
            if rel.relation not in CALL_RELATIONS:
                continue
            if rel.source_id in symbol_ids:
                fan_out[rel.source_id] += 1
            if rel.target_id in symbol_ids:
                fan_in[rel.target_id] += 1
            call_edges += 1

        degree = {
            sid: {"in": fan_in.get(sid, 0), "out": fan_out.get(sid, 0)}
            for sid in symbol_ids
            if fan_in.get(sid) or fan_out.get(sid)
        }
        context.artifacts[CALL_DEGREE] = degree
        context.stats["call_graph"] = {
            "edges": call_edges,
            "connected_symbols": len(degree),
        }
        context.info(self.name, "analyzed call graph", edges=call_edges)
