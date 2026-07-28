"""Phase 5 tests: concept harvest, workflows, and per-module summaries."""

from __future__ import annotations

from knowledge_builder.compiler import CompilationContext
from knowledge_builder.models import FileType


def test_concepts_harvested(harvested_context: CompilationContext) -> None:
    ir = harvested_context.require_ir()
    labels = [c.label for c in ir.concepts]
    assert labels.count("JWT") == 2  # both concept nodes (dedup happens in Phase 6)
    jwt = next(c for c in ir.concepts if c.id == "concept_jwt")
    assert jwt.file_type is FileType.CONCEPT
    assert jwt.rationale is not None
    # related to the two auth symbols that reference it
    assert "src_auth_service_login" in jwt.related_ids
    assert "src_auth_service_validate_token" in jwt.related_ids


def test_concepts_attached_to_modules(harvested_context: CompilationContext) -> None:
    ir = harvested_context.require_ir()
    auth = ir.find_module("Authentication")
    assert auth is not None
    assert "concept_jwt" in auth.concept_ids


def test_workflows_harvested(harvested_context: CompilationContext) -> None:
    ir = harvested_context.require_ir()
    assert len(ir.workflows) == 1
    flow = ir.workflows[0]
    assert flow.name == "Login Flow"
    assert "src_auth_service_login" in flow.participant_ids
    # workflow attached to the auth module
    auth = ir.find_module("Authentication")
    assert auth is not None
    assert flow.id in auth.workflow_ids


def test_module_summaries(harvested_context: CompilationContext) -> None:
    ir = harvested_context.require_ir()
    assert len(ir.summaries) == len(ir.modules)
    by_module = {s.module_id: s for s in ir.summaries}

    auth = ir.find_module("Authentication")
    assert auth is not None and auth.summary_id is not None
    summary = by_module[auth.id]
    # deterministic fields populated from harvested data
    assert "AuthService" in summary.responsibilities
    assert "AuthController" in summary.responsibilities
    assert "JWT" in summary.concepts
    assert "Login Flow" in summary.workflows
    # god node (login) belongs to this module
    assert "login" in summary.god_nodes
    # fields with no deterministic source are left empty (V2 LLM fills them)
    assert summary.purpose is None
    assert summary.business_rules == ()
