"""Module: a logical module — the primary unit of summarization.

A *Logical Module* is a cohesive group of strongly connected symbols representing a
single business capability, discovered primarily through graphify communities and
secondarily through repository structure (the Hybrid strategy).
"""

from __future__ import annotations

from knowledge_builder.models.base import IRModel, ModuleOrigin


class Module(IRModel):
    """A logical module."""

    id: str
    name: str
    origin: ModuleOrigin = ModuleOrigin.COMMUNITY
    community_id: str | None = None
    cohesion: float | None = None
    symbol_ids: tuple[str, ...] = ()
    source_paths: tuple[str, ...] = ()
    related_module_ids: tuple[str, ...] = ()
    concept_ids: tuple[str, ...] = ()
    service_ids: tuple[str, ...] = ()
    controller_ids: tuple[str, ...] = ()
    api_ids: tuple[str, ...] = ()
    workflow_ids: tuple[str, ...] = ()
    summary_id: str | None = None
