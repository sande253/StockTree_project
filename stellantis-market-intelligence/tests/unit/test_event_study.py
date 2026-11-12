"""Phase 6 - Event Study & Abnormal Returns tests."""

from __future__ import annotations

import pandas as pd
import pytest

from analytics.abnormal_returns import compute_abnormal_returns, load_beta_alpha, persist_abnormal_returns
from analytics.correlation import persist_correlation
from analytics.event_study import (
    compute_event_window_returns,
    compute_event_window_summary,
    persist_event_returns,
    run_event_study,
)
from events.detector import persist_events
from ingestion.market_data import upsert_price_data


def _price_series(closes: list[float]) -> pd.Series:
    dates = pd.date_range("2026-01-01", periods=len(closes), freq="D").date
    return pd.Series(closes, index=dates)


def test_compute_event_window_returns_computes_cumulative_return_relative_to_t0():
    prices = _price_series([100, 102, 101, 105, 103, 108, 110, 112, 109, 115, 120])
    event_date = prices.index[5]  # price = 108

    result = compute_event_window_returns("STLA", event_date, prices=prices, offsets=(-3, -1, 0, 1, 3))

    assert set(result["day_offset"]) == {-3, -1, 0, 1, 3}
    t0_row = result[result["day_offset"] == 0].iloc[0]
    assert t0_row["cumulative_return"] == pytest.approx(0.0)
    plus3_row = result[result["day_offset"] == 3].iloc[0]
    assert plus3_row["cumulative_return"] == pytest.approx(109 / 108 - 1.0)


def test_compute_event_window_returns_drops_offsets_outside_available_range():
    prices = _price_series([100, 102, 101])
    event_date = prices.index[0]
    result = compute_event_window_returns("STLA", event_date, prices=prices, offsets=(-5, 0, 5))
    assert set(result["day_offset"]) == {0}


def test_compute_event_window_returns_empty_when_event_date_missing():
    prices = _price_series([100, 102, 101])
    result = compute_event_window_returns("STLA", "2099-01-01", prices=prices)
    assert result.empty


def test_compute_event_window_summary_aggregates_configurable_windows():
    prices = _price_series([100, 102, 101, 105, 103, 108, 110, 112, 109, 115, 120])
    event_date = prices.index[5]
    summary = compute_event_window_summary(
        "STLA", event_date, prices=prices, windows=((-1, 1), (0, 3))
    )
    assert len(summary) == 2
    window_0_3 = summary[(summary["window_start_offset"] == 0) & (summary["window_end_offset"] == 3)].iloc[0]
    assert window_0_3["window_return"] == pytest.approx(109 / 108 - 1.0)


def test_compute_abnormal_returns_uses_market_model():
    event_returns = pd.DataFrame(
        {
            "day_offset": [0, 1],
            "date": ["2026-01-01", "2026-01-02"],
            "daily_return": [0.04, 0.01],
        }
    )
    reference_returns = pd.Series({"2026-01-01": 0.02, "2026-01-02": 0.02})
    result = compute_abnormal_returns("EVT-1", "SUPPLIER", event_returns, reference_returns, beta=1.5, alpha=0.0)

    assert len(result) == 2
    row0 = result[result["day_offset"] == 0].iloc[0]
    assert row0["expected_return"] == pytest.approx(0.03)
    assert row0["abnormal_return"] == pytest.approx(0.01)


def test_persist_event_returns_and_abnormal_returns_round_trip(tmp_path):
    db_path = tmp_path / "test.duckdb"
    prices = _price_series([100, 102, 101, 105, 103])
    event_date = prices.index[2]
    event_returns = compute_event_window_returns("SUPPLIER", event_date, prices=prices, offsets=(-1, 0, 1))

    inserted = persist_event_returns("EVT-1", event_returns, db_path=db_path)
    assert inserted == len(event_returns)

    reference_returns = pd.Series(
        {d: r for d, r in zip(event_returns["date"], [0.01, 0.02, -0.01])}
    )
    abnormal = compute_abnormal_returns(
        "EVT-1",
        "SUPPLIER",
        event_returns[["day_offset", "date", "daily_return"]],
        reference_returns,
        beta=1.0,
        alpha=0.0,
    )
    persisted = persist_abnormal_returns(abnormal, db_path=db_path)
    assert persisted == len(abnormal)

    import duckdb

    conn = duckdb.connect(str(db_path))
    try:
        er_count = conn.execute("SELECT COUNT(*) FROM event_returns").fetchone()[0]
        ab_count = conn.execute("SELECT COUNT(*) FROM abnormal_returns").fetchone()[0]
        assert er_count == len(event_returns)
        assert ab_count == len(abnormal)
    finally:
        conn.close()


def test_load_beta_alpha_returns_none_when_not_computed(tmp_path):
    db_path = tmp_path / "test.duckdb"
    assert load_beta_alpha("UNKNOWN", db_path=db_path) is None


def test_run_event_study_end_to_end(tmp_path):
    db_path = tmp_path / "test.duckdb"
    n = 15
    dates = pd.date_range("2026-01-01", periods=n, freq="D").date
    stla_closes = [100 + i * 0.5 for i in range(n)]
    supplier_closes = [50 + i * 0.3 for i in range(n)]

    # "F" must be a ticker from the configured company universe (config/companies.yaml)
    # since run_event_study() iterates that universe, not arbitrary tickers.
    for ticker, closes in (("STLA", stla_closes), ("F", supplier_closes)):
        rows = pd.DataFrame(
            {
                "ticker": ticker,
                "date": dates,
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

    event_date = dates[7]
    events = pd.DataFrame(
        [
            {
                "event_id": "STLA-evt1",
                "event_date": event_date,
                "ticker": "STLA",
                "return": 0.05,
                "z_score": 2.5,
                "volume_z_score": 1.0,
                "volatility": 0.02,
                "severity": "high",
                "direction": "positive",
                "detection_method": "absolute_return",
                "combined_score": 0.25,
            }
        ]
    )
    persist_events(events, db_path=db_path)

    beta_record = {
        "ticker": "F",
        "reference_ticker": "STLA",
        "pearson_correlation": 0.9,
        "pearson_p_value": 0.01,
        "pearson_ci_low": 0.8,
        "pearson_ci_high": 0.95,
        "spearman_correlation": 0.9,
        "spearman_p_value": 0.01,
        "beta": 0.6,
        "alpha": 0.0,
        "r_squared": 0.8,
        "beta_p_value": 0.01,
        "sample_size": 14,
    }
    persist_correlation(beta_record, db_path=db_path)

    summary = run_event_study("STLA-evt1", reference_ticker="STLA", db_path=db_path)
    assert "F" in summary["processed"]

    import duckdb

    conn = duckdb.connect(str(db_path))
    try:
        er = conn.execute(
            "SELECT COUNT(*) FROM event_returns WHERE ticker = 'F' AND event_id = 'STLA-evt1'"
        ).fetchone()[0]
        ab = conn.execute(
            "SELECT COUNT(*) FROM abnormal_returns WHERE ticker = 'F' AND event_id = 'STLA-evt1'"
        ).fetchone()[0]
        assert er > 0
        assert ab > 0
    finally:
        conn.close()


def test_run_event_study_raises_for_unknown_event(tmp_path):
    db_path = tmp_path / "test.duckdb"
    with pytest.raises(ValueError, match="Unknown event_id"):
        run_event_study("does-not-exist", db_path=db_path)
