"""Market vs Sector vs STLA analysis (Phase 7).

Classifies a STLA movement as STLA-specific / sector-wide / market-wide / mixed by
comparing STLA's return on a date against configured market and sector benchmarks
(config/benchmarks.yaml). This is a descriptive comparison of magnitudes only -
it never makes or implies a causal claim.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import yaml

DEFAULT_CONFIG_PATH = Path("config/benchmarks.yaml")
DEFAULT_DOMINANCE_RATIO = 2.0


def load_benchmarks(config_path: Path | str = DEFAULT_CONFIG_PATH) -> dict[str, dict[str, str]]:
    """Load configured benchmarks keyed by their `key` (e.g. "market", "sector")."""
    path = Path(config_path)
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    return {b["key"]: b for b in raw.get("benchmarks", []) if b}


def get_return_on_date(ticker: str, event_date: Any, db_path: Path | str | None = None) -> float | None:
    """Fetch the stored Phase 3 daily return for a ticker on a specific date, if available."""
    from storage.duckdb import get_connection

    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT daily_return FROM price_features WHERE ticker = ? AND date = ?",
            [ticker, event_date],
        ).fetchone()
    finally:
        conn.close()
    return float(row[0]) if row and row[0] is not None else None


def classify_movement(
    stla_return: float,
    market_return: float | None,
    sector_return: float | None,
    dominance_ratio: float = DEFAULT_DOMINANCE_RATIO,
) -> str:
    """Classify a STLA movement as stla_specific / sector_wide / market_wide / mixed.

    A benchmark "explains" the move if it moved in the same direction and STLA's move
    is not disproportionately larger (within `dominance_ratio`x).
    """
    if market_return is None or sector_return is None:
        return "insufficient_data"

    abs_stla = abs(stla_return)
    market_explains = (
        (stla_return * market_return) >= 0 and abs(market_return) > 0 and abs_stla <= dominance_ratio * abs(market_return)
    )
    sector_explains = (
        (stla_return * sector_return) >= 0 and abs(sector_return) > 0 and abs_stla <= dominance_ratio * abs(sector_return)
    )

    if market_explains and sector_explains:
        return "market_wide"
    if sector_explains and not market_explains:
        return "sector_wide"
    if not market_explains and not sector_explains:
        return "stla_specific"
    return "mixed"


def analyze_event_context(
    event_date: Any, stla_ticker: str = "STLA", db_path: Path | str | None = None
) -> dict[str, Any]:
    """Compute market/sector-adjusted returns and a movement classification for one date."""
    benchmarks = load_benchmarks()
    stla_return = get_return_on_date(stla_ticker, event_date, db_path=db_path)
    if stla_return is None:
        raise ValueError(
            f"No {stla_ticker} return found for {event_date}; run Phase 2/3 ingestion for that date first"
        )

    market_cfg = benchmarks.get("market")
    sector_cfg = benchmarks.get("sector")
    market_return = get_return_on_date(market_cfg["ticker"], event_date, db_path=db_path) if market_cfg else None
    sector_return = get_return_on_date(sector_cfg["ticker"], event_date, db_path=db_path) if sector_cfg else None

    return {
        "ticker": stla_ticker,
        "event_date": event_date,
        "stla_return": stla_return,
        "market_return": market_return,
        "sector_return": sector_return,
        "market_adjusted_return": (stla_return - market_return) if market_return is not None else None,
        "sector_adjusted_return": (stla_return - sector_return) if sector_return is not None else None,
        "classification": classify_movement(stla_return, market_return, sector_return),
    }


def persist_event_context(event_id: str, context: dict[str, Any], db_path: Path | str | None = None) -> None:
    """Attach the computed market/sector context to an existing `market_events` row."""
    from storage.duckdb import get_connection

    conn = get_connection(db_path)
    try:
        conn.execute(
            """
            UPDATE market_events SET
                market_return = ?,
                sector_return = ?,
                market_adjusted_return = ?,
                sector_adjusted_return = ?,
                classification = ?
            WHERE event_id = ?
            """,
            [
                context["market_return"],
                context["sector_return"],
                context["market_adjusted_return"],
                context["sector_adjusted_return"],
                context["classification"],
                event_id,
            ],
        )
    finally:
        conn.close()


def analyze_and_store_event_context(
    event_id: str, stla_ticker: str = "STLA", db_path: Path | str | None = None
) -> dict[str, Any]:
    """Full Phase 7 pipeline for one event: load event_date -> analyze -> persist."""
    from storage.duckdb import get_connection

    conn = get_connection(db_path)
    try:
        row = conn.execute("SELECT event_date FROM market_events WHERE event_id = ?", [event_id]).fetchone()
    finally:
        conn.close()
    if row is None:
        raise ValueError(f"Unknown event_id {event_id!r}; run Phase 4 detection first")

    context = analyze_event_context(row[0], stla_ticker=stla_ticker, db_path=db_path)
    persist_event_context(event_id, context, db_path=db_path)
    return context


def load_events_missing_context(ticker: str, db_path: Path | str | None = None) -> pd.DataFrame:
    """`market_events` rows for `ticker` that have not yet had Phase 7 context computed."""
    from storage.duckdb import get_connection, normalize_date_column

    conn = get_connection(db_path)
    try:
        df = conn.execute(
            """
            SELECT event_id, event_date
            FROM market_events
            WHERE ticker = ? AND market_return IS NULL
            ORDER BY event_date
            """,
            [ticker],
        ).fetchdf()
    finally:
        conn.close()
    return normalize_date_column(df, column="event_date")


def analyze_and_store_missing_contexts(
    ticker: str = "STLA", db_path: Path | str | None = None
) -> int:
    """Batch Phase 7 pipeline: compute+persist market/sector context for every un-analyzed event."""
    pending = load_events_missing_context(ticker, db_path=db_path)
    for row in pending.itertuples(index=False):
        analyze_and_store_event_context(row.event_id, stla_ticker=ticker, db_path=db_path)
    return len(pending)
