"""High-level build API — assemble and run the canonical compilation pipeline.

This is where the standard, ordered pass set is wired together (dependency injection at
the top level). ``build_knowledge`` compiles a repository's graphify output into a
``knowledge.kb`` artifact and returns the in-memory :class:`KnowledgeArtifact`.
"""

from __future__ import annotations

from knowledge_builder.compiler.artifact import KnowledgeArtifact
from knowledge_builder.compiler.compiler import Compiler
from knowledge_builder.compiler.config import CompilerConfig
from knowledge_builder.compiler.pass_base import CompilerPass
from knowledge_builder.compiler.pipeline import ProgressHook
from knowledge_builder.passes import (
    AgentsDocPass,
    CallEnrichPass,
    CallGraphPass,
    ClassifyPass,
    ConceptPass,
    DatabasePass,
    DependencyPass,
    GraphBuildPass,
    LoadPass,
    ModulePass,
    OpenApiPass,
    OptimizePass,
    SerializePass,
    SummaryPass,
    SymbolEnrichPass,
    SymbolPass,
    ValidatePass,
    WorkflowPass,
)


def default_passes() -> list[CompilerPass]:
    """The canonical, ordered compilation pipeline (graph build → validation)."""
    return [
        GraphBuildPass(),  # run graphify → import into workspace → discard transient
        LoadPass(),  # Phase 3: graphify → IR skeleton
        SymbolPass(),  # Phase 4: deterministic extraction
        SymbolEnrichPass(),  # fill source-derived detail (docstrings, signatures, kinds)
        CallEnrichPass(),  # resolve local-variable receivers graphify cannot type
        CallGraphPass(),
        DependencyPass(),
        ClassifyPass(),
        OpenApiPass(),  # authoritative contracts override heuristic routes
        DatabasePass(),  # deterministic DB-schema extraction (independent of graphify)
        ModulePass(),
        ConceptPass(),  # Phase 5: semantic harvest
        WorkflowPass(),
        SummaryPass(),
        OptimizePass(),  # Phase 6: optimization
        SerializePass(),  # Phase 7: write knowledge.kb
        AgentsDocPass(),  # write/update AGENTS.md so agents use the KB
        ValidatePass(),  # Phase 8: validation
    ]


def build_knowledge(
    config: CompilerConfig, progress: ProgressHook | None = None
) -> KnowledgeArtifact:
    """Compile ``config.repo_path`` into ``knowledge.kb`` and return the artifact."""
    compiler = Compiler(default_passes())
    return compiler.compile(config, progress)
