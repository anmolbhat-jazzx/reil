"""Tests for the agnostic database-knowledge extraction subsystem."""

from __future__ import annotations

from pathlib import Path

import pytest
from knowledge_builder.models import Confidence, Metadata, Repository
from knowledge_builder.parser.db import (
    alembic_extractor,
    detect,
    dialect_for,
    extract_database,
    sql_extractor,
)
from knowledge_builder.passes import DatabasePass
from knowledge_builder.query import KnowledgeBase
from knowledge_builder.serializer import KnowledgeReader, KnowledgeWriter
from knowledge_builder.validation import validate_repository

DB_REPO = Path(__file__).parent.parent / "fixtures" / "db_repo"


# -- fingerprint detection --------------------------------------------------
def test_detect_identifies_stacks() -> None:
    techs = {t.id: t for t in detect(DB_REPO)}
    assert "alembic" in techs
    assert "flyway" in techs
    assert "postgres" in techs
    # A declared dependency / conventional path is high-confidence.
    assert techs["alembic"].confidence is Confidence.EXTRACTED
    assert techs["postgres"].confidence is Confidence.EXTRACTED


def test_detect_records_evidence() -> None:
    techs = {t.id: t for t in detect(DB_REPO)}
    assert techs["alembic"].evidence  # non-empty source evidence
    assert any("requirements.txt" in e or "alembic" in e for e in techs["alembic"].evidence)


def test_dialect_resolves_to_postgres() -> None:
    assert dialect_for(detect(DB_REPO)) == "postgres"


def test_unknown_repo_yields_no_false_positives(tmp_path: Path) -> None:
    (tmp_path / "main.py").write_text("print('hello')\n")
    assert detect(tmp_path) == ()


# -- SQL extraction ---------------------------------------------------------
def test_sql_extractor_columns_and_constraints() -> None:
    sql = (
        "CREATE TABLE users ("
        " id SERIAL PRIMARY KEY,"
        " email VARCHAR(255) NOT NULL UNIQUE,"
        " org_id INTEGER REFERENCES organizations(id));"
    )
    tables = sql_extractor.extract_tables(sql, source_file="x.sql", dialect="postgres")
    assert len(tables) == 1
    table = tables[0]
    cols = {c.name: c for c in table.columns}
    assert cols["id"].primary_key is True
    assert cols["email"].unique is True
    assert cols["email"].nullable is False
    assert cols["org_id"].references_table == "organizations"
    assert cols["org_id"].references_column == "id"
    assert table.source_location is not None


def test_sql_extractor_attaches_index() -> None:
    sql = "CREATE TABLE t (id INT); CREATE UNIQUE INDEX ix ON t (id);"
    table = sql_extractor.extract_tables(sql, source_file="x.sql")[0]
    assert len(table.indexes) == 1
    assert table.indexes[0].unique is True
    assert table.indexes[0].columns == ("id",)


def test_sql_extractor_quiet_on_unsupported_ddl(capsys: pytest.CaptureFixture[str]) -> None:
    """Unmodelled DDL is skipped silently — no sqlglot chatter in build output."""
    sql = (
        "CREATE EXTENSION IF NOT EXISTS vector;"
        "CREATE USER app WITH PASSWORD 'pw';"
        "CREATE DATABASE app_db OWNER app;"
        "CREATE TABLE doc (id INT PRIMARY KEY);"
    )
    tables = sql_extractor.extract_tables(sql, source_file="init.sql", dialect="postgres")
    assert [t.name for t in tables] == ["doc"]  # the real table still extracted
    captured = capsys.readouterr()
    assert "unsupported syntax" not in (captured.out + captured.err)


def test_sql_extractor_skips_unparseable() -> None:
    tables = sql_extractor.extract_tables("this is not sql;;;", source_file="x.sql")
    assert tables == []


# -- Alembic (static AST) extraction ---------------------------------------
def test_alembic_extractor_reads_create_table() -> None:
    source = (DB_REPO / "alembic/versions/0001_documents.py").read_text()
    tables, migration = alembic_extractor.extract(source, source_file="m.py")
    assert migration is not None
    assert "create_table documents" in migration.operations
    table = tables[0]
    assert table.name == "documents"
    cols = {c.name: c for c in table.columns}
    assert cols["id"].primary_key is True
    assert cols["owner_id"].references_table == "users"
    assert cols["owner_id"].references_column == "id"
    assert cols["owner_id"].nullable is False
    assert cols["title"].nullable is True


