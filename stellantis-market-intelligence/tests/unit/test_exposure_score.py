"""Phase 22 - STLA Ecosystem Exposure Score tests."""

from __future__ import annotations

from datetime import date

import duckdb
import pytest

from relationships.exposure_score import (
    NOT_AN_INVESTMENT_SCORE_DISCLAIMER,
    WEIGHTS,
    compute_all_exposure_scores,
    compute_exposure_score,
)
from relationships.graph import Relationship, build_graph, persist_relationships


def test_weights_sum_to_one():
    assert sum(WEIGHTS.values()) == pytest.approx(1.0)


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


def test_compute_exposure_score_returns_none_for_unconnected_entity(tmp_path):
    db_path = tmp_path / "test.duckdb"
    persist_relationships([_relationship()], db_path=db_path)
    graph = build_graph(db_path=db_path)

    assert compute_exposure_score(graph, "Not Connected Inc", db_path=db_path) is None


def test_compute_exposure_score_includes_disclaimer_and_bounded_score(tmp_path):
    db_path = tmp_path / "test.duckdb"
    persist_relationships([_relationship()], db_path=db_path)
    graph = build_graph(db_path=db_path)

    result = compute_exposure_score(graph, "Peugeot", event_type="Production", db_path=db_path)
    assert result["disclaimer"] == NOT_AN_INVESTMENT_SCORE_DISCLAIMER
    assert 0 <= result["ecosystem_exposure_score"] <= 100
    # brand ownership + first-order + Production event relevance for "brand" -> high score.
    assert result["components"]["business_relationship_strength"]["score"] == 100
    assert result["components"]["graph_proximity"]["label"] == "first-order"
    assert result["components"]["event_relevance"]["score"] == 100


def test_compute_exposure_score_uses_neutral_relevance_for_unmapped_event_type(tmp_path):
    db_path = tmp_path / "test.duckdb"
    persist_relationships([_relationship()], db_path=db_path)
    graph = build_graph(db_path=db_path)

    result = compute_exposure_score(graph, "Peugeot", event_type="Macro", db_path=db_path)
    assert result["components"]["event_relevance"]["score"] == 50


def test_compute_exposure_score_uses_ticker_sensitivity_when_available(tmp_path):
    db_path = tmp_path / "test.duckdb"
    persist_relationships(
        [_relationship(target_entity="Supplier A", target_entity_type="company",
                        relationship_type="supplier", target_entity_ticker="SUP")],
        db_path=db_path,
    )
    from storage.duckdb import get_connection

    conn = get_connection(db_path)
    conn.execute(
        """
        INSERT INTO market_events
            (event_id, event_date, ticker, "return", severity, direction, detection_method, combined_score)
        VALUES ('STLA-2026-01-01', '2026-01-01', 'STLA', -0.08, 'high', 'negative', 'absolute_return', 0.25)
        """
    )
    conn.execute(
        """
        INSERT INTO abnormal_returns (event_id, ticker, day_offset, date, actual_return, expected_return, abnormal_return)
        VALUES ('STLA-2026-01-01', 'SUP', 0, '2026-01-01', -0.05, -0.01, -0.05)
        """
    )
    conn.close()
    graph = build_graph(db_path=db_path)

    result = compute_exposure_score(graph, "Supplier A", db_path=db_path)
    assert result["components"]["historical_sensitivity"]["label"] == "High"
    assert result["components"]["historical_reaction_frequency"]["ratio"] == pytest.approx(1.0)
    assert result["components"]["historical_reaction_frequency"]["score"] == 100


def test_compute_all_exposure_scores_sorted_descending(tmp_path):
    db_path = tmp_path / "test.duckdb"
    persist_relationships(
        [_relationship(), _relationship(target_entity="Competitor Co", target_entity_type="company", relationship_type="competitor")],
        db_path=db_path,
    )
    graph = build_graph(db_path=db_path)

    scores = compute_all_exposure_scores(graph, event_type="Production", db_path=db_path)
    assert [s["entity_id"] for s in scores] == ["Peugeot", "Competitor Co"]
    assert scores[0]["ecosystem_exposure_score"] >= scores[1]["ecosystem_exposure_score"]
