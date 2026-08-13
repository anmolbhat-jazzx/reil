"""Router: resolve source-derived call sites into ``calls`` edges over symbols.

The provider ( :mod:`python_calls` ) says *"``svc.handle()`` where ``svc`` is a ``Repo``"*;
this module turns that into an edge between two symbol ids, using the enriched symbol
table as the index. No second parse of anything: the class list and the declared return
types both come from :class:`~knowledge_builder.models.symbol.Symbol` fields that
:class:`~knowledge_builder.passes.symbol_enrich_pass.SymbolEnrichPass` already filled in.

Resolution is strict on purpose. A name bound to two different classes resolves to
neither, and an unresolvable receiver emits nothing. Recall lost that way is recoverable
later; a wrong edge quietly corrupts every reachability answer built on top of it.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from knowledge_builder.models.base import Confidence, RelationType
from knowledge_builder.models.graph import Relationship
from knowledge_builder.models.symbol import Symbol
from knowledge_builder.parser.db.walk import read_text
from knowledge_builder.parser.symbols.python_calls import CallSite, TypeIndex, parse_calls

#: Trailing ``-> Return`` of a rendered signature, e.g. ``(a: int) -> Repo``.
_RETURN = re.compile(r"->\s*(.+)$")
#: Wrappers a return type may be nested in; the receiver is always the element type.
_UNWRAP = re.compile(r"^[\w.]*\[(.+)]$")


def resolve_calls(
    repo_path: Path,
    symbols: tuple[Symbol, ...],
    existing: tuple[Relationship, ...],
) -> tuple[Relationship, ...]:
    """Return ``calls`` edges derivable from source but absent from ``existing``."""
    index = _SymbolIndex(symbols)
    if not index.by_file:
        return ()
    types = index.type_index()
    known = {rel.id for rel in existing}
    bases = _base_classes(existing, index)

    out: dict[str, Relationship] = {}
    root = Path(repo_path)
    for source_file in index.by_file:
        text = read_text(root / source_file)
        if not text:
            continue
        for site in parse_calls(text, source_file, types):
            edge = _edge(site, source_file, index, bases)
            if edge is not None and edge.id not in known:
                out[edge.id] = edge
    return tuple(out.values())


def _edge(
    site: CallSite,
    source_file: str,
    index: _SymbolIndex,
    bases: dict[str, tuple[str, ...]],
) -> Relationship | None:
    caller = index.by_qualname.get(site.caller)
    if caller is None:
        return None
    target = (
        index.method_of(site.receiver_type, site.callee, bases)
        if site.receiver_type
        else index.module_function(source_file, site.callee)
    )
    if target is None or target == caller:
        return None
    return Relationship(
        id=Relationship.make_id(caller, target, RelationType.CALLS),
        source_id=caller,
        target_id=target,
        relation=RelationType.CALLS,
        # Deterministic static analysis, but from a type the source stated rather than a
        # token graphify saw at the call site — INFERRED keeps the two distinguishable.
        confidence=Confidence.INFERRED,
        source_file=source_file,
    )


class _SymbolIndex:
    """Lookup tables over the enriched symbol table."""

    def __init__(self, symbols: tuple[Symbol, ...]) -> None:
        self.by_qualname: dict[str, str] = {}
        self.by_file: dict[str, list[Symbol]] = defaultdict(list)
        self._classes: dict[str, list[Symbol]] = defaultdict(list)
        self._returns: dict[str, set[str]] = defaultdict(set)
        self._by_id: dict[str, Symbol] = {}

        for sym in symbols:
            self._by_id[sym.id] = sym
            if sym.source_file and sym.source_file.endswith(".py"):
                self.by_file[sym.source_file].append(sym)
            if sym.qualified_name:
                # A qualified name repeated across files cannot identify one symbol; drop
                # it rather than let insertion order pick a winner.
                self.by_qualname[sym.qualified_name] = (
                    "" if sym.qualified_name in self.by_qualname else sym.id
                )
            if sym.kind == "class" and sym.name:
                self._classes[sym.name].append(sym)
            elif sym.kind in ("function", "method") and sym.name and sym.signature:
                declared = _return_type(sym.signature)
                if declared:
                    self._returns[sym.name].add(declared)
        self.by_qualname = {k: v for k, v in self.by_qualname.items() if v}

    def type_index(self) -> TypeIndex:
        return TypeIndex(
            class_names=frozenset(self._classes),
            # Overloads that disagree about their return type tell us nothing usable.
            return_types={n: next(iter(r)) for n, r in self._returns.items() if len(r) == 1},
        )

    def method_of(
        self, class_name: str, method: str, bases: dict[str, tuple[str, ...]]
    ) -> str | None:
        """Symbol id of ``class_name.method``, following base classes; ``None`` if unsure."""
        candidates = self._classes.get(class_name, ())
        if len(candidates) != 1:
            return None  # two classes share this name — the call site cannot say which
        found: list[str] = []
        for cls_id in self._mro(candidates[0].id, bases):
            cls = self._by_id.get(cls_id)
            if cls is None or not cls.qualified_name:
                continue
            owner = self.by_qualname.get(f"{cls.qualified_name}.{method}")
            if owner:
                found.append(owner)
                break  # nearest definition in the chain wins, as Python resolves it
        return found[0] if found else None

    def module_function(self, source_file: str, name: str) -> str | None:
        """A module-local function of this name — the one bare-call case that is safe."""
        matches = [
            s
            for s in self.by_file.get(source_file, ())
            if s.name == name and s.kind in ("function", "class")
        ]
        return matches[0].id if len(matches) == 1 else None

    def _mro(self, class_id: str, bases: dict[str, tuple[str, ...]]) -> list[str]:
        """Breadth-first walk of the inheritance chain, cycle-safe."""
        order, seen, queue = [], {class_id}, [class_id]
        while queue:
            current = queue.pop(0)
            order.append(current)
            for base in bases.get(current, ()):
                if base not in seen:
                    seen.add(base)
                    queue.append(base)
        return order


def _base_classes(
    relationships: tuple[Relationship, ...], index: _SymbolIndex
) -> dict[str, tuple[str, ...]]:
    """Class symbol id -> base class symbol ids, from graphify's ``inherits`` edges."""
    out: dict[str, list[str]] = defaultdict(list)
    for rel in relationships:
        if rel.relation == RelationType.INHERITS:
            out[rel.source_id].append(rel.target_id)
    return {k: tuple(v) for k, v in out.items()}


def _return_type(signature: str) -> str | None:
    """``(a: int) -> Optional[Repo]`` → ``Repo``; ``None`` when nothing usable is declared."""
    match = _RETURN.search(signature)
    if not match:
        return None
    text = match.group(1).strip().strip('"').strip("'")
    for _ in range(3):  # unwrap nested generics: Awaitable[Optional[Repo]]
        inner = _UNWRAP.match(text)
        if inner is None:
            break
        text = inner.group(1).split(",")[0].strip()
    text = text.split("|")[0].strip()
    return text if text.isidentifier() else None


def call_stats(edges: tuple[Relationship, ...]) -> dict[str, Any]:
    """Summary of what resolution added, for the pass log."""
    return {"added": len(edges), "callers": len({e.source_id for e in edges})}
