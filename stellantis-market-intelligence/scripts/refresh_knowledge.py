"""Refresh public news, enrich event links, and rebuild the investigation corpus."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ai.vector_store import build_vector_store
from events.detector import enrich_events
from ingestion.news import ingest_all_sources

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def refresh_knowledge() -> dict[str, object]:
    news_result = ingest_all_sources()
    enrich_events("STLA")
    index_result = build_vector_store()
    logger.info("News ingestion: %s", news_result)
    logger.info("Search corpus: %s", index_result)
    return {"news": news_result, "index": index_result}


if __name__ == "__main__":
    refresh_knowledge()