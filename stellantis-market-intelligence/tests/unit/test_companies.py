"""Phase 1 - Company Universe tests."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from storage.load_companies import load_companies_config, upsert_companies
from storage.duckdb import get_connection
from storage.schemas import Company


def _write_config(tmp_path: Path, yaml_text: str) -> Path:
    config_path = tmp_path / "companies.yaml"
    config_path.write_text(textwrap.dedent(yaml_text), encoding="utf-8")
    return config_path


def test_load_default_companies_config_includes_stla():
    companies = load_companies_config()
    tickers = {c.ticker for c in companies}
    assert "STLA" in tickers
    stla = next(c for c in companies if c.ticker == "STLA")
    assert stla.relationship_type == "self"


def test_load_companies_config_rejects_duplicate_tickers(tmp_path):
    config_path = _write_config(
        tmp_path,
        """
        companies:
          - ticker: STLA
            company_name: Stellantis N.V.
            exchange: NYSE
            sector: Consumer Cyclical
            industry: Auto Manufacturers
            country: Netherlands
            relationship_type: self
          - ticker: STLA
            company_name: Stellantis Duplicate
            exchange: NYSE
            sector: Consumer Cyclical
            industry: Auto Manufacturers
            country: Netherlands
            relationship_type: self
        """,
    )
    with pytest.raises(ValueError, match="Duplicate ticker"):
        load_companies_config(config_path)


def test_load_companies_config_rejects_invalid_relationship_type(tmp_path):
    config_path = _write_config(
        tmp_path,
        """
        companies:
          - ticker: XYZ
            company_name: Example Co
            exchange: NYSE
            sector: Technology
            industry: Software
            country: United States
            relationship_type: definitely_not_valid
        """,
    )
    with pytest.raises(ValueError, match="relationship_type"):
        load_companies_config(config_path)


def test_load_companies_config_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_companies_config(tmp_path / "does_not_exist.yaml")


def test_load_companies_config_empty_list_raises(tmp_path):
    config_path = _write_config(tmp_path, "companies: []")
    with pytest.raises(ValueError, match="No companies defined"):
        load_companies_config(config_path)


def test_company_rejects_blank_ticker():
    with pytest.raises(ValueError, match="ticker"):
        Company(
            ticker="  ",
            company_name="Example",
            exchange=None,
            sector=None,
            industry=None,
            country=None,
            relationship_type="other",
        )


def test_upsert_companies_persists_and_updates(tmp_path):
    db_path = tmp_path / "test.duckdb"

    companies = [
        Company(
            ticker="STLA",
            company_name="Stellantis N.V.",
            exchange="NYSE",
            sector="Consumer Cyclical",
            industry="Auto Manufacturers",
            country="Netherlands",
            relationship_type="self",
        )
    ]
    count = upsert_companies(companies, db_path=db_path)
    assert count == 1

    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT ticker, company_name, relationship_type FROM companies WHERE ticker = 'STLA'"
        ).fetchone()
    finally:
        conn.close()
    assert row == ("STLA", "Stellantis N.V.", "self")

    # Upsert again with a changed name - should update, not duplicate.
    updated = [
        Company(
            ticker="STLA",
            company_name="Stellantis N.V. (renamed)",
            exchange="NYSE",
            sector="Consumer Cyclical",
            industry="Auto Manufacturers",
            country="Netherlands",
            relationship_type="self",
        )
    ]
    upsert_companies(updated, db_path=db_path)

    conn = get_connection(db_path)
    try:
        rows = conn.execute("SELECT ticker, company_name FROM companies").fetchall()
    finally:
        conn.close()
    assert rows == [("STLA", "Stellantis N.V. (renamed)")]
