"""Phase 3 tests: loader, graph parser, report parser, IR builder, load pass."""

from __future__ import annotations

from pathlib import Path

import pytest
from knowledge_builder.compiler import CompilationContext, CompilerConfig
from knowledge_builder.models import FileType
from knowledge_builder.parser import GraphParser, RepositoryLoader
from knowledge_builder.parser.report_parser import ReportParser
from knowledge_builder.passes import keys
from knowledge_builder.passes.load_pass import LoadPass
from knowledge_builder.utils.errors import LoaderError, ParseError


def test_loader_missing_dir_raises(tmp_path: Path) -> None:
    with pytest.raises(LoaderError):
        RepositoryLoader().load(tmp_path / "graphify-out")


def test_loader_missing_graph_json_raises(tmp_path: Path) -> None:
    (tmp_path / "graphify-out").mkdir()
    with pytest.raises(LoaderError):
        RepositoryLoader().load(tmp_path / "graphify-out")


def test_loader_invalid_json_raises(tmp_path: Path) -> None:
    out = tmp_path / "graphify-out"
    out.mkdir()
    (out / "graph.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ParseError):
        RepositoryLoader().load(out)


def test_graph_parser_parses_nodes_edges_communities(sample_repo: Path) -> None:
    bundle = RepositoryLoader().load(sample_repo / "graphify-out")
    parsed = GraphParser().parse(bundle)

    assert len(parsed.nodes) == 8
    assert len(parsed.relationships) == 6
    assert len(parsed.hyperedges) == 1
    assert parsed.directed is True

    node_ids = {n.id for n in parsed.nodes}
    assert "src_auth_service_login" in node_ids

    # community membership is stamped onto nodes
    login = next(n for n in parsed.nodes if n.id == "src_auth_service_login")
    assert login.community_id == "0"
    assert login.file_type is FileType.CODE

    # community labels resolved from .graphify_labels.json
    auth = next(c for c in parsed.communities if c.id == "0")
    assert auth.label == "Authentication"
    assert auth.cohesion == pytest.approx(0.82)

    assert parsed.god_ids == ("src_auth_service_login",)


def test_graph_parser_relation_and_confidence(sample_repo: Path) -> None:
    parsed = GraphParser().parse(RepositoryLoader().load(sample_repo / "graphify-out"))
    relations = {r.relation for r in parsed.relationships}
    assert "calls" in relations
    assert "imports" in relations
    assert "conceptually_related_to" in relations


def test_report_parser_extracts_questions(sample_repo: Path) -> None:
    insights = ReportParser().parse(RepositoryLoader().load(sample_repo / "graphify-out"))
    assert "How does the login flow work?" in insights.questions


def test_load_pass_builds_ir_skeleton(sample_config: CompilerConfig) -> None:
    context = CompilationContext(sample_config)
    LoadPass().run(context)
    ir = context.require_ir()

    assert ir.metadata.repo_name == "sample_repo"
    assert ir.metadata.node_count == 8
    assert ir.metadata.edge_count == 6
    assert ir.metadata.community_count == 2
    assert ir.metadata.source_graph_hash  # non-empty hash
    # real source files were hashed; concept nodes (no source_file) were skipped
    assert "src/auth/service.py" in ir.metadata.file_hashes
    assert keys.PARSED_GRAPH in context.artifacts
    # projections not yet populated
    assert ir.symbols == ()
