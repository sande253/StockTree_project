"""STLA Ecosystem Exposure Score (Phase 22).

A transparent, 0-100 analytical score answering: "How strongly should this company be
investigated in the context of the current STLA event?" This is explicitly NOT an
investment score - never interpret it as buy/sell/outperform/underperform/expected
return. The calculation is a documented weighted sum of six components, each itself
a transparent table/formula (no hidden model, no black box).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import networkx as nx

from relationships.business_profile import build_company_profile
from relationships.combined_profile import load_historical_event_sensitivity, load_statistical_correlation
from relationships.graph import STELLANTIS_ENTITY_ID
from relationships.supply_chain import compute_supply_chain_exposure

NOT_AN_INVESTMENT_SCORE_DISCLAIMER = (
    "The Ecosystem Exposure Score is NOT an investment recommendation. It is not Buy, Sell, "
    "Outperform, Underperform, or an expected return. It only indicates how strongly this "
    "company may be worth investigating in the context of the current STLA event."
)

# Component weights. Must sum to 1.0 - verified by a unit test, not just by inspection.
WEIGHTS = {
    "business_relationship_strength": 0.25,
    "historical_sensitivity": 0.20,
    "event_relevance": 0.20,
    "graph_proximity": 0.15,
    "evidence_strength": 0.10,
    "historical_reaction_frequency": 0.10,
}

RELATIONSHIP_STRENGTH_SCORE = {
    "Direct (ownership)": 100,
    "Direct": 90,
    "Indirect (strategic)": 60,
    "None (competitive, not collaborative)": 20,
    "Unclassified": 40,
}

SENSITIVITY_SCORE = {
    "High": 100,
    "Medium": 60,
    "Low": 30,
    "None observed": 10,
    "Insufficient data": 40,
    "Data unavailable": 40,
}

CONFIDENCE_SCORE = {"high": 100, "medium": 60, "low": 30}

GRAPH_PROXIMITY_SCORE = {"first-order": 100, "second-order": 60, "third-order": 30}
GRAPH_PROXIMITY_DEFAULT = 10  # fourth-order or deeper

# Which relationship_types are especially relevant to each event_type. Any relationship_type
# not listed for a given event_type (or any event_type not listed here, e.g. "Other") gets the
# neutral baseline score below - this is a documented heuristic, not a claim of certainty.
EVENT_RELEVANCE_MAP: dict[str, set[str]] = {
    "Production": {"supplier", "supplier_tier1", "supplier_tier2", "battery_supplier", "semiconductor_supplier", "manufacturing_partner", "brand"},
    "Factory": {"manufacturing_partner", "brand"},
    "Supply Chain": {"supplier", "battery_supplier", "semiconductor_supplier", "logistics_partner"},
    "Recall": {"supplier", "manufacturing_partner", "brand"},
    "Battery": {"battery_supplier"},
    "Technology": {"technology_partner", "software_partner", "semiconductor_supplier"},
    "EV Strategy": {"battery_supplier", "technology_partner"},
}
EVENT_RELEVANCE_MATCH_SCORE = 100
EVENT_RELEVANCE_NEUTRAL_SCORE = 50


def _event_relevance(event_type: str | None, relationship_type: str | None) -> int:
    relevant_types = EVENT_RELEVANCE_MAP.get(event_type or "")
    if relevant_types is None or relationship_type in relevant_types:
        return EVENT_RELEVANCE_MATCH_SCORE if relevant_types else EVENT_RELEVANCE_NEUTRAL_SCORE
    return EVENT_RELEVANCE_NEUTRAL_SCORE


def compute_exposure_score(
    graph: nx.DiGraph, entity_id: str, event_type: str | None = None, db_path: Path | str | None = None
) -> dict[str, Any] | None:
    """Full Phase 22 score + transparent per-component breakdown for one entity."""
    profile = build_company_profile(graph, entity_id)
    if profile is None:
        return None

    strength_score = RELATIONSHIP_STRENGTH_SCORE.get(profile["relationship_strength"], 40)
    confidence_score = CONFIDENCE_SCORE.get((profile["confidence"] or "").lower(), 40)

    exposure = {e["entity_id"]: e for e in compute_supply_chain_exposure(graph)}
    proximity_order = exposure.get(entity_id, {}).get("exposure_order")
    proximity_score = GRAPH_PROXIMITY_SCORE.get(proximity_order, GRAPH_PROXIMITY_DEFAULT)

    ticker = graph.edges[STELLANTIS_ENTITY_ID, entity_id].get("target_entity_ticker")
    if ticker:
        sensitivity = load_historical_event_sensitivity(ticker, db_path=db_path)
        sensitivity_label = sensitivity["sensitivity_label"] if sensitivity else "Data unavailable"
        frequency_ratio = (
            sensitivity["significant_reaction_count"] / sensitivity["sample_size"] if sensitivity else None
        )
    else:
        sensitivity_label = "Data unavailable"
        frequency_ratio = None
    sensitivity_score = SENSITIVITY_SCORE.get(sensitivity_label, 40)
    frequency_score = round(frequency_ratio * 100) if frequency_ratio is not None else 40

    relevance_score = _event_relevance(event_type, profile["relationship_type"])

    components = {
        "business_relationship_strength": {"label": profile["relationship_strength"], "score": strength_score},
        "historical_sensitivity": {"label": sensitivity_label, "score": sensitivity_score},
        "event_relevance": {"event_type": event_type, "score": relevance_score},
        "graph_proximity": {"label": proximity_order, "score": proximity_score},
        "evidence_strength": {"confidence": profile["confidence"], "score": confidence_score},
        "historical_reaction_frequency": {"ratio": frequency_ratio, "score": frequency_score},
    }
    total = sum(components[key]["score"] * weight for key, weight in WEIGHTS.items())

    return {
        "entity_id": entity_id,
        "name": profile["name"],
        "ecosystem_exposure_score": round(total),
        "components": components,
        "disclaimer": NOT_AN_INVESTMENT_SCORE_DISCLAIMER,
    }


def compute_all_exposure_scores(
    graph: nx.DiGraph, event_type: str | None = None, db_path: Path | str | None = None
) -> list[dict[str, Any]]:
    """Exposure scores for every entity directly connected to STLA, highest first."""
    from relationships.queries import neighbors

    scores = [
        compute_exposure_score(graph, n["entity_id"], event_type=event_type, db_path=db_path)
        for n in neighbors(graph, STELLANTIS_ENTITY_ID)
    ]
    return sorted(scores, key=lambda s: s["ecosystem_exposure_score"], reverse=True)
