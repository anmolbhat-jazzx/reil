"""Router: fingerprint a repository, then dispatch to the right extractors.

Ties the pieces together without hard-coding a stack anywhere: detection is data-driven
(:mod:`fingerprints`), SQL is handled universally (:mod:`sql_extractor`), and specific
non-SQL stacks plug in as extractors keyed off content (Alembic today; Django/others are
additive). Anything unrecognized still yields whatever SQL facts are readable, and the
rest stays unknown.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from knowledge_builder.models.base import Confidence
from knowledge_builder.models.database import DbMigration, DbTable, DbTechnology
from knowledge_builder.parser.db import alembic_extractor, sql_extractor
from knowledge_builder.parser.db.fingerprints import detect, dialect_for
from knowledge_builder.parser.db.walk import iter_files, read_text

#: Marker that identifies an Alembic migration by content (path-independent).
_ALEMBIC_MARKER = "from alembic import op"
#: Cap on files handed to each extractor (schema lives in a bounded set of files).
_MAX_EXTRACT_FILES = 4000


@dataclass(frozen=True)
class DatabaseExtraction:
    """The complete database projection for a repository."""

    technologies: tuple[DbTechnology, ...] = ()
    tables: tuple[DbTable, ...] = ()
    migrations: tuple[DbMigration, ...] = ()


def extract_database(repo_path: Path) -> DatabaseExtraction:
    """Detect technologies and extract tables/migrations from ``repo_path``."""
    root = Path(repo_path)
    technologies = detect(root)
    dialect = dialect_for(technologies)

    tables: list[DbTable] = []
    migrations: list[DbMigration] = []
    processed = 0

    for entry in iter_files(root):
        if processed >= _MAX_EXTRACT_FILES:
            break
        suffix = Path(entry.rel).suffix.lower()

        if suffix == ".sql":
            text = read_text(entry.path)
            if not text:
                continue
            processed += 1
            technology = _sql_technology(entry.rel)
            file_tables = sql_extractor.extract_tables(
                text, source_file=entry.rel, dialect=dialect, technology=technology
            )
            tables.extend(file_tables)
            migration = _sql_migration(entry.rel, technology, file_tables)
            if migration is not None:
                migrations.append(migration)

        elif suffix == ".py":
            text = read_text(entry.path)
            if not text or _ALEMBIC_MARKER not in text:
                continue
            processed += 1
            file_tables, migration = alembic_extractor.extract(text, source_file=entry.rel)
            tables.extend(file_tables)
            if migration is not None:
                migrations.append(migration)

    return DatabaseExtraction(
        technologies=technologies,
        tables=tuple(_dedupe_by_id(tables)),
        migrations=tuple(_dedupe_by_id(migrations)),
    )


def _dedupe_by_id(items: list) -> list:  # type: ignore[type-arg]
    """Keep the first entity per id (ids are the serializer's primary key)."""
    seen: set[str] = set()
    result = []
    for item in items:
        if item.id in seen:
            continue
        seen.add(item.id)
        result.append(item)
    return result


def _sql_technology(rel: str) -> str:
    """Classify a ``.sql`` file's stack from its conventional location."""
    lower = rel.lower()
    if "changelog" in lower:
        return "liquibase"
    name = Path(rel).name
    if "/db/migration/" in f"/{lower}" or (name.startswith("V") and "__" in name):
        return "flyway"
    return "raw-sql"


def _sql_migration(rel: str, technology: str, tables: list[DbTable]) -> DbMigration | None:
    if not tables:
        return None
    operations = tuple(f"create_table {t.name}" for t in tables)
    return DbMigration(
        id=f"migration::{rel}",
        name=Path(rel).name,
        technology=technology,
        operations=operations,
        source_file=rel,
        confidence=Confidence.EXTRACTED,
    )
