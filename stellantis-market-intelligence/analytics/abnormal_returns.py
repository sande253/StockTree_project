"""Abnormal-return calculation using a simple market model (Phase 6).

Expected return = alpha + beta * reference_ticker_return, where beta/alpha come
from the Phase 5 `correlations` table. Abnormal return = actual - expected.
This is a simple, transparent model - not a claim of predictive power.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def load_beta_alpha(
    ticker: str, reference_ticker: str = "STLA", db_path: Path | str | None = None
) -> tuple[float, float] | None:
    """Fetch the Phase 5 market-model (beta, alpha) for a ticker, or None if not computed."""
    from storage.duckdb import get_connection

    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT beta, alpha FROM correlations WHERE ticker = ? AND reference_ticker = ?",
            [ticker, reference_ticker],
        ).fetchone()
    finally:
        conn.close()
    if row is None or row[0] is None or row[1] is None:
        return None
    return float(row[0]), float(row[1])


def compute_abnormal_returns(
    event_id: str,
    ticker: str,
    event_returns: pd.DataFrame,
    reference_returns: pd.Series,
    beta: float,
    alpha: float,
) -> pd.DataFrame:
    """`event_returns` must have columns: day_offset, date, daily_return (for `ticker`)."""
    records = []
    for row in event_returns.itertuples(index=False):
        actual = row.daily_return
        ref_return = reference_returns.get(row.date)
        if actual is None or ref_return is None or pd.isna(actual) or pd.isna(ref_return):
            continue
        expected = alpha + beta * ref_return
        records.append(
            {
                "event_id": event_id,
                "ticker": ticker,
                "day_offset": row.day_offset,
                "date": row.date,
                "actual_return": float(actual),
                "expected_return": float(expected),
                "abnormal_return": float(actual - expected),
            }
        )
    return pd.DataFrame.from_records(records)


def persist_abnormal_returns(df: pd.DataFrame, db_path: Path | str | None = None) -> int:
    """Upsert abnormal-return rows into `abnormal_returns`."""
    from storage.duckdb import get_connection

    if df.empty:
        return 0

    conn = get_connection(db_path)
    try:
        conn.register("ab_rows", df)
        conn.execute(
            """
            INSERT INTO abnormal_returns
                (event_id, ticker, day_offset, date, actual_return, expected_return, abnormal_return)
            SELECT event_id, ticker, day_offset, date, actual_return, expected_return, abnormal_return
            FROM ab_rows
            ON CONFLICT (event_id, ticker, day_offset) DO UPDATE SET
                date = excluded.date,
                actual_return = excluded.actual_return,
                expected_return = excluded.expected_return,
                abnormal_return = excluded.abnormal_return
            """
        )
        conn.unregister("ab_rows")
        return len(df)
    finally:
        conn.close()
