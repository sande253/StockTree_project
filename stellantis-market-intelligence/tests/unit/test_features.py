"""Phase 3 - Return & Volatility Engine tests."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from analytics.features import compute_and_store_price_features, compute_price_features
from analytics.returns import (
    daily_return,
    drawdown,
    log_return,
    rolling_mean,
    rolling_std,
    rolling_volatility,
    volume_change,
    volume_zscore,
    zscore,
)
from ingestion.market_data import upsert_price_data


def test_daily_and_log_return_basic_values():
    prices = pd.Series([100.0, 110.0, 99.0])
    ret = daily_return(prices)
    assert ret.iloc[0] != ret.iloc[0]  # NaN for first element
    assert ret.iloc[1] == pytest.approx(0.10)
    assert ret.iloc[2] == pytest.approx(-0.1)

    lret = log_return(prices)
    assert lret.iloc[1] == pytest.approx(np.log(110.0 / 100.0))


def test_rolling_mean_std_and_zscore_require_full_window():
    series = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    mean = rolling_mean(series, window=3)
    std = rolling_std(series, window=3)
    z = zscore(series, window=3)

    assert mean.iloc[:2].isna().all()
    assert mean.iloc[2] == pytest.approx(2.0)
    assert std.iloc[2] == pytest.approx(series.iloc[0:3].std())
    assert z.iloc[2] == pytest.approx((series.iloc[2] - mean.iloc[2]) / std.iloc[2])


def test_rolling_volatility_annualizes_when_requested():
    returns = pd.Series([0.01, -0.02, 0.015, 0.03, -0.01])
    vol = rolling_volatility(returns, window=3, annualize=False)
    vol_annualized = rolling_volatility(returns, window=3, annualize=True)
    assert vol_annualized.iloc[-1] == pytest.approx(vol.iloc[-1] * np.sqrt(252))


def test_drawdown_is_zero_at_new_highs_and_negative_after_decline():
    prices = pd.Series([100.0, 110.0, 90.0])
    dd = drawdown(prices)
    assert dd.iloc[0] == pytest.approx(0.0)
    assert dd.iloc[1] == pytest.approx(0.0)
    assert dd.iloc[2] == pytest.approx(90.0 / 110.0 - 1.0)


def test_volume_change_and_zscore():
    volume = pd.Series([1000, 1100, 1200, 2300, 1150])
    change = volume_change(volume)
    assert change.iloc[1] == pytest.approx(0.10)

    vz = volume_zscore(volume, window=3)
    assert vz.iloc[:2].isna().all()


def test_compute_price_features_returns_expected_columns():
    prices = pd.DataFrame(
        {
            "ticker": ["STLA"] * 5,
            "date": pd.date_range("2026-01-01", periods=5, freq="D").date,
            "close": [10.0, 10.5, 10.2, 10.8, 11.0],
            "volume": [1000, 1100, 900, 1200, 1300],
        }
    )
    features = compute_price_features(prices, window=3)

    expected_cols = {
        "ticker",
        "date",
        "daily_return",
        "log_return",
        "rolling_return",
        "rolling_mean",
        "rolling_std",
        "rolling_volatility",
        "zscore",
        "drawdown",
        "volume_change",
        "volume_zscore",
        "lookback_window",
    }
    assert expected_cols.issubset(features.columns)
    assert (features["lookback_window"] == 3).all()
    assert len(features) == 5


def test_compute_and_store_price_features_end_to_end(tmp_path):
    db_path = tmp_path / "test.duckdb"
    rows = pd.DataFrame(
        {
            "ticker": ["STLA"] * 5,
            "date": pd.date_range("2026-01-01", periods=5, freq="D").date,
            "open": [10.0, 10.5, 10.2, 10.8, 11.0],
            "high": [10.2, 10.7, 10.4, 11.0, 11.2],
            "low": [9.8, 10.3, 10.0, 10.6, 10.8],
            "close": [10.0, 10.5, 10.2, 10.8, 11.0],
            "adj_close": [10.0, 10.5, 10.2, 10.8, 11.0],
            "volume": [1000, 1100, 900, 1200, 1300],
            "interval": "1d",
            "source": "yfinance",
        }
    )
    upsert_price_data(rows, db_path=db_path)
    intraday = rows.copy()
    intraday["interval"] = "1h"
    intraday["close"] = 999.0
    upsert_price_data(intraday, db_path=db_path)

    count = compute_and_store_price_features("STLA", window=3, db_path=db_path)
    assert count == 5

    import duckdb

    conn = duckdb.connect(str(db_path))
    try:
        stored = conn.execute(
            "SELECT COUNT(*) FROM price_features WHERE ticker = 'STLA'"
        ).fetchone()[0]
        assert stored == 5
        from analytics.event_study import load_close_prices

        daily_prices = load_close_prices("STLA", db_path=db_path)
        assert len(daily_prices) == 5
        assert daily_prices.iloc[0] == 10.0
    finally:
        conn.close()


def test_compute_and_store_price_features_raises_for_unknown_ticker(tmp_path):
    db_path = tmp_path / "empty.duckdb"
    with pytest.raises(ValueError, match="No price_data found"):
        compute_and_store_price_features("UNKNOWN", db_path=db_path)
