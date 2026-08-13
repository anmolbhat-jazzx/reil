"""OpenAPI/Swagger spec discovery and parsing (framework-agnostic contracts).

An OpenAPI document *is* the API contract, so it beats guessing routes from file paths:
method, path, ``operationId``, parameters, and response codes are read directly. Both
JSON and YAML are supported, and Swagger 2.0 as well as OpenAPI 3.x — the fields used
here are common to both.

Discovery is content-based, not name-based: any ``.json``/``.yaml``/``.yml`` file whose
top level carries an ``openapi``/``swagger`` key plus ``paths`` is a spec, wherever it
lives. Files that do not parse are skipped, never guessed at.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from knowledge_builder.parser.db.walk import iter_files, read_text

#: HTTP verbs an OpenAPI path item may declare.
HTTP_METHODS: frozenset[str] = frozenset(
    {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
)

_SPEC_SUFFIXES = (".json", ".yaml", ".yml")
#: Skip very large candidate files (specs are text, but lockfiles can be huge).
_MAX_SPEC_BYTES = 8_000_000


@dataclass(frozen=True)
class Operation:
    """One operation (method + path) declared by a spec."""

    method: str
    path: str
    spec_file: str
    operation_id: str | None = None
    summary: str | None = None
    description: str | None = None
    tags: tuple[str, ...] = ()
    parameters: tuple[str, ...] = ()
    response_codes: tuple[str, ...] = ()
    request_schema: str | None = None


def discover_specs(repo_path: Path) -> list[tuple[str, dict[str, Any]]]:
    """Return ``(relative_path, document)`` for every OpenAPI/Swagger spec in the repo."""
    root = Path(repo_path)
    found: list[tuple[str, dict[str, Any]]] = []
    for entry in iter_files(root):
        if not entry.rel.lower().endswith(_SPEC_SUFFIXES):
            continue
        try:
            if entry.path.stat().st_size > _MAX_SPEC_BYTES:
                continue
        except OSError:
            continue
        text = read_text(entry.path)
        if not text or not _looks_like_spec(text):
            continue
        document = _load(text, entry.rel)
        if document is not None and _is_spec(document):
            found.append((entry.rel, document))
    return found


def parse_operations(spec_file: str, document: dict[str, Any]) -> list[Operation]:
    """Extract every operation declared under the spec's ``paths``."""
    paths = document.get("paths")
    if not isinstance(paths, dict):
        return []
    base = _base_path(document)
    operations: list[Operation] = []
    for raw_path, item in paths.items():
        if not isinstance(item, dict):
            continue
        # Parameters declared once for the whole path item apply to each operation.
        shared = _parameter_names(item.get("parameters"))
        for method, operation in item.items():
            if method.lower() not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            operations.append(
                _operation(base + str(raw_path), method, operation, spec_file, shared)
            )
    return operations


def _operation(
    path: str,
    method: str,
    body: dict[str, Any],
    spec_file: str,
    shared_params: tuple[str, ...],
) -> Operation:
    responses = body.get("responses")
    codes = tuple(str(c) for c in responses) if isinstance(responses, dict) else ()
    tags = body.get("tags")
    return Operation(
        method=method.upper(),
        path=path,
        spec_file=spec_file,
        operation_id=_opt_str(body.get("operationId")),
        summary=_opt_str(body.get("summary")),
        description=_opt_str(body.get("description")),
        tags=tuple(str(t) for t in tags) if isinstance(tags, list) else (),
        parameters=tuple(dict.fromkeys(shared_params + _parameter_names(body.get("parameters")))),
        response_codes=codes,
        request_schema=_request_schema(body),
    )


def _parameter_names(raw: Any) -> tuple[str, ...]:
    if not isinstance(raw, list):
        return ()
    names: list[str] = []
    for param in raw:
        if isinstance(param, dict):
            name = _opt_str(param.get("name")) or _ref_name(param.get("$ref"))
            if name:
                names.append(name)
    return tuple(names)


def _request_schema(body: dict[str, Any]) -> str | None:
    """Schema name for the request body (OpenAPI 3 ``requestBody``, Swagger 2 ``body``)."""
    request = body.get("requestBody")
    if isinstance(request, dict):
        content = request.get("content")
        if isinstance(content, dict):
            for media in content.values():
                if isinstance(media, dict):
                    ref = _schema_ref(media.get("schema"))
                    if ref:
                        return ref
        return _ref_name(request.get("$ref"))
    parameters = body.get("parameters")
    if isinstance(parameters, list):
        for param in parameters:
            if isinstance(param, dict) and param.get("in") == "body":
                ref = _schema_ref(param.get("schema"))
                if ref:
                    return ref
    return None


def _schema_ref(schema: Any) -> str | None:
    if not isinstance(schema, dict):
        return None
    ref = _ref_name(schema.get("$ref"))
    if ref:
        return ref
    items = schema.get("items")
    if isinstance(items, dict):
        inner = _ref_name(items.get("$ref"))
        if inner:
            return f"{inner}[]"
    return _opt_str(schema.get("type"))


def _ref_name(ref: Any) -> str | None:
    text = _opt_str(ref)
    return text.rsplit("/", 1)[-1] if text else None


def _base_path(document: dict[str, Any]) -> str:
    """Swagger 2 ``basePath``; OpenAPI 3 paths are already absolute."""
    base = _opt_str(document.get("basePath")) or ""
    return base.rstrip("/")


def _looks_like_spec(text: str) -> bool:
    """Cheap pre-filter before paying for a full parse."""
    head = text[:4000]
    return ("openapi" in head or "swagger" in head) and "paths" in text


def _is_spec(document: dict[str, Any]) -> bool:
    return ("openapi" in document or "swagger" in document) and isinstance(
        document.get("paths"), dict
    )


def _load(text: str, rel: str) -> dict[str, Any] | None:
    if rel.lower().endswith(".json"):
        try:
            loaded = json.loads(text)
        except ValueError:
            return None
    else:
        try:
            import yaml

            loaded = yaml.safe_load(text)
        except Exception:  # noqa: BLE001 - malformed YAML is simply not a spec
            return None
    return loaded if isinstance(loaded, dict) else None


def _opt_str(value: Any) -> str | None:
    if value is None or isinstance(value, (dict, list)):
        return None
    text = str(value).strip()
    return text or None
