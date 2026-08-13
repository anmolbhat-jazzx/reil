"""Agnostic database-knowledge extraction subsystem.

Pipeline: fingerprint the repository to learn which stack(s) it uses, then dispatch to
the right extractors. SQL is the universal substrate (parsed by sqlglot, dialect-agnostic);
specific stacks (Alembic today) plug in as additional extractors. Every fact carries
source evidence + a confidence tier; unknowns are left unknown.
"""

from __future__ import annotations

from knowledge_builder.parser.db.extractor import DatabaseExtraction, extract_database
from knowledge_builder.parser.db.fingerprints import detect, dialect_for

__all__ = [
    "DatabaseExtraction",
    "detect",
    "dialect_for",
    "extract_database",
]
