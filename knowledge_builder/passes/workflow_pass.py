"""WorkflowPass (Phase 5) — harvest workflows from graphify hyperedges."""

from __future__ import annotations

from collections import defaultdict

from knowledge_builder.compiler.context import CompilationContext
from knowledge_builder.compiler.pass_base import CompilerPass
from knowledge_builder.models.module import Module
from knowledge_builder.models.symbol import Symbol
from knowledge_builder.models.workflow import Workflow
from knowledge_builder.parser.types import ParsedGraph
from knowledge_builder.passes import keys


class WorkflowPass(CompilerPass):
    """Project hyperedges into :class:`Workflow` records and link them to modules."""

    name = "workflows"

    def run(self, context: CompilationContext) -> None:
        ir = context.require_ir()
        parsed: ParsedGraph = context.artifacts[keys.PARSED_GRAPH]

        workflows = tuple(
            Workflow(
                id=hyperedge.id,
                name=hyperedge.label,
                participant_ids=hyperedge.nodes,
                relation=hyperedge.relation,
                confidence=hyperedge.confidence,
                confidence_score=hyperedge.confidence_score,
                source_file=hyperedge.source_file,
            )
            for hyperedge in parsed.hyperedges
        )

        modules = _attach_workflows(ir.modules, workflows, ir.symbol_by_id())
        context.set_ir(ir.evolve(workflows=workflows, modules=modules))
        context.stats["workflows"] = len(workflows)
        context.info(self.name, "harvested workflows", count=len(workflows))


def _attach_workflows(
    modules: tuple[Module, ...],
    workflows: tuple[Workflow, ...],
    symbols_by_id: dict[str, Symbol],
) -> tuple[Module, ...]:
    module_workflows: dict[str, set[str]] = defaultdict(set)
    for workflow in workflows:
        for participant in workflow.participant_ids:
            symbol = symbols_by_id.get(participant)
            module_id = symbol.module_id if symbol else None
            if module_id:
                module_workflows[module_id].add(workflow.id)
    return tuple(
        module.model_copy(
            update={
                "workflow_ids": tuple(
                    sorted(set(module.workflow_ids) | module_workflows.get(module.id, set()))
                )
            }
        )
        for module in modules
    )
