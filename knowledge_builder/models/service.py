"""Service: a derived service component (business-logic unit)."""

from __future__ import annotations

from knowledge_builder.models.base import IRModel


class Service(IRModel):
    """A service component derived by heuristic classification.

    Grouping of code symbols that a heuristic identified as a service (e.g. files under
    ``**/services/**`` or symbols labelled ``*Service``).
    """

    id: str
    name: str
    symbol_ids: tuple[str, ...] = ()
    source_files: tuple[str, ...] = ()
    module_id: str | None = None
