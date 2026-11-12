"""Document search service (Phase 24) - wraps the Phase 19/20 retrieval layer.

Raw retrieval only (no LLM call) - POST /investigate is the endpoint that triggers the
full AI-synthesized investigation; this is a lighter-weight document/evidence search.
"""

from __future__ import annotations

from typing import Any


def search(query: str, top_k: int = 5) -> list[dict[str, Any]]:
    from ai.retrieval import retrieve

    return retrieve(query, top_k=top_k)
