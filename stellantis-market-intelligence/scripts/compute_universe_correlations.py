"""Phase 5 pipeline: correlate every company in the universe against STLA.

Supersedes the old compute_correlations.py, which only filled pearson_correlation/
p_value/sample_size (no beta/alpha/spearman/rolling), breaking the Phase 6 event
study that depends on beta/alpha. Uses the real analytics.correlation module.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import logging

from analytics.correlation import compute_and_store_universe_correlations

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def main(reference_ticker: str = "STLA") -> None:
    logger.info("Computing full correlation profiles (pearson/spearman/beta/alpha) vs %s...", reference_ticker)
    result = compute_and_store_universe_correlations(reference_ticker=reference_ticker)
    logger.info("✓ Processed %d companies", len(result["processed"]))
    if result["skipped"]:
        logger.warning("Skipped (no price data): %s", result["skipped"])


if __name__ == "__main__":
    main()
