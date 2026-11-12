"""Read-only repository helpers over the DuckDB warehouse (Phase 24 repository layer).

Thin, reusable query functions returning plain dicts/lists (JSON-ready), used by the
api/services/* layer. Keeps routes free of SQL/business logic.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    """DataFrame -> list of plain dicts with NaN/NaT normalized to None (JSON-safe)."""
    return [{k: (None if pd.isna(v) else v) for k, v in row.items()} for row in df.to_dict("records")]


def list_companies(db_path: Path | str | None = None) -> list[dict[str, Any]]:
    from storage.duckdb import get_connection

    conn = get_connection(db_path)
    try:
        df = conn.execute("SELECT * FROM companies ORDER BY ticker").fetchdf()
    finally:
        conn.close()
    return _records(df)


def get_company(ticker: str, db_path: Path | str | None = None) -> dict[str, Any] | None:
    from storage.duckdb import get_connection

    conn = get_connection(db_path)
    try:
        df = conn.execute("SELECT * FROM companies WHERE ticker = ?", [ticker]).fetchdf()
    finally:
        conn.close()
    records = _records(df)
    return records[0] if records else None


def list_price_data(
    ticker: str, start: str | None = None, end: str | None = None, db_path: Path | str | None = None
) -> list[dict[str, Any]]:
    from storage.duckdb import get_connection

    conditions = ["ticker = ?"]
    params: list[Any] = [ticker]
    if start:
        conditions.append("date >= ?")
        params.append(start)
    if end:
        conditions.append("date <= ?")
        params.append(end)

    conn = get_connection(db_path)
    try:
        df = conn.execute(
            f"SELECT * FROM price_data WHERE {' AND '.join(conditions)} ORDER BY date", params
        ).fetchdf()
    finally:
        conn.close()
    return _records(df)


def list_events(ticker: str = "STLA", db_path: Path | str | None = None) -> list[dict[str, Any]]:
    from storage.duckdb import get_connection

    conn = get_connection(db_path)
    try:
        df = conn.execute(
            'SELECT * FROM market_events WHERE ticker = ? ORDER BY event_date DESC', [ticker]
        ).fetchdf()
    finally:
        conn.close()
    return _records(df)


def get_event(event_id: str, db_path: Path | str | None = None) -> dict[str, Any] | None:
    from storage.duckdb import get_connection

    conn = get_connection(db_path)
    try:
        df = conn.execute("SELECT * FROM market_events WHERE event_id = ?", [event_id]).fetchdf()
    finally:
        conn.close()
    records = _records(df)
    return records[0] if records else None


def list_relationships(db_path: Path | str | None = None) -> list[dict[str, Any]]:
    from relationships.graph import load_relationships

    return _records(load_relationships(db_path=db_path))


def get_relationships_for_company(company: str, db_path: Path | str | None = None) -> list[dict[str, Any]]:
    from storage.duckdb import get_connection

    conn = get_connection(db_path)
    try:
        df = conn.execute(
                        """
                        SELECT * FROM relationships
                        WHERE (target_entity = ? OR source_entity = ?)
                            AND lower(source) <> lower(?)
                        """,
                        [company, company, "Yahoo Finance Market Data Analysis"],
        ).fetchdf()
    finally:
        conn.close()
    return _records(df)


def list_historical_events(db_path: Path | str | None = None) -> list[dict[str, Any]]:
    from events.similarity import load_historical_events

    return _records(load_historical_events(db_path=db_path))
