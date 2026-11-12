"""Build the searchable corpus from current DuckDB records."""

from __future__ import annotations

import argparse
import logging

from ai.vector_store import build_vector_store

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def build_index(force: bool = False) -> dict[str, int]:
    """Always rebuild: database rows can change without changing the document count."""
    del force  # Keep the existing CLI/API argument compatible; rebuilds are always safe.
    result = build_vector_store()
    logger.info("Indexed %d documents in %d chunks", result["documents"], result["chunks"])
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Build or rebuild the DuckDB-backed vector index")
    parser.add_argument("--force", action="store_true", help="Accepted for compatibility; the index is always rebuilt")
    args = parser.parse_args()
    build_index(force=args.force)


if __name__ == "__main__":
    main()