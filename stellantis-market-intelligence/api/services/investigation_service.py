"""AI investigation service (Phase 24) - wraps the Phase 21 agent."""

from __future__ import annotations

from typing import Any


def investigate(event_id: str) -> dict[str, Any] | None:
    from ai.agent import investigate_event

    return investigate_event(event_id)
