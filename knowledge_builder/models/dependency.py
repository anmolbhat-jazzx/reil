"""Dependency: an import/reference relationship, possibly to an external module."""

from __future__ import annotations

from typing import Literal

from knowledge_builder.models.base import IRModel


class Dependency(IRModel):
    """A directed dependency derived from ``imports``/``references`` edges.

    ``target_id`` is set when the dependency resolves to a known node in the graph;
    ``target_name`` carries the raw import target (used when the dependency is external
    to the repository, in which case ``external`` is ``True``).
    """

    id: str
    source_id: str
    target_id: str | None = None
    target_name: str | None = None
    kind: Literal["import", "reference"] = "import"
    external: bool = False
