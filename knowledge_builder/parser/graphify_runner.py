"""GraphifyRunner — invoke graphify to build a graph for a repository.

Isolated behind a small protocol so the compiler depends on an interface, not on the
graphify binary. The default implementation shells out; tests inject a fake.

Note: graphify exposes no single ``build`` subcommand — its structural (AST) extraction
is ``graphify update <repo>``, which is deterministic and needs no LLM. Community
*labeling* would use an LLM, but with no API backend graphify falls back to placeholder
labels (the Hybrid module strategy handles those). So this runs the **zero-token**
AST path.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Protocol

from knowledge_builder.utils.errors import KnowledgeBuilderError
from knowledge_builder.utils.logging import get_logger

#: The command used to build a graph, AST-only (no LLM, no tokens).
#: ``{repo}`` is substituted with the repository path.
GRAPHIFY_BUILD_COMMAND: tuple[str, ...] = ("graphify", "update", "{repo}")


class GraphBuildError(KnowledgeBuilderError):
    """Raised when graphify cannot be run or produces no graph."""


class GraphifyRunner(Protocol):
    """Produces a ``graphify-out/graph.json`` for a repository."""

    def run(self, repo_path: Path) -> Path:
        """Build the graph for ``repo_path`` and return the graphify-out directory."""
        ...


class SubprocessGraphifyRunner:
    """Runs the real ``graphify`` CLI in a subprocess (AST-only)."""

    def __init__(self, command: tuple[str, ...] = GRAPHIFY_BUILD_COMMAND) -> None:
        self._command = command

    def run(self, repo_path: Path) -> Path:
        if shutil.which(self._command[0]) is None:
            raise GraphBuildError(
                f"'{self._command[0]}' is not installed or not on PATH. Install graphify, "
                "or run `knowledge build --no-build-graph` against an existing graphify-out/."
            )
        argv = [part.replace("{repo}", str(repo_path)) for part in self._command]
        logger = get_logger("graphify")
        logger.info("graphify.run", argv=argv, cwd=str(repo_path))
        try:
            result = subprocess.run(  # noqa: S603 - argv is a fixed template, not shell
                argv,
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as exc:
            raise GraphBuildError(f"failed to launch graphify: {exc}") from exc
        if result.returncode != 0:
            tail = (result.stderr or result.stdout or "").strip()[-500:]
            raise GraphBuildError(f"graphify exited with {result.returncode}: {tail}")

        out_dir = repo_path / "graphify-out"
        if not (out_dir / "graph.json").is_file():
            raise GraphBuildError(
                f"graphify ran but produced no {out_dir / 'graph.json'}. "
                "Check the graphify version/command."
            )
        return out_dir
