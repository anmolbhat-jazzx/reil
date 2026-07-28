"""Phase 1 tests: pass/pipeline/context/compiler framework with stub passes."""

from __future__ import annotations

from pathlib import Path

import pytest
from knowledge_builder.compiler import (
    CompilationContext,
    CompilationPipeline,
    Compiler,
    CompilerConfig,
    CompilerPass,
    Severity,
)
from knowledge_builder.models import Metadata, Module, ModuleOrigin, Repository
from knowledge_builder.utils.errors import CompilationError, ParseError


class _InitPass(CompilerPass):
    name = "init"

    def run(self, context: CompilationContext) -> None:
        meta = Metadata(repo_path=str(context.config.repo_path), repo_name="demo")
        context.set_ir(Repository(metadata=meta))
        context.info(self.name, "created empty IR")


class _AddModulePass(CompilerPass):
    name = "add-module"

    def run(self, context: CompilationContext) -> None:
        ir = context.require_ir()
        module = Module(id="m1", name="Demo", origin=ModuleOrigin.STANDALONE)
        context.set_ir(ir.evolve(modules=(*ir.modules, module)))


class _BoomPass(CompilerPass):
    name = "boom"

    def run(self, context: CompilationContext) -> None:
        raise ParseError("bad graph")


def _config(tmp_path: Path) -> CompilerConfig:
    return CompilerConfig(repo_path=tmp_path)


def test_pipeline_runs_passes_in_order(tmp_path: Path) -> None:
    compiler = Compiler([_InitPass(), _AddModulePass()])
    artifact = compiler.compile(_config(tmp_path))
    assert len(artifact.repository.modules) == 1
    assert artifact.repository.modules[0].name == "Demo"
    assert not artifact.has_errors()


def test_pass_timings_recorded(tmp_path: Path) -> None:
    compiler = Compiler([_InitPass(), _AddModulePass()])
    artifact = compiler.compile(_config(tmp_path))
    timings = artifact.stats["pass_timings_ms"]
    assert set(timings) == {"init", "add-module"}


def test_typed_error_is_wrapped_with_pass_name(tmp_path: Path) -> None:
    compiler = Compiler([_InitPass(), _BoomPass()])
    with pytest.raises(CompilationError) as excinfo:
        compiler.compile(_config(tmp_path))
    assert excinfo.value.pass_name == "boom"
    assert isinstance(excinfo.value.__cause__, ParseError)


def test_empty_pipeline_rejected() -> None:
    with pytest.raises(CompilationError):
        CompilationPipeline([])


def test_require_ir_raises_when_missing(tmp_path: Path) -> None:
    ctx = CompilationContext(_config(tmp_path))
    with pytest.raises(CompilationError):
        ctx.require_ir()


def test_diagnostics_captured(tmp_path: Path) -> None:
    compiler = Compiler([_InitPass(), _AddModulePass()])
    artifact = compiler.compile(_config(tmp_path))
    assert any(d.severity is Severity.INFO for d in artifact.diagnostics)
