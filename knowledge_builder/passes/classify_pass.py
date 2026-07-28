"""ClassifyPass (Phase 4) — derive Service / Controller / Api components.

graphify does not label architectural roles, so this pass infers them deterministically
from source-file path segments and symbol labels. Every symbol that matches no pattern
stays a plain :class:`Symbol`. Heuristics here are intentionally conservative and fully
documented so misclassifications are easy to reason about.
"""

from __future__ import annotations

import re
from collections import defaultdict

from knowledge_builder.compiler.context import CompilationContext
from knowledge_builder.compiler.pass_base import CompilerPass
from knowledge_builder.models.api import Api
from knowledge_builder.models.base import ComponentKind
from knowledge_builder.models.controller import Controller
from knowledge_builder.models.service import Service
from knowledge_builder.models.symbol import Symbol
from knowledge_builder.utils.paths import capability_base, title_case

_METHOD_PATH = re.compile(r"^(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(/\S*)", re.IGNORECASE)


class ClassifyPass(CompilerPass):
    """Classify symbols into services, controllers, and API endpoints."""

    name = "classify"

    def run(self, context: CompilationContext) -> None:
        ir = context.require_ir()

        service_files: dict[str, list[Symbol]] = defaultdict(list)
        controller_files: dict[str, list[Symbol]] = defaultdict(list)
        api_symbols: list[Symbol] = []

        for symbol in ir.symbols:
            role = _role(symbol)
            if role is ComponentKind.SERVICE:
                service_files[symbol.source_file or "<root>"].append(symbol)
            elif role is ComponentKind.CONTROLLER:
                controller_files[symbol.source_file or "<root>"].append(symbol)
            elif role in (ComponentKind.API, ComponentKind.ROUTE):
                api_symbols.append(symbol)

        services = tuple(
            Service(
                id=f"service::{file}",
                name=_component_name(file, "Service"),
                symbol_ids=tuple(s.id for s in syms),
                source_files=(file,),
            )
            for file, syms in sorted(service_files.items())
        )
        controllers = tuple(
            Controller(
                id=f"controller::{file}",
                name=_component_name(file, "Controller"),
                symbol_ids=tuple(s.id for s in syms),
                source_files=(file,),
            )
            for file, syms in sorted(controller_files.items())
        )
        controller_by_file = {c.source_files[0]: c.id for c in controllers}
        apis = tuple(
            _make_api(symbol, controller_by_file.get(symbol.source_file or "<root>"))
            for symbol in sorted(api_symbols, key=lambda s: s.id)
        )

        context.set_ir(ir.evolve(services=services, controllers=controllers, apis=apis))
        context.stats["components"] = {
            "services": len(services),
            "controllers": len(controllers),
            "apis": len(apis),
        }
        context.info(
            self.name,
            "classified components",
            services=len(services),
            controllers=len(controllers),
            apis=len(apis),
        )


def _role(symbol: Symbol) -> ComponentKind | None:
    path = (symbol.source_file or "").lower()
    parts = path.split("/")
    stem = parts[-1].rsplit(".", 1)[0] if parts else ""
    label = symbol.label.lower()

    if "controllers" in parts or "controller" in stem or label.endswith(("controller", "handler")):
        return ComponentKind.CONTROLLER
    if (
        any(seg in parts for seg in ("routes", "route", "urls", "endpoints", "api", "apis"))
        or stem in ("routes", "urls", "endpoints", "route")
        or "route" in label
        or "endpoint" in label
    ):
        return ComponentKind.API
    if (
        "services" in parts
        or "service" in parts
        or stem.endswith("service")
        or "_service" in stem
        or label.endswith("service")
    ):
        return ComponentKind.SERVICE
    return None


def _component_name(source_file: str, suffix: str) -> str:
    base = capability_base(source_file) or "Component"
    title = title_case(base)
    if title.lower().endswith(suffix.lower()):
        return title
    return f"{title}{suffix}"


def _make_api(symbol: Symbol, controller_id: str | None) -> Api:
    method: str | None = None
    path: str | None = None
    match = _METHOD_PATH.match(symbol.label)
    if match:
        method = match.group(1).upper()
        path = match.group(2)
    return Api(
        id=f"api::{symbol.id}",
        name=symbol.label,
        method=method,
        path=path,
        handler_symbol_id=symbol.id,
        controller_id=controller_id,
        source_file=symbol.source_file,
    )
