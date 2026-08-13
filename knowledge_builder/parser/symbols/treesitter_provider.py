"""Language-agnostic symbol enrichment via tree-sitter.

One engine, many languages: the traversal, name/……/flag extraction, and the
decorator-excluded ``start_line`` convention are entirely generic. Everything
language-specific lives in :data:`LANGUAGE_RULES` as *data* — which grammar node types
are definitions, what our ``kind`` for each is, how a doc comment attaches, and which
keywords express modifiers. Adding a language is one registry row; the engine never
changes.

If the ``tree-sitter`` runtime or a grammar is unavailable, the provider yields nothing
and symbols keep their graphify-only baseline — never guessed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from knowledge_builder.parser.symbols.python_ast import DefInfo

#: Doc comment attaches as a comment node immediately *above* the definition.
DOC_PRECEDING = "preceding_comment"

#: Node types that never count as the "declaration start" (annotations/modifiers sit here),
#: so ``start_line`` lands on the real ``class``/``def``/type keyword line.
_MODIFIER_NODES = frozenset({"modifiers", "decorator", "annotation", "marker_annotation"})


@dataclass(frozen=True)
class LanguageRules:
    """Declarative description of one language's definition syntax."""

    language: str
    extensions: tuple[str, ...]
    #: grammar node type -> our canonical kind.
    kinds: dict[str, str]
    #: Node types that hold the parameter list.
    params_types: tuple[str, ...] = ("formal_parameters", "parameters", "parameter_list")
    #: Comment node types that can carry documentation.
    comment_types: tuple[str, ...] = ("block_comment", "comment", "line_comment")
    #: A comment is documentation only if it starts with one of these.
    doc_prefixes: tuple[str, ...] = ("/**", "///")
    doc_style: str = DOC_PRECEDING
    #: Node types representing an annotation/decorator (collected into ``decorators``).
    annotation_types: tuple[str, ...] = ("marker_annotation", "annotation", "decorator")
    #: Node type holding the package/namespace declaration (for qualified names).
    package_node: str | None = None
    #: Kinds whose names nest into a child's qualified name.
    container_kinds: tuple[str, ...] = ("class", "interface", "enum", "struct")


#: The language registry — add a row to support a new language.
LANGUAGE_RULES: tuple[LanguageRules, ...] = (
    LanguageRules(
        language="java",
        extensions=(".java",),
        kinds={
            "class_declaration": "class",
            "interface_declaration": "interface",
            "enum_declaration": "enum",
            "record_declaration": "class",
            "method_declaration": "method",
            "constructor_declaration": "method",
        },
        package_node="package_declaration",
    ),
    LanguageRules(
        language="kotlin",
        extensions=(".kt", ".kts"),
        kinds={"class_declaration": "class", "function_declaration": "function"},
        package_node="package_header",
    ),
    LanguageRules(
        language="go",
        extensions=(".go",),
        kinds={
            "function_declaration": "function",
            "method_declaration": "method",
            "type_declaration": "type",
        },
        comment_types=("comment",),
        doc_prefixes=("//",),
    ),
    LanguageRules(
        language="typescript",
        extensions=(".ts",),
        kinds={
            "class_declaration": "class",
            "interface_declaration": "interface",
            "function_declaration": "function",
            "method_definition": "method",
        },
    ),
    LanguageRules(
        language="tsx",
        extensions=(".tsx",),
        kinds={
            "class_declaration": "class",
            "function_declaration": "function",
            "method_definition": "method",
        },
    ),
    LanguageRules(
        language="javascript",
        extensions=(".js", ".jsx", ".mjs"),
        kinds={
            "class_declaration": "class",
            "function_declaration": "function",
            "method_definition": "method",
        },
    ),
    LanguageRules(
        language="ruby",
        extensions=(".rb",),
        kinds={"class": "class", "module": "module", "method": "method"},
        comment_types=("comment",),
        doc_prefixes=("#",),
    ),
    LanguageRules(
        language="rust",
        extensions=(".rs",),
        kinds={
            "function_item": "function",
            "struct_item": "struct",
            "trait_item": "interface",
            "impl_item": "impl",
        },
        comment_types=("line_comment", "block_comment"),
        doc_prefixes=("///", "/**", "//!"),
    ),
    LanguageRules(
        language="csharp",
        extensions=(".cs",),
        kinds={
            "class_declaration": "class",
            "interface_declaration": "interface",
            "method_declaration": "method",
            "struct_declaration": "struct",
        },
        package_node="namespace_declaration",
    ),
    LanguageRules(
        language="php",
        extensions=(".php",),
        kinds={
            "class_declaration": "class",
            "interface_declaration": "interface",
            "method_declaration": "method",
            "function_definition": "function",
        },
        comment_types=("comment",),
    ),
)