def test_alembic_extractor_ignores_downgrade_ops() -> None:
    """Only forward (upgrade) operations are captured; downgrade drops are noise."""
    source = (
        "from alembic import op\n"
        "def upgrade():\n"
        "    op.create_table('t', __import__('sqlalchemy').Column('id', None))\n"
        "def downgrade():\n"
        "    op.drop_table('t')\n"
    )
    _, migration = alembic_extractor.extract(source, source_file="m.py")
    assert migration is not None
    assert any(op.startswith("create_table") for op in migration.operations)
    assert not any(op.startswith("drop_table") for op in migration.operations)


def test_alembic_extractor_table_level_constraints() -> None:
    """PK/FK/unique declared as table-level constraints must fold onto columns."""
    source = (DB_REPO / "alembic/versions/0002_collection_tables.py").read_text()
    tables, _ = alembic_extractor.extract(source, source_file="m.py")
    by_name = {t.name: t for t in tables}

    collection = by_name["collection"]
    cols = {c.name: c for c in collection.columns}
    assert cols["id"].primary_key is True  # from sa.PrimaryKeyConstraint("id")
    assert cols["name"].unique is True  # from sa.UniqueConstraint("name")
    assert any(c.kind == "primary_key" for c in collection.constraints)

    chunk = by_name["chunk"]
    chunk_cols = {c.name: c for c in chunk.columns}
    assert chunk_cols["id"].primary_key is True
    # FK declared via sa.ForeignKeyConstraint(["document_id"], ["document.id"]).
    assert chunk_cols["document_id"].references_table == "document"
    assert chunk_cols["document_id"].references_column == "id"
    assert any(c.kind == "foreign_key" for c in chunk.constraints)
    # A composite unique(document_id, seq_no) must NOT mark either column individually
    # unique, but the constraint itself is still recorded.
    assert chunk_cols["document_id"].unique is False
    assert chunk_cols["seq_no"].unique is False
    assert any(c.kind == "unique" and len(c.columns) == 2 for c in chunk.constraints)


# -- router -----------------------------------------------------------------
def test_extract_database_end_to_end() -> None:
    result = extract_database(DB_REPO)
    names = {t.name for t in result.tables}
    assert {"users", "documents"} <= names
    assert {t.id for t in result.tables}  # ids present
    assert len(result.tables) == len({t.id for t in result.tables})  # ids unique
    techs = {t.technology for t in result.tables}
    assert "flyway" in techs and "alembic" in techs


# -- pipeline pass ----------------------------------------------------------
def test_database_pass_populates_ir() -> None:
    from knowledge_builder.compiler import CompilationContext, CompilerConfig

    config = CompilerConfig(repo_path=DB_REPO, build_graph=False)
    context = CompilationContext(config)
    context.set_ir(Repository(metadata=Metadata(repo_path=str(DB_REPO), repo_name="db_repo")))
    DatabasePass().run(context)
    ir = context.require_ir()
    assert ir.db_tables and ir.db_technologies and ir.db_migrations


def test_database_pass_survives_missing_repo(tmp_path: Path) -> None:
    from knowledge_builder.compiler import CompilationContext, CompilerConfig

    config = CompilerConfig(repo_path=tmp_path / "nope", build_graph=False)
    context = CompilationContext(config)
    context.set_ir(Repository(metadata=Metadata(repo_path="x", repo_name="x")))
    DatabasePass().run(context)  # must not raise
    assert context.require_ir().db_tables == ()


# -- serialization round-trip + query --------------------------------------
@pytest.fixture
def db_kb(tmp_path: Path) -> Path:
    ext = extract_database(DB_REPO)
    repo = Repository(
        metadata=Metadata(repo_path=str(DB_REPO), repo_name="db_repo"),
        db_technologies=ext.technologies,
        db_tables=ext.tables,
        db_migrations=ext.migrations,
    )
    return KnowledgeWriter().write(repo, tmp_path / "knowledge.kb")


def test_db_round_trip_lossless(db_kb: Path) -> None:
    ext = extract_database(DB_REPO)
    with KnowledgeReader(db_kb) as reader:
        assert set(reader.db_tables()) == set(ext.tables)
        assert set(reader.db_technologies()) == set(ext.technologies)
        assert set(reader.db_migrations()) == set(ext.migrations)
        assert reader.counts()["db_tables"] == len(ext.tables)


def test_db_validation_clean(db_kb: Path) -> None:
    with KnowledgeReader(db_kb) as reader:
        report = validate_repository(reader.load_repository())
    assert report.ok


def test_db_query_by_kind(db_kb: Path) -> None:
    with KnowledgeBase(db_kb) as base:
        hits = base.query("users email", kinds=("db_table", "db_migration", "db_technology"))
        assert any(h.kind == "db_table" and h.name == "users" for h in hits)
        # kind filter excludes non-db entities
        assert all(h.kind.startswith("db_") for h in hits)
