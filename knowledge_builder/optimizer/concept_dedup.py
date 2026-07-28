"""Concept deduplication — collapse repeated concepts into a single canonical record.

The classic case: four modules each mention ``JWT`` as its own concept node. After this
pass there is one ``JWT`` concept and every module references it by id. The raw graph
layer is left untouched (it stays faithful to graphify); only the typed ``Concept``
projection is deduplicated.
"""

from __future__ import annotations

from collections import defaultdict

from knowledge_builder.models.concept import Concept
from knowledge_builder.models.repository import Repository


def deduplicate_concepts(repo: Repository) -> Repository:
    """Return a copy of ``repo`` with duplicate concepts merged by normalized label."""
    groups: dict[str, list[Concept]] = defaultdict(list)
    for concept in repo.concepts:
        groups[concept.normalized_label].append(concept)

    canonical: dict[str, str] = {}
    merged: list[Concept] = []
    for members in groups.values():
        # Prefer a concept that carries a rationale, then the lexicographically first id.
        keeper = sorted(members, key=lambda c: (c.rationale is None, c.id))[0]
        for member in members:
            canonical[member.id] = keeper.id
        related: set[str] = set()
        for member in members:
            related.update(member.related_ids)
        rationale = keeper.rationale or next((m.rationale for m in members if m.rationale), None)
        related = {canonical.get(r, r) for r in related} - {keeper.id}
        merged.append(
            keeper.model_copy(
                update={"rationale": rationale, "related_ids": tuple(sorted(related))}
            )
        )

    modules = tuple(
        module.model_copy(
            update={
                "concept_ids": tuple(
                    sorted({canonical.get(cid, cid) for cid in module.concept_ids})
                )
            }
        )
        for module in repo.modules
    )
    return repo.evolve(concepts=tuple(sorted(merged, key=lambda c: c.id)), modules=modules)
