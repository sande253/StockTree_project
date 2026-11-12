"""Business + Stock Relationship (Phase 13).

Combines the Phase 12 business-relationship profile (documented, evidence-backed)
with the Phase 5/6 market relationship (statistical correlation + historical event
sensitivity + the most recent event's abnormal return) into one analytical profile
per company connected to Stellantis in the graph.

A graph entity only has a market profile if it is itself separately publicly traded
(`target_entity_ticker` set on its relationship AND ingested into `price_data`/
`correlations`/`abnormal_returns`). Many entities (e.g. Stellantis's own brands) are
not separately traded, so their market fields are explicitly "Not applicable" -
never fabricated. This module never claims correlation implies causation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import networkx as nx

from relationships.business_profile import build_company_profile

DATA_UNAVAILABLE = "Data unavailable"
NOT_APPLICABLE = "Not applicable: no tracked ticker"

# Reuses Phase 4's severity thresholds as a transparent, consistent definition of what
# counts as a "significant" historical reaction for ANY ticker (not just STLA itself).
SENSITIVITY_THRESHOLDS = {"high": 0.07, "medium": 0.04, "low": 0.02}


def _sensitivity_label(significant_ratio: float | None) -> str:
    if significant_ratio is None:
        return "Insufficient data"
    if significant_ratio >= 0.5:
        return "High"
    if significant_ratio >= 0.25:
        return "Medium"
    if significant_ratio > 0:
        return "Low"
    return "None observed"


def load_statistical_correlation(
    ticker: str, reference_ticker: str = "STLA", db_path: Path | str | None = None
) -> dict[str, Any] | None:
    """Phase 5 full-sample correlation, or None if it has not been computed for this ticker."""
    from storage.duckdb import get_connection

    conn = get_connection(db_path)
    try:
        # First check if correlations table exists
        table_exists = conn.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'correlations'"
        ).fetchone()[0]
        
        if not table_exists:
            return None
        
        # Cast both parameters as strings to avoid type conversion issues
        row = conn.execute(
            """
            SELECT pearson_correlation, pearson_p_value, sample_size
            FROM correlations
            WHERE CAST(ticker AS VARCHAR) = ? AND CAST(reference_ticker AS VARCHAR) = ?
            """,
            [str(ticker), str(reference_ticker)],
        ).fetchone()
    except Exception:
        return None
    finally:
        conn.close()
    
    if row is None or row[0] is None:
        return None
    return {"pearson_correlation": float(row[0]), "pearson_p_value": row[1], "sample_size": row[2]}


def load_historical_event_sensitivity(ticker: str, db_path: Path | str | None = None) -> dict[str, Any] | None:
    """How often `ticker` showed a significant abnormal return (day_offset=0) on a past STLA event."""
    from storage.duckdb import get_connection

    conn = get_connection(db_path)
    try:
        # Check if table exists first
        table_exists = conn.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'abnormal_returns'"
        ).fetchone()[0]
        
        if not table_exists:
            return None
        
        rows = conn.execute(
            "SELECT abnormal_return FROM abnormal_returns WHERE CAST(ticker AS VARCHAR) = ? AND day_offset = 0",
            [str(ticker)],
        ).fetchall()
    except Exception:
        return None
    finally:
        conn.close()
        
    if not rows:
        return None

    magnitudes = [abs(r[0]) for r in rows if r[0] is not None]
    if not magnitudes:
        return None
    significant = sum(1 for m in magnitudes if m >= SENSITIVITY_THRESHOLDS["medium"])
    ratio = significant / len(magnitudes)
    return {
        "sample_size": len(magnitudes),
        "significant_reaction_count": significant,
        "sensitivity_label": _sensitivity_label(ratio),
    }


def load_current_event_reaction(
    ticker: str, event_id: str | None = None, db_path: Path | str | None = None
) -> dict[str, Any] | None:
    """`ticker`'s abnormal return (day_offset=0) for one event, or the most recent event if `event_id` is None."""
    from storage.duckdb import get_connection

    conn = get_connection(db_path)
    try:
        # Check if tables exist first
        abnormal_table_exists = conn.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'abnormal_returns'"
        ).fetchone()[0]
        
        events_table_exists = conn.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'market_events'"
        ).fetchone()[0]
        
        if not abnormal_table_exists:
            return None
        
        if event_id is not None:
            row = conn.execute(
                "SELECT event_id, abnormal_return FROM abnormal_returns WHERE CAST(ticker AS VARCHAR) = ? AND event_id = ? AND day_offset = 0",
                [str(ticker), event_id],
            ).fetchone()
        elif events_table_exists:
            row = conn.execute(
                """
                SELECT ab.event_id, ab.abnormal_return
                FROM abnormal_returns ab
                JOIN market_events m ON m.event_id = ab.event_id
                WHERE CAST(ab.ticker AS VARCHAR) = ? AND ab.day_offset = 0
                ORDER BY m.event_date DESC
                LIMIT 1
                """,
                [str(ticker)],
            ).fetchone()
        else:
            return None
    except Exception:
        return None
    finally:
        conn.close()
        
    if row is None or row[1] is None:
        return None
    return {"event_id": row[0], "abnormal_return": float(row[1])}


def build_combined_profile(
    graph: nx.DiGraph, entity_id: str, event_id: str | None = None, db_path: Path | str | None = None
) -> dict[str, Any] | None:
    """Full Phase 13 profile for one entity: business relationship + market relationship."""
    business = build_company_profile(graph, entity_id)
    if business is None:
        return None

    ticker = graph.edges["STLA", entity_id].get("target_entity_ticker")
    if not ticker:
        return {
            **business,
            "ticker": None,
            "historical_correlation": NOT_APPLICABLE,
            "historical_event_sensitivity": NOT_APPLICABLE,
            "current_event_reaction": NOT_APPLICABLE,
            "documented_relationship": True,
        }

    correlation = load_statistical_correlation(ticker, db_path=db_path)
    sensitivity = load_historical_event_sensitivity(ticker, db_path=db_path)
    reaction = load_current_event_reaction(ticker, event_id=event_id, db_path=db_path)

    return {
        **business,
        "ticker": ticker,
        "historical_correlation": correlation["pearson_correlation"] if correlation else DATA_UNAVAILABLE,
        "historical_correlation_sample_size": correlation["sample_size"] if correlation else None,
        "historical_event_sensitivity": sensitivity["sensitivity_label"] if sensitivity else DATA_UNAVAILABLE,
        "current_event_reaction": reaction["abnormal_return"] if reaction else DATA_UNAVAILABLE,
        "current_event_id": reaction["event_id"] if reaction else None,
        "documented_relationship": True,
    }


def build_all_combined_profiles(
    graph: nx.DiGraph, source_entity: str = "STLA", event_id: str | None = None, db_path: Path | str | None = None
) -> list[dict[str, Any]]:
    """Combined Phase 13 profiles for every entity directly connected to `source_entity`."""
    from relationships.queries import neighbors

    return [
        build_combined_profile(graph, n["entity_id"], event_id=event_id, db_path=db_path)
        for n in neighbors(graph, source_entity)
    ]
