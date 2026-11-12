"""Phase 16 - Regime Detection tests."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from analytics.regime import (
    NEGLIGIBLE_CORRELATION,
    REGIME_CHANGE_THRESHOLD,
    detect_regime_changes,
    summarize_by_year,
)


def _rolling_series(records: list[tuple[date, float | None]]) -> pd.DataFrame:
    return pd.DataFrame(records, columns=["date", "rolling_correlation"])


def test_summarize_by_year_groups_and_drops_nan():
    series = _rolling_series(
        [
            (date(2022, 1, 1), 0.20),
            (date(2022, 6, 1), 0.22),
            (date(2022, 12, 1), None),
            (date(2024, 1, 1), 0.48),
        ]
    )
    yearly = summarize_by_year(series)
    assert list(yearly["year"]) == [2022, 2024]
    assert yearly.iloc[0]["sample_size"] == 2
    assert yearly.iloc[0]["mean_correlation"] == pytest.approx(0.21)


def test_summarize_by_year_returns_empty_frame_for_empty_input():
    yearly = summarize_by_year(_rolling_series([]))
    assert yearly.empty


def test_detect_regime_changes_reports_insufficient_history_with_one_year(monkeypatch):
    series = _rolling_series([(date(2026, 1, 1), 0.3), (date(2026, 6, 1), 0.32)])
    monkeypatch.setattr("analytics.regime.load_rolling_correlation_series", lambda *a, **k: series)

    result = detect_regime_changes("SUP")
    assert result["changes"] == []
    assert "Not enough historical periods" in result["note"]


def test_detect_regime_changes_labels_strengthened_weakened_direction_change_and_disappeared(monkeypatch):
    series = _rolling_series(
        [
            (date(2021, 1, 1), 0.20),   # baseline
            (date(2022, 1, 1), 0.50),   # +0.30 -> strengthened
            (date(2023, 1, 1), 0.52),   # +0.02 -> stable
            (date(2024, 1, 1), -0.40),  # sign flip, both non-negligible -> direction change
            (date(2025, 1, 1), 0.02),   # was non-negligible negative, now negligible -> disappeared
        ]
    )
    monkeypatch.setattr("analytics.regime.load_rolling_correlation_series", lambda *a, **k: series)

    result = detect_regime_changes("SUP")
    labels = [c["change"] for c in result["changes"]]
    assert labels == ["strengthened", "stable", "direction change", "disappeared"]


def test_regime_thresholds_are_documented_constants():
    assert REGIME_CHANGE_THRESHOLD == pytest.approx(0.15)
    assert NEGLIGIBLE_CORRELATION == pytest.approx(0.10)
