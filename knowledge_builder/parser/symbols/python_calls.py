"""Python call-site extraction with local receiver-type inference.

graphify resolves ``self.method()`` and bare-name calls well, but not calls through a
local variable — ``svc = get_service(); svc.handle()`` yields no edge, because nothing in
the syntax of the call site says what ``svc`` is. On a real service codebase that single
gap is ~80% of the missing call edges, and the ones it hides are exactly the
service-to-service calls impact analysis is asked about.

This provider closes the part of that gap the source *states outright*. It never guesses
a type: a receiver is typed only by an annotation, a constructor call, or the declared
return type of the function that produced it. What stays untyped stays unresolved, and
emits nothing — a missing edge is recoverable, a wrong one silently corrupts reachability.

Inference is deliberately intraprocedural and assignment-order-independent (a single pass
collecting every binding in the function). That makes it O(size of function) with no
fixpoint, and wrong only in the rare case of a variable rebound to a *different* class
mid-function, where it reports the last binding seen rather than the one in scope.
"""

from __future__ import annotations

import ast
import warnings
from dataclasses import dataclass, field

from knowledge_builder.parser.symbols.python_ast import module_qualname

#: Receiver expression for a call on the enclosing instance (``self.foo()``).
SELF = "self"


@dataclass(frozen=True)
class CallSite:
    """One call, with the receiver's class resolved as far as local syntax allows."""

    #: Qualified name of the enclosing definition — joins against ``Symbol.qualified_name``.
    caller: str
    #: The name being called (``handle`` in ``svc.handle()``).
    callee: str
    #: Class name of the receiver, or ``None`` for a bare ``callee()`` call.
    receiver_type: str | None
    line: int


@dataclass(frozen=True)
class TypeIndex:
    """Repo-wide type facts the per-file pass needs, built once from the symbol table.

    Both maps are keyed by bare name because that is all a call site gives us; a name
    bound to more than one class is dropped rather than guessed at (see
    :meth:`is_class`), so ambiguity costs recall and never precision.
    """

    #: Class names defined anywhere in the repository.
    class_names: frozenset[str] = frozenset()
    #: Function/method name -> its declared return type, when that type is a known class.
    return_types: dict[str, str] = field(default_factory=dict)

    def is_class(self, name: str | None) -> bool:
        return bool(name) and name in self.class_names


def parse_calls(source: str, source_file: str, types: TypeIndex) -> list[CallSite]:
    """Extract call sites from Python ``source``, or ``[]`` if it does not parse."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return []
    module = module_qualname(source_file)
    attrs = _self_attribute_types(tree, types)
    out: list[CallSite] = []
    _walk(
        tree,
        scope=[module] if module else [],
        enclosing_class=None,
        types=types,
        attrs=attrs,
        out=out,
    )
    return out


def _walk(
    node: ast.AST,
    scope: list[str],
    enclosing_class: str | None,
    types: TypeIndex,
    attrs: dict[str, dict[str, str]],
    out: list[CallSite],
) -> None:
    for child in getattr(node, "body", []):
        if isinstance(child, ast.ClassDef):
            _walk(child, [*scope, child.name], child.name, types, attrs, out)
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            qualified = ".".join([*scope, child.name])
            local = _local_types(child, enclosing_class, types)
            _emit(child, qualified, enclosing_class, local, attrs, out)
            # Nested defs get their own scope and their own local type environment.
            _walk(child, [*scope, child.name], None, types, attrs, out)


def _emit(
    fn: ast.AST,
    caller: str,
    enclosing_class: str | None,
    local: dict[str, str],
    attrs: dict[str, dict[str, str]],
    out: list[CallSite],
) -> None:
    """Record every call in ``fn``'s body, skipping calls inside nested definitions."""
    for node in _body_nodes(fn):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            out.append(CallSite(caller, func.id, None, node.lineno))
        elif isinstance(func, ast.Attribute):
            receiver = _receiver_type(func.value, enclosing_class, local, attrs)
            out.append(CallSite(caller, func.attr, receiver, node.lineno))


def _body_nodes(fn: ast.AST) -> list[ast.AST]:
    """Every node under ``fn`` except those belonging to a nested definition.

    A call inside a nested ``def`` is that function's call, not this one's — attributing
    it here would invent edges from the outer function to everything its closures touch.
    """
    out: list[ast.AST] = []
    stack: list[ast.AST] = list(ast.iter_child_nodes(fn))
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        out.append(node)
        stack.extend(ast.iter_child_nodes(node))
    return out


