"""GraphBuildPass — make the workspace hold graph files, end to end.

Runs first. Guarantees ``config.resolved_graph_dir`` (the workspace) contains a
``graph.json`` by, in order:

1. Skipping if the workspace already has one (unless ``rebuild_graph``).
2. Otherwise locating a graphify output dir — running graphify to create it when
   ``build_graph`` is set and none exists — then **importing** the needed files into the
   workspace.
3. Deleting the transient ``graphify-out/`` **only if this pass created it**, so a
   pre-existing (e.g. committed) graphify-out is never destroyed.

The result: everything the compiler needs lives in one workspace folder the user can
gitignore.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from knowledge_builder.compiler.context import CompilationContext
from knowledge_builder.compiler.pass_base import CompilerPass
from knowledge_builder.parser.graphify_runner import (
    GraphBuildError,
    GraphifyRunner,
    SubprocessGraphifyRunner,
)

GRAPH_FILE = "graph.json"
#: Files imported from graphify-out into the workspace (graph + sidecars, if present).
_IMPORT_FILES = (
    "graph.json",
    ".graphify_labels.json",
    ".graphify_analysis.json",
    "manifest.json",
)


class GraphBuildPass(CompilerPass):
    """Prepare the workspace with graphify's graph files (running graphify if needed)."""

    name = "graph-build"

    def __init__(self, runner: GraphifyRunner | None = None) -> None:
        self._runner = runner or SubprocessGraphifyRunner()

    def run(self, context: CompilationContext) -> None:
        cfg = context.config
        workspace = cfg.resolved_workspace
        workspace_graph = workspace / GRAPH_FILE

        if workspace_graph.is_file() and not cfg.rebuild_graph:
            context.info(self.name, "using cached graph in workspace", workspace=str(workspace))
            return

        source_dir = cfg.transient_graphify_dir
        created = False

        if cfg.rebuild_graph or not (source_dir / GRAPH_FILE).is_file():
            if not cfg.build_graph:
                raise GraphBuildError(
                    f"no graph at {source_dir / GRAPH_FILE} and --no-build-graph is set. "
                    "Run graphify first, or drop --no-build-graph."
                )
            context.info(self.name, "building graphify graph", repo=str(cfg.repo_path))
            source_dir = self._runner.run(cfg.repo_path)
            created = True

        imported = _import_files(source_dir, workspace)
        context.info(self.name, "imported graph files", files=imported, workspace=str(workspace))

        if created and cfg.graphify_out is None:
            shutil.rmtree(source_dir, ignore_errors=True)
            context.info(self.name, "removed transient graphify-out", dir=str(source_dir))

        context.stats["graph_build"] = {
            "workspace": str(workspace),
            "ran_graphify": created,
            "imported": imported,
        }


def _import_files(source_dir: Path, workspace: Path) -> list[str]:
    workspace.mkdir(parents=True, exist_ok=True)
    imported: list[str] = []
    for name in _IMPORT_FILES:
        src = source_dir / name
        if src.is_file():
            shutil.copy2(src, workspace / name)
            imported.append(name)
    return imported
