"""SQLite schema for the ``knowledge.kb`` artifact.

Each entity table carries a few indexed columns for fast lookup plus a ``data`` column
holding the full JSON ``model_dump`` of the IR entity, so the reader can reconstruct
typed models losslessly. The graph layer is ``graph_nodes`` + ``relationships``.
``PRAGMA user_version`` mirrors :data:`SCHEMA_VERSION`.
"""

from __future__ import annotations

from knowledge_builder.models.metadata import SCHEMA_VERSION

__all__ = ["SCHEMA_STATEMENTS", "SCHEMA_VERSION"]

SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE version (
        schema_version   INTEGER NOT NULL,
        builder_version  TEXT,
        graphify_version TEXT
    )
    """,
    """
    CREATE TABLE metadata (
        key   TEXT PRIMARY KEY,
        value TEXT
    )
    """,
    """
    CREATE TABLE file_hashes (
        source_file TEXT PRIMARY KEY,
        hash        TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE graph_nodes (
        id           TEXT PRIMARY KEY,
        label        TEXT,
        file_type    TEXT,
        source_file  TEXT,
        community_id TEXT,
        data         TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE relationships (
        id        TEXT PRIMARY KEY,
        source_id TEXT,
        target_id TEXT,
        relation  TEXT,
        data      TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE symbols (
        id             TEXT PRIMARY KEY,
        label          TEXT,
        name           TEXT,
        kind           TEXT,
        qualified_name TEXT,
        source_file    TEXT,
        start_line     INTEGER,
        end_line       INTEGER,
        module_id      TEXT,
        language       TEXT,
        data           TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE modules (
        id     TEXT PRIMARY KEY,
        name   TEXT,
        origin TEXT,
        data   TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE services (
        id   TEXT PRIMARY KEY,
        name TEXT,
        data TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE controllers (
        id   TEXT PRIMARY KEY,
        name TEXT,
        data TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE apis (
        id     TEXT PRIMARY KEY,
        name   TEXT,
        method TEXT,
        path   TEXT,
        data   TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE concepts (
        id    TEXT PRIMARY KEY,
        label TEXT,
        data  TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE workflows (
        id   TEXT PRIMARY KEY,
        name TEXT,
        data TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE dependencies (
        id        TEXT PRIMARY KEY,
        source_id TEXT,
        target_id TEXT,
        kind      TEXT,
        data      TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE summaries (
        id        TEXT PRIMARY KEY,
        module_id TEXT,
        data      TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE db_technologies (
        id         TEXT PRIMARY KEY,
        name       TEXT,
        category   TEXT,
        confidence TEXT,
        data       TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE db_tables (
        id          TEXT PRIMARY KEY,
        name        TEXT,
        schema_name TEXT,
        technology  TEXT,
        source_file TEXT,
        confidence  TEXT,
        data        TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE db_migrations (
        id          TEXT PRIMARY KEY,
        name        TEXT,
        technology  TEXT,
        source_file TEXT,
        data        TEXT NOT NULL
    )
    """,
    "CREATE INDEX idx_modules_name ON modules (name)",
    "CREATE INDEX idx_services_name ON services (name)",
    "CREATE INDEX idx_controllers_name ON controllers (name)",
    "CREATE INDEX idx_apis_name ON apis (name)",
    "CREATE INDEX idx_concepts_label ON concepts (label)",
    "CREATE INDEX idx_workflows_name ON workflows (name)",
    "CREATE INDEX idx_symbols_label ON symbols (label)",
    "CREATE INDEX idx_symbols_module ON symbols (module_id)",
    "CREATE INDEX idx_symbols_name ON symbols (name)",
    # The (name, source_file, start_line) identity tuple external indexers join on.
    "CREATE INDEX idx_symbols_identity ON symbols (name, source_file, start_line)",
    "CREATE INDEX idx_summaries_module ON summaries (module_id)",
    "CREATE INDEX idx_relationships_source ON relationships (source_id)",
    "CREATE INDEX idx_relationships_target ON relationships (target_id)",
    "CREATE INDEX idx_db_tables_name ON db_tables (name)",
    "CREATE INDEX idx_db_technologies_name ON db_technologies (name)",
    "CREATE INDEX idx_db_migrations_name ON db_migrations (name)",
)
