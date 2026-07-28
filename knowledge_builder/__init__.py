"""Repository Intelligence Layer.

Compile any software repository into a portable, AI-native ``knowledge.kb`` artifact.

The public surface grows as the phases land. The two entry points are:

* ``knowledge_builder.build.build_knowledge`` — compile a repository (Phase 10).
* ``knowledge_builder.query.KnowledgeBase`` — query a built artifact (Phase 9).

They are re-exported from this module once their phases are implemented.
"""

from __future__ import annotations

from knowledge_builder.query import KnowledgeBase

__version__ = "0.1.0"

__all__ = ["KnowledgeBase", "__version__"]
