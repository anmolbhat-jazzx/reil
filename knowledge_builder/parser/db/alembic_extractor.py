"""Alembic migration extraction via Python's ``ast`` (static — no code execution).

Alembic migrations express schema as Python calls (``op.create_table``, ``op.create_index``,
``op.add_column`` …). This reads them with the standard-library AST parser — deterministic,
zero side effects, and requires none of the project's dependencies to be installed (unlike
running Alembic). It is one concrete extractor plugged in behind the fingerprint router;
the same shape generalizes to Django's ``migrations.CreateModel`` and similar stacks.
"""

from __future__ import annotations

import ast

from knowledge_builder.models.base import Confidence
from knowledge_builder.models.database import DbColumn, DbConstraint, DbMigration, DbTable

#: ``op.*`` calls we summarize as migration operations.
_OP_METHODS = frozenset(
    {
        "create_table",
        "drop_table",
        "add_column",
        "drop_column",
        "alter_column",
        "create_index",
        "drop_index",
        "create_foreign_key",
        "create_unique_constraint",
        "rename_table",
    }
)


def extract(source: str, *, source_file: str) -> tuple[list[DbTable], DbMigration | None]:
    """Parse an Alembic migration file; return its tables and a migration summary."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return [], None

    tables: list[DbTable] = []
    operations: list[str] = []

    # Only read the forward (``upgrade``) migration; ``downgrade`` is the inverse and
    # would double the operation list with confusing drop_* noise.
    upgrade = next(
        (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "upgrade"),
        None,
    )
    scope: ast.AST = upgrade if upgrade is not None else tree

    for node in ast.walk(scope):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or not _is_op_call(func):
            continue
        method = func.attr
        summary = _summarize(method, node)
        if summary:
            operations.append(summary)
        if method == "create_table":
            table = _create_table(node, source_file)
            if table is not None:
                tables.append(table)

    migration = None
    if operations:
        name = source_file.rsplit("/", 1)[-1]
        migration = DbMigration(
            id=f"migration::{source_file}",
            name=name,
            technology="alembic",
            operations=tuple(operations),
            source_file=source_file,
            confidence=Confidence.EXTRACTED,
        )
    return tables, migration


def _is_op_call(func: ast.Attribute) -> bool:
    return func.attr in _OP_METHODS and _root_name(func) == "op"


def _root_name(attr: ast.Attribute) -> str | None:
    value = attr.value
    if isinstance(value, ast.Name):
        return value.id
    return None


def _summarize(method: str, node: ast.Call) -> str:
    target = _first_str_arg(node)
    return f"{method} {target}".strip() if target else method


def _create_table(node: ast.Call, source_file: str) -> DbTable | None:
    name = _first_str_arg(node)
    if not name:
        return None
    columns: list[DbColumn] = []
    constraints: list[DbConstraint] = []
    for arg in node.args[1:]:
        if not isinstance(arg, ast.Call):
            continue
        callee = _callee_name(arg.func)
        if callee == "Column":
            column = _column(arg)
            if column is not None:
                columns.append(column)
        elif callee in _TABLE_CONSTRAINTS:
            constraint = _table_constraint(callee, arg)
            if constraint is not None:
                constraints.append(constraint)

    # Fold table-level constraints back onto the columns they cover, so a column
    # carries its PK / FK / unique marks regardless of how the migration declared them.
    columns = _apply_constraints(columns, constraints)
    return DbTable(
        id=f"table::{source_file}::{name}",
        name=name,
        columns=tuple(columns),
        constraints=tuple(constraints),
        technology="alembic",
        source_file=source_file,
        source_location=f"L{node.lineno}",
        confidence=Confidence.EXTRACTED,
        evidence=(source_file,),
    )


#: sqlalchemy table-level constraint callables recognized inside ``op.create_table``.
_TABLE_CONSTRAINTS = frozenset({"PrimaryKeyConstraint", "ForeignKeyConstraint", "UniqueConstraint"})


def _table_constraint(callee: str, call: ast.Call) -> DbConstraint | None:
    if callee == "PrimaryKeyConstraint":
        return DbConstraint(kind="primary_key", columns=_str_args(call))
    if callee == "UniqueConstraint":
        return DbConstraint(kind="unique", columns=_str_args(call))
    if callee == "ForeignKeyConstraint":
        # ForeignKeyConstraint(['local_col', ...], ['other.col', ...]).
        local = _str_list(call.args[0]) if call.args else ()
        refs = _str_list(call.args[1]) if len(call.args) > 1 else ()
        ref_table = None
        ref_columns: list[str] = []
        for ref in refs:
            table, _, column = ref.rpartition(".")
            ref_table = table or ref_table
            if column:
                ref_columns.append(column)
        return DbConstraint(
            kind="foreign_key",
            columns=local,
            references_table=ref_table,
            references_columns=tuple(ref_columns),
        )
    return None


def _apply_constraints(columns: list[DbColumn], constraints: list[DbConstraint]) -> list[DbColumn]:
    updates: dict[str, dict[str, object]] = {}
    for con in constraints:
        if con.kind == "primary_key":
            for col in con.columns:
                updates.setdefault(col, {}).update(primary_key=True, nullable=False)
        elif con.kind == "unique" and len(con.columns) == 1:
            # A composite unique(a, b) does NOT make a or b individually unique;
            # only a single-column unique constraint marks the column unique.
            updates.setdefault(con.columns[0], {})["unique"] = True
        elif con.kind == "foreign_key" and con.references_table:
            for i, col in enumerate(con.columns):
                ref_col = con.references_columns[i] if i < len(con.references_columns) else None
                updates.setdefault(col, {}).update(
                    references_table=con.references_table, references_column=ref_col
                )
    if not updates:
        return columns
    return [
        col.model_copy(update=updates[col.name]) if col.name in updates else col for col in columns
    ]


def _str_args(call: ast.Call) -> tuple[str, ...]:
    return tuple(
        a.value for a in call.args if isinstance(a, ast.Constant) and isinstance(a.value, str)
    )


def _str_list(node: ast.expr) -> tuple[str, ...]:
    if isinstance(node, (ast.List, ast.Tuple)):
        return tuple(
            e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)
        )
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return (node.value,)
    return ()


def _column(call: ast.Call) -> DbColumn | None:
    name = _first_str_arg(call)
    if not name:
        return None
    data_type = None
    if len(call.args) >= 2:
        data_type = _type_name(call.args[1])
    primary_key = _bool_keyword(call, "primary_key")
    nullable = _opt_bool_keyword(call, "nullable")
    unique = _bool_keyword(call, "unique")
    ref_table, ref_column = _foreign_key(call)
    return DbColumn(
        name=name,
        data_type=data_type,
        nullable=nullable,
        primary_key=primary_key,
        unique=unique,
        references_table=ref_table,
        references_column=ref_column,
    )


def _foreign_key(call: ast.Call) -> tuple[str | None, str | None]:
    for arg in call.args[1:]:
        if isinstance(arg, ast.Call) and _callee_name(arg.func) == "ForeignKey":
            target = _first_str_arg(arg)
            if target and "." in target:
                table, _, column = target.rpartition(".")
                return table, column
            return target, None
    return None, None


def _first_str_arg(call: ast.Call) -> str | None:
    for arg in call.args:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return arg.value
    return None


def _type_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Call):
        return _callee_name(node.func)
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None


def _callee_name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _bool_keyword(call: ast.Call, name: str) -> bool:
    return _opt_bool_keyword(call, name) is True


def _opt_bool_keyword(call: ast.Call, name: str) -> bool | None:
    for kw in call.keywords:
        value = kw.value
        if kw.arg == name and isinstance(value, ast.Constant) and isinstance(value.value, bool):
            return value.value
    return None
