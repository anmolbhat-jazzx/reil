"""Concrete compiler passes (Phases 3–8)."""

from __future__ import annotations

from knowledge_builder.passes.agents_doc_pass import AgentsDocPass
from knowledge_builder.passes.callgraph_pass import CallGraphPass
from knowledge_builder.passes.classify_pass import ClassifyPass
from knowledge_builder.passes.concept_pass import ConceptPass
from knowledge_builder.passes.dependency_pass import DependencyPass
from knowledge_builder.passes.graph_build_pass import GraphBuildPass
from knowledge_builder.passes.load_pass import LoadPass
from knowledge_builder.passes.module_pass import ModulePass
from knowledge_builder.passes.optimize_pass import OptimizePass
from knowledge_builder.passes.serialize_pass import SerializePass
from knowledge_builder.passes.summary_pass import SummaryPass
from knowledge_builder.passes.symbol_pass import SymbolPass
from knowledge_builder.passes.validate_pass import ValidatePass
from knowledge_builder.passes.workflow_pass import WorkflowPass

__all__ = [
    "AgentsDocPass",
    "CallGraphPass",
    "ClassifyPass",
    "ConceptPass",
    "DependencyPass",
    "GraphBuildPass",
    "LoadPass",
    "ModulePass",
    "OptimizePass",
    "SerializePass",
    "SummaryPass",
    "SymbolPass",
    "ValidatePass",
    "WorkflowPass",
]
