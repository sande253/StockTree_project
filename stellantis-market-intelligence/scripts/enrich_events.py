"""Backfill Phase 7/9/10 enrichment (market context, classification, news correlation)
for any already-detected event that is missing it. Safe to re-run; only touches gaps.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import logging

from events.detector import enrich_events

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def main(ticker: str = "STLA") -> None:
    logger.info("Backfilling market context / classification / news correlation for %s events...", ticker)
    enrich_events(ticker)
    logger.info("Done.")


if __name__ == "__main__":
    main()
