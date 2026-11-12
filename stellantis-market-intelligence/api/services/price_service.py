"""Price-data service (Phase 24) - thin wrapper over the repository layer."""

from __future__ import annotations

from typing import Any

from storage.repository import list_price_data


def get_prices(ticker: str, start: str | None = None, end: str | None = None) -> list[dict[str, Any]]:
    return list_price_data(ticker, start=start, end=end)
