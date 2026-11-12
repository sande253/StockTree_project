"""Load the configurable company universe (config/companies.yaml) into DuckDB.

Phase 1 - Company Universe.

Usage:
    python -m storage.load_companies [--config path/to/companies.yaml]
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import yaml

from storage.duckdb import get_connection
from storage.schemas import Company

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path("config/companies.yaml")


def load_companies_config(config_path: Path | str = DEFAULT_CONFIG_PATH) -> list[Company]:
    """Parse and validate the company universe YAML file into Company objects."""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Company universe config not found: {path}")

    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    entries = raw.get("companies", [])
    if not entries:
        raise ValueError(f"No companies defined in {path}")

    companies: list[Company] = []
    seen_tickers: set[str] = set()
    for entry in entries:
        company = Company(
            ticker=str(entry["ticker"]).strip(),
            company_name=str(entry["company_name"]).strip(),
            exchange=entry.get("exchange"),
            sector=entry.get("sector"),
            industry=entry.get("industry"),
            country=entry.get("country"),
            relationship_type=str(entry["relationship_type"]).strip(),
        )
        if company.ticker in seen_tickers:
            raise ValueError(f"Duplicate ticker in company universe config: {company.ticker}")
        seen_tickers.add(company.ticker)
        companies.append(company)

    return companies


def upsert_companies(companies: list[Company], db_path: Path | str | None = None) -> int:
    """Insert/update the given companies into the DuckDB `companies` table."""
    conn = get_connection(db_path)
    try:
        for c in companies:
            conn.execute(
                """
                INSERT INTO companies
                    (ticker, company_name, exchange, sector, industry, country, relationship_type)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (ticker) DO UPDATE SET
                    company_name = excluded.company_name,
                    exchange = excluded.exchange,
                    sector = excluded.sector,
                    industry = excluded.industry,
                    country = excluded.country,
                    relationship_type = excluded.relationship_type,
                    updated_at = now()
                """,
                [
                    c.ticker,
                    c.company_name,
                    c.exchange,
                    c.sector,
                    c.industry,
                    c.country,
                    c.relationship_type,
                ],
            )
        return len(companies)
    finally:
        conn.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Load the company universe into DuckDB.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to companies.yaml")
    args = parser.parse_args()

    companies = load_companies_config(args.config)
    count = upsert_companies(companies)
    logger.info("Loaded %d companies from %s into DuckDB.", count, args.config)


if __name__ == "__main__":
    main()
