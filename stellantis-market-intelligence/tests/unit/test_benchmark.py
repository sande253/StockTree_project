"""Phase 7 - Market vs Sector vs STLA tests."""

from __future__ import annotations

import pandas as pd
import pytest

from analytics.benchmark import (
    analyze_and_store_event_context,
    analyze_event_context,
    classify_movement,
    get_return_on_date,
    load_benchmarks,
    persist_event_context,
)
from analytics.features import compute_and_store_price_features
from events.detector import persist_events
from ingestion.market_data import upsert_price_data


def test_load_benchmarks_returns_configured_market_and_sector():
    benchmarks = load_benchmarks()
    assert benchmarks["market"]["ticker"] == "^GSPC"
    assert benchmarks["sector"]["ticker"] == "CARZ"


def test_classify_movement_stla_specific_when_benchmarks_flat():
    result = classify_movement(stla_return=-0.08, market_return=-0.001, sector_return=0.001)
    assert result == "stla_specific"


def test_classify_movement_market_wide_when_everything_moves_together():
    result = classify_movement(stla_return=-0.05, market_return=-0.04, sector_return=-0.045)
    assert result == "market_wide"


def test_classify_movement_sector_wide_when_only_sector_explains():
    result = classify_movement(stla_return=-0.05, market_return=-0.001, sector_return=-0.04)
    assert result == "sector_wide"


def test_classify_movement_mixed_when_only_market_explains():
    result = classify_movement(stla_return=-0.05, market_return=-0.04, sector_return=0.01)
    assert result == "mixed"


def test_classify_movement_insufficient_data_when_benchmark_missing():
    assert classify_movement(-0.05, None, -0.01) == "insufficient_data"


def _seed_ticker(db_path, ticker: str, closes: list[float]) -> None:
    n = len(closes)
    rows = pd.DataFrame(
        {
            "ticker": ticker,
            "date": pd.date_range("2026-01-01", periods=n, freq="D").date,
            "open": closes,
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "close": closes,
            "adj_close": closes,
            "volume": [1000] * n,
            "interval": "1d",
            "source": "yfinance",
        }
    )
    upsert_price_data(rows, db_path=db_path)
    compute_and_store_price_features(ticker, window=3, db_path=db_path)


def test_get_return_on_date_and_analyze_event_context_end_to_end(tmp_path):
    db_path = tmp_path / "test.duckdb"
    stla_closes = [100, 101, 100, 92]  # big drop on day 4 (index 3)
    market_closes = [100, 100.5, 100.2, 99.8]  # market roughly flat
    sector_closes = [100, 100.4, 100.1, 98.5]  # sector down a bit, but far less than STLA

    _seed_ticker(db_path, "STLA", stla_closes)
    _seed_ticker(db_path, "^GSPC", market_closes)
    _seed_ticker(db_path, "CARZ", sector_closes)

    event_date = pd.date_range("2026-01-01", periods=4, freq="D").date[3]

    stla_return = get_return_on_date("STLA", event_date, db_path=db_path)
    assert stla_return == pytest.approx(92 / 100 - 1.0)

    context = analyze_event_context(event_date, db_path=db_path)
    assert context["classification"] == "stla_specific"
    assert context["market_adjusted_return"] == pytest.approx(context["stla_return"] - context["market_return"])
    assert context["sector_adjusted_return"] == pytest.approx(context["stla_return"] - context["sector_return"])


def test_analyze_event_context_raises_when_stla_return_missing(tmp_path):
    db_path = tmp_path / "empty.duckdb"
    with pytest.raises(ValueError, match="No STLA return found"):
        analyze_event_context("2026-01-01", db_path=db_path)


def test_analyze_and_store_event_context_persists_onto_market_event(tmp_path):
    db_path = tmp_path / "test.duckdb"
    stla_closes = [100, 101, 100, 92]
    market_closes = [100, 100.5, 100.2, 99.8]
    sector_closes = [100, 100.4, 100.1, 98.5]
    _seed_ticker(db_path, "STLA", stla_closes)
    _seed_ticker(db_path, "^GSPC", market_closes)
    _seed_ticker(db_path, "CARZ", sector_closes)

    event_date = pd.date_range("2026-01-01", periods=4, freq="D").date[3]
    events = pd.DataFrame(
        [
            {
                "event_id": "STLA-evt1",
                "event_date": event_date,
                "ticker": "STLA",
                "return": -0.08,
                "z_score": -2.0,
                "volume_z_score": 1.0,
                "volatility": 0.02,
                "severity": "high",
                "direction": "negative",
                "detection_method": "absolute_return",
                "combined_score": 0.25,
            }
        ]
    )
    persist_events(events, db_path=db_path)

    context = analyze_and_store_event_context("STLA-evt1", db_path=db_path)
    assert context["classification"] == "stla_specific"

    import duckdb

    conn = duckdb.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT classification, market_return, sector_return FROM market_events WHERE event_id = 'STLA-evt1'"
        ).fetchone()
    finally:
        conn.close()
    assert row[0] == "stla_specific"
    assert row[1] is not None
    assert row[2] is not None


def test_analyze_and_store_event_context_raises_for_unknown_event(tmp_path):
    db_path = tmp_path / "empty.duckdb"
    with pytest.raises(ValueError, match="Unknown event_id"):
        analyze_and_store_event_context("does-not-exist", db_path=db_path)
