"""Api: an HTTP endpoint / route derived by heuristic classification."""

from __future__ import annotations

from knowledge_builder.models.base import IRModel


class Api(IRModel):
    """A derived API endpoint / route.

    graphify does not model routes, so every field is best-effort from heuristics:
    HTTP ``method`` and ``path`` parsed from labels/source when available, otherwise
    ``None``. ``handler_symbol_id`` links to the symbol implementing the endpoint.
    """

    id: str
    name: str
    method: str | None = None
    path: str | None = None
    handler_symbol_id: str | None = None
    controller_id: str | None = None
    module_id: str | None = None
    source_file: str | None = None
