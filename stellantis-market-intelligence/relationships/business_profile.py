"""Business Relationship Analysis (Phase 12).

Builds a per-company analytical profile for every entity directly connected to
Stellantis in the relationship graph (Phase 11): relationship type, a transparent
"relationship strength" classification, business area, geographic exposure, and the
supporting evidence. This operates generically over whatever is in the graph - so as
verified supplier/partner relationships are added later (with evidence), profiles are
produced automatically without code changes.
"""

from __future__ import annotations

from typing import Any

import networkx as nx

from relationships.entities import STELLANTIS_ENTITY_ID
from relationships.queries import neighbors

# Transparent, hand-documented mapping from relationship_type -> a strength label.
# "Direct" = a direct, named business tie. "Indirect" = collaborative/strategic but
# not a direct supply/ownership tie. "None" = explicitly non-collaborative.
RELATIONSHIP_STRENGTH_BY_TYPE: dict[str, str] = {
    "brand": "Direct (ownership)",
    "supplier": "Direct",
    "battery_supplier": "Direct",
    "semiconductor_supplier": "Direct",
    "manufacturing_partner": "Direct",
    "joint_venture": "Direct",
    "customer": "Direct",
    "technology_partner": "Indirect (strategic)",
    "software_partner": "Indirect (strategic)",
    "cloud_partner": "Indirect (strategic)",
    "logistics_partner": "Indirect (strategic)",
    "partner": "Indirect (strategic)",
    "competitor": "None (competitive, not collaborative)",
}


def relationship_strength(relationship_type: str) -> str:
    """Transparent, table-driven strength label for a relationship_type. Never a black box."""
    return RELATIONSHIP_STRENGTH_BY_TYPE.get(relationship_type, "Unclassified")


def build_company_profile(graph: nx.DiGraph, entity_id: str) -> dict[str, Any] | None:
    """Business relationship profile for one entity directly connected to Stellantis."""
    if not graph.has_edge(STELLANTIS_ENTITY_ID, entity_id):
        return None

    edge = graph.edges[STELLANTIS_ENTITY_ID, entity_id]
    node = graph.nodes[entity_id]
    return {
        "entity_id": entity_id,
        "name": node.get("name", entity_id),
        "entity_type": node.get("entity_type"),
        "relationship_type": edge.get("relationship_type"),
        "relationship_strength": relationship_strength(edge.get("relationship_type")),
        "business_area": edge.get("business_area"),
        "geographic_exposure": edge.get("geographic_exposure"),
        "description": edge.get("description"),
        "confidence": edge.get("confidence"),
        "relationship_start": edge.get("relationship_start"),
        "relationship_end": edge.get("relationship_end"),
        "evidence_source": edge.get("source"),
        "evidence_url": edge.get("evidence_url"),
    }


def build_all_profiles(graph: nx.DiGraph, source_entity: str = STELLANTIS_ENTITY_ID) -> list[dict[str, Any]]:
    """Business relationship profiles for every entity directly connected to `source_entity`."""
    return [
        build_company_profile(graph, n["entity_id"])
        for n in neighbors(graph, source_entity)
    ]
