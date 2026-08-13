"""Router mount discovery — where a router is attached, and under what prefix.

A handler's decorator only gives the path *relative* to its router
(``@router.get("/{config_id}")``). The prefix lives at the **mount site**, usually in a
different file::

    # app/configuration/api.py
    router = APIRouter()

    # app/router/api_v1/endpoints.py
    api_v1.include_router(config_router, prefix="/global-config")

    # app/main.py
    app.include_router(api_v1, prefix="/api/v1")

Nothing in the handler's own file mentions ``global-config``, so decorator analysis alone
can never recover it. This resolves the mount graph statically — following import
aliases across files and composing nested prefixes — so every router's full prefix is
known before binding.

Python (stdlib ``ast``) today. The same shape applies elsewhere — Spring's class-level
``@RequestMapping``, Express's ``app.use("/prefix", router)`` — and plugs in the same way.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from knowledge_builder.parser.db.walk import iter_files, read_text

#: Constructor names that create a mountable router.
_ROUTER_FACTORIES = frozenset({"APIRouter", "Router", "Blueprint"})
#: Method that mounts one router inside another.
_INCLUDE = "include_router"

#: A router node: the file its variable is defined in, and that variable's name.
Node = tuple[str, str]


@dataclass
class _FileInfo:
    rel: str
    #: local alias -> (dotted module, original name)
    imports: dict[str, tuple[str, str]] = field(default_factory=dict)
    #: router variable -> prefix declared on its constructor
    routers: dict[str, tuple[str, ...]] = field(default_factory=dict)
    #: (parent variable, child expression name, prefix given at the mount site)
    includes: list[tuple[str, str, tuple[str, ...]]] = field(default_factory=list)


def discover_mounts(repo_path: Path) -> dict[Node, tuple[str, ...]]:
    """Return each router's fully-composed mount prefix, keyed by ``(file, variable)``."""
    files: dict[str, _FileInfo] = {}
    for entry in iter_files(Path(repo_path)):
        if not entry.rel.endswith(".py"):
            continue
        text = read_text(entry.path)
        if text is None or _INCLUDE not in text and "Router(" not in text:
            continue
        info = _parse_file(text, entry.rel)
        if info is not None:
            files[entry.rel] = info
    if not files:
        return {}
    return _resolve(files)


def _parse_file(source: str, rel: str) -> _FileInfo | None:
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None
    info = _FileInfo(rel=rel)

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = _absolute_module(node, rel)
            if module:
                for alias in node.names:
                    info.imports[alias.asname or alias.name] = (module, alias.name)
        elif isinstance(node, ast.Assign):
            _collect_router_def(node, info)
        elif isinstance(node, ast.Call):
            _collect_include(node, info)
    return info


def _collect_router_def(node: ast.Assign, info: _FileInfo) -> None:
    """``router = APIRouter(prefix="/x")`` → the variable carries its own prefix."""
    if not isinstance(node.value, ast.Call):
        return
    name = _callee_name(node.value.func)
    if name not in _ROUTER_FACTORIES:
        return
    prefix = _segments(_keyword_str(node.value, "prefix") or "")
    for target in node.targets:
        if isinstance(target, ast.Name):
            info.routers[target.id] = prefix


def _collect_include(node: ast.Call, info: _FileInfo) -> None:
    """``app.include_router(child, prefix="/api/v1")`` → an edge parent → child."""
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr != _INCLUDE:
        return
    parent = func.value.id if isinstance(func.value, ast.Name) else ""
    if not node.args:
        return
    child = _expr_name(node.args[0])
    if not child:
        return
    info.includes.append((parent, child, _segments(_keyword_str(node, "prefix") or "")))


def _resolve(files: dict[str, _FileInfo]) -> dict[Node, tuple[str, ...]]:
    """Compose prefixes down the mount graph, from unmounted roots inward."""
    own: dict[Node, tuple[str, ...]] = {}
    for info in files.values():
        for var, prefix in info.routers.items():
            own[(info.rel, var)] = prefix

    edges: list[tuple[Node, Node, tuple[str, ...]]] = []
    children: set[Node] = set()
    for info in files.values():
        for parent_var, child_var, prefix in info.includes:
            parent = _node_for(parent_var, info, files)
            child = _node_for(child_var, info, files)
            if child is None:
                continue
            # An unresolvable parent (typically ``app = FastAPI()``) is a mount root.
            edges.append((parent or (info.rel, parent_var), child, prefix))
            children.add(child)
            own.setdefault(child, ())

    full: dict[Node, tuple[str, ...]] = {}
    for parent, _child, _prefix in edges:
        if parent not in children:
            full[parent] = own.get(parent, ())

    # Relax until stable; the graph is tiny and acyclic in practice, and the bound
    # stops a pathological cycle from looping forever.
    for _ in range(len(edges) + 1):
        changed = False
        for parent, child, prefix in edges:
            base = full.get(parent)
            if base is None:
                continue
            composed = base + prefix + own.get(child, ())
            if full.get(child) != composed:
                full[child] = composed
                changed = True
        if not changed:
            break

    # A router never mounted anywhere still contributes its own constructor prefix.
    for node, prefix in own.items():
        full.setdefault(node, prefix)
    # Empty prefixes are kept: a router mounted at the root (``@app.get("/")``) needs an
    # explicit "no prefix" entry to compose against, and dropping it loses those routes.
    return full


def _node_for(name: str, info: _FileInfo, files: dict[str, _FileInfo]) -> Node | None:
    """Resolve a router reference to the file that defines it, following import aliases.

    Handles both ``include_router(router)`` after ``from x.y import router`` and the
    module-qualified ``include_router(y.router)`` after ``from x import y``.
    """
    if "." in name:
        head, _, attribute = name.rpartition(".")
        imported = info.imports.get(head)
        if imported is not None:
            module, original = imported
            # ``from app.configuration import api`` → module ``app.configuration.api``.
            target = _module_file(f"{module}.{original}", files)
            if target is not None:
                return (target, attribute)
        return None
    imported = info.imports.get(name)
    if imported is not None:
        module, original = imported
        target = _module_file(module, files)
        if target is not None:
            return (target, original)
        return None
    if name in info.routers:
        return (info.rel, name)
    return None


def _module_file(module: str, files: dict[str, _FileInfo]) -> str | None:
    base = module.replace(".", "/")
    for candidate in (f"{base}.py", f"{base}/__init__.py"):
        if candidate in files:
            return candidate
    return None


def _absolute_module(node: ast.ImportFrom, rel: str) -> str:
    """Resolve a relative import (``from .api import router``) against the current file."""
    if not node.level:
        return node.module or ""
    parts = list(PurePosixPath(rel).parent.parts)
    if node.level > 1:
        parts = parts[: -(node.level - 1)] or []
    return ".".join([*parts, node.module]) if node.module else ".".join(parts)


def _expr_name(node: ast.expr) -> str:
    """``router`` → ``router``; ``api.router`` → ``api.router`` (dotted, for resolution)."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _expr_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def _callee_name(func: ast.expr) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _keyword_str(call: ast.Call, name: str) -> str | None:
    for kw in call.keywords:
        value = kw.value
        if kw.arg == name and isinstance(value, ast.Constant) and isinstance(value.value, str):
            return value.value
    return None


def _segments(path: str) -> tuple[str, ...]:
    return tuple(p for p in path.strip("/").lower().split("/") if p)
