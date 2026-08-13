"""KnowledgeBase — the read-only runtime SDK over a ``knowledge.kb`` artifact.

No AI: :meth:`query` is deterministic keyword retrieval over the indexed entities and
their harvested summaries. Getters return typed IR models. Open a knowledge base with a
path and use it directly or as a context manager.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any

from knowledge_builder.models import (
    Concept,
    DbMigration,
    DbTable,
    DbTechnology,
    Module,
    Service,
    Summary,
    Symbol,
    Workflow,
)
from knowledge_builder.query.retrieval import GraphRetriever
from knowledge_builder.query.snippets import SnippetReader, SourceSnippet
from knowledge_builder.serializer.reader import KnowledgeReader
from knowledge_builder.utils.text import is_test_path as _is_test
from knowledge_builder.utils.text import query_tokens as _query_tokens
from knowledge_builder.utils.text import token_set as _token_set
from knowledge_builder.utils.tokens import count_tokens, tokenizer_name


@dataclass(frozen=True)
class QueryResult:
    """A single retrieval hit."""

    kind: str
    id: str
    name: str
    score: float
    detail: str | None = None


@dataclass(frozen=True)
class ContextResult:
    """An LLM-ready context assembled from the KB, with its exact token cost."""

    text: str
    tokens: int
    tokenizer: str
    hits: tuple[QueryResult, ...]


@dataclass(frozen=True)
class _Searchable:
    """One indexed entity: its identity plus stemmed name/body token sets."""

    kind: str
    id: str
    name: str
    name_tokens: frozenset[str]
    body_tokens: frozenset[str]
    #: Test scaffolding — still searchable, but never above production code.
    is_test: bool = False


#: Weight for a query token matching the entity name vs. its body (columns, summary, …).
_NAME_MATCH_WEIGHT = 2.0

#: Tie-break ordering at equal score (lower sorts first). Migrations are demoted.
_KIND_RANK: dict[str, int] = {"db_migration": 2}

#: Score multiplier for test scaffolding, so production code leads on "how does X work".
_TEST_SCORE_PENALTY = 0.4

#: Query words that mean the user actually wants tests, lifting the penalty above.
_TEST_INTENT_TOKENS: frozenset[str] = frozenset({"test", "spec", "fixture", "mock"})

#: Symbol kinds excluded from retrieval (files/modules/imports/variables are noise).
_NON_RETRIEVABLE_KINDS: frozenset[str] = frozenset({"file", "module", "import", "variable"})


@dataclass(frozen=True)
class HybridContextResult:
    """KB map + exact source snippets, with a token breakdown."""

    text: str
    tokens: int
    kb_tokens: int
    code_tokens: int
    tokenizer: str
    hits: tuple[QueryResult, ...]
    snippets: tuple[SourceSnippet, ...]


class KnowledgeBase:
    """Query a compiled ``knowledge.kb`` file."""

    def __init__(self, path: str | Path) -> None:
        self._reader = KnowledgeReader(path)
        self._searchables: list[_Searchable] | None = None
        self._symbols_by_id: dict[str, Symbol] | None = None
        self._retriever: GraphRetriever | None = None
        self._db_tables_by_id: dict[str, DbTable] | None = None
        self._db_migrations_by_id: dict[str, DbMigration] | None = None
        self._db_tech_by_id: dict[str, DbTechnology] | None = None

    # -- lifecycle ----------------------------------------------------------
    def close(self) -> None:
        self._reader.close()

    def __enter__(self) -> KnowledgeBase:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # -- getters ------------------------------------------------------------
    def get_module(self, name: str) -> Module | None:
        return self._reader.module_by_name(name)

    def get_service(self, name: str) -> Service | None:
        return self._reader.service_by_name(name)

    def get_workflow(self, name: str) -> Workflow | None:
        return self._reader.workflow_by_name(name)

    def get_concept(self, name: str) -> Concept | None:
        return self._reader.concept_by_label(name)

    def get_summary(self, module_id: str) -> Summary | None:
        return self._reader.summary_for_module(module_id)

    def db_technologies(self) -> tuple[DbTechnology, ...]:
        return self._reader.db_technologies()

    def db_tables(self) -> tuple[DbTable, ...]:
        return self._reader.db_tables()

    def db_migrations(self) -> tuple[DbMigration, ...]:
        return self._reader.db_migrations()

    def _db_tables(self) -> dict[str, DbTable]:
        if self._db_tables_by_id is None:
            self._db_tables_by_id = {t.id: t for t in self._reader.db_tables()}
        return self._db_tables_by_id

    def _db_migrations(self) -> dict[str, DbMigration]:
        if self._db_migrations_by_id is None:
            self._db_migrations_by_id = {m.id: m for m in self._reader.db_migrations()}
        return self._db_migrations_by_id

    def _db_technologies(self) -> dict[str, DbTechnology]:
        if self._db_tech_by_id is None:
            self._db_tech_by_id = {t.id: t for t in self._reader.db_technologies()}
        return self._db_tech_by_id

    # -- retrieval ----------------------------------------------------------
    def query(
        self, text: str, *, limit: int = 10, kinds: tuple[str, ...] | None = None
    ) -> list[QueryResult]:
        """Return entities ranked by keyword overlap with ``text`` (deterministic).

        ``kinds`` optionally restricts results to specific entity kinds (e.g.
        ``("db_table", "db_migration", "db_technology")`` for a database-only query).

        Matching is token-level (not raw substring) with light stemming, so ``documents``
        matches a ``document`` table and ``and``/``are`` no longer match by accident. A hit
        on the entity's *name* is weighted above an incidental body hit.
        """
        query_tokens = _query_tokens(text)
        if not query_tokens:
            return []
        allowed = set(kinds) if kinds else None
        # Only demote tests when the question is not itself about tests.
        penalty = 1.0 if query_tokens & _TEST_INTENT_TOKENS else _TEST_SCORE_PENALTY
        results: list[QueryResult] = []
        test_ids: dict[str, bool] = {}
        for entry in self._index():
            if allowed is not None and entry.kind not in allowed:
                continue
            score = 0.0
            for token in query_tokens:
                if token in entry.name_tokens:
                    score += _NAME_MATCH_WEIGHT
                elif token in entry.body_tokens:
                    score += 1.0
            if score and entry.is_test:
                # A test named after a feature (``test_zip_upload_processing``) matches
                # more query words than the feature itself, so a tie-break is too weak —
                # test scaffolding needs an actual penalty, lifted when the question is
                # explicitly about tests.
                score *= penalty
            if score:
                test_ids[entry.id] = entry.is_test
                results.append(
                    QueryResult(kind=entry.kind, id=entry.id, name=entry.name, score=score)
                )
        # Rank production code above test scaffolding: a test *about* a feature should
        # never outrank the feature itself. Then prefer definitional entities over
        # migrations, which are history and tend to be noisy.
        results.sort(
            key=lambda r: (
                -r.score,
                test_ids.get(r.id, False),
                _KIND_RANK.get(r.kind, 1),
                r.kind,
                r.name,
            )
        )
        return results[:limit]

    def build_context(
        self, text: str, *, limit: int = 8, kinds: tuple[str, ...] | None = None
    ) -> ContextResult:
        """Assemble the scoped, LLM-ready context for ``text`` and count its tokens.

        This is exactly what a "DB approach" would feed a model to answer the question —
        so its token count is the real cost of using the knowledge base instead of raw
        source. ``kinds`` optionally restricts the context to specific entity kinds.
        """
        hits = self.query(text, limit=limit, kinds=kinds)
        rendered = self._render_context(text, hits)
        return ContextResult(
            text=rendered,
            tokens=count_tokens(rendered),
            tokenizer=tokenizer_name(),
            hits=tuple(hits),
        )

    def _render_context(self, text: str, hits: list[QueryResult]) -> str:
        lines = [f"# Question: {text}", "", "## Relevant repository knowledge", ""]
        for hit in hits:
            if hit.kind == "module":
                module = self.get_module(hit.name)
                lines.append(f"### Module: {hit.name}")
                if module is not None:
                    summary = self.get_summary(module.id)
                    if summary is not None:
                        if summary.purpose:
                            lines.append(f"purpose: {summary.purpose}")
                        if summary.responsibilities:
                            lines.append("responsibilities: " + ", ".join(summary.responsibilities))
                        if summary.public_apis:
                            lines.append("public APIs: " + ", ".join(summary.public_apis))
                        if summary.concepts:
                            lines.append("concepts: " + ", ".join(summary.concepts))
                        if summary.dependencies:
                            lines.append("depends on: " + ", ".join(summary.dependencies))
                        if summary.workflows:
                            lines.append("workflows: " + ", ".join(summary.workflows))
            elif hit.kind == "concept":
                concept = self.get_concept(hit.name)
                detail = f": {concept.rationale}" if concept and concept.rationale else ""
                lines.append(f"### Concept: {hit.name}{detail}")
            elif hit.kind == "symbol":
                lines.extend(_render_symbol(self._symbol_index().get(hit.id)))
            elif hit.kind == "db_table":
                lines.extend(_render_db_table(self._db_tables().get(hit.id)))
            elif hit.kind == "db_migration":
                lines.extend(_render_db_migration(self._db_migrations().get(hit.id)))
            elif hit.kind == "db_technology":
                lines.extend(_render_db_technology(self._db_technologies().get(hit.id)))
            else:
                lines.append(f"### {hit.kind.title()}: {hit.name}")
            lines.append("")
        return "\n".join(lines).strip()

    def build_hybrid_context(
        self,
        text: str,
        repo_path: str | Path,
        *,
        limit: int = 8,
        hops: int = 1,
        max_symbols: int = 40,
        max_lines: int = 60,
        code_token_budget: int = 2000,
    ) -> HybridContextResult:
        """KB map + exact source slices for the symbols the graph points at.

        Uses the KB as a graph index: the query builds the summary map, while a
        graph-guided retriever (precise seeds + edge expansion) selects which functions
        to read. Only those precise line ranges are read from ``repo_path`` (never whole
        files), stopping once ``code_token_budget`` code tokens are collected.
        """
        hits = self.query(text, limit=limit)
        kb_text = self._render_context(text, hits)

        symbols = self._symbol_index()
        candidates = self._retriever_engine().retrieve(text, hops=hops, max_candidates=max_symbols)

        reader = SnippetReader(Path(repo_path), max_lines=max_lines)
        all_snippets = reader.read_for_symbols(candidates, tuple(symbols.values()))

        kept: list[SourceSnippet] = []
        used = 0
        for snippet in all_snippets:
            cost = count_tokens(snippet.code)
            if kept and used + cost > code_token_budget:
                break
            kept.append(snippet)
            used += cost

        code_text = _render_snippets(kept)
        full = f"{kb_text}\n\n## Exact code\n\n{code_text}".strip() if kept else kb_text
        return HybridContextResult(
            text=full,
            tokens=count_tokens(full),
            kb_tokens=count_tokens(kb_text),
            code_tokens=count_tokens(code_text) if kept else 0,
            tokenizer=tokenizer_name(),
            hits=tuple(hits),
            snippets=tuple(kept),
        )

    def _symbol_index(self) -> dict[str, Symbol]:
        if self._symbols_by_id is None:
            self._symbols_by_id = {s.id: s for s in self._reader.symbols()}
        return self._symbols_by_id

    def _retriever_engine(self) -> GraphRetriever:
        if self._retriever is None:
            self._retriever = GraphRetriever(
                self._reader.symbols(),
                self._reader.graph_nodes(),
                self._reader.relationships(),
            )
        return self._retriever

    # -- introspection ------------------------------------------------------
    def stats(self) -> dict[str, Any]:
        meta = self._reader.metadata()
        return {
            "repo_name": meta.repo_name,
            "schema_version": meta.schema_version,
            "builder_version": meta.builder_version,
            "graphify_version": meta.graphify_version,
            "counts": self._reader.counts(),
        }

    def metadata(self) -> dict[str, Any]:
        return self._reader.metadata().model_dump(mode="json")

    # -- internals ----------------------------------------------------------
    def _index(self) -> list[_Searchable]:
        if self._searchables is not None:
            return self._searchables

        summaries = {s.module_id: s for s in self._reader.summaries()}
        index: list[_Searchable] = []

        def add(kind: str, entity_id: str, name: str, body: str, origin: str = "") -> None:
            index.append(
                _Searchable(
                    kind=kind,
                    id=entity_id,
                    name=name,
                    name_tokens=_token_set(name),
                    body_tokens=_token_set(f"{name} {body}"),
                    is_test=_is_test(f"{origin} {name}"),
                )
            )

        for module in self._reader.modules():
            summary = summaries.get(module.id)
            add(
                "module",
                module.id,
                module.name,
                _module_haystack(module, summary),
                origin=" ".join(module.source_paths),
            )
        for service in self._reader.services():
            add("service", service.id, service.name, "")
        for controller in self._reader.controllers():
            add("controller", controller.id, controller.name, "")
        for api in self._reader.apis():
            add("api", api.id, api.name, " ".join(filter(None, (api.method, api.path))))
        for concept in self._reader.concepts():
            add("concept", concept.id, concept.label, concept.rationale or "")
        for workflow in self._reader.workflows():
            add("workflow", workflow.id, workflow.name, "")
        for symbol in self._reader.symbols():
            # Exclude non-code kinds (files/modules/imports) so they don't pollute
            # retrieval — federation search parity.
            if symbol.kind in _NON_RETRIEVABLE_KINDS:
                continue
            display = symbol.name or symbol.label
            body = " ".join(
                filter(None, (symbol.qualified_name, symbol.signature, symbol.docstring))
            )
            add("symbol", symbol.id, display, body, origin=symbol.source_file or "")
        for table in self._reader.db_tables():
            columns = " ".join(c.name for c in table.columns)
            add("db_table", table.id, table.name, f"{table.technology or ''} {columns}")
        for migration in self._reader.db_migrations():
            ops = " ".join(migration.operations)
            add("db_migration", migration.id, migration.name, f"{migration.technology or ''} {ops}")
        for tech in self._reader.db_technologies():
            add("db_technology", tech.id, tech.name, tech.category)

        self._searchables = index
        return index


def _module_haystack(module: Module, summary: Summary | None) -> str:
    parts = [module.name]
    if summary:
        parts.extend(
            [
                summary.purpose or "",
                *summary.responsibilities,
                *summary.concepts,
                *summary.workflows,
                *summary.public_apis,
            ]
        )
    return " ".join(parts).lower()


def _render_symbol(symbol: Symbol | None) -> list[str]:
    """Render a symbol with the detail source enrichment recovered.

    A bare name tells a model nothing; the signature and docstring are the whole reason
    those fields are extracted.
    """
    if symbol is None:
        return []
    header = f"### {(symbol.kind or 'symbol').title()}: {symbol.qualified_name or symbol.name}"
    if symbol.signature:
        header += symbol.signature
    lines = [header]
    where = symbol.source_file or "?"
    if symbol.start_line:
        where = f"{where}:L{symbol.start_line}"
    lines.append(f"defined at: {where}")
    if symbol.docstring:
        lines.append(symbol.docstring.strip().splitlines()[0])
    return lines


def _render_db_table(table: DbTable | None) -> list[str]:
    if table is None:
        return []
    where = table.source_file or "?"
    if table.source_location:
        where = f"{where}:{table.source_location}"
    header = f"### Table: {table.name}"
    if table.technology:
        header += f"  ({table.technology}, {table.confidence.value}, {where})"
    lines = [header]
    for col in table.columns:
        flags = []
        if col.primary_key:
            flags.append("PK")
        if col.unique:
            flags.append("unique")
        if col.nullable is False:
            flags.append("not null")
        if col.references_table:
            target = col.references_table
            if col.references_column:
                target += f".{col.references_column}"
            flags.append(f"FK→{target}")
        suffix = f"  [{', '.join(flags)}]" if flags else ""
        lines.append(f"- {col.name}: {col.data_type or '?'}{suffix}")
    for con in table.constraints:
        cols = ", ".join(con.columns)
        detail = (
            f" → {con.references_table}({', '.join(con.references_columns)})"
            if con.references_table
            else ""
        )
        lines.append(f"- constraint {con.kind}({cols}){detail}")
    for idx in table.indexes:
        kind = "unique index" if idx.unique else "index"
        lines.append(f"- {kind} {idx.name or ''} ({', '.join(idx.columns)})".replace("  ", " "))
    return lines


def _render_db_migration(migration: DbMigration | None) -> list[str]:
    if migration is None:
        return []
    lines = [f"### Migration: {migration.name}  ({migration.technology or '?'})"]
    if migration.source_file:
        lines.append(f"file: {migration.source_file}")
    if migration.operations:
        lines.append("operations: " + ", ".join(migration.operations))
    return lines


def _render_db_technology(tech: DbTechnology | None) -> list[str]:
    if tech is None:
        return []
    line = f"### Database technology: {tech.name} ({tech.category}, {tech.confidence.value})"
    evidence = f"\nevidence: {', '.join(tech.evidence)}" if tech.evidence else ""
    return [line + evidence]


def _render_snippets(snippets: list[SourceSnippet]) -> str:
    blocks: list[str] = []
    for s in snippets:
        blocks.append(f"### {s.symbol}  ({s.file}:L{s.start}-L{s.end})\n```\n{s.code}\n```")
    return "\n\n".join(blocks)
