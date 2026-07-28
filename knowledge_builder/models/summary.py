"""Summary: the structured, per-module knowledge summary.

Shape mirrors the Phase-5 target JSON (purpose / responsibilities / business rules /
dependencies / public APIs / workflows / constraints / concepts). In deterministic V1
these are assembled from graphify's harvested content; fields with no deterministic
source are left empty (a V2 LLM pass fills them).
"""

from __future__ import annotations

from knowledge_builder.models.base import IRModel


class Summary(IRModel):
    """A structured summary attached to exactly one module."""

    id: str
    module_id: str
    purpose: str | None = None
    responsibilities: tuple[str, ...] = ()
    business_rules: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    public_apis: tuple[str, ...] = ()
    workflows: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    concepts: tuple[str, ...] = ()
    god_nodes: tuple[str, ...] = ()

    def content_key(self) -> tuple[object, ...]:
        """Hashable key over the summary's content (id-independent).

        Two summaries with the same content key are duplicates and can be collapsed by
        the optimizer.
        """
        return (
            self.purpose,
            self.responsibilities,
            self.business_rules,
            self.dependencies,
            self.public_apis,
            self.workflows,
            self.constraints,
            self.concepts,
            self.god_nodes,
        )
