"""Retrieval layer for the local RAG pipeline (Phase 20).

Thin wrapper over Phase 19's vector store search, with a documented default top_k.
Kept separate from ai/rag.py so Phase 21's investigation agent can reuse retrieval
without depending on the LLM call itself.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ai.vector_store import DEFAULT_INDEX_DIR, search

DEFAULT_TOP_K = 5


def retrieve(
    query: str, top_k: int = DEFAULT_TOP_K, index_dir: Path | str = DEFAULT_INDEX_DIR, db_path: Path | str | None = None
) -> list[dict[str, Any]]:
    """Retrieve the most relevant indexed chunks for `query`. Empty list if no index/no matches."""
    return search(query, top_k=top_k, index_dir=index_dir, db_path=db_path)
