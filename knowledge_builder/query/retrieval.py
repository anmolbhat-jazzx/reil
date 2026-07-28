"""Graph-guided symbol retrieval.

Selecting the right functions to read is a *graph* problem, not a flat keyword search:

1. **Seed** with high-precision matches — nodes whose file path or name contains the
   query keywords (so ``app/zip_upload/**`` and ``*zip*`` light up for "zip upload").
2. **Expand** along the graph edges (``contains``/``calls``/``imports``/…) a hop or two
   from those seeds, so structurally-connected functions come along even when their
   names share no keyword (e.g. ``confirm_zip_upload`` → ``run_zip_processing``).
3. **Rank** by seed-match strength decayed by graph distance.

Fully deterministic and zero-token — it uses the relationships already stored in the KB.
"""

from __future__ import annotations

from collections import defaultdict

from knowledge_builder.models.graph import GraphNode, Relationship
from knowledge_builder.models.symbol import Symbol

_STOPWORDS = frozenset(
    {
        "give",
        "me",
        "the",
        "a",
        "an",
        "of",
        "full",
        "summary",
        "architecture",
        "explain",
        "how",
        "does",
        "do",
        "what",
        "is",
        "are",
        "and",
        "or",
        "to",
        "for",
        "in",
        "on",
        "with",
        "this",
        "that",
        "please",
        "about",
        "all",
        "get",
        "show",
        "tell",
        "can",
        "you",
        "it",
        "its",
        "using",
        "use",
    }
)
_HOP_DECAY = 0.5
_MIN_CONTRIBUTION = 0.15
_MAX_SEED_FRONTIER = 40


def keywords(query: str) -> list[str]:
    """Query keywords: alphanumeric tokens, length ≥ 3, minus stopwords."""
    raw = "".join(c if c.isalnum() else " " for c in query.lower()).split()
    return [t for t in raw if len(t) >= 3 and t not in _STOPWORDS]


class GraphRetriever:
    """Ranks code symbols for a query via seed matching + graph expansion."""

    def __init__(
        self,
        symbols: tuple[Symbol, ...],
        nodes: tuple[GraphNode, ...],
        relationships: tuple[Relationship, ...],
    ) -> None:
        self._symbols = {s.id: s for s in symbols}
        self._node_text = {n.id: f"{n.label} {n.source_file or ''}".lower() for n in nodes}
        adjacency: dict[str, set[str]] = defaultdict(set)
        for rel in relationships:
            adjacency[rel.source_id].add(rel.target_id)
            adjacency[rel.target_id].add(rel.source_id)
        self._adjacency = adjacency

    def retrieve(self, query: str, *, hops: int = 1, max_candidates: int = 40) -> list[Symbol]:
        tokens = keywords(query)
        if not tokens:
            return []

        seeds: dict[str, float] = {}
        for node_id, text in self._node_text.items():
            score = float(sum(1 for tok in tokens if tok in text))
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
        ]
        ranked.sort(key=lambda pair: (-pair[0], pair[1].id))
        return [sym for _, sym in ranked[:max_candidates]]
