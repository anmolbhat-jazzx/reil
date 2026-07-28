"""Controller: a derived controller/handler component."""

from __future__ import annotations

from knowledge_builder.models.base import IRModel


class Controller(IRModel):
    """A controller component derived by heuristic classification.

    Groups code symbols identified as request handlers (files under
    ``**/controllers/**`` or ``**/routes/**``, symbols labelled ``*Controller``).
    ``api_ids`` links the controller to the endpoints it exposes.
    """

    id: str
    name: str
    symbol_ids: tuple[str, ...] = ()
    source_files: tuple[str, ...] = ()
    api_ids: tuple[str, ...] = ()
    module_id: str | None = None
