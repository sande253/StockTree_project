"""DuckDB connection helper.

Centralizes how the rest of the codebase opens the local DuckDB warehouse so that
the database path and schema initialization stay consistent across modules.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

import duckdb
import pandas as pd

from storage.schemas import (
    CREATE_ABNORMAL_RETURNS_TABLE,
    CREATE_COMPANIES_TABLE,
    CREATE_CORRELATIONS_TABLE,
    CREATE_DOCUMENT_CHUNKS_TABLE,
    CREATE_DOCUMENTS_TABLE,
    CREATE_EVENT_NEWS_TABLE,
    CREATE_EVENT_RETURNS_TABLE,
    CREATE_HISTORICAL_EVENTS_TABLE,
    CREATE_MARKET_EVENTS_TABLE,
    CREATE_NEWS_TABLE,
    CREATE_PRICE_DATA_TABLE,
    CREATE_PRICE_FEATURES_TABLE,
    CREATE_RELATIONSHIP_EVIDENCE_TABLE,
    CREATE_RELATIONSHIPS_TABLE,
    CREATE_ROLLING_CORRELATIONS_TABLE,
)

DEFAULT_DUCKDB_PATH = Path("data/warehouse/market.duckdb")
_SCHEMA_LOCK = threading.RLock()


def get_duckdb_path() -> Path:
    """Resolve the DuckDB file path from the DUCKDB_PATH env var, with a safe default."""
    raw_path = os.environ.get("DUCKDB_PATH", str(DEFAULT_DUCKDB_PATH))
    return Path(raw_path)


def normalize_date_column(df: pd.DataFrame, column: str = "date") -> pd.DataFrame:
    """Convert a DataFrame's DATE column from pandas Timestamps to python `date` objects.

    `conn.execute(...).fetchdf()` returns DuckDB DATE columns as datetime64 Timestamps,
    while `conn.execute(...).fetchone()` returns native `datetime.date`. Mixing the two
    breaks index/equality lookups (e.g. "is this event_date in this price series?"), so
    every loader that reads a DATE column via fetchdf() must normalize through this helper.
    """
    if column in df.columns:
        df[column] = pd.to_datetime(df[column]).dt.date
    return df


def get_connection(db_path: Path | str | None = None) -> duckdb.DuckDBPyConnection:
    """Open (creating if necessary) the DuckDB warehouse and ensure core tables exist."""
    path = Path(db_path) if db_path is not None else get_duckdb_path()
    with _SCHEMA_LOCK:
        return _initialize_connection(path)


def _initialize_connection(path: Path) -> duckdb.DuckDBPyConnection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(path))
    conn.execute(CREATE_COMPANIES_TABLE)
    conn.execute(CREATE_PRICE_DATA_TABLE)
    conn.execute(CREATE_PRICE_FEATURES_TABLE)
    conn.execute(CREATE_MARKET_EVENTS_TABLE)
    conn.execute(CREATE_CORRELATIONS_TABLE)
    conn.execute(CREATE_ROLLING_CORRELATIONS_TABLE)
    conn.execute(CREATE_EVENT_RETURNS_TABLE)
    conn.execute(CREATE_ABNORMAL_RETURNS_TABLE)
    conn.execute(CREATE_NEWS_TABLE)
    conn.execute(CREATE_EVENT_NEWS_TABLE)
    conn.execute(CREATE_RELATIONSHIPS_TABLE)
    conn.execute(CREATE_RELATIONSHIP_EVIDENCE_TABLE)
    conn.execute(CREATE_HISTORICAL_EVENTS_TABLE)
    conn.execute(CREATE_DOCUMENTS_TABLE)
    conn.execute(CREATE_DOCUMENT_CHUNKS_TABLE)
    _apply_schema_migrations(conn)
    return conn


def _apply_schema_migrations(conn: duckdb.DuckDBPyConnection) -> None:
    """Add columns to already-existing tables from earlier phases (additive, idempotent).

    `CREATE TABLE IF NOT EXISTS` does not retroactively add new columns to a table
    that already exists on disk from a prior run, so new columns must be migrated here.
    """
    conn.execute("ALTER TABLE correlations ADD COLUMN IF NOT EXISTS alpha DOUBLE")
    # Phase 7 - market/sector context attached to an already-detected event.
    conn.execute("ALTER TABLE market_events ADD COLUMN IF NOT EXISTS market_return DOUBLE")
    conn.execute("ALTER TABLE market_events ADD COLUMN IF NOT EXISTS sector_return DOUBLE")
    conn.execute("ALTER TABLE market_events ADD COLUMN IF NOT EXISTS market_adjusted_return DOUBLE")
    conn.execute("ALTER TABLE market_events ADD COLUMN IF NOT EXISTS sector_adjusted_return DOUBLE")
    conn.execute("ALTER TABLE market_events ADD COLUMN IF NOT EXISTS classification VARCHAR")
    # Phase 9 - rule-based event classification (type/description/source of best-matching news).
    conn.execute("ALTER TABLE market_events ADD COLUMN IF NOT EXISTS event_type VARCHAR")
    conn.execute("ALTER TABLE market_events ADD COLUMN IF NOT EXISTS event_description VARCHAR")
    conn.execute("ALTER TABLE market_events ADD COLUMN IF NOT EXISTS news_source VARCHAR")
    # Phase 12 - business relationship analysis annotations on top of Phase 11 relationships.
    conn.execute("ALTER TABLE relationships ADD COLUMN IF NOT EXISTS business_area VARCHAR")
    conn.execute("ALTER TABLE relationships ADD COLUMN IF NOT EXISTS geographic_exposure VARCHAR")
    # Phase 13 - optional link from a graph entity to its own publicly-traded ticker (if any).
    conn.execute("ALTER TABLE relationships ADD COLUMN IF NOT EXISTS target_entity_ticker VARCHAR")
    conn.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS source_url VARCHAR")
    conn.execute("ALTER TABLE news ADD COLUMN IF NOT EXISTS source_kind VARCHAR")
    conn.execute("ALTER TABLE news ADD COLUMN IF NOT EXISTS source_url VARCHAR")
    conn.execute("ALTER TABLE news ADD COLUMN IF NOT EXISTS retrieved_at TIMESTAMPTZ")
    conn.execute("ALTER TABLE news ADD COLUMN IF NOT EXISTS content_sha256 VARCHAR")
    conn.execute("ALTER TABLE news ADD COLUMN IF NOT EXISTS timestamp_status VARCHAR")
    conn.execute("ALTER TABLE relationships ADD COLUMN IF NOT EXISTS evidence_date DATE")
    conn.execute("ALTER TABLE relationships ADD COLUMN IF NOT EXISTS last_reviewed DATE")
    conn.execute("ALTER TABLE relationships ADD COLUMN IF NOT EXISTS evidence_scope VARCHAR")
