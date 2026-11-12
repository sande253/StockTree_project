"""Phase 13 - Business + Stock Relationship tests."""

from __future__ import annotations

from datetime import date

import duckdb
import pytest

from relationships.combined_profile import (
    DATA_UNAVAILABLE,
    NOT_APPLICABLE,
    build_all_combined_profiles,
    build_combined_profile,
    load_current_event_reaction,
    load_historical_event_sensitivity,
    load_statistical_correlation,
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
    )
    defaults.update(overrides)
    return Relationship(**defaults)


def test_build_combined_profile_reports_not_applicable_when_entity_has_no_ticker(tmp_path):
    db_path = tmp_path / "test.duckdb"
    persist_relationships([_relationship()], db_path=db_path)
    graph = build_graph(db_path=db_path)

    profile = build_combined_profile(graph, "Peugeot", db_path=db_path)
    assert profile["ticker"] is None
    assert profile["historical_correlation"] == NOT_APPLICABLE
    assert profile["historical_event_sensitivity"] == NOT_APPLICABLE
    assert profile["current_event_reaction"] == NOT_APPLICABLE
    assert profile["documented_relationship"] is True


def test_build_combined_profile_returns_none_for_unconnected_entity(tmp_path):
    db_path = tmp_path / "test.duckdb"
    persist_relationships([_relationship()], db_path=db_path)
    graph = build_graph(db_path=db_path)

    assert build_combined_profile(graph, "Not Connected Inc", db_path=db_path) is None


def _seed_market_data(db_path):
    from storage.duckdb import get_connection

    conn = get_connection(db_path)
    conn.execute(
        "INSERT INTO correlations (ticker, reference_ticker, pearson_correlation, sample_size) "
        "VALUES ('SUP', 'STLA', 0.68, 120)"
    )
    conn.execute(
        """
        INSERT INTO market_events
            (event_id, event_date, ticker, "return", severity, direction, detection_method, combined_score)
        VALUES
            ('STLA-2026-01-01', '2026-01-01', 'STLA', -0.08, 'high', 'negative', 'absolute_return', 0.25),
            ('STLA-2026-02-01', '2026-02-01', 'STLA', -0.06, 'medium', 'negative', 'absolute_return', 0.25)
        """
    )
    conn.execute(
        """
        INSERT INTO abnormal_returns (event_id, ticker, day_offset, date, actual_return, expected_return, abnormal_return)
        VALUES
            ('STLA-2026-01-01', 'SUP', 0, '2026-01-01', -0.05, -0.01, -0.05),
            ('STLA-2026-02-01', 'SUP', 0, '2026-02-01', -0.01, -0.005, -0.005)
        """
    )
    conn.close()


def test_load_statistical_correlation_returns_none_when_not_computed(tmp_path):
    db_path = tmp_path / "test.duckdb"
    from storage.duckdb import get_connection

    get_connection(db_path).close()
    assert load_statistical_correlation("SUP", db_path=db_path) is None


def test_load_historical_event_sensitivity_and_current_reaction(tmp_path):
    db_path = tmp_path / "test.duckdb"
    _seed_market_data(db_path)

    sensitivity = load_historical_event_sensitivity("SUP", db_path=db_path)
    assert sensitivity["sample_size"] == 2
    assert sensitivity["significant_reaction_count"] == 1
    assert sensitivity["sensitivity_label"] == "High"  # 1/2 significant reactions = 0.5 ratio -> High

    reaction = load_current_event_reaction("SUP", db_path=db_path)
    assert reaction["event_id"] == "STLA-2026-02-01"
    assert reaction["abnormal_return"] == pytest.approx(-0.005)


def test_build_combined_profile_merges_business_and_market_data(tmp_path):
    db_path = tmp_path / "test.duckdb"
    _seed_market_data(db_path)
    persist_relationships(
        [_relationship(target_entity="Supplier A", target_entity_type="company",
                        relationship_type="supplier", target_entity_ticker="SUP")],
        db_path=db_path,
    )
    graph = build_graph(db_path=db_path)

    profile = build_combined_profile(graph, "Supplier A", db_path=db_path)
    assert profile["ticker"] == "SUP"
    assert profile["historical_correlation"] == pytest.approx(0.68)
    assert profile["historical_event_sensitivity"] == "High"
    assert profile["current_event_reaction"] == pytest.approx(-0.005)
    assert profile["relationship_type"] == "supplier"


def test_build_all_combined_profiles_covers_every_neighbor(tmp_path):
    db_path = tmp_path / "test.duckdb"
    persist_relationships([_relationship(), _relationship(target_entity="Jeep")], db_path=db_path)
    graph = build_graph(db_path=db_path)

    profiles = build_all_combined_profiles(graph, db_path=db_path)
    assert {p["entity_id"] for p in profiles} == {"Peugeot", "Jeep"}
