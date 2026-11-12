"""Historical-event service (Phase 24)."""

from __future__ import annotations

from typing import Any

from storage.repository import list_historical_events


def get_all_historical_events() -> list[dict[str, Any]]:
    return list_historical_events()


def get_similar_events(event_id: str, top_n: int = 3) -> list[dict[str, Any]]:
    from events.similarity import find_similar_events

    return find_similar_events(event_id, top_n=top_n)
