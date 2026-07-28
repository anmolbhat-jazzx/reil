"""Phase 10 integration tests: the `knowledge` CLI end-to-end (build → query)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from knowledge_builder.cli.main import app
from typer.testing import CliRunner

runner = CliRunner()


@pytest.fixture
def repo_copy(sample_repo: Path, tmp_path: Path) -> Path:
    """A writable copy of the sample repo (so knowledge.kb lands in tmp)."""
    dest = tmp_path / "repo"
    shutil.copytree(sample_repo, dest)
    return dest


def test_build_end_to_end(repo_copy: Path) -> None:
    # The fixture already has graphify-out/, so graphify is not run; the graph files are
    # imported into the .knowledge workspace and knowledge.kb lands there.
    result = runner.invoke(app, ["build", str(repo_copy), "--no-build-graph"])
    assert result.exit_code == 0, result.output
    assert "knowledge.kb generated successfully" in result.output
    assert (repo_copy / ".knowledge" / "knowledge.kb").is_file()
    assert (repo_copy / ".knowledge" / "graph.json").is_file()  # imported into workspace
    # AGENTS.md and CLAUDE.md are written so agents know to use the KB
    for name in ("AGENTS.md", "CLAUDE.md"):
        doc = repo_copy / name
        assert doc.is_file(), name
        assert "knowledge ask" in doc.read_text()
    # a second build updates in place without duplicating the managed block
    runner.invoke(app, ["build", str(repo_copy), "--no-build-graph"])
    for name in ("AGENTS.md", "CLAUDE.md"):
        assert (repo_copy / name).read_text().count("BEGIN knowledge.kb") == 1
    # Definition-of-Done stage lines are shown
    assert "Building Graphify graph" in result.output
    assert "Validating artifact" in result.output


def test_build_custom_output_then_query_and_stats(repo_copy: Path, tmp_path: Path) -> None:
    out = tmp_path / "custom.kb"
    build = runner.invoke(app, ["build", str(repo_copy), "-o", str(out)])
    assert build.exit_code == 0, build.output
    assert out.is_file()

    validate = runner.invoke(app, ["validate", str(out)])
    assert validate.exit_code == 0, validate.output
    assert "valid" in validate.output

    query = runner.invoke(app, ["query", str(out), "upload"])
    assert query.exit_code == 0, query.output
    assert "Upload Pipeline" in query.output

    stats = runner.invoke(app, ["stats", str(out)])
    assert stats.exit_code == 0
    assert "repo" in stats.output

    inspect = runner.invoke(app, ["inspect", str(out)])
    assert inspect.exit_code == 0
    assert "Authentication" in inspect.output


def test_build_missing_graph_with_no_build_fails(tmp_path: Path) -> None:
    empty = tmp_path / "empty_repo"
    empty.mkdir()
    result = runner.invoke(app, ["build", str(empty), "--no-build-graph"])
    assert result.exit_code == 1
    assert "build failed" in result.output
