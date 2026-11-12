"""Regime Detection (Phase 16).

Relationships between STLA and another company can change over time. This groups
the Phase 5 rolling-correlation time series into calendar-year periods and reports
whether the relationship strengthened, weakened, disappeared, or changed direction
between consecutive periods. All thresholds are simple and documented below -
no hidden tuning. Requires at least two periods with data; with less, it correctly
reports that there is not enough history to detect a regime change (never fabricates
a trend from a single data point).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

# A change in mean rolling correlation of at least this much between consecutive
# periods counts as "strengthened"/"weakened". Below this, the relationship is "stable".
REGIME_CHANGE_THRESHOLD = 0.15
# A mean rolling correlation with |value| below this is treated as "no relationship".
NEGLIGIBLE_CORRELATION = 0.10


def load_rolling_correlation_series(
    ticker: str, reference_ticker: str = "STLA", db_path: Path | str | None = None
) -> pd.DataFrame:
    """Load the stored Phase 5 rolling-correlation time series for one ticker pair."""
    from storage.duckdb import get_connection, normalize_date_column

    conn = get_connection(db_path)
    try:
        df = conn.execute(
            """
            SELECT date, rolling_correlation
            FROM rolling_correlations
            WHERE ticker = ? AND reference_ticker = ?
            ORDER BY date
            """,
            [ticker, reference_ticker],
        ).fetchdf()
    finally:
        conn.close()
    return normalize_date_column(df)


def summarize_by_year(rolling_series: pd.DataFrame) -> pd.DataFrame:
    """Mean rolling correlation per calendar year, dropping years with no valid data."""
    if rolling_series.empty:
        return pd.DataFrame(columns=["year", "mean_correlation", "sample_size"])

    df = rolling_series.dropna(subset=["rolling_correlation"]).copy()
    if df.empty:
        return pd.DataFrame(columns=["year", "mean_correlation", "sample_size"])

    df["year"] = df["date"].apply(lambda d: d.year)
    grouped = df.groupby("year")["rolling_correlation"].agg(["mean", "count"]).reset_index()
    grouped.columns = ["year", "mean_correlation", "sample_size"]
    return grouped


def _classify_change(prior: float, current: float) -> str:
    prior_negligible = abs(prior) < NEGLIGIBLE_CORRELATION
    current_negligible = abs(current) < NEGLIGIBLE_CORRELATION

    if not prior_negligible and not current_negligible and (prior > 0) != (current > 0):
        return "direction change"
    if not prior_negligible and current_negligible:
        return "disappeared"
    if current - prior >= REGIME_CHANGE_THRESHOLD:
        return "strengthened"
    if prior - current >= REGIME_CHANGE_THRESHOLD:
        return "weakened"
    return "stable"


def detect_regime_changes(
    ticker: str, reference_ticker: str = "STLA", db_path: Path | str | None = None
) -> dict[str, Any]:
    """Full Phase 16 pipeline: yearly correlation summary + period-over-period regime labels."""
    rolling_series = load_rolling_correlation_series(ticker, reference_ticker, db_path=db_path)
    yearly = summarize_by_year(rolling_series)

    yearly_records = yearly.to_dict("records")
    changes: list[dict[str, Any]] = []
    if len(yearly_records) < 2:
        return {
            "ticker": ticker,
            "reference_ticker": reference_ticker,
            "yearly": yearly_records,
            "changes": changes,
            "note": "Not enough historical periods to detect a regime change (need at least 2 years of data).",
        }

    for prior, current in zip(yearly_records, yearly_records[1:]):
        change = _classify_change(prior["mean_correlation"], current["mean_correlation"])
        changes.append(
            {
                "from_year": prior["year"],
                "to_year": current["year"],
                "from_correlation": prior["mean_correlation"],
                "to_correlation": current["mean_correlation"],
                "change": change,
            }
        )

    return {
        "ticker": ticker,
        "reference_ticker": reference_ticker,
        "yearly": yearly_records,
        "changes": changes,
    }
