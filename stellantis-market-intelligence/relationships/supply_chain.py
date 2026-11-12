"""Supply-Chain Impact Propagation (Phase 14).

Classifies every entity reachable from Stellantis in the relationship graph by
exposure order - first-order (direct), second-order (a supplier of a supplier),
third-order, etc. - and reports the actual chain of evidenced relationships along
the path. Never infers a relationship that is not an actual edge in the graph
(exposure order is purely graph distance; it does not use Phase 13's statistical
correlation, which has nothing to do with the physical/contractual supply chain).
"""

from __future__ import annotations

from typing import Any

import networkx as nx

ORDER_LABELS = {1: "first-order", 2: "second-order", 3: "third-order"}
DEFAULT_MAX_DEPTH = 3


def order_label(hop_count: int) -> str:
    """Human label for a graph distance (in hops) from Stellantis. Falls back for hop_count > 3."""
    return ORDER_LABELS.get(hop_count, f"{hop_count}th-order")


def trace_exposure_path(graph: nx.DiGraph, source_entity: str, target_entity: str) -> list[dict[str, Any]] | None:
    """The actual chain of evidenced relationships from `source_entity` to `target_entity`.

    Returns one dict per hop: {from, to, relationship_type, confidence, evidence_url}.
    None if there is no path (or either entity is unknown to the graph).
    """
    if source_entity not in graph or target_entity not in graph:
        return None
    try:
        path = nx.shortest_path(graph, source_entity, target_entity)
    except nx.NetworkXNoPath:
        return None

    hops: list[dict[str, Any]] = []
    for from_node, to_node in zip(path, path[1:]):
        edge = graph.edges[from_node, to_node]
        hops.append(
            {
                "from": from_node,
                "to": to_node,
                "relationship_type": edge.get("relationship_type"),
                "confidence": edge.get("confidence"),
                "evidence_url": edge.get("evidence_url"),
            }
        )
    return hops


def compute_supply_chain_exposure(
    graph: nx.DiGraph, source_entity: str = "STLA", max_depth: int = DEFAULT_MAX_DEPTH
) -> list[dict[str, Any]]:
    """Every entity reachable from `source_entity` within `max_depth` hops, with its exposure order."""
    if source_entity not in graph:
        return []

    results: list[dict[str, Any]] = []
    # BFS distances bounded to max_depth (networkx's single-source shortest path length supports a cutoff).
    distances = nx.single_source_shortest_path_length(graph, source_entity, cutoff=max_depth)
    for entity_id, hop_count in distances.items():
        if entity_id == source_entity or hop_count == 0:
            continue
        hops = trace_exposure_path(graph, source_entity, entity_id)
        results.append(
            {
                "entity_id": entity_id,
                "name": graph.nodes[entity_id].get("name", entity_id),
                "entity_type": graph.nodes[entity_id].get("entity_type"),
                "exposure_order": order_label(hop_count),
                "hop_count": hop_count,
                "path": hops,
            }
        )
    return sorted(results, key=lambda r: (r["hop_count"], r["entity_id"]))
