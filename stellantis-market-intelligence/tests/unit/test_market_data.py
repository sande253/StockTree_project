"""Phase 2 - Market Data Ingestion tests.

These tests exercise validation/normalization/persistence logic with synthetic
DataFrames and never call the network (yfinance download is tested only via
manual/integration runs since it depends on an external service).
"""

from __future__ import annotations

import pandas as pd
import pytest

from ingestion.market_data import (
    MarketDataError,
    normalize_price_data,
    save_raw_parquet,
    upsert_price_data,
    validate_price_data,
)


def _raw_frame() -> pd.DataFrame:
    dates = pd.to_datetime(
        [
            "2026-01-02",  # Friday
            "2026-01-02",  # duplicate of the row above
            "2026-01-05",  # Monday
            "2026-01-08",  # Thursday -> 01-06/01-07 become missing business days
            "2026-01-09",  # Friday, invalid (negative prices)
        ]
    )
    return pd.DataFrame(
        {
            "Open": [10.0, 10.0, 11.0, 11.5, -5.0],
            "High": [10.5, 10.5, 11.5, 12.0, -4.0],
            "Low": [9.5, 9.5, 10.5, 11.0, -6.0],
            "Close": [10.2, 10.2, 11.2, 11.8, -4.5],
            "Adj Close": [10.2, 10.2, 11.2, 11.8, -4.5],
            "Volume": [1000, 1000, 1200, 1300, 500],
        },
        index=dates,
    )


def test_validate_price_data_removes_duplicates_and_invalid_rows_and_reports_gaps():
    clean, issues = validate_price_data(_raw_frame(), ticker="STLA")

    assert len(clean) == 3  # 01-02 (deduped), 01-05, 01-08
    assert issues["duplicates_removed"] == 1
    assert issues["invalid_rows_removed"] == 1
    assert issues["missing_business_days"] == ["2026-01-06", "2026-01-07"]


def test_validate_price_data_raises_when_required_columns_missing():
    df = pd.DataFrame({"Open": [1.0]}, index=pd.to_datetime(["2026-01-02"]))
    with pytest.raises(MarketDataError, match="missing required columns"):
        validate_price_data(df, ticker="STLA")


def test_validate_price_data_raises_when_no_rows_survive():
    df = pd.DataFrame(
        {
            "Open": [-1.0],
            "High": [-1.0],
            "Low": [-1.0],
            "Close": [-1.0],
            "Volume": [1],
        },
        index=pd.to_datetime(["2026-01-02"]),
    )
    with pytest.raises(MarketDataError, match="no valid rows remain"):
        validate_price_data(df, ticker="STLA")


def test_normalize_price_data_produces_expected_schema():
    clean, _ = validate_price_data(_raw_frame(), ticker="STLA")
    rows = normalize_price_data(clean, ticker="STLA", interval="1d")

    assert list(rows.columns) == [
        "ticker",
        "date",
        "open",
        "high",
        "low",
        "close",
        "adj_close",
        "volume",
        "interval",
        "source",
    ]
    assert (rows["ticker"] == "STLA").all()
    assert (rows["interval"] == "1d").all()
    assert (rows["source"] == "yfinance").all()
    assert rows["volume"].dtype.kind == "i"


@pytest.mark.parametrize(
    "column,value",
    [("Close", float("inf")), ("Open", 99), ("Close", 1),
     ("Volume", float("inf")), ("Volume", 1.5), ("Volume", 2**63),
     ("Adj Close", 0), ("High", "invalid")],
)
def test_validate_price_data_rejects_unusable_values(column, value):
    frame = _raw_frame().iloc[[0]].copy()
    frame[column] = value
    with pytest.raises(MarketDataError, match="no valid rows remain"):
        validate_price_data(frame, "STLA")


def test_validate_price_data_rejects_invalid_date():
    frame = _raw_frame().iloc[[0]].copy()
    frame.index = ["not-a-date"]
    with pytest.raises(MarketDataError, match="no valid rows remain"):
        validate_price_data(frame, "STLA")


def test_save_raw_parquet_and_upsert_price_data_round_trip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    clean, _ = validate_price_data(_raw_frame(), ticker="STLA")
    rows = normalize_price_data(clean, ticker="STLA", interval="1d")

    parquet_path = save_raw_parquet(rows, "STLA", "2026-01-01", "2026-01-08", "1d")
    assert parquet_path.exists()
    assert pd.read_parquet(parquet_path).shape[0] == len(rows)

    db_path = tmp_path / "test.duckdb"
    inserted = upsert_price_data(rows, db_path=db_path)
    assert inserted == len(rows)

    # Re-running the same upsert should update in place, not duplicate rows.
    inserted_again = upsert_price_data(rows, db_path=db_path)
    assert inserted_again == len(rows)

    import duckdb

    conn = duckdb.connect(str(db_path))
    try:
        count = conn.execute("SELECT COUNT(*) FROM price_data").fetchone()[0]
        assert count == len(rows)
    finally:
        conn.close()
