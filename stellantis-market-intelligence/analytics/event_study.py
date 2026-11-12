"""Event-study analysis: how other companies react around a reference ticker's events (Phase 6).

`day_offset` is measured in trading days relative to the event date (T0): e.g.
day_offset=-5 is five trading days before the event, +5 is five trading days after.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

DEFAULT_OFFSETS: tuple[int, ...] = (-5, -3, -1, 0, 1, 3, 5)
DEFAULT_WINDOWS: tuple[tuple[int, int], ...] = ((-5, 5), (-3, 3), (-1, 1), (0, 1), (0, 3), (0, 5))


def load_close_prices(ticker: str, db_path: Path | str | None = None) -> pd.Series:
    """Load the stored close-price series for a ticker, indexed by (python) date."""
    from storage.duckdb import get_connection, normalize_date_column

    conn = get_connection(db_path)
    try:
        df = conn.execute(
            "SELECT date, close FROM price_data WHERE ticker = ? AND interval = '1d' ORDER BY date", [ticker]
        ).fetchdf()
    finally:
        conn.close()
    df = normalize_date_column(df)
    return df.set_index("date")["close"]


def compute_event_window_returns(
    ticker: str,
    event_date: Any,
    prices: pd.Series | None = None,
    offsets: tuple[int, ...] = DEFAULT_OFFSETS,
    db_path: Path | str | None = None,
) -> pd.DataFrame:
    """Per-offset daily return + cumulative return (relative to the T0 close) around an event date."""
    if prices is None:
        prices = load_close_prices(ticker, db_path=db_path)
    if prices.empty or event_date not in prices.index:
        return pd.DataFrame()

    dates = list(prices.index)
    returns = prices.pct_change()
    t0_idx = dates.index(event_date)
    t0_price = prices.iloc[t0_idx]

    records: list[dict[str, Any]] = []
    for offset in offsets:
        pos = t0_idx + offset
        if pos < 0 or pos >= len(dates):
            continue
        records.append(
            {
                "ticker": ticker,
                "event_date": event_date,
                "day_offset": offset,
                "date": dates[pos],
                "daily_return": float(returns.iloc[pos]) if pd.notna(returns.iloc[pos]) else None,
                "cumulative_return": float(prices.iloc[pos] / t0_price - 1.0),
            }
        )
    return pd.DataFrame.from_records(records)


def compute_event_window_summary(
    ticker: str,
    event_date: Any,
    prices: pd.Series | None = None,
    windows: tuple[tuple[int, int], ...] = DEFAULT_WINDOWS,
    db_path: Path | str | None = None,
) -> pd.DataFrame:
    """Aggregate cumulative return over configurable [start, end] windows, e.g. [-5, +5]."""
    if prices is None:
        prices = load_close_prices(ticker, db_path=db_path)
    if prices.empty or event_date not in prices.index:
        return pd.DataFrame()

    dates = list(prices.index)
    t0_idx = dates.index(event_date)

    records: list[dict[str, Any]] = []
    for start_offset, end_offset in windows:
        start_pos, end_pos = t0_idx + start_offset, t0_idx + end_offset
        if start_pos < 0 or end_pos >= len(dates):
            continue
        records.append(
            {
                "ticker": ticker,
                "event_date": event_date,
                "window_start_offset": start_offset,
                "window_end_offset": end_offset,
                "window_return": float(prices.iloc[end_pos] / prices.iloc[start_pos] - 1.0),
            }
        )
    return pd.DataFrame.from_records(records)


def persist_event_returns(event_id: str, event_returns: pd.DataFrame, db_path: Path | str | None = None) -> int:
    """Upsert per-offset event-reaction rows into `event_returns`."""
    from storage.duckdb import get_connection

    if event_returns.empty:
        return 0

    rows = event_returns.copy()
    rows.insert(0, "event_id", event_id)

    conn = get_connection(db_path)
    try:
        conn.register("er_rows", rows)
        conn.execute(
            """
            INSERT INTO event_returns
                (event_id, ticker, event_date, day_offset, date, daily_return, cumulative_return)
            SELECT event_id, ticker, event_date, day_offset, date, daily_return, cumulative_return
            FROM er_rows
            ON CONFLICT (event_id, ticker, day_offset) DO UPDATE SET
                date = excluded.date,
                daily_return = excluded.daily_return,
                cumulative_return = excluded.cumulative_return
            """
        )
        conn.unregister("er_rows")
        return len(rows)
    finally:
        conn.close()


def run_event_study(
    event_id: str,
    reference_ticker: str = "STLA",
    offsets: tuple[int, ...] = DEFAULT_OFFSETS,
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    """Full Phase 6 pipeline: react every company in the universe to one reference-ticker event."""
    from analytics.abnormal_returns import compute_abnormal_returns, load_beta_alpha, persist_abnormal_returns
    from storage.duckdb import get_connection
    from storage.load_companies import load_companies_config

    conn = get_connection(db_path)
    try:
        event_row = conn.execute(
            "SELECT event_date FROM market_events WHERE event_id = ?", [event_id]
        ).fetchone()
    finally:
        conn.close()
    if event_row is None:
        raise ValueError(f"Unknown event_id {event_id!r}; run Phase 4 detection first")
    event_date = event_row[0]

    reference_returns = load_close_prices(reference_ticker, db_path=db_path).pct_change()

    processed: list[str] = []
    skipped: list[str] = []
    for company in load_companies_config():
        ticker = company.ticker
        event_returns = compute_event_window_returns(ticker, event_date, offsets=offsets, db_path=db_path)
        if event_returns.empty:
            skipped.append(ticker)
            continue
        persist_event_returns(event_id, event_returns, db_path=db_path)

        beta_alpha = load_beta_alpha(ticker, reference_ticker=reference_ticker, db_path=db_path)
        if beta_alpha is not None:
            beta, alpha = beta_alpha
            abnormal = compute_abnormal_returns(
                event_id,
                ticker,
                event_returns[["day_offset", "date", "daily_return"]],
                reference_returns,
                beta,
                alpha,
            )
            persist_abnormal_returns(abnormal, db_path=db_path)

        processed.append(ticker)

    return {
        "event_id": event_id,
        "event_date": str(event_date),
        "processed": processed,
        "skipped": skipped,
    }
