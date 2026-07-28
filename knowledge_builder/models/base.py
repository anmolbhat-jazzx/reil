"""Foundational types for the Repository IR.

All IR models derive from :class:`IRModel`, a frozen Pydantic v2 base. Immutability
means a compiler pass never mutates the IR in place; instead it produces a new
:class:`~knowledge_builder.models.repository.Repository` (via ``model_copy(update=...)``),
which the pipeline threads forward. Cross-references between entities are stored **by
string id**, never as nested objects, so the optimizer and serializer can normalize and
deduplicate freely.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class IRModel(BaseModel):
    """Immutable base for every Repository IR entity."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class FileType(StrEnum):
    """The six ``file_type`` values graphify assigns to every node."""

    CODE = "code"
    DOCUMENT = "document"
    PAPER = "paper"
    IMAGE = "image"
    RATIONALE = "rationale"
    CONCEPT = "concept"


class RelationType(StrEnum):
    """Well-known edge ``relation`` values seen in graphify's ``graph.json``.

    graphify emits an open-ended set of relation names, so :class:`Relationship.relation`
    is a free string; these are only the constants the passes branch on. Observed in real
    graphs: ``calls``, ``contains``, ``method``, ``uses``, ``inherits``, ``imports_from``,
    ``exports``, ``reads_env_var``, plus the semantic relations below.
    """

    CALLS = "calls"
    INDIRECT_CALL = "indirect_call"
    CONTAINS = "contains"
    METHOD = "method"
    USES = "uses"
    INHERITS = "inherits"
    IMPORTS = "imports"
    IMPORTS_FROM = "imports_from"
    EXPORTS = "exports"
    RE_EXPORTS = "re_exports"
    IMPLEMENTS = "implements"
    REFERENCES = "references"
    CITES = "cites"
    CONCEPTUALLY_RELATED_TO = "conceptually_related_to"
    SHARES_DATA_WITH = "shares_data_with"
    SEMANTICALLY_SIMILAR_TO = "semantically_similar_to"
    RATIONALE_FOR = "rationale_for"


#: Relations treated as a "call" edge (used by the call-graph pass).
CALL_RELATIONS: frozenset[str] = frozenset({"calls", "indirect_call"})

#: Relations treated as import dependencies.
IMPORT_RELATIONS: frozenset[str] = frozenset({"imports", "imports_from", "re_exports"})

#: Relations treated as (non-import) reference dependencies.
REFERENCE_RELATIONS: frozenset[str] = frozenset({"references", "uses"})

#: Relations that link a concept to the symbols/nodes it relates to.
SEMANTIC_RELATIONS: frozenset[str] = frozenset(
    {
        "conceptually_related_to",
        "semantically_similar_to",
        "rationale_for",
        "references",
        "cites",
    }
)


class Confidence(StrEnum):
    """Edge confidence tier assigned during extraction."""

    EXTRACTED = "EXTRACTED"
    INFERRED = "INFERRED"
    AMBIGUOUS = "AMBIGUOUS"

    @classmethod
    def from_raw(cls, value: str | None) -> Confidence:
        """Coerce a raw string to a member, defaulting to ``EXTRACTED``."""
        if value is None:
            return cls.EXTRACTED
        try:
            return cls(value)
        except ValueError:
            return cls.EXTRACTED


class HyperedgeRelation(StrEnum):
    """Relation of a graphify hyperedge (a group of 3+ participating nodes)."""

    PARTICIPATE_IN = "participate_in"
    IMPLEMENT = "implement"
    FORM = "form"

    @classmethod
    def from_raw(cls, value: str | None) -> HyperedgeRelation:
        if value is None:
            return cls.PARTICIPATE_IN
        try:
            return cls(value)
        except ValueError:
            return cls.PARTICIPATE_IN


class ComponentKind(StrEnum):
    """Architectural component kinds *derived* from deterministic heuristics.

    graphify does not label these — the classify pass infers them from source-file
    path patterns, label patterns, and graph structure.
    """

    SERVICE = "service"
    CONTROLLER = "controller"
    API = "api"
    ROUTE = "route"


class ModuleOrigin(StrEnum):
    """How a logical module's boundary was determined (Hybrid strategy)."""

    COMMUNITY = "community"
    PACKAGE = "package"
    MERGED = "merged"
    STANDALONE = "standalone"
