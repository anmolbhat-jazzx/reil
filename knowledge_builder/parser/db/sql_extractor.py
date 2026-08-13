"""Deterministic SQL DDL extraction via sqlglot (dialect-agnostic).

sqlglot parses ``CREATE TABLE`` / ``CREATE INDEX`` / ``ALTER TABLE`` across 30+ dialects
into one AST, so this layer needs no knowledge of *which* database or which tool emitted
the SQL — it is the universal substrate every stack funnels down to. Each fact is tagged
with its source file and (best-effort) line, and marked ``EXTRACTED``. Statements that do
not parse are skipped, never guessed.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import cast

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from knowledge_builder.models.base import Confidence
from knowledge_builder.models.database import DbColumn, DbConstraint, DbIndex, DbTable


@contextmanager
def _quiet_sqlglot() -> Iterator[None]:
    """Silence sqlglot's parser chatter for the duration of a parse.

    Statements we do not model (``CREATE EXTENSION``, ``CREATE USER``, ``CREATE DATABASE``)
    make sqlglot log an "unsupported syntax, falling back to Command" warning. That is the
    expected, handled path here — it should not surface as build output.
    """
    logger = logging.getLogger("sqlglot")
    previous = logger.level
    logger.setLevel(logging.ERROR)
    try:
        yield
    finally:
        logger.setLevel(previous)


def extract_tables(
    sql: str,
    *,
    source_file: str,
    dialect: str | None = None,
    technology: str | None = None,
) -> list[DbTable]:
    """Parse ``sql`` and return the tables it defines, with indexes/constraints merged."""
    statements = _parse(sql, dialect)
    tables: dict[str, DbTable] = {}
    order: list[str] = []
    pending_indexes: list[DbIndex] = []

    for stmt in statements:
        if isinstance(stmt, exp.Create):
            kind = (stmt.kind or "").upper()
            if kind == "TABLE":
                table = _table_from_create(stmt, sql, source_file, technology)
                if table is not None:
                    tables[table.name.lower()] = table
                    order.append(table.name.lower())
            elif kind == "INDEX":
                index = _index_from_create(stmt, source_file)
                if index is not None:
                    pending_indexes.append(index)

    # Attach standalone CREATE INDEX statements to their table when known.
    for index in pending_indexes:
        key = (index.table or "").lower()
        if key in tables:
            current = tables[key]
            tables[key] = current.model_copy(update={"indexes": (*current.indexes, index)})

    return [tables[key] for key in order]


def _parse(sql: str, dialect: str | None) -> list[exp.Expression]:
    """Parse a multi-statement SQL string, tolerating unparseable statements."""
    try:
        with _quiet_sqlglot():
            parsed = sqlglot.parse(sql, dialect=dialect, error_level=sqlglot.ErrorLevel.IGNORE)
    except SqlglotError:
        return []
    return cast("list[exp.Expression]", [stmt for stmt in parsed if stmt is not None])


def _table_from_create(
    create: exp.Create, sql: str, source_file: str, technology: str | None
) -> DbTable | None:
    schema = create.this
    table_expr = schema.this if isinstance(schema, exp.Schema) else schema
    if not isinstance(table_expr, exp.Table):
        return None
    name = table_expr.name
    if not name:
        return None
    schema_name = table_expr.db or None

    columns: list[DbColumn] = []
    constraints: list[DbConstraint] = []
    if isinstance(schema, exp.Schema):
        for item in schema.expressions:
            if isinstance(item, exp.ColumnDef):
                columns.append(_column(item))
            else:
                constraint = _table_constraint(item)
                if constraint is not None:
                    constraints.append(constraint)

    return DbTable(
        id=f"table::{source_file}::{name}",
        name=name,
        schema_name=schema_name,
        columns=tuple(columns),
        constraints=tuple(constraints),
        technology=technology,
        source_file=source_file,
        source_location=_locate(sql, name),
        confidence=Confidence.EXTRACTED,
        evidence=(source_file,),
    )


def _column(col: exp.ColumnDef) -> DbColumn:
    data_type = None
    kind = col.args.get("kind")
    if isinstance(kind, exp.DataType):
        data_type = kind.sql().upper() or None

    primary_key = False
    unique = False
    nullable: bool | None = None
    default: str | None = None
    ref_table: str | None = None
    ref_column: str | None = None

    for cons in col.constraints:
        ckind = cons.kind
        if isinstance(ckind, exp.PrimaryKeyColumnConstraint):
            primary_key = True
            nullable = False
        elif isinstance(ckind, exp.NotNullColumnConstraint):
            nullable = ckind.args.get("allow_null") is True
        elif isinstance(ckind, exp.UniqueColumnConstraint):
            unique = True
        elif isinstance(ckind, exp.DefaultColumnConstraint):
            default = ckind.this.sql() if ckind.this else None
        elif isinstance(ckind, exp.Reference):
            ref_table, ref_column = _reference_target(ckind)

    return DbColumn(
        name=col.name,
        data_type=data_type,
        nullable=nullable,
        primary_key=primary_key,
        unique=unique,
        default=default,
        references_table=ref_table,
        references_column=ref_column,
    )


def _table_constraint(item: exp.Expression) -> DbConstraint | None:
    if isinstance(item, exp.PrimaryKey):
        return DbConstraint(kind="primary_key", columns=_columns_of(item))
    if isinstance(item, exp.ForeignKey):
        ref_table, ref_cols = _foreign_key_target(item)
        return DbConstraint(
            kind="foreign_key",
            columns=_columns_of(item),
            references_table=ref_table,
            references_columns=ref_cols,
        )
    if isinstance(item, exp.UniqueColumnConstraint):
        return DbConstraint(kind="unique", columns=_columns_of(item))
    if isinstance(item, exp.Constraint):
        # Named constraint wrapper — flatten what we can recognize inside it.
        for inner in item.expressions:
            recognized = _table_constraint(inner)
            if recognized is not None:
                return recognized.model_copy(update={"name": item.name or recognized.name})
    if isinstance(item, exp.Check):
        expr = item.this
        return DbConstraint(kind="check", expression=expr.sql() if expr else None)
    return None


def _index_from_create(create: exp.Create, source_file: str) -> DbIndex | None:
    index_expr = create.this
    if not isinstance(index_expr, exp.Index):
        return None
    table_expr = index_expr.args.get("table")
    table = table_expr.name if isinstance(table_expr, exp.Table) else None
    columns = tuple(col.name for col in index_expr.find_all(exp.Column) if col.name)
    unique = bool(create.args.get("unique"))
    name_ident = index_expr.args.get("this")
    name = name_ident.name if isinstance(name_ident, exp.Identifier) else None
    return DbIndex(
        name=name or None,
        table=table,
        columns=columns,
        unique=unique,
        source_file=source_file,
    )


def _columns_of(item: exp.Expression) -> tuple[str, ...]:
    return tuple(col.name for col in item.find_all(exp.Column) if col.name) or tuple(
        ident.name for ident in item.find_all(exp.Identifier) if ident.name
    )


def _reference_target(ref: exp.Reference) -> tuple[str | None, str | None]:
    schema = ref.this
    if isinstance(schema, exp.Schema) and isinstance(schema.this, exp.Table):
        cols = [e.name for e in schema.expressions if isinstance(e, exp.Identifier) and e.name]
        return schema.this.name, (cols[0] if cols else None)
    if isinstance(schema, exp.Table):
        return schema.name, None
    return None, None


def _foreign_key_target(fk: exp.ForeignKey) -> tuple[str | None, tuple[str, ...]]:
    ref = fk.args.get("reference")
    if isinstance(ref, exp.Reference):
        schema = ref.this
        if isinstance(schema, exp.Schema) and isinstance(schema.this, exp.Table):
            cols = tuple(c.name for c in schema.expressions if isinstance(c, exp.Identifier))
            return schema.this.name, cols
        if isinstance(schema, exp.Table):
            return schema.name, ()
    return None, ()


def _locate(sql: str, table_name: str) -> str | None:
    """Best-effort 1-based line of the table name within the SQL text."""
    lowered = sql.lower()
    needle = table_name.lower()
    idx = lowered.find(needle)
    if idx < 0:
        return None
    return f"L{sql.count(chr(10), 0, idx) + 1}"
