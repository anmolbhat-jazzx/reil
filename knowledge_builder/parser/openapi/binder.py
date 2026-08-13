"""Bind OpenAPI operations to the symbols that implement them.

The spec says *what* the contract is; the symbol table says *where* it lives. Binding the
two is what lets a consumer walk endpoint → handler → call sites. Three deterministic
strategies, strongest first:

1. **Route decorator/annotation** — the handler declares the path itself
   (``@app.get("/documents/{id}")``, ``@GetMapping("/documents/{id}")``). Matching on the
   normalized path (and method when present) is the most reliable signal.
2. **operationId** — matches a symbol ``name`` or ``qualified_name`` exactly.
3. **Path-derived name** — ``GET /documents/{id}`` → ``get_documents_id`` style, compared
   against the symbol name.

Anything unmatched is left unbound rather than guessed.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from knowledge_builder.models.symbol import Symbol
from knowledge_builder.parser.openapi.spec import HTTP_METHODS, Operation

#: The *first positional* argument of a decorator call — the route path when present.
#: Anchored at the opening paren so keyword strings (``summary="List collections"``,
#: ``response_description=…``) can never be mistaken for the path.
_FIRST_POSITIONAL = re.compile(r"""\(\s*[rbuf]*["']([^"']*)["']""")
_PARAM = re.compile(r"[{<:][^}>/]*[}>]?")
#: Leading receiver of a decorator call, e.g. ``ontology_router`` in ``ontology_router.get(…)``.
_RECEIVER = re.compile(r"^@?([A-Za-z_]\w*)\s*\.")


def bind(
    operations: list[Operation],
    symbols: tuple[Symbol, ...],
    mounts: dict[tuple[str, str], tuple[str, ...]] | None = None,
) -> dict[tuple[str, str], str]:
    """Map ``(method, path)`` → symbol id for every operation that resolves.

    Two passes. The first binds what is unambiguous on its own. Those results reveal each
    router file's mount prefix (spec path minus declared path), and the second pass uses
    that prefix to resolve the rest — which is what rescues the many handlers declaring
    only ``@router.get("/{id}")``, identical across routers until you know the prefix.
    """
    routes = _route_multi(symbols)
    # A route binds directly only when exactly one handler declares it; the ambiguous
    # ones stay in ``routes`` so later strategies can still disambiguate them.
    by_route = {key: ids[0] for key, ids in routes.items() if len(set(ids)) == 1}
    declared = _declared_routes(symbols)
    files_by_symbol = {s.id: s.source_file or "" for s in symbols}
    by_name: dict[str, str] = {}
    for sym in symbols:
        by_name.setdefault(sym.name.lower(), sym.id)
        if sym.qualified_name:
            by_name.setdefault(sym.qualified_name.lower(), sym.id)

    bound: dict[tuple[str, str], str] = {}
    for op in operations:
        key = (op.method, op.path)
        normalized = normalize_path(op.path)
        symbol_id = (
            by_route.get((op.method, normalized))
            or by_route.get(("", normalized))
            or _match_by_suffix(routes, op.method, normalized, files_by_symbol)
            or (by_name.get(op.operation_id.lower()) if op.operation_id else None)
            or _match_by_operation_prefix(by_name, op)
            or by_name.get(_derived_name(op))
        )
        if symbol_id:
            bound[key] = symbol_id

    # Mount-site and inferred prefixes are both *candidates*, never overrides: either can
    # be wrong for a given router, and a composition that does not hit the target simply
    # loses. Whichever composes to the operation path wins, and only if it is unique.
    prefixes: dict[tuple[str, str], set[tuple[str, ...]]] = defaultdict(set)
    for scope, prefix in _infer_prefixes(operations, bound, declared).items():
        prefixes[scope].add(prefix)
    for scope, prefix in (mounts or {}).items():
        prefixes[scope].add(prefix)
    if prefixes:
        for op in operations:
            key = (op.method, op.path)
            if key in bound:
                continue
            symbol_id = _match_with_prefix(op, declared, prefixes)
            if symbol_id:
                bound[key] = symbol_id
    return bound


@dataclass(frozen=True)
class _Route:
    """A route declared by a handler's decorator/annotation."""

    symbol_id: str
    source_file: str
    #: Receiver of the decorator call (``router``, ``ontology_router``, …). One file
    #: often mounts several routers at different prefixes, so this is part of the key.
    router: str
    method: str
    segments: tuple[str, ...]

    @property
    def scope(self) -> tuple[str, str]:
        return (self.source_file, self.router)


def _declared_routes(symbols: tuple[Symbol, ...]) -> list[_Route]:
    routes: list[_Route] = []
    for sym in symbols:
        for decorator in sym.decorators:
            method, path = _route_of(decorator)
            if path is None:
                continue
            routes.append(
                _Route(
                    symbol_id=sym.id,
                    source_file=sym.source_file or "",
                    router=_receiver(decorator),
                    method=method,
                    segments=_segments(normalize_path(path)),
                )
            )
    return routes


def _receiver(decorator: str) -> str:
    """``ontology_router.get("/x")`` → ``ontology_router``; ``GetMapping(…)`` → ``""``."""
    match = _RECEIVER.match(decorator.strip())
    return match.group(1) if match else ""


def _infer_prefixes(
    operations: list[Operation],
    bound: dict[tuple[str, str], str],
    declared: list[_Route],
) -> dict[tuple[str, str], tuple[str, ...]]:
    """Learn each router's mount prefix from the bindings already established.

    Keyed by ``(file, router variable)``: a single module frequently defines several
    routers mounted at different prefixes (``router`` and ``ontology_router`` side by
    side), and collapsing them to the file would make every prefix look ambiguous.
    """
    routes_by_symbol: dict[str, list[_Route]] = defaultdict(list)
    for route in declared:
        routes_by_symbol[route.symbol_id].append(route)

    candidates: dict[tuple[str, str], set[tuple[str, ...]]] = defaultdict(set)
    ops_by_key = {(op.method, op.path): op for op in operations}
    for key, symbol_id in bound.items():
        op = ops_by_key.get(key)
        if op is None:
            continue
        full = _segments(normalize_path(op.path))
        for route in routes_by_symbol.get(symbol_id, []):
            tail = len(route.segments)
            if tail and full[len(full) - tail :] == route.segments:
                candidates[route.scope].add(full[: len(full) - tail])
            elif not tail:
                candidates[route.scope].add(full)
    # Only trust a router whose bindings all agree on one prefix.
    return {scope: next(iter(v)) for scope, v in candidates.items() if len(v) == 1}


def _match_with_prefix(
    op: Operation,
    declared: list[_Route],
    prefixes: dict[tuple[str, str], set[tuple[str, ...]]],
) -> str | None:
    """Resolve an operation by composing a router's known prefixes with a declared route.

    A scope may carry more than one candidate prefix (one inferred, one read from the
    mount site). Each is tried; a candidate that does not reconstruct the operation path
    simply does not match, so a wrong prefix costs nothing.
    """
    target = _segments(normalize_path(op.path))
    matches = [
        route.symbol_id
        for route in declared
        if route.method in ("", op.method)
        for prefix in prefixes.get(route.scope, ())
        if prefix + route.segments == target
    ]
    return matches[0] if len(set(matches)) == 1 else None


def _segments(normalized: str) -> tuple[str, ...]:
    return tuple(p for p in normalized.split("/") if p)


def _match_by_suffix(
    routes: dict[tuple[str, str], list[str]],
    method: str,
    normalized: str,
    files: dict[str, str] | None = None,
) -> str | None:
    """Match a decorator path that omits its router's mount prefix.

    A handler usually declares only its own segment (``@router.get("/{id}")``) while the
    spec carries the fully-mounted path (``/api/v1/collections/{id}``). Matching the
    declared route as a *suffix* of the spec path bridges the two. Only an unambiguous,
    segment-aligned match binds.
    """
    matched = [
        (len(_segments(route_path)), symbol_id)
        for (route_method, route_path), symbol_ids in routes.items()
        if route_method in ("", method) and _is_path_suffix(normalized, route_path)
        for symbol_id in symbol_ids
    ]
    if not matched:
        return None
    # Most-specific route wins: ``/by-name/{}`` beats a bare ``/{}`` that also matches,
    # exactly as a router resolves overlapping patterns.
    longest = max(length for length, _ in matched)
    candidates = [symbol_id for length, symbol_id in matched if length == longest]
    unique = set(candidates)
    if len(unique) == 1:
        return candidates[0]
    if unique and files is not None:
        # Several routers declare the same tail (``/minimal`` under both /v1 and /v2).
        # Break the tie only when one candidate's file clearly echoes the spec path.
        return _best_by_path_affinity(unique, normalized, files)
    return None


def _best_by_path_affinity(
    candidates: set[str], normalized: str, files: dict[str, str]
) -> str | None:
    """Pick the candidate whose source path shares the most segments with the route.

    ``/api/v2/reasoning/entities`` belongs to ``app/router/api_v2/...`` rather than
    ``app/reasoning/api.py``. Only a strict single winner is accepted.
    """
    wanted = {seg for seg in _segments(normalized) if seg and seg != "{}"}
    if not wanted:
        return None
    scored: list[tuple[int, str]] = []
    for symbol_id in candidates:
        tokens = _file_tokens(files.get(symbol_id, ""))
        scored.append((sum(1 for w in wanted if w in tokens), symbol_id))
    scored.sort(reverse=True)
    if len(scored) < 2 or scored[0][0] == 0 or scored[0][0] == scored[1][0]:
        return None
    return scored[0][1]


def _file_tokens(source_file: str) -> set[str]:
    """Path split into comparable tokens: ``app/router/api_v2/x.py`` → {app, router, api, v2, x}."""
    cleaned = re.split(r"[/_.\-]+", source_file.lower())
    return {token for token in cleaned if token and token != "py"}


def _is_path_suffix(full: str, candidate: str) -> bool:
    """True when ``candidate`` is a trailing whole-segment slice of ``full``."""
    if candidate in ("", "/"):
        return False
    full_parts = [p for p in full.split("/") if p]
    cand_parts = [p for p in candidate.split("/") if p]
    return bool(cand_parts) and full_parts[-len(cand_parts) :] == cand_parts


def _match_by_operation_prefix(by_name: dict[str, str], op: Operation) -> str | None:
    """FastAPI auto-generates ``<function>_<path>_<method>`` operation ids."""
    if not op.operation_id:
        return None
    lowered = op.operation_id.lower()
    matches = [
        symbol_id
        for name, symbol_id in by_name.items()
        if name and "." not in name and lowered.startswith(f"{name}_")
    ]
    return matches[0] if len(set(matches)) == 1 else None


def _route_multi(symbols: tuple[Symbol, ...]) -> dict[tuple[str, str], list[str]]:
    """Map each declared ``(method, path)`` to every symbol declaring it.

    Kept as a multi-map rather than deduped up front: a route claimed by two handlers
    (the same tail under ``/v1`` and ``/v2``) cannot bind directly, but is still the
    input a later disambiguating strategy needs.
    """
    grouped: dict[tuple[str, str], list[str]] = defaultdict(list)
    for sym in symbols:
        for decorator in sym.decorators:
            method, path = _route_of(decorator)
            if path is None:
                continue
            grouped[(method, normalize_path(path))].append(sym.id)
    return grouped


def _route_of(decorator: str) -> tuple[str, str | None]:
    """Extract ``(method, path)`` from a route decorator/annotation, if it is one."""
    lowered = decorator.lower()
    method = ""
    for verb in HTTP_METHODS:
        # FastAPI/Flask ``@app.get(...)`` and Spring ``@GetMapping(...)``.
        if f".{verb}(" in lowered or lowered.startswith(f"{verb}mapping"):
            method = verb.upper()
            break

    positional = _FIRST_POSITIONAL.search(decorator)
    if positional is None:
        # ``@router.get()`` / ``@router.get(response_model=X)`` — no path given, so the
        # route *is* the router's mount point; the prefix pass resolves it.
        return (method, "/") if method else ("", None)
    path = positional.group(1)
    if path == "":
        # ``@router.get("", response_model=X)`` — the collection-root case.
        return (method, "/") if method else ("", None)
    if path.startswith("/"):
        return method, path
    return "", None  # a positional string that is not a path: not a route decorator


def normalize_path(path: str) -> str:
    """Strip parameter names so ``/docs/{id}`` and ``/docs/<doc_id>`` compare equal."""
    collapsed = _PARAM.sub("{}", path)
    return "/" + collapsed.strip("/").lower()


def _derived_name(op: Operation) -> str:
    """``GET /documents/{id}`` → ``get_documents_id``."""
    parts = [op.method.lower()]
    for segment in op.path.strip("/").split("/"):
        cleaned = re.sub(r"[^a-z0-9]+", "_", segment.lower()).strip("_")
        if cleaned:
            parts.append(cleaned)
    return "_".join(parts)
