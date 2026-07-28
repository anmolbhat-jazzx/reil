"""IRBuilder — assemble a Repository IR skeleton from a parsed graph.

The skeleton carries the faithful graph layer (nodes + relationships) and complete
metadata. Typed projections (symbols, modules, concepts, …) are left empty here and
populated by the Phase 4/5 passes.
"""

from __future__ import annotations

from knowledge_builder import __version__
from knowledge_builder.compiler.config import CompilerConfig
from knowledge_builder.models.metadata import Metadata
from knowledge_builder.models.repository import Repository
from knowledge_builder.parser.types import ParsedGraph


class IRBuilder:
    """Builds the initial :class:`Repository` from a :class:`ParsedGraph`."""

    def build(
        self,
        parsed: ParsedGraph,
        config: CompilerConfig,
        *,
        source_graph_hash: str,
        file_hashes: dict[str, str] | None = None,
    ) -> Repository:
        metadata = Metadata(
            repo_path=str(config.repo_path),
            repo_name=config.repo_path.name or str(config.repo_path),
            builder_version=config.builder_version or __version__,
            graphify_version=parsed.graphify_version,
            directed=parsed.directed,
            multigraph=parsed.multigraph,
            node_count=len(parsed.nodes),
            edge_count=len(parsed.relationships),
            community_count=len(parsed.communities),
            source_graph_hash=source_graph_hash,
            file_hashes=file_hashes or {},
        )
        return Repository(
            metadata=metadata,
            graph_nodes=parsed.nodes,
            relationships=parsed.relationships,
        )
