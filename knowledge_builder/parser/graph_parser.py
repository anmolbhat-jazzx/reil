"""GraphParser — turn a raw graphify bundle into a :class:`ParsedGraph`.

``graph.json`` is a NetworkX node-link document: nodes under ``nodes``, edges under
``links`` (NetworkX's default key), and graph-level attributes — including
``hyperedges`` — under ``graph``. Community membership comes from the analysis sidecar
when present, otherwise from a per-node ``community`` attribute if graphify stamped one.
"""

from __future__ import annotations

from typing import Any

from knowledge_builder.models.base import (
    Confidence,
    FileType,
    HyperedgeRelation,
)
from knowledge_builder.models.graph import GraphNode, Relationship
from knowledge_builder.parser.loader import GraphifyBundle
from knowledge_builder.parser.types import CommunityInfo, ParsedGraph, RawHyperedge
from knowledge_builder.utils.errors import ParseError


class GraphParser:
    """Parses a :class:`GraphifyBundle` into the intermediate :class:`ParsedGraph`."""

    def parse(self, bundle: GraphifyBundle) -> ParsedGraph:
        graph = bundle.graph
        directed = bool(graph.get("directed", True))
        multigraph = bool(graph.get("multigraph", False))

        communities = self._parse_communities(bundle)
        community_of = _invert_communities(communities)

        nodes = self._parse_nodes(graph.get("nodes", []), community_of)
        relationships, _dropped = self._parse_edges(_edge_list(graph))
        hyperedges = self._parse_hyperedges(_hyperedge_list(graph))
        god_ids = _parse_gods(bundle.analysis.get("gods", []))

        return ParsedGraph(
            nodes=nodes,
            relationships=relationships,
            hyperedges=hyperedges,
            communities=communities,
            god_ids=god_ids,
            directed=directed,
            multigraph=multigraph,
            graphify_version=bundle.graphify_version,
        )

    # -- nodes --------------------------------------------------------------
    def _parse_nodes(self, raw_nodes: Any, community_of: dict[str, str]) -> tuple[GraphNode, ...]:
        if not isinstance(raw_nodes, list):
            raise ParseError("graph.json 'nodes' must be a list")
        result: list[GraphNode] = []
        for raw in raw_nodes:
            if not isinstance(raw, dict) or "id" not in raw:
                raise ParseError(f"invalid node (missing id): {raw!r}")
            node_id = str(raw["id"])
            community_id = _first_str(raw, ("community", "community_id")) or community_of.get(
                node_id
            )
            result.append(
                GraphNode(
                    id=node_id,
                    label=str(raw.get("label", node_id)),
                    file_type=_parse_file_type(raw.get("file_type")),
                    source_file=_opt_str(raw.get("source_file")),
                    source_location=_opt_str(raw.get("source_location")),
                    source_url=_opt_str(raw.get("source_url")),
                    captured_at=_opt_str(raw.get("captured_at")),
                    author=_opt_str(raw.get("author")),
                    contributor=_opt_str(raw.get("contributor")),
                    rationale=_opt_str(raw.get("rationale")),
                    community_id=community_id,
                )
            )
        return tuple(result)

    # -- edges --------------------------------------------------------------
    def _parse_edges(self, raw_edges: list[dict[str, Any]]) -> tuple[tuple[Relationship, ...], int]:
        result: list[Relationship] = []
        dropped = 0
        for raw in raw_edges:
            source = _opt_str(raw.get("source"))
            target = _opt_str(raw.get("target"))
            relation = _opt_str(raw.get("relation"))
            if source is None or target is None or relation is None:
                dropped += 1
                continue
            result.append(
                Relationship(
                    id=Relationship.make_id(source, target, relation),
                    source_id=source,
                    target_id=target,
                    relation=relation,
                    confidence=Confidence.from_raw(_opt_str(raw.get("confidence"))),
                    confidence_score=_as_float(raw.get("confidence_score"), 1.0),
                    weight=_as_float(raw.get("weight"), 1.0),
                    source_file=_opt_str(raw.get("source_file")),
                )
            )
        return tuple(result), dropped

    # -- hyperedges ---------------------------------------------------------
    def _parse_hyperedges(self, raw_hyperedges: list[dict[str, Any]]) -> tuple[RawHyperedge, ...]:
        result: list[RawHyperedge] = []
        for raw in raw_hyperedges:
            members = tuple(str(n) for n in raw.get("nodes", []) if _opt_str(n))
            if not members:
                continue
            hid = _opt_str(raw.get("id")) or f"hyperedge_{len(result)}"
            result.append(
                RawHyperedge(
                    id=hid,
                    label=str(raw.get("label", hid)),
                    nodes=members,
                    relation=HyperedgeRelation.from_raw(_opt_str(raw.get("relation"))),
                    confidence=Confidence.from_raw(_opt_str(raw.get("confidence"))),
                    confidence_score=_as_float(raw.get("confidence_score"), 1.0),
                    source_file=_opt_str(raw.get("source_file")),
                )
            )
        return tuple(result)

    # -- communities --------------------------------------------------------
    def _parse_communities(self, bundle: GraphifyBundle) -> tuple[CommunityInfo, ...]:
        raw_communities = bundle.analysis.get("communities")
        if not isinstance(raw_communities, dict):
            return self._communities_from_nodes(bundle)
        cohesion = bundle.analysis.get("cohesion", {})
        cohesion = cohesion if isinstance(cohesion, dict) else {}
        result: list[CommunityInfo] = []
        for cid, members in raw_communities.items():
            cid_str = str(cid)
            member_ids = tuple(str(m) for m in members) if isinstance(members, list) else ()
            result.append(
                CommunityInfo(
                    id=cid_str,
                    label=bundle.labels.get(cid_str, f"Community {cid_str}"),
                    member_ids=member_ids,
                    cohesion=_as_optional_float(cohesion.get(cid_str)),
                )
            )
        return tuple(result)

    def _communities_from_nodes(self, bundle: GraphifyBundle) -> tuple[CommunityInfo, ...]:
        """Fallback: reconstruct communities from per-node ``community`` attributes."""
        buckets: dict[str, list[str]] = {}
        for raw in bundle.graph.get("nodes", []):
            if not isinstance(raw, dict):
                continue
            cid = _first_str(raw, ("community", "community_id"))
            if cid is None:
                continue
            buckets.setdefault(cid, []).append(str(raw["id"]))
        return tuple(
            CommunityInfo(
                id=cid,
                label=bundle.labels.get(cid, f"Community {cid}"),
                member_ids=tuple(members),
            )
            for cid, members in buckets.items()
        )


