"""KnowledgeReader — typed read access to a ``knowledge.kb`` artifact.

Opens the SQLite file read-only and reconstructs IR models from the JSON ``data``
columns. Shared by the validation pass (re-reading a written artifact) and the query
engine SDK.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import TracebackType
from typing import TypeVar

from pydantic import BaseModel

from knowledge_builder.models import (
    Api,
    Concept,
    Controller,
    DbMigration,
    DbTable,
    DbTechnology,
    Dependency,
    GraphNode,
    Metadata,
    Module,
    Relationship,
    Repository,
    Service,
    Summary,
    Symbol,
    Workflow,
)
from knowledge_builder.utils.errors import QueryError, SerializationError

_M = TypeVar("_M", bound=BaseModel)


class KnowledgeReader:
    """Read-only accessor for a compiled ``knowledge.kb`` file."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        if not self._path.is_file():
            raise QueryError(f"knowledge artifact not found: {self._path}")
        try:
            self._conn = sqlite3.connect(f"file:{self._path}?mode=ro", uri=True)
        except sqlite3.Error as exc:  # pragma: no cover - defensive
            raise SerializationError(f"cannot open {self._path}: {exc}") from exc
        self._conn.row_factory = sqlite3.Row

    # -- lifecycle ----------------------------------------------------------
    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> KnowledgeReader:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # -- metadata -----------------------------------------------------------
    def schema_version(self) -> int:
        row = self._conn.execute("PRAGMA user_version").fetchone()
        return int(row[0])

    def metadata(self) -> Metadata:
        kv = {
            row["key"]: json.loads(row["value"])
            for row in self._conn.execute("SELECT key, value FROM metadata")
        }
        version = self._conn.execute(
            "SELECT schema_version, builder_version, graphify_version FROM version"
        ).fetchone()
        return Metadata(
            repo_path=kv.get("repo_path", ""),
            repo_name=kv.get("repo_name", ""),
            schema_version=version["schema_version"] if version else 1,
            generated_by=kv.get("generated_by", "knowledge_builder"),
            builder_version=version["builder_version"] if version else None,
            graphify_version=version["graphify_version"] if version else None,
            directed=kv.get("directed", True),
            multigraph=kv.get("multigraph", False),
            node_count=kv.get("node_count", 0),
            edge_count=kv.get("edge_count", 0),
            community_count=kv.get("community_count", 0),
            source_graph_hash=kv.get("source_graph_hash"),
            file_hashes=self.file_hashes(),
        )

    def file_hashes(self) -> dict[str, str]:
        return {
            row["source_file"]: row["hash"]
            for row in self._conn.execute("SELECT source_file, hash FROM file_hashes")
        }

    # -- collections --------------------------------------------------------
    def modules(self) -> tuple[Module, ...]:
        return self._load("modules", Module)

    def services(self) -> tuple[Service, ...]:
        return self._load("services", Service)

    def controllers(self) -> tuple[Controller, ...]:
        return self._load("controllers", Controller)

    def apis(self) -> tuple[Api, ...]:
        return self._load("apis", Api)

    def concepts(self) -> tuple[Concept, ...]:
        return self._load("concepts", Concept)

    def workflows(self) -> tuple[Workflow, ...]:
        return self._load("workflows", Workflow)

    def symbols(self) -> tuple[Symbol, ...]:
        return self._load("symbols", Symbol)

    def summaries(self) -> tuple[Summary, ...]:
        return self._load("summaries", Summary)

    def dependencies(self) -> tuple[Dependency, ...]:
        return self._load("dependencies", Dependency)

    def graph_nodes(self) -> tuple[GraphNode, ...]:
        return self._load("graph_nodes", GraphNode)

    def relationships(self) -> tuple[Relationship, ...]:
        return self._load("relationships", Relationship)

    def db_technologies(self) -> tuple[DbTechnology, ...]:
        return self._load("db_technologies", DbTechnology)

    def db_tables(self) -> tuple[DbTable, ...]:
        return self._load("db_tables", DbTable)

    def db_migrations(self) -> tuple[DbMigration, ...]:
        return self._load("db_migrations", DbMigration)

    # -- lookups ------------------------------------------------------------
    def module_by_name(self, name: str) -> Module | None:
        return self._one_by("modules", "name", name, Module)

    def service_by_name(self, name: str) -> Service | None:
        return self._one_by("services", "name", name, Service)

    def workflow_by_name(self, name: str) -> Workflow | None:
        return self._one_by("workflows", "name", name, Workflow)

    def concept_by_label(self, label: str) -> Concept | None:
        return self._one_by("concepts", "label", label, Concept)

    def summary_for_module(self, module_id: str) -> Summary | None:
        row = self._conn.execute(
            "SELECT data FROM summaries WHERE module_id = ? LIMIT 1", (module_id,)
        ).fetchone()
        return Summary.model_validate(json.loads(row["data"])) if row else None

    # -- whole-IR -----------------------------------------------------------
    def load_repository(self) -> Repository:
        return Repository(
            metadata=self.metadata(),
            graph_nodes=self.graph_nodes(),
            relationships=self.relationships(),
            symbols=self.symbols(),
            modules=self.modules(),
            services=self.services(),
            controllers=self.controllers(),
            apis=self.apis(),
            workflows=self.workflows(),
            concepts=self.concepts(),
            dependencies=self.dependencies(),
            summaries=self.summaries(),
            db_technologies=self.db_technologies(),
            db_tables=self.db_tables(),
            db_migrations=self.db_migrations(),
        )

    # -- internals ----------------------------------------------------------
    def _load(self, table: str, model_cls: type[_M]) -> tuple[_M, ...]:
        rows = self._conn.execute(
            f"SELECT data FROM {table} ORDER BY id"
        )  # noqa: S608 - fixed names
        return tuple(model_cls.model_validate(json.loads(row["data"])) for row in rows)

    def _one_by(self, table: str, column: str, value: str, model_cls: type[_M]) -> _M | None:
        row = self._conn.execute(
            f"SELECT data FROM {table} WHERE {column} = ? COLLATE NOCASE LIMIT 1",  # noqa: S608
            (value,),
        ).fetchone()
        return model_cls.model_validate(json.loads(row["data"])) if row else None

    def counts(self) -> dict[str, int]:
        tables = (
            "modules",
            "services",
            "controllers",
            "apis",
            "concepts",
            "workflows",
            "symbols",
            "summaries",
            "dependencies",
            "graph_nodes",
            "relationships",
            "db_technologies",
            "db_tables",
            "db_migrations",
        )
        result: dict[str, int] = {}
        for table in tables:
            row = self._conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()  # noqa: S608
            result[table] = int(row["n"])
        return result
