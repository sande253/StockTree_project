"""Company service (Phase 24) - thin wrapper over the repository layer."""

from __future__ import annotations

from typing import Any

from storage.repository import get_company, list_companies


def get_all_companies() -> list[dict[str, Any]]:
    return list_companies()


def get_company_by_ticker(ticker: str) -> dict[str, Any] | None:
    return get_company(ticker)
