"""RepositoryLoader — locate and read the raw graphify artifacts for a repository."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from knowledge_builder.utils.errors import LoaderError, ParseError

GRAPH_FILE = "graph.json"
LABELS_FILE = ".graphify_labels.json"
ANALYSIS_FILE = ".graphify_analysis.json"
VERSION_FILE = ".graphify_version"


@dataclass(frozen=True)
class GraphifyBundle:
    """The raw JSON artifacts read from a ``graphify-out/`` directory."""

    graph_path: Path
    graph: dict[str, Any]
    labels: dict[str, str]
    analysis: dict[str, Any]
    graphify_version: str | None
    graph_hash: str


class RepositoryLoader:
    """Locates ``graphify-out/`` and loads its JSON artifacts into a bundle."""

    def load(self, graphify_out: Path) -> GraphifyBundle:
        """Read the graphify artifacts from ``graphify_out``.

        Raises:
            LoaderError: if the directory or ``graph.json`` is missing.
            ParseError: if a present artifact is not valid JSON of the expected shape.
        """
        if not graphify_out.exists():
            raise LoaderError(
                f"no graphify output at {graphify_out}. "
                "Run graphify on the repository first (e.g. `graphify build <repo>`)."
            )
        graph_path = graphify_out / GRAPH_FILE
        if not graph_path.is_file():
            raise LoaderError(
                f"{graph_path} not found. The graphify-out directory exists but has no "
                f"{GRAPH_FILE}; re-run graphify to (re)generate it."
            )

        raw_bytes = graph_path.read_bytes()
        graph = _load_json_object(graph_path, raw_bytes)
        graph_hash = hashlib.sha256(raw_bytes).hexdigest()

        labels = _load_optional_object(graphify_out / LABELS_FILE)
        analysis = _load_optional_object(graphify_out / ANALYSIS_FILE)
        version = _read_version(graphify_out / VERSION_FILE)

        return GraphifyBundle(
            graph_path=graph_path,
            graph=graph,
            labels={str(k): str(v) for k, v in labels.items()},
            analysis=analysis,
            graphify_version=version,
            graph_hash=graph_hash,
        )


def _load_json_object(path: Path, raw: bytes) -> dict[str, Any]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ParseError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ParseError(f"{path} must contain a JSON object, got {type(data).__name__}")
    return data


def _load_optional_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return _load_json_object(path, path.read_bytes())


def _read_version(path: Path) -> str | None:
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8").strip()
    return text or None
