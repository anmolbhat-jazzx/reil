"""DatabasePass (Phase 4) — extract the database layer from repository source.

Runs REIL's own :mod:`knowledge_builder.parser.db` subsystem over the checked-out
repository: fingerprint the stack (Alembic / Flyway / Django / raw SQL / …) and extract
tables, columns, constraints, indexes, and migrations — each with source evidence and a
confidence tier. This is *independent* of graphify's graph, so it never affects the code
layer. Extraction is best-effort: any failure is logged as a warning and leaves the DB
layer empty rather than failing the build.
"""

from __future__ import annotations

from knowledge_builder.compiler.context import CompilationContext
from knowledge_builder.compiler.pass_base import CompilerPass
from knowledge_builder.parser.db import extract_database


class DatabasePass(CompilerPass):
    """Extract database technologies, tables, and migrations from repo source."""

    name = "database"

    def run(self, context: CompilationContext) -> None:
        ir = context.require_ir()
        repo_path = context.config.repo_path
        try:
            extraction = extract_database(repo_path)
        except Exception as exc:  # noqa: BLE001 - extraction must never fail the build
            context.warning(self.name, "database extraction failed", error=str(exc))
            return

        context.set_ir(
            ir.evolve(
                db_technologies=extraction.technologies,
                db_tables=extraction.tables,
                db_migrations=extraction.migrations,
            )
        )
        context.stats["database"] = {
            "technologies": len(extraction.technologies),
            "tables": len(extraction.tables),
            "migrations": len(extraction.migrations),
        }
        context.info(
            self.name,
            "extracted database knowledge",
            technologies=len(extraction.technologies),
            tables=len(extraction.tables),
            migrations=len(extraction.migrations),
        )