def _receiver_type(
    receiver: ast.expr,
    enclosing_class: str | None,
    local: dict[str, str],
    attrs: dict[str, dict[str, str]],
) -> str | None:
    """Class of the receiver expression, or ``None`` when the source does not say."""
    if isinstance(receiver, ast.Name):
        if receiver.id == SELF:
            return enclosing_class
        return local.get(receiver.id)
    # ``self.repo.save()`` — the attribute's type comes from the class's own bindings.
    if (
        isinstance(receiver, ast.Attribute)
        and isinstance(receiver.value, ast.Name)
        and receiver.value.id == SELF
        and enclosing_class
    ):
        return attrs.get(enclosing_class, {}).get(receiver.attr)
    return None


def _local_types(fn: ast.AST, enclosing_class: str | None, types: TypeIndex) -> dict[str, str]:
    """Local variable -> class name, from types the function states outright."""
    out: dict[str, str] = {}
    args = getattr(fn, "args", None)
    if args is not None:
        for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs]:
            name = _annotation_name(arg.annotation)
            if types.is_class(name):
                out[arg.arg] = name  # type: ignore[assignment]
    for node in _body_nodes(fn):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = _annotation_name(node.annotation)
            if types.is_class(name):
                out[node.target.id] = name  # type: ignore[assignment]
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                bound = _value_type(node.value, types)
                if bound:
                    out[target.id] = bound
    return out


def _value_type(value: ast.expr, types: TypeIndex) -> str | None:
    """Class produced by an expression: ``Foo()`` directly, or ``f()`` via its return type."""
    if isinstance(value, ast.Await):
        value = value.value
    if not isinstance(value, ast.Call):
        return None
    func = value.func
    name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
    if name is None:
        return None
    if types.is_class(name):
        return name
    declared = types.return_types.get(name)
    return declared if types.is_class(declared) else None


def _self_attribute_types(tree: ast.AST, types: TypeIndex) -> dict[str, dict[str, str]]:
    """Per class, ``self.<attr>`` -> class name, from annotations and ``__init__`` bindings.

    This is the Python stand-in for a typed field declaration — the construct that makes
    the same call shape resolvable in Java without any inference at all.
    """
    out: dict[str, dict[str, str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        bound: dict[str, str] = {}
        for item in node.body:
            if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                name = _annotation_name(item.annotation)
                if types.is_class(name):
                    bound[item.target.id] = name  # type: ignore[assignment]
            elif isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if item.name == "__init__":
                    bound.update(_init_attribute_types(item, types))
        if bound:
            out[node.name] = bound
    return out


def _init_attribute_types(init: ast.AST, types: TypeIndex) -> dict[str, str]:
    """``self.x = <typed param | Ctor() | f()>`` bindings inside ``__init__``."""
    args = getattr(init, "args", None)
    params: dict[str, str] = {}
    if args is not None:
        for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs]:
            name = _annotation_name(arg.annotation)
            if types.is_class(name):
                params[arg.arg] = name  # type: ignore[assignment]
    out: dict[str, str] = {}
    for node in ast.walk(init):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not (
            isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Name)
            and target.value.id == SELF
        ):
            continue
        value = node.value
        if isinstance(value, ast.Name) and value.id in params:
            out[target.attr] = params[value.id]
        else:
            bound = _value_type(value, types)
            if bound:
                out[target.attr] = bound
    return out


def _annotation_name(node: ast.expr | None) -> str | None:
    """Bare class name inside an annotation, unwrapping the usual generic wrappers.

    ``Optional[Repo]``, ``Awaitable[Repo]``, ``Repo | None`` and ``"Repo"`` all name
    ``Repo`` for our purposes: the receiver of a method call is the element type, never
    the container. Only the *first* type argument is followed, which is right for the
    single-argument wrappers above and harmless for the rest (a ``dict[str, Repo]`` is
    not a ``Repo``, and yields ``str``, which is not a repo class and so is dropped).
    """
    if node is None:
        return None
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value  # forward reference: "Repo"
    if isinstance(node, ast.Subscript):
        inner = node.slice
        if isinstance(inner, ast.Tuple):
            return _annotation_name(inner.elts[0]) if inner.elts else None
        return _annotation_name(inner)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _annotation_name(node.left) or _annotation_name(node.right)
    return None
