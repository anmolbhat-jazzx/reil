"""Summary compression — drop empty summaries that carry no signal.

A deterministic V1 build can produce a summary whose every field is empty (a module with
no classified components, concepts, workflows, or god nodes). Such summaries only bloat
the artifact, so they are removed and their module's ``summary_id`` cleared.
"""

from __future__ import annotations

from knowledge_builder.models.repository import Repository
from knowledge_builder.models.summary import Summary


def compress_summaries(repo: Repository) -> Repository:
    """Return a copy of ``repo`` with empty summaries removed."""
    kept: list[Summary] = []
    removed: set[str] = set()
    for summary in repo.summaries:
        if _is_empty(summary):
            removed.add(summary.id)
        else:
            kept.append(summary)

    if not removed:
        return repo

    modules = tuple(
        module.model_copy(update={"summary_id": None}) if module.summary_id in removed else module
        for module in repo.modules
    )
    return repo.evolve(summaries=tuple(kept), modules=modules)


def _is_empty(summary: Summary) -> bool:
    return not any(
        (
            summary.purpose,
            summary.responsibilities,
            summary.business_rules,
            summary.dependencies,
            summary.public_apis,
            summary.workflows,
            summary.constraints,
            summary.concepts,
            summary.god_nodes,
        )
    )
