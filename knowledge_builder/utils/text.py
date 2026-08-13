"""Shared query tokenization: one definition of "do these words match?".

Both retrieval paths — the KB entity search and the graph-guided code retriever — must
agree on what a query word is and when it matches, or the same question yields different
answers depending on the command. Keeping the rules here is what stops them drifting.
"""

from __future__ import annotations

#: Words that carry no retrieval signal in a natural-language question.
STOPWORDS = frozenset(
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
        "work",
        "works",
        "handled",
        "happen",
        "happens",
        "where",
        "when",
        "why",
    }
)

#: Suffixes stripped so a query verb matches the noun in an identifier
#: (``chunked``/``chunking`` → ``chunk``, ``embedded``/``embedding`` → ``embed``).
_SUFFIXES = ("ing", "ed", "ions", "ion", "ies", "es", "s")


def keywords(query: str) -> list[str]:
    """Query keywords: alphanumeric tokens, length ≥ 3, minus stopwords."""
    raw = "".join(c if c.isalnum() else " " for c in query.lower()).split()
    return [t for t in raw if len(t) >= 3 and t not in STOPWORDS]


def normalize_token(token: str) -> str:
    """Reduce a word to a comparable stem.

    Deliberately conservative and dependency-free: strip one known suffix, undo the
    consonant doubling English adds before it (``embedd`` → ``embed``), and leave short
    or unrecognized words alone. Good enough to make ``chunked`` find ``chunk`` without
    the false merges an aggressive stemmer produces.
    """
    if len(token) <= 4:
        return token
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    # ``process``/``class`` end in ``s`` but are not plurals.
    if token.endswith(("ss", "us", "is")):
        return token
    for suffix in _SUFFIXES:
        # Require a stem of 4+ so root words ending in a suffix keep their shape:
        # ``embed`` must stay ``embed`` to match ``embedding``, not become ``emb``.
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            stem = token[: -len(suffix)]
            # ``embedded`` → ``embedd`` → ``embed``; ``process`` keeps its double ``s``.
            if len(stem) > 3 and stem[-1] == stem[-2] and stem[-1] not in "sl":
                stem = stem[:-1]
            return stem
    return token


def token_set(text: str) -> frozenset[str]:
    """Split ``text`` into normalized (stemmed) alphanumeric tokens."""
    raw = "".join(c if c.isalnum() else " " for c in text.lower()).split()
    return frozenset(normalize_token(tok) for tok in raw if tok)


def query_tokens(query: str) -> set[str]:
    """Stemmed, stopword-filtered tokens for a natural-language question."""
    return {normalize_token(t) for t in keywords(query)}


def is_test_path(text: str) -> bool:
    """True when a path or name marks test scaffolding rather than production code."""
    lowered = text.lower()
    return any(
        marker in lowered
        for marker in ("/tests/", "/test/", "test_", "_test.", "tests/", "__tests__")
    )
