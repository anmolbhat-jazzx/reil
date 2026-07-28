"""Metadata: provenance and integrity information for a compiled artifact."""

from __future__ import annotations

from knowledge_builder.models.base import IRModel

SCHEMA_VERSION = 1
"""Version of the ``knowledge.kb`` schema. Bump on any breaking table change."""


class Metadata(IRModel):
    """Repository-level metadata carried through the pipeline into ``knowledge.kb``."""

    repo_path: str
    repo_name: str
    schema_version: int = SCHEMA_VERSION
    generated_by: str = "knowledge_builder"
    builder_version: str | None = None
    graphify_version: str | None = None
    directed: bool = True
    multigraph: bool = False
    node_count: int = 0
    edge_count: int = 0
    community_count: int = 0
    source_graph_hash: str | None = None
    file_hashes: dict[str, str] = {}
