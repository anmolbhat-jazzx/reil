"""Database IR: schema knowledge extracted deterministically from repository source.

Unlike the code layer (which is projected from graphify's graph), the database layer is
extracted directly from source by REIL's own :mod:`knowledge_builder.parser.db`
subsystem — SQL DDL via sqlglot, ORM/migration definitions via static AST. Every fact
carries a :class:`~knowledge_builder.models.base.Confidence` tier and the source
evidence (``source_file`` + ``source_location``) it was derived from. Information that
cannot be determined from the source is left ``None`` — never inferred.

The design is repository-, SQL-dialect-, and technology-agnostic: which stack produced a
fact (Alembic, Flyway, Django, raw SQL, …) is recorded in ``technology`` as *data*, and
unrecognized stacks degrade to SQL-level facts plus an explicit ``unknown``.
"""

from __future__ import annotations

from knowledge_builder.models.base import Confidence, IRModel


class DbColumn(IRModel):
    """A single column of a table (nested inside :class:`DbTable`)."""

    name: str
    data_type: str | None = None
    nullable: bool | None = None
    primary_key: bool = False
    unique: bool = False
    default: str | None = None
    references_table: str | None = None
    references_column: str | None = None


class DbConstraint(IRModel):
    """A table constraint (primary key, foreign key, unique, or check)."""

    #: One of ``primary_key`` / ``foreign_key`` / ``unique`` / ``check``.
    kind: str
    name: str | None = None
    columns: tuple[str, ...] = ()
    references_table: str | None = None
    references_columns: tuple[str, ...] = ()
    expression: str | None = None


class DbIndex(IRModel):
    """An index defined on a table."""

    name: str | None = None
    table: str | None = None
    columns: tuple[str, ...] = ()
    unique: bool = False
    source_file: str | None = None
    source_location: str | None = None


class DbTable(IRModel):
    """A database table (or ORM entity) and its columns, constraints, and indexes."""

    id: str
    name: str
    schema_name: str | None = None
    columns: tuple[DbColumn, ...] = ()
    constraints: tuple[DbConstraint, ...] = ()
    indexes: tuple[DbIndex, ...] = ()
    #: The technology this fact was extracted from (e.g. ``flyway``, ``alembic``).
    technology: str | None = None
    source_file: str | None = None
    source_location: str | None = None
    confidence: Confidence = Confidence.EXTRACTED
    #: Source files/snippets the fact was derived from.
    evidence: tuple[str, ...] = ()


class DbMigration(IRModel):
    """A single migration script and the schema operations it applies."""

    id: str
    name: str
    technology: str | None = None
    #: Human-readable operation summaries (e.g. ``create_table users``).
    operations: tuple[str, ...] = ()
    source_file: str | None = None
    confidence: Confidence = Confidence.EXTRACTED


class DbTechnology(IRModel):
    """A database technology detected in the repository by fingerprinting."""

    #: Canonical id, e.g. ``alembic`` / ``flyway`` / ``django-migrations`` / ``raw-sql``.
    id: str
    name: str
    #: One of ``migration`` / ``orm`` / ``dialect`` / ``driver``.
    category: str
    confidence: Confidence = Confidence.INFERRED
    #: Source files that triggered the detection.
    evidence: tuple[str, ...] = ()
