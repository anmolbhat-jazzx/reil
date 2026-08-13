"""Router: enrich symbols with source-derived detail, per language provider.

Groups symbols by source file, parses each supported file once, and matches every symbol
to its definition — primarily by name, tie-broken by the closest ``start_line`` (so a
graphify line that points at a decorator or is off by one still resolves). The matched
definition's fields become the update applied to the symbol; ``start_line`` is rewritten
to the parser's authoritative ``def``/``class`` line (the join key).

Python is handled by :mod:`python_ast`; every other language goes through
:mod:`treesitter_provider`. A file with no provider — or that a provider cannot parse —
keeps the graphify-only baseline, never guessed.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any

from knowledge_builder.models.symbol import Symbol
from knowledge_builder.parser.db.walk import read_text
from knowledge_builder.parser.symbols import python_ast, treesitter_provider
from knowledge_builder.parser.symbols.python_ast import DefInfo

#: A provider parses source text into definition records.
Provider = Callable[[str, str], list[DefInfo]]

#: Baseline kind for a node that stands for a whole file rather than a definition.
#: These are never enriched — see :func:`_is_definition_site`.
FILE_KIND = "file"


def _provider_for(source_file: str) -> Provider | None:
    """Pick the extraction provider for a file, or ``None`` if unsupported.

    Python uses the standard library ``ast`` (exact and dependency-free); every other
    language goes through the generic tree-sitter provider, whose per-language knowledge
    is declarative data.
    """
    if source_file.endswith(".py"):
        return python_ast.parse_file
    if treesitter_provider.rules_for(source_file) is not None:
        return treesitter_provider.parse_file
    return None


def _is_definition_site(sym: Symbol) -> bool:
    """False for nodes that stand for a whole file rather than a definition in it.

    A file node's name is the file stem (``DocumentService.java`` → ``DocumentService``),
    which in Java — and by convention in Kotlin, C# and TypeScript — is exactly the name
    of the public type declared inside. Matching those by name would enrich the file node
    into a second copy of that class: same ``name``, ``kind`` and ``qualified_name`` as
    the real class node, and promoted out of :data:`~knowledge_builder.models.symbol.
    REFERENCE_KINDS` into retrieval. File nodes are containers; they are never defined
    by a ``class``/``def`` and so are never enriched.
    """
    return sym.kind != FILE_KIND


def enrich_symbols(repo_path: Path, symbols: tuple[Symbol, ...]) -> dict[str, dict[str, Any]]:
    """Return per-symbol field updates keyed by symbol id (only enriched symbols)."""
    root = Path(repo_path)
    by_file: dict[str, list[Symbol]] = defaultdict(list)
    for sym in symbols:
        if not _is_definition_site(sym):
            continue
        if sym.source_file and _provider_for(sym.source_file) is not None:
            by_file[sym.source_file].append(sym)

    updates: dict[str, dict[str, Any]] = {}
    for rel, file_symbols in by_file.items():
        parse = _provider_for(rel)
        if parse is None:
            continue
        text = read_text(root / rel)
        if not text:
            continue
        defs = parse(text, rel)
        if not defs:
            continue
        by_name: dict[str, list[DefInfo]] = defaultdict(list)
        for d in defs:
            by_name[d.name].append(d)
        for sym in file_symbols:
            match = _match(sym, defs, by_name)
            if match is not None:
                updates[sym.id] = _to_update(match)
    return updates


def _match(sym: Symbol, defs: list[DefInfo], by_name: dict[str, list[DefInfo]]) -> DefInfo | None:
    candidates = by_name.get(sym.name) or []
    if len(candidates) == 1:
        return candidates[0]
    line = sym.start_line
    if line is None:
        # No line to disambiguate by; only an unambiguous name match is trustworthy.
        return None
    if candidates:
        # Same name defined more than once (overloads, nested scopes) — closest wins.
        return min(candidates, key=lambda d: abs(d.start_line - line))
    # No name match at all: only accept a definition starting on exactly this line.
    # Falling back to the nearest def would mis-attribute file nodes to stray functions.
    return next((d for d in defs if d.start_line == line), None)


def _to_update(d: DefInfo) -> dict[str, Any]:
    return {
        "name": d.name,
        "kind": d.kind,
        "qualified_name": d.qualified_name,
        "signature": d.signature,
        "docstring": d.docstring,
        "start_line": d.start_line,  # authoritative def line (join key)
        "end_line": d.end_line,
        "start_col": d.start_col,
        "end_col": d.end_col,
        "decorators": d.decorators,
        "is_async": d.is_async,
        "is_static": d.is_static,
        "is_abstract": d.is_abstract,
        "visibility": d.visibility,
    }
