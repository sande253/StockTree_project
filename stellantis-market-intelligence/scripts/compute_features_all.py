"""Backfill price_features for every ticker present in price_data (Phase 3, all tickers).

The original Phase 3 rollout only ever computed features for STLA + the two benchmark
tickers; this fills the gap for every supplier/OEM/competitor ticker now tracked.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import logging

from analytics.features import compute_and_store_price_features
from storage.duckdb import get_connection

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    conn = get_connection()
    try:
        tickers = [r[0] for r in conn.execute("SELECT DISTINCT ticker FROM price_data ORDER BY ticker").fetchall()]
    finally:
        conn.close()

    logger.info("Computing price features for %d tickers...", len(tickers))
    for ticker in tickers:
        try:
            count = compute_and_store_price_features(ticker)
            logger.info("✓ %s: %d rows", ticker, count)
        except Exception as exc:  # noqa: BLE001 - one bad ticker must not stop the batch
            logger.error("✗ %s failed: %s", ticker, exc)


if __name__ == "__main__":
    main()
