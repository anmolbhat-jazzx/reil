"""Serializer: Repository IR ↔ portable ``knowledge.kb`` SQLite artifact."""

from __future__ import annotations

from knowledge_builder.serializer.reader import KnowledgeReader
from knowledge_builder.serializer.schema import SCHEMA_STATEMENTS, SCHEMA_VERSION
from knowledge_builder.serializer.writer import KnowledgeWriter

__all__ = [
    "SCHEMA_STATEMENTS",
    "SCHEMA_VERSION",
    "KnowledgeReader",
    "KnowledgeWriter",
]
