"""Read-only query helpers over the corporate relationship graph (Phase 11).

Thin, reusable helpers on top of a built `networkx.DiGraph` (see relationships/graph.py).
Later phases (12-14: business relationship analysis, supply-chain propagation) build on
these rather than querying NetworkX directly.
"""

from __future__ import annotations

from typing import Any

import networkx as nx


def neighbors(graph: nx.DiGraph, entity_id: str, relationship_type: str | None = None) -> list[dict[str, Any]]:
    """List outgoing relationships from `entity_id`, optionally filtered by relationship_type."""
    if entity_id not in graph:
        return []

    results: list[dict[str, Any]] = []
    for target in graph.successors(entity_id):
        edge = graph.edges[entity_id, target]
        if relationship_type is not None and edge.get("relationship_type") != relationship_type:
            continue
        results.append({"entity_id": target, **graph.nodes[target], **edge})
    return results


def relationship_types_present(graph: nx.DiGraph) -> list[str]:
    """Distinct relationship_type values present anywhere in the graph."""
    return sorted({data["relationship_type"] for _, _, data in graph.edges(data=True)})


def find_path(graph: nx.DiGraph, source_entity: str, target_entity: str) -> list[str] | None:
    """Shortest relationship path between two entities, or None if unreachable/unknown."""
    if source_entity not in graph or target_entity not in graph:
        return None
    try:
        return nx.shortest_path(graph, source_entity, target_entity)
    except nx.NetworkXNoPath:
        return None


def entity_summary(graph: nx.DiGraph, entity_id: str) -> dict[str, Any] | None:
    """Node attributes plus relationship count for one entity, or None if unknown."""
    if entity_id not in graph:
        return None
    return {
        "entity_id": entity_id,
        **graph.nodes[entity_id],
        "outgoing_relationships": graph.out_degree(entity_id),
        "incoming_relationships": graph.in_degree(entity_id),
    }
