"""Integrity validation of a Repository IR.

Produces a :class:`ValidationReport` listing errors and warnings. Runs against the
in-memory IR (which is exactly what the serializer persists), checking referential
integrity, graph consistency, and metadata sanity.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from knowledge_builder.models.metadata import SCHEMA_VERSION
from knowledge_builder.models.repository import Repository
from knowledge_builder.models.symbol import REFERENCE_KINDS


class Level(StrEnum):
    ERROR = "error"
    WARNING = "warning"


class ValidationIssue(BaseModel):
    model_config = ConfigDict(frozen=True)

    level: Level
    code: str
    message: str


class ValidationReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    issues: tuple[ValidationIssue, ...] = ()

    @property
    def errors(self) -> tuple[ValidationIssue, ...]:
        return tuple(i for i in self.issues if i.level is Level.ERROR)

    @property
    def warnings(self) -> tuple[ValidationIssue, ...]:
        return tuple(i for i in self.issues if i.level is Level.WARNING)

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_repository(repo: Repository) -> ValidationReport:
    """Validate ``repo`` and return a report of any integrity issues."""
    issues: list[ValidationIssue] = []
    add = issues.append

    node_ids = {n.id for n in repo.graph_nodes}
    symbol_ids = {s.id for s in repo.symbols}
    module_ids = {m.id for m in repo.modules}
    concept_ids = {c.id for c in repo.concepts}
    service_ids = {s.id for s in repo.services}
    controller_ids = {c.id for c in repo.controllers}
    api_ids = {a.id for a in repo.apis}
    workflow_ids = {w.id for w in repo.workflows}
    summary_ids = {s.id for s in repo.summaries}

    # -- metadata ----------------------------------------------------------
    if not repo.metadata.repo_name:
        add(_err("META_REPO_NAME", "metadata.repo_name is empty"))
    if repo.metadata.schema_version != SCHEMA_VERSION:
        add(
            _err(
                "META_SCHEMA",
                f"schema_version {repo.metadata.schema_version} != expected {SCHEMA_VERSION}",
            )
        )
    if repo.metadata.node_count != len(repo.graph_nodes):
        add(
            _warn(
                "META_NODE_COUNT",
                f"metadata.node_count {repo.metadata.node_count} != {len(repo.graph_nodes)} nodes",
            )
        )

    # -- modules -----------------------------------------------------------
    if repo.symbols and not repo.modules:
        add(_err("NO_MODULES", "symbols exist but no modules were produced"))

    for module in repo.modules:
        _check_refs(add, f"module {module.id}", "symbol", module.symbol_ids, symbol_ids)
        _check_refs(add, f"module {module.id}", "concept", module.concept_ids, concept_ids)
        _check_refs(add, f"module {module.id}", "service", module.service_ids, service_ids)
        _check_refs(add, f"module {module.id}", "controller", module.controller_ids, controller_ids)
        _check_refs(add, f"module {module.id}", "api", module.api_ids, api_ids)
        _check_refs(add, f"module {module.id}", "workflow", module.workflow_ids, workflow_ids)
        _check_refs(
            add, f"module {module.id}", "related-module", module.related_module_ids, module_ids
        )
        if module.summary_id is not None and module.summary_id not in summary_ids:
            add(
                _err(
                    "MODULE_BAD_SUMMARY",
                    f"module {module.id} → missing summary {module.summary_id}",
                )
            )

    # -- symbols -----------------------------------------------------------
    for symbol in repo.symbols:
        if symbol.id not in node_ids:
            add(_err("SYMBOL_NOT_NODE", f"symbol {symbol.id} has no backing graph node"))
        if not symbol.name:
            add(_warn("SYMBOL_NO_NAME", f"symbol {symbol.id} has no resolved name"))
        # Imported/external references have no definition site here — that is expected,
        # so only a symbol that should be defined in this repo is worth warning about.
        if symbol.start_line is None and symbol.kind not in REFERENCE_KINDS:
            add(_warn("SYMBOL_NO_START_LINE", f"symbol {symbol.id} has no start_line"))
        # A module is a business capability. An import belongs to none by construction, so
        # only an unassigned *definition* is a real gap in the module partition.
        if symbol.module_id is None:
            # Only an unassigned *definition* is a gap; a reference belonging to no module
            # is the expected case, and must not fall through to the dangling-ref check
            # below — "missing module None" is the absence itself, not a broken pointer.
            if symbol.kind not in REFERENCE_KINDS:
                add(_warn("SYMBOL_NO_MODULE", f"symbol {symbol.id} is not assigned to a module"))
        elif symbol.module_id not in module_ids:
            add(
                _err(
                    "SYMBOL_BAD_MODULE",
                    f"symbol {symbol.id} → missing module {symbol.module_id}",
                )
            )

    # ``(name, source_file, start_line)`` is the identity tuple external indexers join on.
    # Two definitions claiming it are two rows for one entity downstream, so the collision
    # has to surface here rather than in the consumer's database.
    definitions = Counter(
        (s.name, s.source_file, s.start_line)
        for s in repo.symbols
        if s.kind not in REFERENCE_KINDS and s.source_file and s.start_line is not None
    )
    for (name, source_file, start_line), count in definitions.items():
        if count > 1:
            add(
                _err(
                    "DUP_SYMBOL_DEF",
                    f"{count} symbols claim definition {name!r} at {source_file}:{start_line}",
                )
            )

    # -- graph integrity ---------------------------------------------------
    for rel in repo.relationships:
        if rel.source_id not in node_ids or rel.target_id not in node_ids:
            add(_err("GRAPH_DANGLING_EDGE", f"edge {rel.id} references a missing node"))

    # -- orphan concepts ---------------------------------------------------
    referenced = {cid for m in repo.modules for cid in m.concept_ids}
    for concept in repo.concepts:
        if concept.id not in referenced and not concept.related_ids:
            add(_warn("ORPHAN_CONCEPT", f"concept {concept.id} is unreferenced"))

    # -- database layer ----------------------------------------------------
    db_table_ids = [t.id for t in repo.db_tables]
    for table_id, count in Counter(db_table_ids).items():
        if count > 1:
            add(_err("DUP_DB_TABLE", f"db table id {table_id!r} appears {count} times"))
    for table in repo.db_tables:
        if not table.columns:
            add(_warn("DB_TABLE_NO_COLUMNS", f"db table {table.id} has no extracted columns"))

    # -- duplicate summaries / concepts ------------------------------------
    per_module = Counter(s.module_id for s in repo.summaries)
    for module_id, count in per_module.items():
        if count > 1:
            add(_err("DUP_SUMMARY", f"module {module_id} has {count} summaries"))
    per_label = Counter(c.normalized_label for c in repo.concepts)
    for label, count in per_label.items():
        if count > 1:
            add(_err("DUP_CONCEPT", f"concept label {label!r} appears {count} times (not deduped)"))

    return ValidationReport(issues=tuple(issues))


def _check_refs(
    add: Callable[[ValidationIssue], None],
    owner: str,
    kind: str,
    ids: tuple[str, ...],
    valid: set[str],
) -> None:
    for ref in ids:
        if ref not in valid:
            add(_err(f"{kind.upper()}_REF", f"{owner} → missing {kind} {ref}"))


def _err(code: str, message: str) -> ValidationIssue:
    return ValidationIssue(level=Level.ERROR, code=code, message=message)


def _warn(code: str, message: str) -> ValidationIssue:
    return ValidationIssue(level=Level.WARNING, code=code, message=message)
