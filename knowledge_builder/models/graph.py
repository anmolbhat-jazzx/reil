"""Raw graph layer of the IR: nodes and edges as parsed from graphify.

These retain *every* node and edge from ``graph.json`` so the serializer can persist a
faithful ``graph`` table. The typed projections (:class:`Symbol`, :class:`Concept`, …)
are derived subsets built by later passes.
"""

from __future__ import annotations

from knowledge_builder.models.base import Confidence, FileType, IRModel


class GraphNode(IRModel):
    """A node exactly as it appears in graphify's ``graph.json`` (plus community id)."""

    id: str
    label: str
    file_type: FileType
    source_file: str | None = None
    source_location: str | None = None
    source_url: str | None = None
    captured_at: str | None = None
    author: str | None = None
    contributor: str | None = None
    rationale: str | None = None
    community_id: str | None = None


class Relationship(IRModel):
    """A directed edge between two nodes (persisted from graphify's ``links``).

    ``relation`` is a free-form string: graphify emits an open-ended set of relation
    names (``calls``, ``contains``, ``method``, ``uses``, ``inherits``, ``imports_from``,
    …), so every edge is preserved verbatim rather than constrained to a fixed enum. See
    :class:`~knowledge_builder.models.base.RelationType` for the well-known constants the
    passes branch on.
    """

    id: str
    source_id: str
    target_id: str
    relation: str
    confidence: Confidence = Confidence.EXTRACTED
    confidence_score: float = 1.0
    weight: float = 1.0
    source_file: str | None = None

    @staticmethod
    def make_id(source_id: str, target_id: str, relation: str) -> str:
        """Deterministic id for an edge, stable across runs."""
        return f"{source_id}--{relation}-->{target_id}"
