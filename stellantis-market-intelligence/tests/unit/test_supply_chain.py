"""Phase 14 - Supply-Chain Impact Propagation tests."""

from __future__ import annotations

from datetime import date

import pytest

from relationships.graph import Relationship, build_graph, persist_relationships
from relationships.supply_chain import (
    compute_supply_chain_exposure,
    order_label,
    trace_exposure_path,
)


def _relationship(**overrides) -> Relationship:
    defaults = dict(
        source_entity="STLA",
        target_entity="Supplier A",
        target_entity_type="company",
        relationship_type="supplier",
        confidence="high",
        date_discovered=date(2026, 10, 4),
        source="Example filing",
        evidence_url="https://example.com/evidence",
    )
    defaults.update(overrides)
    return Relationship(**defaults)


def test_order_label_known_and_fallback():
    assert order_label(1) == "first-order"
    assert order_label(2) == "second-order"
    assert order_label(3) == "third-order"
    assert order_label(4) == "4th-order"


def test_trace_exposure_path_returns_none_for_unreachable_or_unknown_entities(tmp_path):
    db_path = tmp_path / "test.duckdb"
    persist_relationships([_relationship()], db_path=db_path)
    graph = build_graph(db_path=db_path)

    assert trace_exposure_path(graph, "STLA", "Unknown Co") is None
    assert trace_exposure_path(graph, "Unknown Co", "STLA") is None


def test_trace_exposure_path_reports_direct_hop(tmp_path):
    db_path = tmp_path / "test.duckdb"
    persist_relationships([_relationship()], db_path=db_path)
    graph = build_graph(db_path=db_path)

    hops = trace_exposure_path(graph, "STLA", "Supplier A")
    assert len(hops) == 1
    assert hops[0] == {
        "from": "STLA",
        "to": "Supplier A",
        "relationship_type": "supplier",
        "confidence": "high",
        "evidence_url": "https://example.com/evidence",
    }


def test_compute_supply_chain_exposure_first_order_only(tmp_path):
    db_path = tmp_path / "test.duckdb"
    persist_relationships(
        [_relationship(), _relationship(target_entity="Supplier B", relationship_type="battery_supplier")],
        db_path=db_path,
    )
    graph = build_graph(db_path=db_path)

    exposure = compute_supply_chain_exposure(graph)
    assert {e["entity_id"] for e in exposure} == {"Supplier A", "Supplier B"}
    assert all(e["exposure_order"] == "first-order" for e in exposure)
    assert all(e["hop_count"] == 1 for e in exposure)


def test_compute_supply_chain_exposure_multi_hop_second_order(tmp_path):
    db_path = tmp_path / "test.duckdb"
    persist_relationships(
        [
            _relationship(),
            # Second-order edge: Supplier A -> Semiconductor Co B (not from STLA directly).
            _relationship(
                source_entity="Supplier A",
                target_entity="Semiconductor Co B",
                relationship_type="semiconductor_supplier",
            ),
        ],
        db_path=db_path,
    )
    graph = build_graph(db_path=db_path)

    exposure = compute_supply_chain_exposure(graph)
    by_id = {e["entity_id"]: e for e in exposure}
    assert by_id["Supplier A"]["exposure_order"] == "first-order"
    assert by_id["Semiconductor Co B"]["exposure_order"] == "second-order"
    assert by_id["Semiconductor Co B"]["path"][0]["to"] == "Supplier A"
    assert by_id["Semiconductor Co B"]["path"][1]["to"] == "Semiconductor Co B"


def test_compute_supply_chain_exposure_respects_max_depth(tmp_path):
    db_path = tmp_path / "test.duckdb"
    persist_relationships(
        [
            _relationship(),
            _relationship(
                source_entity="Supplier A", target_entity="Semiconductor Co B",
                relationship_type="semiconductor_supplier",
            ),
        ],
        db_path=db_path,
    )
    graph = build_graph(db_path=db_path)

    exposure = compute_supply_chain_exposure(graph, max_depth=1)
    assert {e["entity_id"] for e in exposure} == {"Supplier A"}


def test_compute_supply_chain_exposure_empty_for_unknown_source(tmp_path):
    db_path = tmp_path / "test.duckdb"
    persist_relationships([_relationship()], db_path=db_path)
    graph = build_graph(db_path=db_path)

    assert compute_supply_chain_exposure(graph, source_entity="Unknown Co") == []
