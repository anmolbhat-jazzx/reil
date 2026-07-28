"""Compiler configuration — immutable inputs that shape a compilation run."""

from __future__ import annotations

from pathlib import Path

from pydantic import ConfigDict

from knowledge_builder.models.base import IRModel

WORKSPACE_DIRNAME = ".knowledge"


class CompilerConfig(IRModel):
    """Configuration for a single compilation.

    Only ``repo_path`` is required; other paths default relative to it. The **workspace**
    is the single output folder that holds the imported graph files *and* the compiled
    ``knowledge.kb`` — the folder a user adds to ``.gitignore``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    repo_path: Path
    workspace: Path | None = None
    graphify_out: Path | None = None
    output_path: Path | None = None

    # End-to-end graph build (Phase: GraphBuildPass).
    build_graph: bool = True
    rebuild_graph: bool = False

    # Write/update AGENTS.md so agents know to consult knowledge.kb (AgentsDocPass).
    write_agents_doc: bool = True

    strict: bool = False
    builder_version: str | None = None

    # Hybrid module-boundary tuning (module_pass).
    min_cohesion: float = 0.15
    max_module_size: int = 60

    @property
    def resolved_workspace(self) -> Path:
        """The single output folder for graph files + ``knowledge.kb``."""
        return self.workspace or (self.repo_path / WORKSPACE_DIRNAME)

    @property
    def resolved_graph_dir(self) -> Path:
        """Directory the loader reads graph files from (the workspace)."""
        return self.resolved_workspace

    @property
    def transient_graphify_dir(self) -> Path:
        """Where graphify writes its output before we import + discard it."""
        return self.graphify_out or (self.repo_path / "graphify-out")

    @property
    def resolved_output_path(self) -> Path:
        """Where the compiled ``knowledge.kb`` artifact is written."""
        return self.output_path or (self.resolved_workspace / "knowledge.kb")
