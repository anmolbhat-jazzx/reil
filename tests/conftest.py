"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest
from knowledge_builder.compiler import CompilationContext, CompilerConfig
from knowledge_builder.passes import (
    CallGraphPass,
    ClassifyPass,
    ConceptPass,
    DependencyPass,
    LoadPass,
    ModulePass,
    OptimizePass,
    SummaryPass,
    SymbolPass,
    ValidatePass,
    WorkflowPass,
)

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_REPO = FIXTURES / "sample_repo"

# Deterministic + semantic pass sequence (Phases 3–5), in canonical order.
HARVEST_PASSES = (
    LoadPass,
    SymbolPass,
    CallGraphPass,
    DependencyPass,
    ClassifyPass,
    ModulePass,
    ConceptPass,
    WorkflowPass,
    SummaryPass,
)

# Full compile sequence through optimization (Phases 3–6).
OPTIMIZED_PASSES = (*HARVEST_PASSES, OptimizePass)

# Full compile sequence including validation (Phases 3–6, 8).
FULL_PASSES = (*OPTIMIZED_PASSES, ValidatePass)


def run_passes(config: CompilerConfig, pass_classes: tuple[type, ...]) -> CompilationContext:
    """Run the given pass classes over a fresh context and return it."""
    context = CompilationContext(config)
    for pass_cls in pass_classes:
        pass_cls().run(context)
    return context


@pytest.fixture
def sample_repo() -> Path:
    """Path to the bundled sample repository (contains a graphify-out/)."""
    return SAMPLE_REPO


@pytest.fixture
def sample_config(sample_repo: Path) -> CompilerConfig:
    # Point the workspace at the fixture's existing graphify-out so the loader reads it
    # directly (no graphify run, no writes into the fixture tree).
    return CompilerConfig(
        repo_path=sample_repo,
        workspace=sample_repo / "graphify-out",
        build_graph=False,
    )


@pytest.fixture
def loaded_context(sample_config: CompilerConfig) -> CompilationContext:
    """A context with the sample repo already loaded (LoadPass applied)."""
    return run_passes(sample_config, (LoadPass,))


@pytest.fixture
def harvested_context(sample_config: CompilerConfig) -> CompilationContext:
    """A context run through the deterministic + semantic passes (Phases 3–5)."""
    return run_passes(sample_config, HARVEST_PASSES)


@pytest.fixture
def optimized_context(sample_config: CompilerConfig) -> CompilationContext:
    """A context compiled through optimization (Phases 3–6)."""
    return run_passes(sample_config, OPTIMIZED_PASSES)
