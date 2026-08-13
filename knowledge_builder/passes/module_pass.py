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
from knowledge_builder.models.symbol import REFERENCE_KINDS, Symbol
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

        # A cluster of pure references (``Any``, ``UUID``, ``asyncio``) is not a capability.
        modules = [m for m in modules if not _is_reference_only(m, symbols_by_id)]

        # A dozen modules all called "Collection" are unusable in a listing; widen each
        # colliding name with enough of its path to tell them apart.
        modules = _disambiguate_names(modules, symbols_by_id)

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
                    # Use the resolved identifier, not the raw label: a label may be
                    # ``.test_foo()`` or a bare imported type, neither of which names
                    # a capability. Fall back to the package for those.
                    name=_standalone_name(only),
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


def _is_reference_only(module: Module, symbols_by_id: dict[str, Symbol]) -> bool:
    """True when a module defines nothing and points at no file.

    graphify clusters imports too, so ``typing.Any``, ``uuid.UUID`` and ``asyncio`` each
    attract a community of their own users. Such a group has no source path, no docstring
    and no definition — there is nothing a reader could open. It names a *type the code
    depends on*, never a capability the code provides, so it is not a module.
    """
    if module.source_paths:
        return False
    return all(
        (symbol := symbols_by_id.get(sid)) is None or symbol.kind in REFERENCE_KINDS
        for sid in module.symbol_ids
    )


def _disambiguate_names(modules: list[Module], symbols_by_id: dict[str, Symbol]) -> list[Module]:
    """Widen colliding module names until every name in the listing is distinct.

    ``Collection`` × 15 tells a reader nothing. Adding the smallest amount of the module's
    own path that separates it — ``Collection Api``, ``Tests Collection`` — keeps names
    short while making them identifying. Names that are already unique are untouched.
    """
    by_name: dict[str, list[Module]] = defaultdict(list)
    for module in modules:
        by_name[module.name].append(module)

    # One shared pool of claimed names. Per-group pools are not enough: two *different*
    # colliding groups can widen into the same string (``FsManager`` and ``TestFsManager``
    # both reach for ``LocalFs TestFsManager``), which reintroduces the duplicate the
    # widening exists to remove.
    taken = {name for name, group in by_name.items() if len(group) == 1}
    renamed: dict[str, str] = {}
    for name, group in sorted(by_name.items()):
        if len(group) < 2:
            continue
        for module in group:
            widened = _widen_name(name, module, taken, symbols_by_id)
            renamed[module.id] = widened
            taken.add(widened)
    if not renamed:
        return modules
    return [m.model_copy(update={"name": renamed[m.id]}) if m.id in renamed else m for m in modules]


def _widen_name(
    base: str, module: Module, taken: set[str], symbols_by_id: dict[str, Symbol]
) -> str:
    """Add path context, then symbol context, then a counter — first unique wins.

    Starts at two path segments because one is rarely identifying on its own: modules in
    the same directory differ only by file, so ``Collection Api`` / ``Collection Models``
    separates them where ``Collection`` alone cannot. When the path runs out — several
    modules carved out of a *single* file — what tells them apart is the code they own,
    not where it lives, so the symbol names are tried next.
    """
    parts = _path_parts(module)
    # Two segments normally, because one rarely separates same-directory modules. A
    # one-segment path (``demo/__init__.py``) has nothing more to give, so use it —
    # ``Demo`` alongside ``Demo Utils`` beats ``Demo 2``.
    start = 1 if len(parts) == 1 else 2
    for depth in range(start, min(len(parts), 4) + 1):
        candidate = _join_parts(parts[-depth:])
        if candidate and candidate not in taken:
            return candidate
    for candidate in _symbol_names(module, symbols_by_id):
        if candidate not in taken:
            return candidate
    suffix = 2
    while f"{base} {suffix}" in taken:
        suffix += 1
    return f"{base} {suffix}"


def _join_parts(parts: list[str]) -> str:
    """Title-case path segments into a name, collapsing an immediate repeat.

    ``app/collection/document_utils/document_utils.py`` should read ``Collection
    DocumentUtils``, not ``Collection DocumentUtils DocumentUtils``.
    """
    words: list[str] = []
    for part in parts:
        word = title_case(part)
        if word and (not words or word != words[-1]):
            words.append(word)
    return " ".join(words)


