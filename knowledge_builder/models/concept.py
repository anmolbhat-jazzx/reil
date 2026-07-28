"""Concept: a semantic idea harvested from graphify's LLM-extracted nodes."""

from __future__ import annotations

from knowledge_builder.models.base import Confidence, FileType, IRModel


class Concept(IRModel):
    """A named concept or design rationale.

    Projected from nodes with ``file_type in {concept, rationale}``. ``related_ids``
    links the concept to the symbols/modules it relates to (from
    ``conceptually_related_to`` / ``semantically_similar_to`` edges).
    """

    id: str
    label: str
    file_type: FileType = FileType.CONCEPT
    rationale: str | None = None
    source_file: str | None = None
    source_location: str | None = None
    confidence: Confidence = Confidence.EXTRACTED
    related_ids: tuple[str, ...] = ()

    @property
    def normalized_label(self) -> str:
        """Case/whitespace-normalized label, used for deduplication."""
        return " ".join(self.label.lower().split())
