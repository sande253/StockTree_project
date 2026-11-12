"""Phase 6 pipeline: run the market-model event study for every detected STLA event.

Supersedes the old compute_abnormal_returns.py, which used a simplified
"abnormal return = raw return" placeholder instead of the real alpha/beta market
model. Uses the real analytics.event_study module (requires Phase 5 correlations
with beta/alpha already computed - run compute_universe_correlations.py first).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import logging

from analytics.event_study import run_event_study
from storage.duckdb import get_connection

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def main(reference_ticker: str = "STLA") -> None:
    conn = get_connection()
    try:
        event_ids = [
            r[0]
            for r in conn.execute(
                "SELECT event_id FROM market_events WHERE ticker = ? ORDER BY event_date", [reference_ticker]
            ).fetchall()
        ]
    finally:
        conn.close()

    logger.info("Running event study for %d %s events...", len(event_ids), reference_ticker)
    for event_id in event_ids:
        result = run_event_study(event_id, reference_ticker=reference_ticker)
        logger.info("✓ %s: %d companies reacted, %d skipped", event_id, len(result["processed"]), len(result["skipped"]))


if __name__ == "__main__":
    main()