_BY_EXTENSION: dict[str, LanguageRules] = {
    ext: rules for rules in LANGUAGE_RULES for ext in rules.extensions
}

_VISIBILITY_KEYWORDS = ("private", "protected", "public")


def rules_for(source_file: str) -> LanguageRules | None:
    """Return the language rules for ``source_file``, or ``None`` if unsupported."""
    return _BY_EXTENSION.get(PurePosixPath(source_file).suffix.lower())


def parse_file(source: str, source_file: str) -> list[DefInfo]:
    """Extract definitions from ``source`` using the matching language rules."""
    rules = rules_for(source_file)
    if rules is None:
        return []
    parser = _parser(rules.language)
    if parser is None:
        return []
    data = source.encode("utf-8", errors="ignore")
    try:
        tree = parser.parse(data)
    except Exception:  # noqa: BLE001 - a grammar failure must not break the build
        return []

    package = _package(tree.root_node, data, rules) or _module_from_path(source_file)
    out: list[DefInfo] = []
    _walk(tree.root_node, data, rules, scope=[package] if package else [], out=out)
    return out


def _walk(
    node: Any, data: bytes, rules: LanguageRules, scope: list[str], out: list[DefInfo]
) -> None:
    for child in node.named_children:
        kind = rules.kinds.get(child.type)
        if kind is None:
            _walk(child, data, rules, scope, out)
            continue
        name = _name(child, data)
        qualified = ".".join([*scope, name]) if name else ".".join(scope)
        out.append(_build(child, data, rules, kind, name, qualified))
        inner = [*scope, name] if (name and kind in rules.container_kinds) else scope
        _walk(child, data, rules, inner, out)


def _build(
    node: Any, data: bytes, rules: LanguageRules, kind: str, name: str, qualified: str
) -> DefInfo:
    modifier_text = _modifier_text(node, data)
    lowered = modifier_text.lower()
    decorators = tuple(
        _text(n, data).lstrip("@").strip()
        for n in node.children
        if n.type in rules.annotation_types
    ) or tuple(
        _text(n, data).lstrip("@").strip()
        for m in node.children
        if m.type == "modifiers"
        for n in m.children
        if n.type in rules.annotation_types
    )
    return DefInfo(
        name=name,
        kind=_refine_kind(kind, node, rules),
        qualified_name=qualified,
        # Declaration line with annotations/modifiers excluded — the join convention.
        start_line=_declaration_line(node),
        end_line=node.end_point[0] + 1,
        start_col=node.start_point[1],
        end_col=node.end_point[1],
        signature=_signature(node, data, rules),
        docstring=_docstring(node, data, rules),
        decorators=decorators,
        is_async="async" in lowered,
        is_static="static" in lowered,
        is_abstract="abstract" in lowered,
        visibility=_visibility(lowered, name),
    )


def _declaration_line(node: Any) -> int:
    """Line of the real declaration keyword, skipping leading modifiers/annotations."""
    for child in node.children:
        if child.type not in _MODIFIER_NODES:
            return int(child.start_point[0]) + 1
    return int(node.start_point[0]) + 1


def _refine_kind(kind: str, node: Any, rules: LanguageRules) -> str:
    """A function nested inside a class body is really a method."""
    if kind != "function":
        return kind
    parent = node.parent
    while parent is not None:
        if rules.kinds.get(parent.type) in rules.container_kinds:
            return "method"
        parent = parent.parent
    return kind


