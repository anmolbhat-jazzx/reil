"""Technology detection by declarative fingerprints (repo-/stack-agnostic).

Which database stack a repository uses — Alembic vs Flyway vs Django vs raw SQL — is
determined by matching *data*, not by hard-coded branches. Each :class:`Fingerprint` is
one registry row describing how a technology shows up:

* ``manifest_tokens`` — substrings in dependency manifests (``requirements.txt``,
  ``pom.xml``, ``package.json``, ``go.mod``, …). A declared dependency is strong evidence.
* ``path_globs`` — conventional file locations (``**/db/migration/V*__*.sql``).
* ``content_regexes`` — telltale source markers (``from alembic import op``, ``@Entity``).

Adding support for a new technology means appending a row to :data:`REGISTRY` — no code
changes. An unrecognized stack simply yields no technology row; extraction then falls
back to the SQL-level facts it can still read, and the rest stays *unknown* (never
inferred).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path

from knowledge_builder.models.base import Confidence
from knowledge_builder.models.database import DbTechnology
from knowledge_builder.parser.db.walk import iter_files, read_text

#: Files whose contents are scanned for dependency tokens.
MANIFEST_NAMES: frozenset[str] = frozenset(
    {
        "requirements.txt",
        "requirements-dev.txt",
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
        "Pipfile",
        "poetry.lock",
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
        "package.json",
        "go.mod",
        "Gemfile",
        "composer.json",
    }
)

#: Extensions worth scanning for content markers (bounded single pass).
_SCANNABLE_EXTS: frozenset[str] = frozenset(
    {".py", ".java", ".kt", ".ts", ".js", ".go", ".rb", ".prisma", ".xml", ".yaml", ".yml"}
)
#: Cap on files whose content is scanned (detection is a signal, not exhaustive).
_MAX_CONTENT_FILES = 6000


@dataclass(frozen=True)
class Fingerprint:
    """A declarative signature for one database technology."""

    id: str
    name: str
    #: ``migration`` | ``orm`` | ``dialect`` | ``driver``.
    category: str
    manifest_tokens: tuple[str, ...] = ()
    path_globs: tuple[str, ...] = ()
    content_regexes: tuple[str, ...] = ()
    #: sqlglot dialect name, for ``dialect`` fingerprints only.
    dialect: str | None = None


#: The technology registry. Order is cosmetic; matching is independent per row.
REGISTRY: tuple[Fingerprint, ...] = (
    # -- migration frameworks --------------------------------------------------
    Fingerprint(
        id="alembic",
        name="Alembic",
        category="migration",
        manifest_tokens=("alembic",),
        path_globs=("*alembic.ini", "*/alembic/versions/*.py", "*/migrations/versions/*.py"),
        content_regexes=(r"from\s+alembic\s+import\s+op", r"^\s*def\s+upgrade\s*\("),
    ),
    Fingerprint(
        id="flyway",
        name="Flyway",
        category="migration",
        manifest_tokens=("org.flywaydb", "flyway-core", "flyway"),
        path_globs=("*/db/migration/*.sql", "*/resources/db/migration/*.sql", "*V[0-9]*__*.sql"),
    ),
    Fingerprint(
        id="liquibase",
        name="Liquibase",
        category="migration",
        manifest_tokens=("liquibase",),
        path_globs=("*changelog*.xml", "*changelog*.yaml", "*changelog*.yml", "*changelog*.json"),
        content_regexes=(r"databaseChangeLog", r"<changeSet"),
    ),
    Fingerprint(
        id="django-migrations",
        name="Django migrations",
        category="migration",
        manifest_tokens=("Django", "django"),
        path_globs=("*/migrations/0001_initial.py", "*/migrations/[0-9][0-9][0-9][0-9]_*.py"),
        content_regexes=(r"from\s+django\.db\s+import\s+migrations", r"migrations\.CreateModel"),
    ),
    Fingerprint(
        id="rails-activerecord",
        name="Rails ActiveRecord",
        category="migration",
        manifest_tokens=("activerecord", "rails"),
        path_globs=("*/db/migrate/*.rb", "*/db/schema.rb"),
        content_regexes=(r"ActiveRecord::Migration",),
    ),
    # -- ORMs ------------------------------------------------------------------
    Fingerprint(
        id="sqlalchemy",
        name="SQLAlchemy",
        category="orm",
        manifest_tokens=("SQLAlchemy", "sqlalchemy"),
        content_regexes=(r"__tablename__", r"declarative_base", r"DeclarativeBase"),
    ),
    Fingerprint(
        id="django-orm",
        name="Django ORM",
        category="orm",
        manifest_tokens=("Django", "django"),
        path_globs=("*/models.py", "*/models/*.py"),
        content_regexes=(r"class\s+\w+\(.*models\.Model", r"from\s+django\.db\s+import\s+models"),
    ),
    Fingerprint(
        id="hibernate-jpa",
        name="Hibernate / JPA",
        category="orm",
        manifest_tokens=(
            "hibernate",
            "jakarta.persistence",
            "javax.persistence",
            "spring-boot-starter-data-jpa",
        ),
        content_regexes=(r"@Entity\b", r"@Table\s*\(", r"@Column\s*\("),
    ),
    Fingerprint(
        id="prisma",
        name="Prisma",
        category="orm",
        manifest_tokens=("prisma", "@prisma/client"),
        path_globs=("*schema.prisma",),
        content_regexes=(r"datasource\s+\w+\s*\{", r"generator\s+\w+\s*\{"),
    ),
    Fingerprint(
        id="typeorm",
        name="TypeORM",
        category="orm",
        manifest_tokens=("typeorm",),
        content_regexes=(r"@Entity\s*\(", r'from\s+["\']typeorm["\']'),
    ),
    Fingerprint(
        id="sequelize",
        name="Sequelize",
        category="orm",
        manifest_tokens=("sequelize",),
        content_regexes=(r"sequelize\.define", r"extends\s+Model"),
    ),
    Fingerprint(
        id="gorm",
        name="GORM",
        category="orm",
        manifest_tokens=("gorm.io/gorm", "jinzhu/gorm"),
        content_regexes=(r"gorm\.Model", r'gorm:"'),
    ),
    # -- raw SQL (dialect-neutral) --------------------------------------------
    Fingerprint(
        id="raw-sql",
        name="Raw SQL",
        category="migration",
        path_globs=("*.sql",),
    ),
    # -- dialects / drivers (inform the SQL parser) ---------------------------
    Fingerprint(
        id="postgres",
        name="PostgreSQL",
        category="dialect",
        manifest_tokens=("psycopg2", "psycopg", "asyncpg", "org.postgresql", "pg8000"),
        dialect="postgres",
    ),
    Fingerprint(
        id="mysql",
        name="MySQL",
        category="dialect",
        manifest_tokens=("mysqlclient", "PyMySQL", "pymysql", "mysql-connector", "com.mysql"),
        dialect="mysql",
    ),
    Fingerprint(
        id="sqlite",
        name="SQLite",
        category="dialect",
        manifest_tokens=("aiosqlite",),
        dialect="sqlite",
    ),
    Fingerprint(
        id="oracle",
        name="Oracle",
        category="dialect",
        manifest_tokens=("cx_Oracle", "oracledb", "ojdbc"),
        dialect="oracle",
    ),
    Fingerprint(
        id="mssql",
        name="SQL Server",
        category="dialect",
        manifest_tokens=("pyodbc", "pymssql", "mssql-jdbc"),
        dialect="tsql",
    ),
)


@dataclass
class _Signals:
    """Accumulated evidence for one fingerprint during a scan."""

    manifest: bool = False
    path: bool = False
    content: bool = False
    evidence: list[str] = field(default_factory=list)

    def add(self, source: str) -> None:
        if source not in self.evidence and len(self.evidence) < 5:
            self.evidence.append(source)

    @property
    def matched(self) -> bool:
        return self.manifest or self.path or self.content

    @property
    def confidence(self) -> Confidence:
        # A declared dependency or a conventional location is strong; a lone code
        # marker is only suggestive.
        return Confidence.EXTRACTED if (self.manifest or self.path) else Confidence.INFERRED


def detect(repo_path: Path) -> tuple[DbTechnology, ...]:
    """Fingerprint ``repo_path`` and return the database technologies in use."""
    signals: dict[str, _Signals] = {fp.id: _Signals() for fp in REGISTRY}
    compiled = {
        fp.id: [re.compile(rx, re.MULTILINE) for rx in fp.content_regexes] for fp in REGISTRY
    }

    manifest_blobs: list[tuple[str, str]] = []
    content_files: list[tuple[str, Path]] = []

    for entry in iter_files(repo_path):
        name = Path(entry.rel).name
        if name in MANIFEST_NAMES:
            text = read_text(entry.path)
            if text is not None:
                manifest_blobs.append((entry.rel, text))
        # Path-glob signals (cheap, no read).
        for fp in REGISTRY:
            if fp.path_globs and _matches_glob(entry.rel, fp.path_globs):
                sig = signals[fp.id]
                sig.path = True
                sig.add(entry.rel)
        if Path(entry.rel).suffix.lower() in _SCANNABLE_EXTS:
            content_files.append((entry.rel, entry.path))

    # Manifest token signals.
    for rel, text in manifest_blobs:
        for fp in REGISTRY:
            if fp.manifest_tokens and any(tok in text for tok in fp.manifest_tokens):
                sig = signals[fp.id]
                sig.manifest = True
                sig.add(rel)

    # One bounded content pass; stop scanning a fingerprint once satisfied.
    _scan_content(content_files, compiled, signals)

    detected: list[DbTechnology] = []
    for fp in REGISTRY:
        sig = signals[fp.id]
        if not sig.matched:
            continue
        detected.append(
            DbTechnology(
                id=fp.id,
                name=fp.name,
                category=fp.category,
                confidence=sig.confidence,
                evidence=tuple(sig.evidence),
            )
        )
    return tuple(detected)


def dialect_for(technologies: tuple[DbTechnology, ...]) -> str | None:
    """Return the sqlglot dialect name for the highest-confidence detected dialect."""
    by_id = {fp.id: fp for fp in REGISTRY}
    ranked = sorted(
        (t for t in technologies if t.category == "dialect"),
        key=lambda t: 0 if t.confidence is Confidence.EXTRACTED else 1,
    )
    for tech in ranked:
        fp = by_id.get(tech.id)
        if fp and fp.dialect:
            return fp.dialect
    return None


def _matches_glob(rel: str, globs: tuple[str, ...]) -> bool:
    return any(fnmatch(rel, pat) or fnmatch(Path(rel).name, pat) for pat in globs)


def _scan_content(
    content_files: list[tuple[str, Path]],
    compiled: dict[str, list[re.Pattern[str]]],
    signals: dict[str, _Signals],
) -> None:
    pending = {fp_id for fp_id, pats in compiled.items() if pats}
    for rel, path in content_files[:_MAX_CONTENT_FILES]:
        if not pending:
            break
        text = read_text(path)
        if text is None:
            continue
        satisfied: list[str] = []
        for fp_id in pending:
            if any(pat.search(text) for pat in compiled[fp_id]):
                sig = signals[fp_id]
                sig.content = True
                sig.add(rel)
                satisfied.append(fp_id)
        pending.difference_update(satisfied)