def _symbol_names(module: Module, symbols_by_id: dict[str, Symbol]) -> list[str]:
    """Naming candidates from the module's symbols, definitions first.

    References are kept as a last resort rather than dropped: for a module whose members
    are all file or import nodes, the name of a thing it touches still identifies it
    better than a numeric suffix does.
    """
    defined: list[str] = []
    referenced: list[str] = []
    for sid in module.symbol_ids:
        symbol = symbols_by_id.get(sid)
        if symbol is None:
            continue
        name = (symbol.name or "").strip()
        # Private helpers and dunders name no capability — ``__init__`` would become the
        # module "Init", which says less than the counter it was meant to replace.
        if not name or name.startswith("_"):
            continue
        bucket = referenced if symbol.kind in REFERENCE_KINDS else defined
        bucket.append(title_case(name))
    return [*defined, *referenced]


def _path_parts(module: Module) -> list[str]:
    """Segments of the module's dominant source path, file stem included.

    The file name is kept: two modules in one directory are distinguishable only by it.
    """
    if not module.source_paths:
        return []
    counts = Counter(module.source_paths)
    dominant = counts.most_common(1)[0][0]
    parts = [p for p in dominant.split("/") if p and p != "."]
    if parts:
        stem = parts[-1].rsplit(".", 1)[0]
        parts = [*parts[:-1], stem] if stem else parts[:-1]
    return [p for p in parts if p and p != "__init__"]


def _standalone_name(symbol: Symbol) -> str:
    """Name a one-symbol module by its capability, not its raw graphify label."""
    if symbol.kind not in REFERENCE_KINDS:
        name = (symbol.name or "").strip()
        if name and not name.startswith("_"):
            return title_case(name) or name
    return _name_from_symbols([symbol])


def _community_name(community: CommunityInfo, members: list[Symbol]) -> str:
    label = (community.label or "").strip()
    if label and not _PLACEHOLDER.match(label) and not _is_weak_name(label, members):
        return label
    return _name_from_symbols(members)


def _is_weak_name(label: str, members: list[Symbol]) -> bool:
    """True when a label names a reference rather than a capability.

    graphify labels a community after a prominent node, which is often an *imported*
    type (``AsyncSession``, ``Any``) or a private helper (``._execute_command``). Those
    describe what the code uses, not what it does, so the package name is more useful.
    """
    if label.startswith((".", "_")) or not label[:1].isalnum():
        return True
    if "/" in label:
        # A path says where code lives, not what it does — ``app/core/__init__.py`` is a
        # location. The package-derived name is both shorter and more meaningful. A bare
        # file name is left alone: for files whose name *is* the story (a migration such
        # as ``0007_added_reasoner_runs_table.py``) it beats anything we could derive.
        return True
    imported = {s.name for s in members if s.kind in REFERENCE_KINDS and s.name}
    return label in imported


def _definition_symbols(symbols: list[Symbol]) -> list[Symbol]:
    """Symbols actually defined here — imports and file nodes name nothing."""
    return [s for s in symbols if s.kind not in REFERENCE_KINDS] or symbols


def _name_from_symbols(symbols: list[Symbol]) -> str:
    defined = _definition_symbols(symbols)
    packages = Counter(package_key(s.source_file) for s in defined)
    dominant, _ = packages.most_common(1)[0]
    # Hand ``capability_base`` a *real* file from that package. It falls back to the file
    # stem when every directory is generic (``app/``, ``src/``), so a synthetic
    # ``{package}/x.py`` placeholder would smuggle its own stem in and name the module "X".
    sample = next((s.source_file for s in defined if package_key(s.source_file) == dominant), None)
    base = capability_base(sample) if dominant != "<root>" else None
    if base:
        return title_case(base)
    prefix = _common_prefix([s.name or s.label for s in defined])
    if prefix:
        return title_case(prefix)
    stem = title_case(_file_stem(defined))
    if stem:
        return stem
    # Never fall back to a bare "Module". Graph nodes can arrive with no source file at
    # all; the code they hold still names them better than a counter does.
    for symbol in defined:
        name = (symbol.name or symbol.label or "").strip().lstrip("._")
        if name:
            return title_case(name)
    return "Module"


def _file_stem(symbols: list[Symbol]) -> str:
    for symbol in symbols:
        if symbol.source_file:
            stem = symbol.source_file.rsplit("/", 1)[-1]
            return stem.rsplit(".", 1)[0]
    return ""


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
