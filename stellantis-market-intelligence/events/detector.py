"""Significant price-movement event detection (Phase 4).

Combines four independent signals - absolute return, return z-score,
volatility-adjusted return, and abnormal volume - into a per-day detection
record for any ticker. This module does NOT attempt to explain *why* an event
happened; that is Phase 8-10 (news ingestion / classification / correlation).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import yaml

DEFAULT_CONFIG_PATH = Path("config/event_rules.yaml")

DEFAULT_THRESHOLDS: dict[str, Any] = {
    "absolute_return": 0.05,
    "zscore": 2.0,
    "volatility_adjusted": 2.0,
    "volume_zscore": 2.0,
    "severity": {"high": 0.07, "medium": 0.04, "low": 0.02},
}


def load_event_rules(config_path: Path | str = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """Load event-detection thresholds from YAML, falling back to defaults for missing keys."""
    path = Path(config_path)
    thresholds = {**DEFAULT_THRESHOLDS, "severity": dict(DEFAULT_THRESHOLDS["severity"])}
    if path.exists():
        with path.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        configured = raw.get("thresholds") or {}
        for key, value in configured.items():
            if key == "severity" and value:
                thresholds["severity"].update(value)
            elif value is not None:
                thresholds[key] = value
    return thresholds


def _severity(abs_return: float, severity_levels: dict[str, float]) -> str:
    if abs_return >= severity_levels["high"]:
        return "high"
    if abs_return >= severity_levels["medium"]:
        return "medium"
    if abs_return >= severity_levels["low"]:
        return "low"
    return "none"


def detect_events(
    features: pd.DataFrame, ticker: str, thresholds: dict[str, Any] | None = None
) -> pd.DataFrame:
    """Evaluate Phase 4 detection rules over a ticker's computed price features.

    `features` must contain: date, daily_return, zscore, rolling_volatility, volume_zscore.
    Returns one row per date that triggered at least one detection method.
    """
    thresholds = thresholds or load_event_rules()
    severity_levels = thresholds["severity"]

    records: list[dict[str, Any]] = []
    for row in features.itertuples(index=False):
        ret = row.daily_return
        if pd.isna(ret):
            continue
        zscore = row.zscore
        rolling_volatility = row.rolling_volatility
        volume_zscore = row.volume_zscore

        triggered: list[str] = []
        if abs(ret) >= thresholds["absolute_return"]:
            triggered.append("absolute_return")
        if pd.notna(zscore) and abs(zscore) >= thresholds["zscore"]:
            triggered.append("zscore")
        if pd.notna(rolling_volatility) and rolling_volatility > 0:
            if abs(ret) / rolling_volatility >= thresholds["volatility_adjusted"]:
                triggered.append("volatility_adjusted")
        if pd.notna(volume_zscore) and abs(volume_zscore) >= thresholds["volume_zscore"]:
            triggered.append("abnormal_volume")

        if not triggered:
            continue

        records.append(
            {
                "event_id": f"{ticker}-{row.date}",
                "event_date": row.date,
                "ticker": ticker,
                "return": float(ret),
                "z_score": float(zscore) if pd.notna(zscore) else None,
                "volume_z_score": float(volume_zscore) if pd.notna(volume_zscore) else None,
                "volatility": float(rolling_volatility) if pd.notna(rolling_volatility) else None,
                "severity": _severity(abs(ret), severity_levels),
                "direction": "positive" if ret > 0 else "negative",
                "detection_method": ",".join(triggered),
                "combined_score": len(triggered) / 4.0,
            }
        )

    return pd.DataFrame.from_records(records)


def load_price_features(ticker: str, db_path: Path | str | None = None) -> pd.DataFrame:
    """Load stored Phase 3 features for a ticker, sorted by date."""
    from storage.duckdb import get_connection, normalize_date_column

    conn = get_connection(db_path)
    try:
        df = conn.execute(
            """
            SELECT date, daily_return, zscore, rolling_volatility, volume_zscore
            FROM price_features
            WHERE ticker = ?
            ORDER BY date
            """,
            [ticker],
        ).fetchdf()
    finally:
        conn.close()
    return normalize_date_column(df)


def persist_events(events: pd.DataFrame, db_path: Path | str | None = None) -> int:
    """Upsert detected events into the DuckDB `market_events` table."""
    from storage.duckdb import get_connection

    if events.empty:
        return 0

    conn = get_connection(db_path)
    try:
        conn.register("events_rows", events)
        conn.execute(
            """
            INSERT INTO market_events
                (event_id, event_date, ticker, "return", z_score, volume_z_score,
                 volatility, severity, direction, detection_method, combined_score)
            SELECT event_id, event_date, ticker, "return", z_score, volume_z_score,
                   volatility, severity, direction, detection_method, combined_score
            FROM events_rows
            ON CONFLICT (event_id) DO UPDATE SET
                "return" = excluded."return",
                z_score = excluded.z_score,
                volume_z_score = excluded.volume_z_score,
                volatility = excluded.volatility,
                severity = excluded.severity,
                direction = excluded.direction,
                detection_method = excluded.detection_method,
                combined_score = excluded.combined_score
            """
        )
        conn.unregister("events_rows")
        return len(events)
    finally:
        conn.close()


def detect_and_store_events(
    ticker: str, thresholds: dict[str, Any] | None = None, db_path: Path | str | None = None
) -> int:
    """Full Phase 4 pipeline for one ticker: load features -> detect -> persist -> auto-enrich.

    Per the master prompt, an anomaly must automatically kick off its investigation context
    (market/sector comparison, classification, news correlation) rather than sit unexplained.
    """
    features = load_price_features(ticker, db_path=db_path)
    if features.empty:
        raise ValueError(f"No price_features found for ticker {ticker!r}; run Phase 3 first")
    events = detect_events(features, ticker, thresholds=thresholds)
    count = persist_events(events, db_path=db_path)
    if count:
        enrich_events(ticker, db_path=db_path)
    return count


def enrich_events(ticker: str, db_path: Path | str | None = None) -> None:
    """Run Phase 7 (market/sector context) + Phase 9 (classification) + Phase 10 (news
    correlation) for every event still missing them. Safe to call repeatedly/idempotently."""
    from analytics.benchmark import analyze_and_store_missing_contexts
    from events.classifier import classify_and_store_events
    from events.news_correlation import correlate_event_news_and_store

    analyze_and_store_missing_contexts(ticker, db_path=db_path)
    classify_and_store_events(ticker, db_path=db_path)
    correlate_event_news_and_store(ticker, db_path=db_path)
