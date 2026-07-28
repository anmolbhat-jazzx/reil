"""Symbol: a code entity (function/class/etc.) projected from a ``code`` node."""

from __future__ import annotations

from knowledge_builder.models.base import IRModel


class Symbol(IRModel):
    """A code symbol.

    graphify does not record symbol kind (function vs class vs method), so ``kind`` is
    left unset in V1; ``language`` is inferred deterministically from the source-file
    extension.
    """

    id: str
    label: str
    source_file: str | None = None
    source_location: str | None = None
    language: str | None = None
    module_id: str | None = None
    rationale: str | None = None
