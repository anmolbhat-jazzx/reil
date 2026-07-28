"""Internal, parser-level data structures (not part of the persisted IR).

These hold graphify content that later passes consume — hyperedges, community
membership, god nodes — but which is not itself a first-class IR entity.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from knowledge_builder.models.base import Confidence, HyperedgeRelation
from knowledge_builder.models.graph import GraphNode, Relationship


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class RawHyperedge(_Frozen):
    """A graphify hyperedge (group of 3+ participating nodes)."""

    id: str
    label: str
    nodes: tuple[str, ...]
    relation: HyperedgeRelation = HyperedgeRelation.PARTICIPATE_IN
    confidence: Confidence = Confidence.EXTRACTED
    confidence_score: float = 1.0
    source_file: str | None = None


class CommunityInfo(_Frozen):
    """A detected community: its members, label, cohesion, and god nodes."""

    id: str
    label: str
    member_ids: tuple[str, ...] = ()
    cohesion: float | None = None
    god_ids: tuple[str, ...] = ()


class ParsedGraph(_Frozen):
    """The fully parsed graphify bundle, ready for IR assembly."""

    nodes: tuple[GraphNode, ...] = ()
    relationships: tuple[Relationship, ...] = ()
    hyperedges: tuple[RawHyperedge, ...] = ()
    communities: tuple[CommunityInfo, ...] = ()
    god_ids: tuple[str, ...] = ()
    directed: bool = True
    multigraph: bool = False
    graphify_version: str | None = None

    def community_of(self) -> dict[str, str]:
        """Map each member node id to its community id."""
        mapping: dict[str, str] = {}
        for community in self.communities:
            for node_id in community.member_ids:
                mapping.setdefault(node_id, community.id)
        return mapping
