"""Api: an HTTP endpoint / route.

Two provenances, distinguished by ``origin``:

* ``openapi`` — read from a committed OpenAPI/Swagger spec. Authoritative and
  framework-agnostic: method, path, operation id, params, and response codes are the
  contract itself, not a guess.
* ``heuristic`` — inferred by the classify pass from file paths and symbol labels, used
  only where no spec exists.

``handler_symbol_id`` binds the contract to the symbol that implements it, which is what
lets a consumer walk from an endpoint to its code and call sites.
"""

from __future__ import annotations

from knowledge_builder.models.base import Confidence, IRModel


class Api(IRModel):
    """An API endpoint / route."""

    id: str
    name: str
    method: str | None = None
    path: str | None = None
    #: ``openapi`` or ``heuristic``.
    origin: str = "heuristic"
    operation_id: str | None = None
    summary: str | None = None
    description: str | None = None
    tags: tuple[str, ...] = ()
    #: Declared parameter names (path/query/header).
    parameters: tuple[str, ...] = ()
    #: Declared response status codes, e.g. ``("200", "404")``.
    response_codes: tuple[str, ...] = ()
    request_schema: str | None = None
    #: Spec file the operation was read from (``origin="openapi"``).
    spec_file: str | None = None
    #: Other spec files declaring this same route. A repo may ship one spec as both
    #: ``.json`` and ``.yaml``, or split a service across specs; the route is still one
    #: endpoint, so the duplicates are recorded here rather than emitted as extra rows.
    also_declared_in: tuple[str, ...] = ()
    #: True when those declarations disagree on operation id, params, or responses —
    #: the specs have drifted, which is a defect worth surfacing, not averaging away.
    spec_conflict: bool = False
    handler_symbol_id: str | None = None
    controller_id: str | None = None
    module_id: str | None = None
    source_file: str | None = None
    confidence: Confidence = Confidence.EXTRACTED
