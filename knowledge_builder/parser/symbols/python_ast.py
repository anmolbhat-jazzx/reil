"""Python symbol enrichment via the standard-library ``ast`` (static, exact, no deps).

Parses a Python source file into definition records — functions, methods, classes — each
carrying the fields graphify cannot provide: ``kind``, ``qualified_name``, ``signature``,
``docstring``, exact ``start_line``/``end_line`` (+ columns), decorators, and the
``async``/``static``/``abstract`` flags. ``start_line`` is the line of the ``def``/``class``
keyword (decorators excluded) — the identity/join convention.

This is one provider behind :mod:`knowledge_builder.parser.symbols`; tree-sitter providers
for other languages plug in the same way, and unparsed languages simply keep their
graphify-only baseline.
"""

from __future__ import annotations

import ast
import warnings
from dataclasses import dataclass
from pathlib import PurePosixPath


@dataclass(frozen=True)
class DefInfo:
    """A single definition extracted from Python source."""

    name: str
    kind: str  # function | method | class
    qualified_name: str
    start_line: int
    end_line: int | None
    start_col: int | None
    end_col: int | None
    signature: str | None
    docstring: str | None
    decorators: tuple[str, ...] = ()
    is_async: bool = False
    is_static: bool = False
    is_abstract: bool = False
    visibility: str = "public"


def parse_file(source: str, source_file: str) -> list[DefInfo]:
    """Parse Python ``source`` into definition records, or ``[]`` if it does not parse."""
    try:
        # Reading someone else's source must stay silent: a stray ``\L`` escape in a
        # docstring or regex is their lint problem, not something to print mid-build.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return []
    module = module_qualname(source_file)
    out: list[DefInfo] = []
    _collect(tree, scope=[module] if module else [], parent_is_class=False, out=out)
    return out


def _collect(node: ast.AST, scope: list[str], parent_is_class: bool, out: list[DefInfo]) -> None:
    for child in getattr(node, "body", []):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            is_class = isinstance(child, ast.ClassDef)
            kind = "class" if is_class else ("method" if parent_is_class else "function")
            qualified = ".".join([*scope, child.name])
            out.append(_build(child, kind, qualified))
            _collect(child, [*scope, child.name], is_class, out)


_DefNode = ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef


def _build(node: _DefNode, kind: str, qualified_name: str) -> DefInfo:
    decorators = tuple(_unparse(d) for d in node.decorator_list)
    lowered = {d.lower() for d in decorators}
    return DefInfo(
        name=node.name,
        kind=kind,
        qualified_name=qualified_name,
        start_line=node.lineno,  # the def/class line (decorators sit above, excluded)
        end_line=node.end_lineno,
        start_col=node.col_offset,
        end_col=node.end_col_offset,
        signature=_signature(node, kind),
        docstring=ast.get_docstring(node),
        decorators=decorators,
        is_async=isinstance(node, ast.AsyncFunctionDef),
        is_static=any("staticmethod" in d or "classmethod" in d for d in lowered),
        is_abstract=any("abstract" in d for d in lowered),
        visibility=_visibility(node.name),
    )


def _signature(node: _DefNode, kind: str) -> str | None:
    if kind == "class":
        bases = [_unparse(b) for b in getattr(node, "bases", [])]
        return f"({', '.join(bases)})" if bases else None
    args = getattr(node, "args", None)
    if args is None:
        return None
    rendered = _unparse(args)
    returns = getattr(node, "returns", None)
    suffix = f" -> {_unparse(returns)}" if returns is not None else ""
    return f"({rendered}){suffix}"


def _visibility(name: str) -> str:
    if name.startswith("__") and name.endswith("__"):
        return "public"  # dunder
    if name.startswith("__"):
        return "private"
    if name.startswith("_"):
        return "protected"
    return "public"


def module_qualname(source_file: str) -> str:
    """Dotted module path for a source file — the prefix of every qualified name in it.

    Public because the call provider must build caller qualified names that join against
    the ones recorded here; two spellings of the same convention would silently fail.
    """
    path = PurePosixPath(source_file)
    parts = list(path.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _unparse(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except Exception:  # noqa: BLE001 - unparse is best-effort for display
        return ""
