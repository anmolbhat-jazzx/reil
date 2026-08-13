"""Symbol source-enrichment subsystem.

Fills the fields graphify cannot provide — kind, qualified_name, signature, docstring,
exact line/column ranges, and modifier flags — by statically parsing source. Python uses
the standard-library ``ast``; other languages plug in as additional providers, and
unparsed languages keep their graphify-only baseline.
"""

from __future__ import annotations

from knowledge_builder.parser.symbols.enrich import enrich_symbols

__all__ = ["enrich_symbols"]
