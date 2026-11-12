"""Phase 4 - STLA Event Detection tests."""

from __future__ import annotations

import pandas as pd
import pytest

from events.detector import (
    DEFAULT_THRESHOLDS,
    detect_and_store_events,
    detect_events,
    load_event_rules,
    persist_events,
)


def _features_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=4, freq="D").date,
            "daily_return": [0.01, -0.08, 0.02, float("nan")],
            "zscore": [0.2, -2.5, 0.1, None],
            "rolling_volatility": [0.01, 0.02, 0.05, None],
            "volume_zscore": [0.3, 1.0, 3.5, None],
        }
    )


def test_load_event_rules_returns_configured_thresholds():
    thresholds = load_event_rules()
    assert thresholds["absolute_return"] == pytest.approx(0.05)
    assert thresholds["severity"]["high"] == pytest.approx(0.07)


def test_load_event_rules_falls_back_to_defaults_when_file_missing(tmp_path):
    thresholds = load_event_rules(tmp_path / "does-not-exist.yaml")
    assert thresholds == DEFAULT_THRESHOLDS


def test_detect_events_flags_large_negative_return_and_abnormal_volume():
    events = detect_events(_features_frame(), ticker="STLA")

    # Row 0: no rule triggers. Row 1: absolute_return + zscore. Row 2: abnormal_volume.
    # Row 3: NaN return is skipped entirely.
    assert len(events) == 2
    assert set(events["event_id"]) == {"STLA-2026-01-02", "STLA-2026-01-03"}

    negative_event = events[events["event_id"] == "STLA-2026-01-02"].iloc[0]
    assert negative_event["direction"] == "negative"
    assert negative_event["severity"] == "high"
    assert "absolute_return" in negative_event["detection_method"]
    assert "zscore" in negative_event["detection_method"]

    volume_event = events[events["event_id"] == "STLA-2026-01-03"].iloc[0]
    assert volume_event["detection_method"] == "abnormal_volume"
    assert volume_event["severity"] == "low"


def test_detect_events_returns_empty_frame_when_nothing_triggers():
    quiet = pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=2, freq="D").date,
            "daily_return": [0.001, -0.002],
            "zscore": [0.1, -0.1],
            "rolling_volatility": [0.01, 0.01],
            "volume_zscore": [0.2, -0.2],
        }
    )
    events = detect_events(quiet, ticker="STLA")
    assert events.empty


def test_persist_events_and_detect_and_store_events_end_to_end(tmp_path):
    db_path = tmp_path / "test.duckdb"
    events = detect_events(_features_frame(), ticker="STLA")
    inserted = persist_events(events, db_path=db_path)
    assert inserted == 2

    import duckdb

    conn = duckdb.connect(str(db_path))
    try:
        count = conn.execute("SELECT COUNT(*) FROM market_events").fetchone()[0]
        assert count == 2
    finally:
        conn.close()


def test_detect_and_store_events_raises_for_unknown_ticker(tmp_path):
    db_path = tmp_path / "empty.duckdb"
    with pytest.raises(ValueError, match="No price_features found"):
        detect_and_store_events("UNKNOWN", db_path=db_path)
