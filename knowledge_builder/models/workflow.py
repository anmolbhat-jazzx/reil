"""Workflow: a multi-participant flow harvested from a graphify hyperedge."""

from __future__ import annotations

from knowledge_builder.models.base import Confidence, HyperedgeRelation, IRModel


class Workflow(IRModel):
    """A workflow: an ordered set of participating nodes that form one flow.

    Projected from graphify ``hyperedges`` (relations ``participate_in|implement|form``).
    """

    id: str
    name: str
    participant_ids: tuple[str, ...] = ()
    relation: HyperedgeRelation = HyperedgeRelation.PARTICIPATE_IN
    confidence: Confidence = Confidence.EXTRACTED
    confidence_score: float = 1.0
    source_file: str | None = None
