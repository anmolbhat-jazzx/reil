"""SummaryPass (Phase 5) — assemble a structured Summary per module.

Deterministic V1: every field is filled only from data harvested from graphify — related
modules, classified components, workflows, concepts, and god nodes. Fields with no
deterministic source (``purpose``, ``business_rules``, ``constraints``) are left empty; a
V2 LLM pass fills them.
"""

from __future__ import annotations

from knowledge_builder.compiler.context import CompilationContext
from knowledge_builder.compiler.pass_base import CompilerPass
from knowledge_builder.models.module import Module
from knowledge_builder.models.summary import Summary
from knowledge_builder.parser.types import ParsedGraph
from knowledge_builder.passes import keys


class SummaryPass(CompilerPass):
    """Build one :class:`Summary` per module from harvested deterministic signals."""

    name = "summaries"

    def run(self, context: CompilationContext) -> None:
        ir = context.require_ir()
        parsed: ParsedGraph = context.artifacts[keys.PARSED_GRAPH]
        god_ids = set(parsed.god_ids)

        module_names = {m.id: m.name for m in ir.modules}
        api_names = {a.id: a.name for a in ir.apis}
        workflow_names = {w.id: w.name for w in ir.workflows}
        concept_labels = {c.id: c.label for c in ir.concepts}
        service_names = {s.id: s.name for s in ir.services}
        controller_names = {c.id: c.name for c in ir.controllers}
        symbol_labels = {s.id: s.label for s in ir.symbols}

        summaries: list[Summary] = []
        updated_modules: list[Module] = []
        for module in ir.modules:
            responsibilities = _names(module.service_ids, service_names) + _names(
                module.controller_ids, controller_names
            )
            summary = Summary(
                id=f"summary::{module.id}",
                module_id=module.id,
                responsibilities=tuple(sorted(responsibilities)),
                dependencies=_names(module.related_module_ids, module_names),
                public_apis=_names(module.api_ids, api_names),
                workflows=_names(module.workflow_ids, workflow_names),
                concepts=_names(module.concept_ids, concept_labels),
                god_nodes=tuple(
                    sorted(symbol_labels[sid] for sid in module.symbol_ids if sid in god_ids)
                ),
            )
            summaries.append(summary)
            updated_modules.append(module.model_copy(update={"summary_id": summary.id}))

        context.set_ir(ir.evolve(summaries=tuple(summaries), modules=tuple(updated_modules)))
        context.stats["summaries"] = len(summaries)
        context.info(self.name, "built module summaries", count=len(summaries))


def _names(ids: tuple[str, ...], mapping: dict[str, str]) -> tuple[str, ...]:
    """Resolve a tuple of ids to sorted, de-duplicated names via ``mapping``."""
    return tuple(sorted({mapping[i] for i in ids if i in mapping}))
