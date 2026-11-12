"""Phase 11 - Corporate Relationship Graph tests."""

from __future__ import annotations

from datetime import date

import duckdb
import pytest

from relationships.entities import Entity
from relationships.graph import (
    Relationship,
    build_graph,
    load_and_store_relationships,
    load_relationships_config,
    load_relationships,
    persist_relationships,
)
from relationships.queries import entity_summary, find_path, neighbors, relationship_types_present
from storage.duckdb import get_connection
from storage.repository import get_relationships_for_company


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


def test_entity_rejects_invalid_entity_type():
    with pytest.raises(ValueError):
        Entity(entity_id="X", name="X Corp", entity_type="not-a-real-type")


def test_relationship_requires_evidence_url():
    with pytest.raises(ValueError, match="evidence_url"):
        _relationship(evidence_url="")


def test_relationship_requires_source():
    with pytest.raises(ValueError, match="source"):
        _relationship(source="")


def test_market_correlation_is_not_valid_relationship_evidence():
    with pytest.raises(ValueError, match="cannot substantiate a business relationship"):
        _relationship(source="Yahoo Finance Market Data Analysis")


def test_relationship_rejects_unknown_relationship_type():
    with pytest.raises(ValueError):
        _relationship(relationship_type="not-a-real-type")


def test_relationship_id_is_deterministic():
    a = _relationship()
    b = _relationship(description="different description, same identity")
    assert a.relationship_id == b.relationship_id


def test_load_relationships_config_parses_seeded_brands():
    relationships = load_relationships_config()
    brands = [relationship for relationship in relationships if relationship.relationship_type == "brand"]
    assert len(brands) == 14
    assert len(relationships) == 16
    assert all(r.evidence_url for r in relationships)
    assert all(r.source_entity == "STLA" for r in relationships)
    assert all(r.target_entity_type == "brand" for r in brands)
    assert all(r.source == "Stellantis official corporate site" for r in brands)
    names = {r.target_entity for r in relationships}
    assert "Peugeot" in names
    assert "Jeep" in names


def test_review_state_and_unsafe_relationship_urls():
    from relationships.graph import review_state

    assert review_state(None, None) == "unreviewed"
    assert review_state(date(2026, 1, 1), "announcement", date(2026, 10, 29)) == "review_due"
    assert review_state(date(2026, 10, 29), "announcement", date(2026, 10, 29)) == "historical_announcement"
    with pytest.raises(ValueError, match="HTTP"):
        _relationship(evidence_url="javascript:alert(1)")


def test_persist_relationships_round_trip_and_idempotent(tmp_path):
    db_path = tmp_path / "test.duckdb"
    relationships = [_relationship()]

    inserted = persist_relationships(relationships, db_path=db_path)
    assert inserted == 1
    inserted_again = persist_relationships(relationships, db_path=db_path)
    assert inserted_again == 1

    conn = duckdb.connect(str(db_path))
    try:
        count = conn.execute("SELECT COUNT(*) FROM relationships").fetchone()[0]
    finally:
        conn.close()
    assert count == 1


def test_build_graph_creates_nodes_and_edges(tmp_path):
    db_path = tmp_path / "test.duckdb"
    persist_relationships([_relationship(), _relationship(target_entity="Jeep", relationship_type="brand")], db_path=db_path)

    graph = build_graph(db_path=db_path)
    assert graph.has_node("STLA")
    assert graph.has_edge("STLA", "Peugeot")
    assert graph.edges["STLA", "Peugeot"]["evidence_url"] == "https://www.stellantis.com/en/brands"


def test_legacy_correlation_rows_are_hidden_from_relationship_reads(tmp_path):
    db_path = tmp_path / "test.duckdb"
    persist_relationships([_relationship()], db_path=db_path)
    conn = get_connection(db_path)
    try:
        conn.execute(
            """
            INSERT INTO relationships
                (relationship_id, source_entity, target_entity, target_entity_type,
                 relationship_type, description, confidence, date_discovered, source, evidence_url)
            VALUES
                ('legacy-correlation', 'STLA', 'F', 'company', 'competitor',
                 'Same-day market correlation', 'high', DATE '2026-10-05',
                 'Yahoo Finance Market Data Analysis', 'https://finance.yahoo.com/quote/F')
            """
        )
    finally:
        conn.close()

    assert len(load_relationships(db_path=db_path)) == 1
    assert len(get_relationships_for_company("STLA", db_path=db_path)) == 1
    assert not build_graph(db_path=db_path).has_edge("STLA", "F")


def test_queries_neighbors_find_path_and_entity_summary(tmp_path):
    db_path = tmp_path / "test.duckdb"
    persist_relationships([_relationship(), _relationship(target_entity="Jeep")], db_path=db_path)
    graph = build_graph(db_path=db_path)

    names = {n["entity_id"] for n in neighbors(graph, "STLA")}
    assert names == {"Peugeot", "Jeep"}

    assert neighbors(graph, "unknown-entity") == []
    assert relationship_types_present(graph) == ["brand"]
    assert find_path(graph, "STLA", "Peugeot") == ["STLA", "Peugeot"]
    assert find_path(graph, "STLA", "unknown-entity") is None

    summary = entity_summary(graph, "STLA")
    assert summary["outgoing_relationships"] == 2
    assert entity_summary(graph, "unknown-entity") is None


def test_load_and_store_relationships_pipeline(tmp_path):
    db_path = tmp_path / "test.duckdb"
    count = load_and_store_relationships(db_path=db_path)
    assert count >= 10

    conn = duckdb.connect(str(db_path))
    try:
        stored = conn.execute("SELECT COUNT(*) FROM relationships").fetchone()[0]
    finally:
        conn.close()
    assert stored == count
