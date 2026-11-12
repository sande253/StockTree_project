"""Phase 12 - Business Relationship Analysis tests."""

from __future__ import annotations

from datetime import date

import pytest

from relationships.business_profile import (
    RELATIONSHIP_STRENGTH_BY_TYPE,
    build_all_profiles,
    build_company_profile,
    relationship_strength,
)
from relationships.graph import Relationship, build_graph, persist_relationships


def _relationship(**overrides) -> Relationship:
    defaults = dict(
        source_entity="STLA",
        target_entity="Peugeot",
        target_entity_type="brand",
        relationship_type="brand",
        confidence="high",
        date_discovered=date(2026, 10, 4),
        source="Stellantis official corporate site",
        evidence_url="https://www.stellantis.com/en/brands",
        business_area="Mass-market passenger vehicles",
        geographic_exposure="Europe",
    )
    defaults.update(overrides)
    return Relationship(**defaults)


def test_relationship_strength_is_transparent_and_table_driven():
    assert relationship_strength("supplier") == "Direct"
    assert relationship_strength("partner") == "Indirect (strategic)"
    assert relationship_strength("competitor") == "None (competitive, not collaborative)"
    assert relationship_strength("not-a-real-type") == "Unclassified"
    assert set(RELATIONSHIP_STRENGTH_BY_TYPE) <= {
        "brand", "supplier", "customer", "partner", "competitor", "technology_partner",
        "battery_supplier", "semiconductor_supplier", "software_partner", "cloud_partner",
        "logistics_partner", "manufacturing_partner", "joint_venture",
    }


def test_build_company_profile_includes_evidence_and_strength(tmp_path):
    db_path = tmp_path / "test.duckdb"
    persist_relationships([_relationship()], db_path=db_path)
    graph = build_graph(db_path=db_path)

    profile = build_company_profile(graph, "Peugeot")
    assert profile["relationship_type"] == "brand"
    assert profile["relationship_strength"] == "Direct (ownership)"
    assert profile["business_area"] == "Mass-market passenger vehicles"
    assert profile["geographic_exposure"] == "Europe"
    assert profile["evidence_url"] == "https://www.stellantis.com/en/brands"
    assert profile["confidence"] == "high"


def test_build_company_profile_returns_none_for_unconnected_entity(tmp_path):
    db_path = tmp_path / "test.duckdb"
    persist_relationships([_relationship()], db_path=db_path)
    graph = build_graph(db_path=db_path)

    assert build_company_profile(graph, "Not Connected Inc") is None


def test_build_all_profiles_covers_every_direct_neighbor(tmp_path):
    db_path = tmp_path / "test.duckdb"
    persist_relationships(
        [_relationship(), _relationship(target_entity="Jeep", business_area="SUVs", geographic_exposure="North America")],
        db_path=db_path,
    )
    graph = build_graph(db_path=db_path)

    profiles = build_all_profiles(graph)
    assert {p["entity_id"] for p in profiles} == {"Peugeot", "Jeep"}
    jeep = next(p for p in profiles if p["entity_id"] == "Jeep")
    assert jeep["business_area"] == "SUVs"
