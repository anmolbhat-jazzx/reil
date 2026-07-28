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

from knowledge_builder.models import Concept, Module, Service, Summary, Symbol, Workflow
from knowledge_builder.query.retrieval import GraphRetriever
from knowledge_builder.query.snippets import SnippetReader, SourceSnippet
from knowledge_builder.serializer.reader import KnowledgeReader
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
        self._searchables: list[tuple[str, str, str, str]] | None = None
        self._symbols_by_id: dict[str, Symbol] | None = None
        self._retriever: GraphRetriever | None = None

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

    # -- retrieval ----------------------------------------------------------
    def query(self, text: str, *, limit: int = 10) -> list[QueryResult]:
        """Return entities ranked by keyword overlap with ``text`` (deterministic)."""
        tokens = _tokenize(text)
        if not tokens:
            return []
        results: list[QueryResult] = []
        for kind, entity_id, name, haystack in self._index():
            score = sum(1 for token in tokens if token in haystack)
            if score:
                results.append(QueryResult(kind=kind, id=entity_id, name=name, score=float(score)))
        results.sort(key=lambda r: (-r.score, r.kind, r.name))
        return results[:limit]

    def build_context(self, text: str, *, limit: int = 8) -> ContextResult:
        """Assemble the scoped, LLM-ready context for ``text`` and count its tokens.

        This is exactly what a "DB approach" would feed a model to answer the question —
        so its token count is the real cost of using the knowledge base instead of raw
        source.
        """
        hits = self.query(text, limit=limit)
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
    def _index(self) -> list[tuple[str, str, str, str]]:
        if self._searchables is not None:
            return self._searchables

        summaries = {s.module_id: s for s in self._reader.summaries()}
        index: list[tuple[str, str, str, str]] = []

        for module in self._reader.modules():
            summary = summaries.get(module.id)
            index.append(("module", module.id, module.name, _module_haystack(module, summary)))
        for service in self._reader.services():
            index.append(("service", service.id, service.name, service.name.lower()))
        for controller in self._reader.controllers():
            index.append(("controller", controller.id, controller.name, controller.name.lower()))
        for api in self._reader.apis():
            hay = " ".join(filter(None, (api.name, api.method, api.path))).lower()
            index.append(("api", api.id, api.name, hay))
        for concept in self._reader.concepts():
            hay = f"{concept.label} {concept.rationale or ''}".lower()
            index.append(("concept", concept.id, concept.label, hay))
        for workflow in self._reader.workflows():
            index.append(("workflow", workflow.id, workflow.name, workflow.name.lower()))
        for symbol in self._reader.symbols():
            index.append(("symbol", symbol.id, symbol.label, symbol.label.lower()))

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


def _render_snippets(snippets: list[SourceSnippet]) -> str:
    blocks: list[str] = []
    for s in snippets:
        blocks.append(f"### {s.symbol}  ({s.file}:L{s.start}-L{s.end})\n```\n{s.code}\n```")
    return "\n\n".join(blocks)


def _tokenize(text: str) -> list[str]:
    normalized = "".join(c if c.isalnum() else " " for c in text.lower())
    return normalized.split()
