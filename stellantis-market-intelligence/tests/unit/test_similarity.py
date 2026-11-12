"""Phase 18 - Historical Event Similarity tests."""

from __future__ import annotations

import duckdb
import pytest

from events.similarity import find_similar_events, load_historical_events


def _seed_historical_events(db_path, rows):
    from storage.duckdb import get_connection

    get_connection(db_path).close()
    conn = duckdb.connect(str(db_path))
    try:
        for row in rows:
            conn.execute(
                """
                INSERT INTO historical_events
                    (event_id, ticker, event_type, event_description, stla_return, sector_return,
                     market_return, supplier_reaction, competitor_reaction, commodity_reaction, recovery_time_days)
                VALUES (?, 'STLA', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                row,
            )
    finally:
        conn.close()


def test_find_similar_events_returns_empty_for_unknown_event(tmp_path):
    db_path = tmp_path / "test.duckdb"
    _seed_historical_events(
        db_path,
        [
            ("E1", "Production", "production cut announcement", -0.08, -0.02, -0.005, -0.03, -0.1, None, 5),
            ("E2", "Recall", "vehicle safety recall", -0.03, -0.01, -0.002, -0.01, -0.02, None, 2),
        ],
    )
    assert find_similar_events("UNKNOWN", db_path=db_path) == []


def test_find_similar_events_returns_empty_with_fewer_than_two_events(tmp_path):
    db_path = tmp_path / "test.duckdb"
    _seed_historical_events(
        db_path, [("E1", "Production", "production cut announcement", -0.08, -0.02, -0.005, -0.03, -0.1, None, 5)]
    )
    assert find_similar_events("E1", db_path=db_path) == []


def test_find_similar_events_ranks_closer_events_higher(tmp_path):
    db_path = tmp_path / "test.duckdb"
    _seed_historical_events(
        db_path,
        [
            ("E1", "Production", "production cut announcement at a European plant", -0.08, -0.02, -0.005, -0.03, -0.1, None, 5),
            ("E2", "Production", "production cut announcement at a North American plant", -0.075, -0.018, -0.004, -0.028, -0.09, None, 4),
            ("E3", "Recall", "vehicle safety recall over a braking defect", -0.02, -0.005, -0.001, -0.01, -0.01, None, 1),
        ],
    )

    results = find_similar_events("E1", top_n=2, db_path=db_path)
    assert [r["event_id"] for r in results] == ["E2", "E3"]
    assert results[0]["similarity"] > results[1]["similarity"]
    # Cosine similarity of standardized/normalized vectors ranges [-100, 100], not just [0, 100].
    assert all(-100 <= r["similarity"] <= 100 for r in results)


def test_find_similar_events_returns_empty_when_features_do_not_distinguish_events(tmp_path):
    db_path = tmp_path / "test.duckdb"
    _seed_historical_events(
        db_path,
        [
            ("E1", "Other", None, -0.08, None, None, None, None, None, None),
            ("E2", "Other", None, -0.03, None, None, None, None, None, None),
        ],
    )

    assert find_similar_events("E1", db_path=db_path) == []


def test_find_similar_events_respects_top_n(tmp_path):
    db_path = tmp_path / "test.duckdb"
    _seed_historical_events(
        db_path,
        [
            ("E1", "Production", "production cut", -0.08, -0.02, -0.005, -0.03, -0.1, None, 5),
            ("E2", "Production", "production cut", -0.07, -0.015, -0.005, -0.03, -0.1, None, 5),
            ("E3", "Production", "production cut", -0.06, -0.01, -0.005, -0.03, -0.1, None, 5),
        ],
    )
    assert len(find_similar_events("E1", top_n=1, db_path=db_path)) == 1


def test_load_historical_events_loads_all_rows(tmp_path):
    db_path = tmp_path / "test.duckdb"
    _seed_historical_events(
        db_path, [("E1", "Production", "production cut", -0.08, -0.02, -0.005, -0.03, -0.1, None, 5)]
    )
    df = load_historical_events(db_path=db_path)
    assert len(df) == 1
    assert df.iloc[0]["event_id"] == "E1"


def test_similarity_handles_missing_nullable_integer_recovery_times(tmp_path):
    db_path = tmp_path / "test.duckdb"
    _seed_historical_events(
        db_path,
        [
            ("E1", "Production", "production cut", -0.08, -0.02, -0.005, -0.03, -0.1, None, 1),
            ("E2", "Production", "production cut", -0.07, -0.015, -0.005, -0.03, -0.1, None, 2),
            ("E3", "Recall", "recall", -0.02, -0.01, -0.005, -0.01, -0.02, None, None),
        ],
    )
    results = find_similar_events("E3", db_path=db_path)
    assert len(results) == 2
    assert all(-100 <= result["similarity"] <= 100 for result in results)
