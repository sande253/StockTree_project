"""Reusable market-data ingestion pipeline (Phase 2).

Pipeline: fetch (yfinance, with retry) -> validate (missing/duplicate/invalid) ->
normalize -> persist raw Parquet -> upsert into DuckDB `price_data`.

Works for any ticker in the configured company universe, not just STLA.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

SOURCE_NAME = "yfinance"
RAW_DATA_DIR = Path("data/raw")
REQUIRED_RAW_COLUMNS = {"Open", "High", "Low", "Close", "Volume"}


class MarketDataError(RuntimeError):
    """Raised when market data cannot be retrieved or contains no usable rows."""


def _download_with_retry(
    ticker: str,
    start: str,
    end: str,
    interval: str,
    max_retries: int = 3,
    retry_delay_seconds: float = 1.0,
) -> pd.DataFrame:
    """Download OHLCV data via yfinance, retrying transient failures."""
    import yfinance as yf  # imported lazily so unit tests never require network access

    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            df = yf.download(
                ticker,
                start=start,
                end=end,
                interval=interval,
                progress=False,
                auto_adjust=False,
                threads=False,
            )
            if df is None or df.empty:
                raise MarketDataError(
                    f"No data returned for {ticker!r} ({start}..{end}, interval={interval})"
                )
            return df
        except Exception as exc:  # noqa: BLE001 - any failure here is a retryable transport error
            last_error = exc
            logger.warning(
                "yfinance download attempt %d/%d failed for %s: %s", attempt, max_retries, ticker, exc
            )
            if attempt < max_retries:
                time.sleep(retry_delay_seconds * attempt)
    raise MarketDataError(
        f"Failed to download data for {ticker!r} after {max_retries} attempts"
    ) from last_error


def normalize_raw_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Flatten yfinance's (possibly MultiIndex, single-ticker) columns to simple names."""
    out = df.copy()
    if isinstance(out.columns, pd.MultiIndex):
        out.columns = [c[0] for c in out.columns]
    out.index.name = "date"
    return out


def validate_price_data(df: pd.DataFrame, ticker: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Detect duplicate timestamps, invalid prices, and gaps. Returns (clean_df, issues_report)."""
    missing_required = [c for c in REQUIRED_RAW_COLUMNS if c not in df.columns]
    if missing_required:
        raise MarketDataError(f"{ticker}: missing required columns {missing_required}")

    working = df.copy()
    working.index = pd.to_datetime(working.index, errors="coerce").tz_localize(None).normalize()
    working.index.name = "date"
    numeric_columns = sorted(REQUIRED_RAW_COLUMNS | ({"Adj Close"} & set(working.columns)))
    working[numeric_columns] = working[numeric_columns].apply(pd.to_numeric, errors="coerce")

    dup_mask = working.index.duplicated(keep="first")
    duplicates_removed = int(dup_mask.sum())
    working = working[~dup_mask]

    ohlc = working[["Open", "High", "Low", "Close"]]
    invalid_mask = (
        ~np.isfinite(working[numeric_columns]).all(axis=1)
        | working.index.isna()
        | (ohlc <= 0).any(axis=1)
        | (working["High"] < working["Low"])
        | (working["Open"] > working["High"])
        | (working["Open"] < working["Low"])
        | (working["Close"] > working["High"])
        | (working["Close"] < working["Low"])
        | (working["Volume"] < 0)
        | (working["Volume"] % 1 != 0)
        | (working["Volume"] >= 2**63)
    )
    if "Adj Close" in working:
        invalid_mask |= working["Adj Close"] <= 0
    invalid_rows_removed = int(invalid_mask.sum())
    working = working[~invalid_mask]

    if working.empty:
        raise MarketDataError(f"{ticker}: no valid rows remain after validation")

    working = working.sort_index()
    expected_days = pd.bdate_range(working.index.min(), working.index.max())
    missing_business_days = [d.date().isoformat() for d in expected_days.difference(working.index)]

    issues = {
        "duplicates_removed": duplicates_removed,
        "invalid_rows_removed": invalid_rows_removed,
        "missing_business_days": missing_business_days,
    }
    return working, issues


def normalize_price_data(
    df: pd.DataFrame, ticker: str, interval: str, source: str = SOURCE_NAME
) -> pd.DataFrame:
    """Convert validated raw OHLCV data into the standard `price_data` row format."""
    adj_close = df["Adj Close"] if "Adj Close" in df.columns else df["Close"]
    out = pd.DataFrame(
        {
            "ticker": ticker,
            "date": pd.to_datetime(df.index).date,
            "open": df["Open"].astype(float).to_numpy(),
            "high": df["High"].astype(float).to_numpy(),
            "low": df["Low"].astype(float).to_numpy(),
            "close": df["Close"].astype(float).to_numpy(),
            "adj_close": adj_close.astype(float).to_numpy(),
            "volume": df["Volume"].astype("int64").to_numpy(),
            "interval": interval,
            "source": source,
        }
    )
    return out.reset_index(drop=True)


def save_raw_parquet(df: pd.DataFrame, ticker: str, start: str, end: str, interval: str) -> Path:
    """Persist the normalized rows as Parquet under data/raw/ (source-of-truth snapshot)."""
    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RAW_DATA_DIR / f"{ticker}_{start}_{end}_{interval}.parquet"
    df.to_parquet(out_path)
    return out_path


def upsert_price_data(rows: pd.DataFrame, db_path: Path | str | None = None) -> int:
    """Upsert normalized rows into the DuckDB `price_data` table, keyed on (ticker, date, interval)."""
    from storage.duckdb import get_connection

    conn = get_connection(db_path)
    try:
        conn.register("price_rows", rows)
        conn.execute(
            """
            INSERT INTO price_data
                (ticker, date, open, high, low, close, adj_close, volume, interval, source)
            SELECT ticker, date, open, high, low, close, adj_close, volume, interval, source
            FROM price_rows
            ON CONFLICT (ticker, date, interval) DO UPDATE SET
                open = excluded.open,
                high = excluded.high,
                low = excluded.low,
                close = excluded.close,
                adj_close = excluded.adj_close,
                volume = excluded.volume,
                source = excluded.source,
                ingested_at = now()
            """
        )
        conn.unregister("price_rows")
        return len(rows)
    finally:
        conn.close()


def ingest_price_history(
    ticker: str,
    start: str,
    end: str,
    interval: str = "1d",
    max_retries: int = 3,
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    """Full Phase 2 pipeline for a single ticker: fetch -> validate -> normalize -> persist."""
    raw = _download_with_retry(ticker, start, end, interval, max_retries=max_retries)
    raw = normalize_raw_columns(raw)
    clean, issues = validate_price_data(raw, ticker)
    rows = normalize_price_data(clean, ticker, interval)
    parquet_path = save_raw_parquet(rows, ticker, start, end, interval)
    row_count = upsert_price_data(rows, db_path=db_path)

    summary: dict[str, Any] = {
        "ticker": ticker,
        "rows_ingested": row_count,
        "parquet_path": str(parquet_path),
        **issues,
    }
    logger.info("Ingested %d rows for %s (%s..%s, interval=%s)", row_count, ticker, start, end, interval)
    return summary
