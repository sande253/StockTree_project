"""Phase 17 - Event Fingerprinting tests."""

from __future__ import annotations

import duckdb
import pytest

from events.fingerprint import (
    build_and_store_fingerprints,
    build_event_fingerprint,
    compute_peer_group_reaction,
    compute_recovery_time,
    load_event_context,
    persist_fingerprint,
)


def _seed_base_event(db_path):
    from storage.duckdb import get_connection

    conn = get_connection(db_path)
    conn.execute(
        """
        INSERT INTO market_events
            (event_id, event_date, ticker, "return", severity, direction, detection_method,
             combined_score, event_type, event_description, sector_return, market_return)
        VALUES ('STLA-2026-01-01', '2026-01-01', 'STLA', -0.08, 'high', 'negative', 'absolute_return',
                0.25, 'Production', 'Stellantis announces production cut', -0.02, -0.005)
        """
    )
    conn.close()


def _seed_companies(db_path, entries):
    conn = duckdb.connect(str(db_path))
    try:
        for ticker, relationship_type in entries:
            conn.execute(
                "INSERT INTO companies (ticker, company_name, relationship_type) VALUES (?, ?, ?)",
                [ticker, f"{ticker} Inc", relationship_type],
            )
    finally:
        conn.close()


def _seed_abnormal_returns(db_path, entries):
    conn = duckdb.connect(str(db_path))
    try:
        for ticker, abnormal_return in entries:
            conn.execute(
                """
                INSERT INTO abnormal_returns (event_id, ticker, day_offset, date, actual_return, expected_return, abnormal_return)
                VALUES ('STLA-2026-01-01', ?, 0, '2026-01-01', ?, 0.0, ?)
                """,
                [ticker, abnormal_return, abnormal_return],
            )
    finally:
        conn.close()


def _seed_event_returns(db_path, rows):
    conn = duckdb.connect(str(db_path))
    try:
        for day_offset, daily_return, cumulative_return in rows:
            conn.execute(
                """
                INSERT INTO event_returns (event_id, ticker, event_date, day_offset, date, daily_return, cumulative_return)
                VALUES ('STLA-2026-01-01', 'STLA', '2026-01-01', ?, '2026-01-01', ?, ?)
                """,
                [day_offset, daily_return, cumulative_return],
            )
    finally:
        conn.close()


def test_load_event_context_returns_none_for_unknown_event(tmp_path):
    db_path = tmp_path / "test.duckdb"
    from storage.duckdb import get_connection

    get_connection(db_path).close()
    assert load_event_context("UNKNOWN", db_path=db_path) is None


def test_load_event_context_returns_fields(tmp_path):
    db_path = tmp_path / "test.duckdb"
    _seed_base_event(db_path)

    context = load_event_context("STLA-2026-01-01", db_path=db_path)
    assert context["ticker"] == "STLA"
    assert context["event_type"] == "Production"
    assert context["stla_return"] == pytest.approx(-0.08)
    assert context["sector_return"] == pytest.approx(-0.02)


def test_compute_peer_group_reaction_averages_matching_companies(tmp_path):
    db_path = tmp_path / "test.duckdb"
    _seed_base_event(db_path)
    _seed_companies(db_path, [("SUP1", "supplier_tier1"), ("SUP2", "supplier_tier2"), ("OEM1", "oem")])
    _seed_abnormal_returns(db_path, [("SUP1", -0.03), ("SUP2", -0.01), ("OEM1", -0.10)])

    supplier_reaction = compute_peer_group_reaction("STLA-2026-01-01", ("supplier_tier1", "supplier_tier2"), db_path=db_path)
    assert supplier_reaction == pytest.approx(-0.02)

    competitor_reaction = compute_peer_group_reaction("STLA-2026-01-01", ("oem",), db_path=db_path)
    assert competitor_reaction == pytest.approx(-0.10)


def test_compute_peer_group_reaction_returns_none_when_no_matches(tmp_path):
    db_path = tmp_path / "test.duckdb"
    _seed_base_event(db_path)
    assert compute_peer_group_reaction("STLA-2026-01-01", ("commodity",), db_path=db_path) is None


def test_compute_recovery_time_finds_first_retraced_offset(tmp_path):
    db_path = tmp_path / "test.duckdb"
    _seed_base_event(db_path)
    _seed_event_returns(
        db_path,
        [
            (0, -0.08, 0.0),
            (1, 0.01, -0.07),
            (3, 0.02, -0.05),  # |−0.05| > 0.04 (50% of 0.08) -> not yet recovered
            (5, 0.03, -0.03),  # |−0.03| <= 0.04 -> recovered here
        ],
    )
    assert compute_recovery_time("STLA", "STLA-2026-01-01", db_path=db_path) == 5


def test_compute_recovery_time_returns_none_when_never_recovers(tmp_path):
    db_path = tmp_path / "test.duckdb"
    _seed_base_event(db_path)
    _seed_event_returns(db_path, [(0, -0.08, 0.0), (1, -0.01, -0.09)])
    assert compute_recovery_time("STLA", "STLA-2026-01-01", db_path=db_path) is None


def test_build_event_fingerprint_combines_everything(tmp_path):
    db_path = tmp_path / "test.duckdb"
    _seed_base_event(db_path)
    _seed_companies(db_path, [("SUP1", "supplier_tier1")])
    _seed_abnormal_returns(db_path, [("SUP1", -0.03)])
    _seed_event_returns(db_path, [(0, -0.08, 0.0), (5, 0.03, -0.03)])

    fingerprint = build_event_fingerprint("STLA-2026-01-01", db_path=db_path)
    assert fingerprint["event_type"] == "Production"
    assert fingerprint["supplier_reaction"] == pytest.approx(-0.03)
    assert fingerprint["competitor_reaction"] is None
    assert fingerprint["commodity_reaction"] is None
    assert fingerprint["recovery_time_days"] == 5


def test_build_and_store_fingerprints_persists_round_trip(tmp_path):
    db_path = tmp_path / "test.duckdb"
    _seed_base_event(db_path)

    count = build_and_store_fingerprints("STLA", db_path=db_path)
    assert count == 1

    conn = duckdb.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT event_type, stla_return FROM historical_events WHERE event_id = 'STLA-2026-01-01'"
        ).fetchone()
    finally:
        conn.close()
    assert row[0] == "Production"
    assert row[1] == pytest.approx(-0.08)