# -- module-level helpers ---------------------------------------------------
def _edge_list(graph: dict[str, Any]) -> list[dict[str, Any]]:
    raw = graph.get("links")
    if raw is None:
        raw = graph.get("edges", [])
    if not isinstance(raw, list):
        raise ParseError("graph.json edges ('links') must be a list")
    return [e for e in raw if isinstance(e, dict)]


def _hyperedge_list(graph: dict[str, Any]) -> list[dict[str, Any]]:
    meta = graph.get("graph")
    raw = meta.get("hyperedges") if isinstance(meta, dict) else None
    if raw is None:
        raw = graph.get("hyperedges", [])
    if not isinstance(raw, list):
        return []
    return [h for h in raw if isinstance(h, dict)]


def _parse_gods(raw_gods: Any) -> tuple[str, ...]:
    if not isinstance(raw_gods, list):
        return ()
    ids: list[str] = []
    for god in raw_gods:
        if isinstance(god, str):
            ids.append(god)
        elif isinstance(god, dict):
            candidate = _first_str(god, ("id", "node", "node_id", "label"))
            if candidate:
                ids.append(candidate)
    return tuple(ids)


def _invert_communities(communities: tuple[CommunityInfo, ...]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for community in communities:
        for node_id in community.member_ids:
            mapping.setdefault(node_id, community.id)
    return mapping


def _parse_file_type(value: Any) -> FileType:
    if value is None:
        return FileType.CODE
    try:
        return FileType(str(value))
    except ValueError as exc:
        raise ParseError(f"unknown file_type {value!r}") from exc


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


def _first_str(data: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = _opt_str(data.get(key))
        if value is not None:
            return value
    return None


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
