"""Tests for GraphBuildPass: run → import into workspace → discard transient."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from knowledge_builder.compiler import CompilationContext, CompilerConfig
from knowledge_builder.parser.graphify_runner import GraphBuildError
from knowledge_builder.passes.graph_build_pass import GraphBuildPass

_GRAPH = {"directed": True, "multigraph": False, "graph": {}, "nodes": [], "links": []}


class FakeRunner:
    """Writes a minimal graphify-out/ instead of invoking the real graphify."""

    def __init__(self) -> None:
        self.calls = 0

    def run(self, repo_path: Path) -> Path:
        self.calls += 1
        out = repo_path / "graphify-out"
        out.mkdir(parents=True, exist_ok=True)
        (out / "graph.json").write_text(json.dumps(_GRAPH), encoding="utf-8")
        (out / ".graphify_labels.json").write_text("{}", encoding="utf-8")
        return out


def _run(config: CompilerConfig, runner: FakeRunner) -> CompilationContext:
    ctx = CompilationContext(config)
    GraphBuildPass(runner=runner).run(ctx)
    return ctx


def test_runs_graphify_imports_and_deletes_transient(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    runner = FakeRunner()
    cfg = CompilerConfig(repo_path=repo)  # build_graph=True, workspace=.knowledge

    _run(cfg, runner)

    assert runner.calls == 1
    assert (repo / ".knowledge" / "graph.json").is_file()  # imported
    assert (repo / ".knowledge" / ".graphify_labels.json").is_file()
    assert not (repo / "graphify-out").exists()  # transient removed (we created it)


def test_skips_when_workspace_already_has_graph(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    ws = repo / ".knowledge"
    ws.mkdir(parents=True)
    (ws / "graph.json").write_text(json.dumps(_GRAPH), encoding="utf-8")
    runner = FakeRunner()

    _run(CompilerConfig(repo_path=repo), runner)
    assert runner.calls == 0  # cached graph used


def test_rebuild_forces_run(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    ws = repo / ".knowledge"
    ws.mkdir(parents=True)
    (ws / "graph.json").write_text(json.dumps(_GRAPH), encoding="utf-8")
    runner = FakeRunner()

    _run(CompilerConfig(repo_path=repo, rebuild_graph=True), runner)
    assert runner.calls == 1


def test_existing_graphify_out_is_not_deleted(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    existing = repo / "graphify-out"
    existing.mkdir(parents=True)
    (existing / "graph.json").write_text(json.dumps(_GRAPH), encoding="utf-8")
    runner = FakeRunner()

    # graphify_out points at a pre-existing dir → import but never run or delete it.
    _run(CompilerConfig(repo_path=repo, graphify_out=existing), runner)
    assert runner.calls == 0
    assert existing.exists()  # preserved
    assert (repo / ".knowledge" / "graph.json").is_file()


def test_no_build_graph_without_graph_errors(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    with pytest.raises(GraphBuildError):
        _run(CompilerConfig(repo_path=repo, build_graph=False), FakeRunner())
