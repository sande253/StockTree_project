"""Relationship / network service (Phase 24)."""

from __future__ import annotations

from typing import Any

from storage.repository import get_relationships_for_company, list_relationships


def get_all_relationships() -> list[dict[str, Any]]:
    from relationships.graph import review_state

    return [dict(relationship, review_state=review_state(relationship.get("last_reviewed"), relationship.get("evidence_scope"))) for relationship in list_relationships()]


def get_relationships_for(company: str) -> list[dict[str, Any]]:
    return get_relationships_for_company(company)


def get_network() -> dict[str, Any]:
    """The relationship graph as plain JSON nodes/edges, for the Ecosystem Graph page."""
    from relationships.graph import build_graph
    from storage.repository import list_companies

    # Ticker -> full legal/common company name, so the graph never shows a bare ticker.
    names_by_ticker = {c["ticker"]: c["company_name"] for c in list_companies() if c.get("ticker")}

    graph = build_graph()
    nodes = [
        {
            "id": n,
            **graph.nodes[n],
            "company_name": names_by_ticker.get(n, graph.nodes[n].get("name", n)),
        }
        for n in graph.nodes
    ]
    edges = [
        {
            "source": u,
            "target": v,
            "relationship_type": data.get("relationship_type"),
            "confidence": data.get("confidence"),
            "description": data.get("description"),
            "evidence_source": data.get("source"),
            "evidence_url": data.get("evidence_url"),
            "business_area": data.get("business_area"),
            "geographic_exposure": data.get("geographic_exposure"),
            "target_entity_ticker": data.get("target_entity_ticker"),
            "evidence_date": data.get("evidence_date"),
            "last_reviewed": data.get("last_reviewed"),
            "review_state": data.get("review_state"),
        }
        for u, v, data in graph.edges(data=True)
    ]
    return {"nodes": nodes, "edges": edges}
