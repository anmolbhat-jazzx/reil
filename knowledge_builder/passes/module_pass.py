"""ModulePass (Phase 4) — build logical modules using the Hybrid strategy.

A *Logical Module* is a cohesive group of strongly connected symbols representing a
single business capability. Boundaries are discovered:

1. **Primary** — one module per graphify community.
2. **Split** — a low-cohesion or oversized community is partitioned by package.
3. **Fallback** — symbols with no community are grouped by package.
4. **Standalone** — a lone, community-less symbol becomes its own small module.

Each symbol is assigned exactly one primary module; cross-module edges populate
``related_module_ids``. Services/controllers/APIs are linked to the module that owns
their symbols. (Merging of tiny modules happens in the Phase 6 optimizer.)
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

from knowledge_builder.compiler.context import CompilationContext
from knowledge_builder.compiler.pass_base import CompilerPass
from knowledge_builder.models.api import Api
from knowledge_builder.models.base import ModuleOrigin
from knowledge_builder.models.graph import Relationship
from knowledge_builder.models.module import Module
from knowledge_builder.models.symbol import Symbol
from knowledge_builder.parser.types import CommunityInfo, ParsedGraph
from knowledge_builder.passes import keys
from knowledge_builder.utils.paths import capability_base, package_key, title_case

_PLACEHOLDER = re.compile(r"(?i)^community\s+\S+$")


class ModulePass(CompilerPass):
    """Assign symbols to logical modules per the Hybrid strategy."""

    name = "modules"

    def run(self, context: CompilationContext) -> None:
        ir = context.require_ir()
        parsed: ParsedGraph = context.artifacts[keys.PARSED_GRAPH]
        cfg = context.config

        symbols_by_id = {s.id: s for s in ir.symbols}
        assigned: set[str] = set()
        modules: list[Module] = []

        # 1-2. Community-driven modules (with optional split).
        for community in parsed.communities:
            members = [symbols_by_id[sid] for sid in community.member_ids if sid in symbols_by_id]
            if not members:
                continue
            assigned.update(s.id for s in members)
            modules.extend(
                self._modules_for_community(
                    community, members, cfg.min_cohesion, cfg.max_module_size
                )
            )

        # 3-4. Fallback: community-less symbols grouped by package.
        leftovers = [s for s in ir.symbols if s.id not in assigned]
        modules.extend(_fallback_modules(leftovers))

        # Assign module_id back onto symbols.
        symbol_to_module = {sid: m.id for m in modules for sid in m.symbol_ids}
        symbols = tuple(
            s.model_copy(update={"module_id": symbol_to_module.get(s.id)}) for s in ir.symbols
        )

        # Related modules from cross-module edges.
        related = _related_modules(ir.relationships, symbol_to_module)
        # Attach components to their owning module.
        service_ids = _group_component(ir.services, symbol_to_module)
        controller_ids = _group_component(ir.controllers, symbol_to_module)
        api_ids = _group_apis(ir.apis, symbol_to_module)

        modules = [
            m.model_copy(
                update={
                    "related_module_ids": tuple(sorted(related.get(m.id, set()))),
                    "service_ids": tuple(sorted(service_ids.get(m.id, set()))),
                    "controller_ids": tuple(sorted(controller_ids.get(m.id, set()))),
                    "api_ids": tuple(sorted(api_ids.get(m.id, set()))),
                }
            )
            for m in modules
        ]

        context.set_ir(ir.evolve(symbols=symbols, modules=tuple(modules)))
        context.stats["modules"] = {
            "count": len(modules),
            "by_origin": dict(Counter(m.origin.value for m in modules)),
        }
        context.info(self.name, "built modules", count=len(modules))

    def _modules_for_community(
        self,
        community: CommunityInfo,
        members: list[Symbol],
        min_cohesion: float,
        max_size: int,
    ) -> list[Module]:
        should_split = (
            community.cohesion is not None and community.cohesion < min_cohesion
        ) or len(members) > max_size
        source_paths = _source_paths(members)

        if not should_split:
            return [
                Module(
                    id=f"module::community::{community.id}",
                    name=_community_name(community, members),
                    origin=ModuleOrigin.COMMUNITY,
                    community_id=community.id,
                    cohesion=community.cohesion,
                    symbol_ids=tuple(s.id for s in members),
                    source_paths=source_paths,
                )
            ]

        # Split by package boundary.
        by_pkg: dict[str, list[Symbol]] = defaultdict(list)
        for symbol in members:
            by_pkg[package_key(symbol.source_file)].append(symbol)
        result: list[Module] = []
        for pkg, syms in sorted(by_pkg.items()):
            result.append(
                Module(
                    id=f"module::community::{community.id}::{_slug(pkg)}",
                    name=_name_from_symbols(syms),
                    origin=ModuleOrigin.PACKAGE,
                    community_id=community.id,
                    cohesion=community.cohesion,
                    symbol_ids=tuple(s.id for s in syms),
                    source_paths=_source_paths(syms),
                )
            )
        return result


def _fallback_modules(leftovers: list[Symbol]) -> list[Module]:
    by_pkg: dict[str, list[Symbol]] = defaultdict(list)
    for symbol in leftovers:
        by_pkg[package_key(symbol.source_file)].append(symbol)
    modules: list[Module] = []
    for pkg, syms in sorted(by_pkg.items()):
        if len(syms) == 1:
            only = syms[0]
            modules.append(
                Module(
                    id=f"module::symbol::{only.id}",
                    name=title_case(only.label) or only.label,
                    origin=ModuleOrigin.STANDALONE,
                    symbol_ids=(only.id,),
                    source_paths=_source_paths(syms),
                )
            )
        else:
            modules.append(
                Module(
                    id=f"module::package::{_slug(pkg)}",
                    name=_name_from_symbols(syms),
                    origin=ModuleOrigin.PACKAGE,
                    symbol_ids=tuple(s.id for s in syms),
                    source_paths=_source_paths(syms),
                )
            )
    return modules


def _related_modules(
    relationships: tuple[Relationship, ...], symbol_to_module: dict[str, str]
) -> dict[str, set[str]]:
    related: dict[str, set[str]] = defaultdict(set)
    for rel in relationships:
        src = symbol_to_module.get(rel.source_id)
        tgt = symbol_to_module.get(rel.target_id)
        if src and tgt and src != tgt:
            related[src].add(tgt)
            related[tgt].add(src)
    return related


def _group_component(
    components: tuple[Any, ...], symbol_to_module: dict[str, str]
) -> dict[str, set[str]]:
    grouped: dict[str, set[str]] = defaultdict(set)
    for comp in components:
        for sid in comp.symbol_ids:
            module_id = symbol_to_module.get(sid)
            if module_id:
                grouped[module_id].add(comp.id)
                break
    return grouped


def _group_apis(apis: tuple[Api, ...], symbol_to_module: dict[str, str]) -> dict[str, set[str]]:
    grouped: dict[str, set[str]] = defaultdict(set)
    for api in apis:
        module_id = symbol_to_module.get(api.handler_symbol_id or "")
        if module_id:
            grouped[module_id].add(api.id)
    return grouped


def _community_name(community: CommunityInfo, members: list[Symbol]) -> str:
    if community.label and not _PLACEHOLDER.match(community.label):
        return community.label
    return _name_from_symbols(members)


def _name_from_symbols(symbols: list[Symbol]) -> str:
    packages = Counter(package_key(s.source_file) for s in symbols)
    dominant, _ = packages.most_common(1)[0]
    base = capability_base(f"{dominant}/x.py") if dominant != "<root>" else None
    if base:
        return title_case(base)
    prefix = _common_prefix([s.label for s in symbols])
    return title_case(prefix) if prefix else "Module"


def _common_prefix(labels: list[str]) -> str:
    if not labels:
        return ""
    prefix = labels[0]
    for label in labels[1:]:
        while not label.startswith(prefix):
            prefix = prefix[:-1]
            if not prefix:
                return ""
    return prefix.rstrip("_-.")


def _source_paths(symbols: list[Symbol]) -> tuple[str, ...]:
    return tuple(sorted({s.source_file for s in symbols if s.source_file}))


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "root"
