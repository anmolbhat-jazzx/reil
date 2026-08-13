"""Metadata: provenance and integrity information for a compiled artifact."""

from __future__ import annotations

from knowledge_builder.models.base import IRModel

SCHEMA_VERSION = 4
"""Version of the ``knowledge.kb`` schema. Bump on any breaking table change.

v2 adds the database layer (``db_technologies`` / ``db_tables`` / ``db_migrations``).
v3 adds enriched symbol columns (``name`` / ``start_line`` / ``end_line`` / ``kind`` /
``qualified_name``) and the ``(name, source_file, start_line)`` identity index.
v4 makes an ``Api`` one row per route rather than per spec declaration, adding
``also_declared_in`` / ``spec_conflict``. Multi-spec repos could not be compiled at all
before this (duplicate ``apis.id``).
Artifacts built at an older version must be rebuilt.
"""


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
