"""KnowledgeWriter — serialize a Repository IR into a ``knowledge.kb`` SQLite file."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from knowledge_builder.models.repository import Repository
from knowledge_builder.serializer.schema import SCHEMA_STATEMENTS, SCHEMA_VERSION
from knowledge_builder.utils.errors import SerializationError


class KnowledgeWriter:
    """Writes a :class:`Repository` to a single portable SQLite artifact."""

    def write(self, repo: Repository, output_path: Path) -> Path:
        """Serialize ``repo`` to ``output_path`` (overwriting any existing file)."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.exists():
            output_path.unlink()

        try:
            with sqlite3.connect(output_path) as conn:
                conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                for statement in SCHEMA_STATEMENTS:
                    conn.execute(statement)
                self._write_all(conn, repo)
                conn.commit()
        except sqlite3.Error as exc:
            raise SerializationError(f"failed to write {output_path}: {exc}") from exc
        return output_path

    def _write_all(self, conn: sqlite3.Connection, repo: Repository) -> None:
        meta = repo.metadata
        conn.execute(
            "INSERT INTO version (schema_version, builder_version, graphify_version) "
            "VALUES (?,?,?)",
            (meta.schema_version, meta.builder_version, meta.graphify_version),
        )
        conn.executemany(
            "INSERT INTO metadata (key, value) VALUES (?, ?)",
            [
                (key, json.dumps(value))
                for key, value in {
                    "repo_path": meta.repo_path,
                    "repo_name": meta.repo_name,
                    "generated_by": meta.generated_by,
                    "directed": meta.directed,
                    "multigraph": meta.multigraph,
                    "node_count": meta.node_count,
                    "edge_count": meta.edge_count,
                    "community_count": meta.community_count,
                    "source_graph_hash": meta.source_graph_hash,
                }.items()
            ],
        )
        conn.executemany(
            "INSERT INTO file_hashes (source_file, hash) VALUES (?, ?)",
            list(meta.file_hashes.items()),
        )

        conn.executemany(
            "INSERT INTO graph_nodes (id, label, file_type, source_file, community_id, data) "
            "VALUES (?,?,?,?,?,?)",
            [
                (n.id, n.label, n.file_type.value, n.source_file, n.community_id, _dump(n))
                for n in repo.graph_nodes
            ],
        )
        conn.executemany(
            "INSERT INTO relationships (id, source_id, target_id, relation, data) "
            "VALUES (?,?,?,?,?)",
            [(r.id, r.source_id, r.target_id, r.relation, _dump(r)) for r in repo.relationships],
        )
        conn.executemany(
            "INSERT INTO symbols (id, label, name, kind, qualified_name, source_file, "
            "start_line, end_line, module_id, language, data) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    s.id,
                    s.label,
                    s.name,
                    s.kind,
                    s.qualified_name,
                    s.source_file,
                    s.start_line,
                    s.end_line,
                    s.module_id,
                    s.language,
                    _dump(s),
                )
                for s in repo.symbols
            ],
        )
        conn.executemany(
            "INSERT INTO modules (id, name, origin, data) VALUES (?,?,?,?)",
            [(m.id, m.name, m.origin.value, _dump(m)) for m in repo.modules],
        )
        conn.executemany(
            "INSERT INTO services (id, name, data) VALUES (?,?,?)",
            [(s.id, s.name, _dump(s)) for s in repo.services],
        )
        conn.executemany(
            "INSERT INTO controllers (id, name, data) VALUES (?,?,?)",
            [(c.id, c.name, _dump(c)) for c in repo.controllers],
        )
        conn.executemany(
            "INSERT INTO apis (id, name, method, path, data) VALUES (?,?,?,?,?)",
            [(a.id, a.name, a.method, a.path, _dump(a)) for a in repo.apis],
        )
        conn.executemany(
            "INSERT INTO concepts (id, label, data) VALUES (?,?,?)",
            [(c.id, c.label, _dump(c)) for c in repo.concepts],
        )
        conn.executemany(
            "INSERT INTO workflows (id, name, data) VALUES (?,?,?)",
            [(w.id, w.name, _dump(w)) for w in repo.workflows],
        )
        conn.executemany(
            "INSERT INTO dependencies (id, source_id, target_id, kind, data) VALUES (?,?,?,?,?)",
            [(d.id, d.source_id, d.target_id, d.kind, _dump(d)) for d in repo.dependencies],
        )
        conn.executemany(
            "INSERT INTO summaries (id, module_id, data) VALUES (?,?,?)",
            [(s.id, s.module_id, _dump(s)) for s in repo.summaries],
        )
        conn.executemany(
            "INSERT INTO db_technologies (id, name, category, confidence, data) "
            "VALUES (?,?,?,?,?)",
            [
                (t.id, t.name, t.category, t.confidence.value, _dump(t))
                for t in repo.db_technologies
            ],
        )
        conn.executemany(
            "INSERT INTO db_tables (id, name, schema_name, technology, source_file, "
            "confidence, data) VALUES (?,?,?,?,?,?,?)",
            [
                (
                    t.id,
                    t.name,
                    t.schema_name,
                    t.technology,
                    t.source_file,
                    t.confidence.value,
                    _dump(t),
                )
                for t in repo.db_tables
            ],
        )
        conn.executemany(
            "INSERT INTO db_migrations (id, name, technology, source_file, data) "
            "VALUES (?,?,?,?,?)",
            [(m.id, m.name, m.technology, m.source_file, _dump(m)) for m in repo.db_migrations],
        )


def _dump(model: Any) -> str:
    return json.dumps(model.model_dump(mode="json"), separators=(",", ":"))
