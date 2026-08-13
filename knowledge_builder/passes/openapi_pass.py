"""OpenApiPass (Phase 4) — ingest OpenAPI/Swagger contracts as authoritative APIs.

Runs after :class:`~knowledge_builder.passes.classify_pass.ClassifyPass`. Where a spec
exists it is the source of truth: spec-derived :class:`~knowledge_builder.models.api.Api`
entities (``origin="openapi"``) replace the heuristic guesses for the same route, and
each is bound to its handler symbol. Heuristic APIs survive only for routes no spec
declares, so repositories without a spec are unaffected.

Best-effort by design: any failure leaves the heuristic APIs in place.
"""

from __future__ import annotations

from collections import defaultdict

from knowledge_builder.compiler.context import CompilationContext
from knowledge_builder.compiler.pass_base import CompilerPass
from knowledge_builder.models.api import Api
from knowledge_builder.models.base import Confidence
from knowledge_builder.parser.openapi import (
    bind,
    discover_mounts,
    discover_specs,
    normalize_path,
    parse_operations,
)
from knowledge_builder.parser.openapi.spec import Operation


def _routes(operations: list[Operation]) -> dict[tuple[str, str], list[Operation]]:
    """Group operations by the route they describe.

    A route is identified by ``(method, path)``. Two specs declaring ``POST /orders`` are
    describing one endpoint, not two — a repo commonly ships the same spec as ``.json``
    and ``.yaml``, or splits one service across files. Keying on the route (rather than on
    the spec that mentioned it) is also what keeps ``Api.id`` unique.
    """
    grouped: dict[tuple[str, str], list[Operation]] = defaultdict(list)
    for op in operations:
        grouped[(op.method, op.path)].append(op)
    return grouped


#: Fields whose presence makes one declaration of a route more informative than another.
_DETAIL_FIELDS = ("operation_id", "summary", "description", "tags", "parameters", "response_codes")


def _richest(group: list[Operation]) -> Operation:
    """The most detailed declaration of a route, deterministically.

    Prefers the declaration that fills in the most contract detail; ties break on spec
    path so the same repo always compiles to the same artifact.
    """
    return min(
        group, key=lambda o: (-sum(bool(getattr(o, f)) for f in _DETAIL_FIELDS), o.spec_file or "")
    )


def _disagree(group: list[Operation]) -> bool:
    """True when declarations of one route differ on contract-bearing fields.

    Identical copies (the same spec serialized twice) are not a conflict. Differing
    parameters or response codes mean the specs have drifted, and a reader deserves to
    know that rather than silently receive whichever one we happened to pick.
    """
    if len(group) < 2:
        return False
    signatures = {
        (o.operation_id, tuple(sorted(o.parameters)), tuple(sorted(o.response_codes)))
        for o in group
    }
    return len(signatures) > 1


class OpenApiPass(CompilerPass):
    """Replace heuristic routes with spec-derived contracts where a spec exists."""

    name = "openapi"

    def run(self, context: CompilationContext) -> None:
        ir = context.require_ir()
        try:
            specs = discover_specs(context.config.repo_path)
        except Exception as exc:  # noqa: BLE001 - never fail the build on spec discovery
            context.warning(self.name, "openapi discovery failed", error=str(exc))
            return
        if not specs:
            return

        operations = [op for rel, doc in specs for op in parse_operations(rel, doc)]
        if not operations:
            return

        try:
            mounts = discover_mounts(context.config.repo_path)
        except Exception as exc:  # noqa: BLE001 - mount discovery is best-effort
            context.warning(self.name, "router mount discovery failed", error=str(exc))
            mounts = {}
        bound = bind(operations, ir.symbols, mounts)
        symbols_by_id = ir.symbol_by_id()
        controller_of = {
            symbol_id: controller.id
            for controller in ir.controllers
            for symbol_id in controller.symbol_ids
        }

        apis: list[Api] = []
        conflicts: list[str] = []
        for (method, path), group in _routes(operations).items():
            op = _richest(group)
            handler_id = bound.get((method, path)) or next(
                (bound[(o.method, o.path)] for o in group if (o.method, o.path) in bound), None
            )
            handler = symbols_by_id.get(handler_id) if handler_id else None
            others = tuple(
                sorted({o.spec_file for o in group if o.spec_file != op.spec_file if o.spec_file})
            )
            conflict = _disagree(group)
            if conflict:
                conflicts.append(f"{method} {path}")
            apis.append(
                Api(
                    id=f"api::{method}::{path}",
                    name=op.operation_id or f"{method} {path}",
                    method=method,
                    path=path,
                    origin="openapi",
                    operation_id=op.operation_id,
                    summary=op.summary,
                    description=op.description,
                    tags=op.tags,
                    parameters=op.parameters,
                    response_codes=op.response_codes,
                    request_schema=op.request_schema,
                    spec_file=op.spec_file,
                    also_declared_in=others,
                    spec_conflict=conflict,
                    handler_symbol_id=handler_id,
                    controller_id=controller_of.get(handler_id or ""),
                    source_file=handler.source_file if handler else None,
                    confidence=Confidence.EXTRACTED,
                )
            )
        if conflicts:
            context.warning(
                self.name,
                "specs disagree on the same route",
                routes=len(conflicts),
                sample=", ".join(sorted(conflicts)[:5]),
            )

        # Keep heuristic APIs only for real routes the spec does not describe. With an
        # authoritative spec in hand, a guess with no method or path (a helper whose name
        # merely contains "endpoint") is noise, not an endpoint.
        covered = {(op.method, normalize_path(op.path)) for op in operations}
        kept = [
            api
            for api in ir.apis
            if api.origin != "openapi"
            and api.method
            and api.path
            and (api.method, normalize_path(api.path)) not in covered
        ]

        context.set_ir(ir.evolve(apis=tuple(apis) + tuple(kept)))
        context.stats["openapi"] = {
            "specs": len(specs),
            "operations": len(operations),
            "routes": len(apis),
            "bound": len(bound),
            "conflicts": len(conflicts),
        }
        context.info(
            self.name,
            "ingested openapi contracts",
            specs=len(specs),
            operations=len(operations),
            routes=len(apis),
            bound=len(bound),
        )
