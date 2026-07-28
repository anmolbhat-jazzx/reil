"""Real token counting via tiktoken.

Uses OpenAI's ``cl100k_base`` BPE — a genuine tokenizer (not a chars/N estimate). Token
counts are within a small margin of other modern LLM tokenizers; for exact Anthropic
counts you would call their token-counting API, but this gives real, reproducible,
offline numbers for measuring the knowledge-base context cost.
"""

from __future__ import annotations

import functools

_ENCODING_NAME = "cl100k_base"


@functools.lru_cache(maxsize=1)
def _encoder() -> object:
    import tiktoken

    return tiktoken.get_encoding(_ENCODING_NAME)


def tokenizer_name() -> str:
    """Name of the tokenizer used for counts."""
    return _ENCODING_NAME


def count_tokens(text: str) -> int:
    """Return the exact number of tokens in ``text``."""
    if not text:
        return 0
    enc = _encoder()
    return len(enc.encode(text))  # type: ignore[attr-defined]
