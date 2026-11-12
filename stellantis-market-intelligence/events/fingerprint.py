"""Event Fingerprinting (Phase 17).

Builds one comparable "fingerprint" per detected STLA event: its classification
(Phase 9), market context (Phase 7), aggregate reaction of supplier/competitor/
commodity peer groups (Phase 6 abnormal returns, grouped by the coarse Phase 1
company-universe category - NOT a claim of a documented business relationship),
and a simple, transparent recovery-time estimate. Persisted to `historical_events`,
which Phase 18 will later embed for similarity search.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# A peer-group reaction is only reported if backed by at least this many companies.
MIN_PEER_GROUP_SIZE = 1
# "Recovered" = the move has retraced to <= (1 - RECOVERY_FRACTION) of its original magnitude.
RECOVERY_FRACTION = 0.5

# Phase 1 company-universe `relationship_type` categories used for each peer group.
# These are coarse market/sector groupings only - never a documented business relationship.
PEER_GROUP_CATEGORIES = {
    "supplier_reaction": ("supplier_tier1", "supplier_tier2"),
    "competitor_reaction": ("oem",),
    "commodity_reaction": ("commodity",),
}


def load_event_context(event_id: str, db_path: Path | str | None = None) -> dict[str, Any] | None:
    """Load the Phase 4/7/9 fields needed to seed a fingerprint for one event."""
    from storage.duckdb import get_connection

    conn = get_connection(db_path)
    try:
        row = conn.execute(
            """
            SELECT ticker, event_type, event_description, "return" AS stla_return,
                   sector_return, market_return
            FROM market_events
            WHERE event_id = ?
            """,
            [event_id],
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return {
        "ticker": row[0],
        "event_type": row[1],
        "event_description": row[2],
        "stla_return": row[3],
        "sector_return": row[4],
        "market_return": row[5],
    }


def compute_peer_group_reaction(
    event_id: str, relationship_types: tuple[str, ...], db_path: Path | str | None = None
) -> float | None:
    """Mean abnormal return (day_offset=0) across companies in `relationship_types` for one event."""
    from storage.duckdb import get_connection

    placeholders = ",".join("?" for _ in relationship_types)
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            f"""
            SELECT AVG(ab.abnormal_return), COUNT(*)
            FROM abnormal_returns ab
            JOIN companies c ON c.ticker = ab.ticker
            WHERE ab.event_id = ? AND ab.day_offset = 0 AND c.relationship_type IN ({placeholders})
            """,
            [event_id, *relationship_types],
        ).fetchone()
    finally:
        conn.close()
    if row is None or row[0] is None or row[1] < MIN_PEER_GROUP_SIZE:
        return None
    return float(row[0])


def compute_recovery_time(
    ticker: str, event_id: str, recovery_fraction: float = RECOVERY_FRACTION, db_path: Path | str | None = None
) -> int | None:
    """Trading days after the event until `ticker`'s cumulative move retraces by `recovery_fraction`.

    Baseline magnitude = the event day's own daily_return (day_offset=0). None if the
    event never retraces that much within the stored event window, or data is missing.
    """
    from storage.duckdb import get_connection

    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT day_offset, cumulative_return
            FROM event_returns
            WHERE event_id = ? AND ticker = ?
            ORDER BY day_offset
            """,
            [event_id, ticker],
        ).fetchall()
        baseline_row = conn.execute(
            "SELECT daily_return FROM event_returns WHERE event_id = ? AND ticker = ? AND day_offset = 0",
            [event_id, ticker],
        ).fetchone()
    finally:
        conn.close()

    if not rows or baseline_row is None or baseline_row[0] is None:
        return None
    baseline = abs(baseline_row[0])
    if baseline == 0:
        return None

    recovery_level = baseline * (1.0 - recovery_fraction)
    for day_offset, cumulative_return in rows:
        if day_offset > 0 and cumulative_return is not None and abs(cumulative_return) <= recovery_level:
            return int(day_offset)
    return None


def build_event_fingerprint(event_id: str, db_path: Path | str | None = None) -> dict[str, Any] | None:
    """Full Phase 17 fingerprint for one event, or None if the event itself is unknown."""
    context = load_event_context(event_id, db_path=db_path)
    if context is None:
        return None

    reactions = {
        field: compute_peer_group_reaction(event_id, types, db_path=db_path)
        for field, types in PEER_GROUP_CATEGORIES.items()
    }
    recovery_time_days = compute_recovery_time(context["ticker"], event_id, db_path=db_path)

    return {"event_id": event_id, **context, **reactions, "recovery_time_days": recovery_time_days}


def persist_fingerprint(fingerprint: dict[str, Any], db_path: Path | str | None = None) -> None:
    """Upsert one fingerprint into `historical_events`."""
    from storage.duckdb import get_connection

    conn = get_connection(db_path)
    try:
        conn.execute(
            """
            INSERT INTO historical_events
                (event_id, ticker, event_type, event_description, stla_return, sector_return,
                 market_return, supplier_reaction, competitor_reaction, commodity_reaction, recovery_time_days)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (event_id) DO UPDATE SET
                event_type = excluded.event_type,
                event_description = excluded.event_description,
                stla_return = excluded.stla_return,
                sector_return = excluded.sector_return,
                market_return = excluded.market_return,
                supplier_reaction = excluded.supplier_reaction,
                competitor_reaction = excluded.competitor_reaction,
                commodity_reaction = excluded.commodity_reaction,
                recovery_time_days = excluded.recovery_time_days
            """,
            [
                fingerprint["event_id"],
                fingerprint["ticker"],
                fingerprint["event_type"],
                fingerprint["event_description"],
                fingerprint["stla_return"],
                fingerprint["sector_return"],
                fingerprint["market_return"],
                fingerprint["supplier_reaction"],
                fingerprint["competitor_reaction"],
                fingerprint["commodity_reaction"],
                fingerprint["recovery_time_days"],
            ],
        )
    finally:
        conn.close()


def build_and_store_fingerprints(ticker: str = "STLA", db_path: Path | str | None = None) -> int:
    """Full Phase 17 pipeline: every market_events row for `ticker` -> fingerprint -> persist."""
    from storage.duckdb import get_connection

    conn = get_connection(db_path)
    try:
        event_ids = [r[0] for r in conn.execute(
            "SELECT event_id FROM market_events WHERE ticker = ?", [ticker]
        ).fetchall()]
    finally:
        conn.close()

    count = 0
    for event_id in event_ids:
        fingerprint = build_event_fingerprint(event_id, db_path=db_path)
        if fingerprint is not None:
            persist_fingerprint(fingerprint, db_path=db_path)
            count += 1
    return count