def _name(node: Any, data: bytes) -> str:
    field = node.child_by_field_name("name")
    if field is not None:
        return _text(field, data)
    for child in node.named_children:
        if child.type in ("identifier", "type_identifier", "constant", "property_identifier"):
            return _text(child, data)
    return ""


def _signature(node: Any, data: bytes, rules: LanguageRules) -> str | None:
    params = node.child_by_field_name("parameters")
    if params is None:
        params = next((c for c in node.children if c.type in rules.params_types), None)
    if params is None:
        return None
    rendered = " ".join(_text(params, data).split())
    ret = node.child_by_field_name("type") or node.child_by_field_name("return_type")
    if ret is None:
        return rendered
    # Some grammars include the leading ``:`` of the return annotation.
    returns = " ".join(_text(ret, data).split()).lstrip(":").strip()
    return f"{rendered} -> {returns}" if returns else rendered


def _docstring(node: Any, data: bytes, rules: LanguageRules) -> str | None:
    if rules.doc_style != DOC_PRECEDING:
        return None
    sibling = node.prev_named_sibling
    # A declaration may be wrapped (e.g. `export class …`), which puts the doc comment
    # before the *wrapper*; climb while we are the first child of such a wrapper.
    current = node
    while sibling is None and current.parent is not None:
        parent = current.parent
        # Compare node ids: the bindings hand out fresh wrapper objects each access.
        first = parent.named_children[0] if parent.named_children else None
        if first is not None and first.id != current.id:
            break
        sibling = parent.prev_named_sibling
        current = parent
    # Skip annotations that were parsed as separate siblings.
    while sibling is not None and sibling.type in rules.annotation_types:
        sibling = sibling.prev_named_sibling
    if sibling is None or sibling.type not in rules.comment_types:
        return None
    raw = _text(sibling, data).strip()
    if not raw.startswith(rules.doc_prefixes):
        return None
    return _clean_comment(raw) or None


def _clean_comment(raw: str) -> str:
    body = raw
    if body.startswith("/*"):
        body = body[2:]
        body = body[:-2] if body.endswith("*/") else body
    lines: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        for marker in ("///", "//!", "//", "*", "#"):
            if stripped.startswith(marker):
                stripped = stripped[len(marker) :]
                break
        lines.append(stripped.strip())
    return "\n".join(lines).strip()


def _modifier_text(node: Any, data: bytes) -> str:
    """Text of the modifier region — the modifiers node, else text before the name."""
    modifiers = next((c for c in node.children if c.type == "modifiers"), None)
    if modifiers is not None:
        return _text(modifiers, data)
    name_node = node.child_by_field_name("name")
    if name_node is not None and name_node.start_byte > node.start_byte:
        return data[node.start_byte : name_node.start_byte].decode("utf-8", errors="ignore")
    return ""


def _visibility(modifier_text: str, name: str) -> str:
    for keyword in _VISIBILITY_KEYWORDS:
        if keyword in modifier_text:
            return keyword
    return "private" if name.startswith("_") else "public"


def _package(root: Any, data: bytes, rules: LanguageRules) -> str:
    if rules.package_node is None:
        return ""
    node = next((c for c in root.named_children if c.type == rules.package_node), None)
    if node is None:
        return ""
    text = _text(node, data)
    for token in ("package", "namespace", "{", ";"):
        text = text.replace(token, " ")
    return text.strip()


def _module_from_path(source_file: str) -> str:
    return ".".join(PurePosixPath(source_file).with_suffix("").parts)


def _text(node: Any, data: bytes) -> str:
    return data[node.start_byte : node.end_byte].decode("utf-8", errors="ignore")


_PARSER_CACHE: dict[str, Any] = {}


def _parser(language: str) -> Any | None:
    """Return a cached tree-sitter parser, or ``None`` if unavailable."""
    if language in _PARSER_CACHE:
        return _PARSER_CACHE[language]
    try:
        from tree_sitter_language_pack import get_parser

        parser = get_parser(language)
    except Exception:  # noqa: BLE001 - runtime/grammar missing → graceful skip
        parser = None
    _PARSER_CACHE[language] = parser
    return parser
