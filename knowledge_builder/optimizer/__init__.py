"""Compiler-style optimizations over the Repository IR (pure functions)."""

from __future__ import annotations

from knowledge_builder.optimizer.concept_dedup import deduplicate_concepts
from knowledge_builder.optimizer.reference_normalizer import normalize_references
from knowledge_builder.optimizer.summary_compressor import compress_summaries

__all__ = [
    "compress_summaries",
    "deduplicate_concepts",
    "normalize_references",
]
