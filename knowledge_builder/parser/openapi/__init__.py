"""OpenAPI contract ingestion: authoritative endpoints, bound to their handler symbols."""

from __future__ import annotations

from knowledge_builder.parser.openapi.binder import bind, normalize_path
from knowledge_builder.parser.openapi.mounts import discover_mounts
from knowledge_builder.parser.openapi.spec import (
    Operation,
    discover_specs,
    parse_operations,
)

__all__ = [
    "Operation",
    "bind",
    "discover_mounts",
    "discover_specs",
    "normalize_path",
    "parse_operations",
]
