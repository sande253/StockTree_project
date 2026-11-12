"""Price-feature computation pipeline (Phase 3).

Reads `price_data` for a ticker from DuckDB, computes the return/volatility
metrics from `analytics.returns`, and persists them into `price_features`.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from analytics.returns import (
    daily_return,
    drawdown,
    log_return,
    rolling_mean,
    rolling_return,
    rolling_std,
    rolling_volatility,
    volume_change,
    volume_zscore,
    zscore,
)

DEFAULT_WINDOW = 20


def compute_price_features(prices: pd.DataFrame, window: int = DEFAULT_WINDOW) -> pd.DataFrame:
    """Compute all Phase 3 metrics for a single ticker's price history.

    `prices` must be sorted by date and contain at least: ticker, date, close, volume.
    """
    close = prices["close"]
    volume = prices["volume"]
    ret = daily_return(close)

    out = pd.DataFrame(
        {
            "ticker": prices["ticker"],
            "date": prices["date"],
            "daily_return": ret,
            "log_return": log_return(close),
            "rolling_return": rolling_return(close, window),
            "rolling_mean": rolling_mean(close, window),
            "rolling_std": rolling_std(close, window),
            "rolling_volatility": rolling_volatility(ret, window),
            "zscore": zscore(close, window),
            "drawdown": drawdown(close),
            "volume_change": volume_change(volume),
            "volume_zscore": volume_zscore(volume, window),
            "lookback_window": window,
        }
    )
    return out


def load_price_history(ticker: str, db_path: Path | str | None = None) -> pd.DataFrame:
    """Load the full stored price history for a ticker, sorted by date."""
    from storage.duckdb import get_connection, normalize_date_column

    conn = get_connection(db_path)
    try:
        df = conn.execute(
            "SELECT ticker, date, close, volume FROM price_data WHERE ticker = ? AND interval = '1d' ORDER BY date",
            [ticker],
        ).fetchdf()
    finally:
        conn.close()
    return normalize_date_column(df)


def persist_price_features(features: pd.DataFrame, db_path: Path | str | None = None) -> int:
    """Upsert computed features into the DuckDB `price_features` table."""
    from storage.duckdb import get_connection

    conn = get_connection(db_path)
    try:
        conn.register("features_rows", features)
        conn.execute(
            """
            INSERT INTO price_features
                (ticker, date, daily_return, log_return, rolling_return, rolling_mean,
                 rolling_std, rolling_volatility, zscore, drawdown, volume_change,
                 volume_zscore, lookback_window)
            SELECT ticker, date, daily_return, log_return, rolling_return, rolling_mean,
                   rolling_std, rolling_volatility, zscore, drawdown, volume_change,
                   volume_zscore, lookback_window
            FROM features_rows
            ON CONFLICT (ticker, date) DO UPDATE SET
                daily_return = excluded.daily_return,
                log_return = excluded.log_return,
                rolling_return = excluded.rolling_return,
                rolling_mean = excluded.rolling_mean,
                rolling_std = excluded.rolling_std,
                rolling_volatility = excluded.rolling_volatility,
                zscore = excluded.zscore,
                drawdown = excluded.drawdown,
                volume_change = excluded.volume_change,
                volume_zscore = excluded.volume_zscore,
                lookback_window = excluded.lookback_window
            """
        )
        conn.unregister("features_rows")
        return len(features)
    finally:
        conn.close()


def compute_and_store_price_features(
    ticker: str, window: int = DEFAULT_WINDOW, db_path: Path | str | None = None
) -> int:
    """Full Phase 3 pipeline for one ticker: load -> compute -> persist."""
    prices = load_price_history(ticker, db_path=db_path)
    if prices.empty:
        raise ValueError(f"No price_data found for ticker {ticker!r}; run Phase 2 ingestion first")
    features = compute_price_features(prices, window=window)
    return persist_price_features(features, db_path=db_path)
