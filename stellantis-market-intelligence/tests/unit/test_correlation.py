"""Phase 5 - Correlation Analysis tests."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from analytics.correlation import (
    MIN_SAMPLE_SIZE,
    beta_and_r2,
    compute_company_correlation,
    pearson_correlation,
    persist_correlation,
    persist_rolling_correlations,
    rolling_correlation,
    spearman_correlation,
)
from ingestion.market_data import upsert_price_data


def _correlated_series(n: int = 40, noise: float = 0.3) -> tuple[pd.Series, pd.Series]:
    rng = np.random.default_rng(42)
    x = pd.Series(rng.normal(0, 0.02, size=n))
    y = 0.5 * x + noise * rng.normal(0, 0.01, size=n)
    return x, y


def test_pearson_correlation_detects_strong_relationship():
    x, y = _correlated_series()
    result = pearson_correlation(x, y)
    assert result["sample_size"] == len(x)
    assert result["correlation"] > 0.9
    assert result["p_value"] < 0.05
    assert result["ci_low"] < result["correlation"] < result["ci_high"]


def test_pearson_correlation_returns_none_below_min_sample_size():
    x = pd.Series([0.01, 0.02])
    y = pd.Series([0.015, 0.025])
    result = pearson_correlation(x, y)
    assert result["correlation"] is None
    assert result["sample_size"] == 2


def test_spearman_correlation_matches_direction_of_pearson():
    x, y = _correlated_series()
    result = spearman_correlation(x, y)
    assert result["correlation"] > 0.8
    assert result["sample_size"] == len(x)


def test_rolling_correlation_has_nan_prefix_then_values():
    x, y = _correlated_series(n=30)
    rolled = rolling_correlation(x, y, window=10)
    assert rolled.iloc[:9].isna().all()
    assert rolled.iloc[9:].notna().all()


def test_beta_and_r2_recovers_known_slope():
    rng = np.random.default_rng(1)
    reference = pd.Series(rng.normal(0, 0.02, size=50))
    company = 1.5 * reference  # exact beta of 1.5, no noise
    result = beta_and_r2(company, reference)
    assert result["beta"] == pytest.approx(1.5, rel=1e-6)
    assert result["r_squared"] == pytest.approx(1.0, rel=1e-6)
    assert result["sample_size"] == 50


def test_beta_and_r2_returns_none_below_min_sample_size():
    reference = pd.Series(np.arange(MIN_SAMPLE_SIZE - 1, dtype=float))
    company = reference * 2
    result = beta_and_r2(company, reference)
    assert result["beta"] is None
    assert result["sample_size"] == MIN_SAMPLE_SIZE - 1


def _seed_price_data(db_path, ticker: str, closes: list[float]) -> None:
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
            "volume": [1000 + i for i in range(n)],
            "interval": "1d",
            "source": "yfinance",
        }
    )
    upsert_price_data(rows, db_path=db_path)


def test_compute_company_correlation_end_to_end(tmp_path):
    db_path = tmp_path / "test.duckdb"
    rng = np.random.default_rng(7)
    stla_closes = list(100 + np.cumsum(rng.normal(0, 1, size=40)))
    company_closes = [c * 1.2 for c in stla_closes]  # near-perfectly correlated

    _seed_price_data(db_path, "STLA", stla_closes)
    _seed_price_data(db_path, "SUPPLIER", company_closes)

    from analytics.features import compute_and_store_price_features

    compute_and_store_price_features("STLA", window=5, db_path=db_path)
    compute_and_store_price_features("SUPPLIER", window=5, db_path=db_path)

    result = compute_company_correlation("SUPPLIER", reference_ticker="STLA", rolling_window=5, db_path=db_path)
    assert result is not None
    record, rolling_df = result
    assert record["ticker"] == "SUPPLIER"
    assert record["pearson_correlation"] > 0.9
    assert record["sample_size"] > MIN_SAMPLE_SIZE

    persist_correlation(record, db_path=db_path)
    persisted_rows = persist_rolling_correlations(rolling_df, db_path=db_path)
    assert persisted_rows == len(rolling_df)

    import duckdb

    conn = duckdb.connect(str(db_path))
    try:
        stored = conn.execute(
            "SELECT pearson_correlation FROM correlations WHERE ticker = 'SUPPLIER'"
        ).fetchone()
        assert stored[0] > 0.9
        rolling_count = conn.execute(
            "SELECT COUNT(*) FROM rolling_correlations WHERE ticker = 'SUPPLIER'"
        ).fetchone()[0]
        assert rolling_count == len(rolling_df)
    finally:
        conn.close()


def test_compute_company_correlation_returns_none_without_data(tmp_path):
    db_path = tmp_path / "empty.duckdb"
    result = compute_company_correlation("UNKNOWN", reference_ticker="STLA", db_path=db_path)
    assert result is None
