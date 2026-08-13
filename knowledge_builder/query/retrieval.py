"""Graph-guided symbol retrieval.

Selecting the right functions to read is a *graph* problem, not a flat keyword search:

1. **Seed** with high-precision matches — nodes whose name, path, or **docstring** share
   stemmed query words (so ``chunked``/``embedded`` reach ``chunk``/``embedding``).
2. **Expand** along the graph edges (``contains``/``calls``/``imports``/…) a hop or two
   from those seeds, so structurally-connected functions come along even when their
   names share no keyword (e.g. ``confirm_zip_upload`` → ``run_zip_processing``).
3. **Rank** by seed-match strength decayed by graph distance.

Tokenization is shared with the KB entity search (:mod:`knowledge_builder.utils.text`) so
both commands answer the same question the same way.

Fully deterministic and zero-token — it uses the relationships already stored in the KB.
"""

from __future__ import annotations

from collections import defaultdict

from knowledge_builder.models.graph import GraphNode, Relationship
from knowledge_builder.models.symbol import Symbol
from knowledge_builder.utils.text import (
    is_test_path,
    keywords,
    query_tokens,
    token_set,
)

__all__ = ["GraphRetriever", "keywords"]

#: Symbol kinds that are a location or a reference, never an answer to read.
_NON_CODE_KINDS: frozenset[str] = frozenset({"file", "module", "import", "variable"})
#: Score multiplier for test scaffolding, lifted when the query is about tests.
_TEST_SCORE_PENALTY = 0.4
_TEST_INTENT: frozenset[str] = frozenset({"test", "spec", "fixture", "mock"})
_HOP_DECAY = 0.5
_MIN_CONTRIBUTION = 0.15
_MAX_SEED_FRONTIER = 40


class GraphRetriever:
    """Ranks code symbols for a query via seed matching + graph expansion."""

    def __init__(
        self,
        symbols: tuple[Symbol, ...],
        nodes: tuple[GraphNode, ...],
        relationships: tuple[Relationship, ...],
    ) -> None:
        self._symbols = {s.id: s for s in symbols}
        # Seed text comes from the enriched symbol where we have one — its docstring and
        # qualified name describe what the code *does*, which a bare label does not.
        self._seed_tokens: dict[str, frozenset[str]] = {}
        self._is_test: dict[str, bool] = {}
        for node in nodes:
            symbol = self._symbols.get(node.id)
            parts = [node.label, node.source_file or ""]
            if symbol is not None:
                parts += [
                    symbol.name,
                    symbol.qualified_name or "",
                    symbol.docstring or "",
                    symbol.signature or "",
                ]
            self._seed_tokens[node.id] = token_set(" ".join(parts))
            self._is_test[node.id] = is_test_path(f"{node.source_file or ''} {node.label}")

        adjacency: dict[str, set[str]] = defaultdict(set)
        for rel in relationships:
            adjacency[rel.source_id].add(rel.target_id)
            adjacency[rel.target_id].add(rel.source_id)
        self._adjacency = adjacency

    def retrieve(self, query: str, *, hops: int = 1, max_candidates: int = 40) -> list[Symbol]:
        tokens = query_tokens(query)
        if not tokens:
            return []
        test_penalty = 1.0 if tokens & _TEST_INTENT else _TEST_SCORE_PENALTY

        seeds: dict[str, float] = {}
        for node_id, node_tokens in self._seed_tokens.items():
            score = float(len(tokens & node_tokens))
            if score and self._is_test[node_id]:
                score *= test_penalty
            if score:
                seeds[node_id] = score

        scores: dict[str, float] = dict(seeds)
        # Expand only from the strongest seeds so a common token can't explode the fan-out.
        frontier = dict(
            sorted(seeds.items(), key=lambda kv: kv[1], reverse=True)[:_MAX_SEED_FRONTIER]
        )
        for hop in range(hops):
            nxt: dict[str, float] = {}
            for node_id, score in frontier.items():
                contribution = score * (_HOP_DECAY ** (hop + 1))
                if contribution < _MIN_CONTRIBUTION:
                    continue
                for neighbor in self._adjacency.get(node_id, ()):
                    scores[neighbor] = scores.get(neighbor, 0.0) + contribution
                    nxt[neighbor] = max(nxt.get(neighbor, 0.0), score)
            frontier = nxt
            if not frontier:
                break

        ranked = [
            (score, sym)
            for node_id, score in scores.items()
            if (sym := self._symbols.get(node_id)) is not None
            and sym.source_location
            and sym.source_file
            # A file node slices from line 1 — i.e. the import block, never an answer.
            and sym.kind not in _NON_CODE_KINDS
        ]
        ranked.sort(key=lambda pair: (-pair[0], pair[1].id))
        return [sym for _, sym in ranked[:max_candidates]]
