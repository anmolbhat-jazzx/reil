"""LoadPass (Phase 3) — graphify output → Repository IR skeleton.

Orchestrates the parser layer: locate and read ``graphify-out/``, parse the node-link
graph and analysis sidecar, best-effort hash the repository's source files, and assemble
the initial IR. The parsed graph and report insights are stashed in
``context.artifacts`` for downstream passes.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from knowledge_builder.compiler.context import CompilationContext
from knowledge_builder.compiler.pass_base import CompilerPass
from knowledge_builder.parser.graph_parser import GraphParser
from knowledge_builder.parser.ir_builder import IRBuilder
from knowledge_builder.parser.loader import RepositoryLoader
from knowledge_builder.parser.report_parser import ReportParser
from knowledge_builder.parser.types import ParsedGraph
from knowledge_builder.passes import keys

_HASH_CHUNK = 65536


class LoadPass(CompilerPass):
    """Load graphify artifacts and build the IR skeleton."""

    name = "load"

    def __init__(
        self,
        loader: RepositoryLoader | None = None,
        graph_parser: GraphParser | None = None,
        report_parser: ReportParser | None = None,
        ir_builder: IRBuilder | None = None,
    ) -> None:
        self._loader = loader or RepositoryLoader()
        self._graph_parser = graph_parser or GraphParser()
        self._report_parser = report_parser or ReportParser()
        self._ir_builder = ir_builder or IRBuilder()

    def run(self, context: CompilationContext) -> None:
        config = context.config
        bundle = self._loader.load(config.resolved_graph_dir)
        parsed = self._graph_parser.parse(bundle)
        insights = self._report_parser.parse(bundle)

        file_hashes = self._hash_sources(context, parsed)

        repository = self._ir_builder.build(
            parsed,
            config,
            source_graph_hash=bundle.graph_hash,
            file_hashes=file_hashes,
        )
        context.set_ir(repository)
        context.artifacts[keys.PARSED_GRAPH] = parsed
        context.artifacts[keys.REPORT_INSIGHTS] = insights
        context.stats["graph"] = {
            "nodes": len(parsed.nodes),
            "edges": len(parsed.relationships),
            "hyperedges": len(parsed.hyperedges),
            "communities": len(parsed.communities),
        }
        context.info(
            self.name,
            "loaded graphify graph",
            nodes=len(parsed.nodes),
            edges=len(parsed.relationships),
            communities=len(parsed.communities),
        )

    def _hash_sources(self, context: CompilationContext, parsed: ParsedGraph) -> dict[str, str]:
        """Best-effort sha256 of each distinct source file that exists on disk."""
        repo_root = context.config.repo_path
        source_files = {n.source_file for n in parsed.nodes if n.source_file}
        hashes: dict[str, str] = {}
        for rel in sorted(source_files):
            digest = _hash_file(repo_root / rel)
            if digest is not None:
                hashes[rel] = digest
            else:
                context.warning(self.name, "source file not hashable", source_file=rel)
        return hashes


def _hash_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        hasher = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(_HASH_CHUNK):
                hasher.update(chunk)
        return hasher.hexdigest()
    except OSError:
        return None
