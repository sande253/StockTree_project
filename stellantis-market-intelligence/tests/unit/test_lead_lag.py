"""Phase 15 - Lead/Lag Analysis tests."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from analytics.lead_lag import DISCLAIMER, compute_lead_lag_profile, lagged_correlation


def _make_series(values: list[float], n_dates: int = 60) -> pd.Series:
    dates = pd.date_range("2026-01-01", periods=n_dates, freq="D").date
    return pd.Series(values[:n_dates], index=dates)


def test_lagged_correlation_detects_a_company_that_leads_stla_by_3_days():
    rng = np.random.default_rng(42)
    base = rng.normal(0, 0.02, 80)
    # company(i) == base[i+3] == stla(i+3): company's current value is STLA's value 3 days later,
    # i.e. company shows the move first -> company LEADS stla by 3 days.
    company = _make_series(list(base[3:]))
    stla = _make_series(list(base[: len(company)]))

    result = lagged_correlation(stla, company, lag=-3)
    assert result["lag"] == -3
    assert result["correlation"] > 0.95
    assert result["p_value"] < 0.001


def test_lagged_correlation_returns_none_stats_with_insufficient_overlap():
    stla = _make_series([0.01] * 5, n_dates=5)
    company = _make_series([0.01] * 5, n_dates=5)
    result = lagged_correlation(stla, company, lag=5)
    assert result["correlation"] is None
    assert result["sample_size"] == 0


def test_compute_lead_lag_profile_identifies_observed_lead(tmp_path, monkeypatch):
    rng = np.random.default_rng(7)
    base = list(rng.normal(0, 0.02, 80))

    def fake_load_returns(ticker, db_path=None):
        if ticker == "STLA":
            return _make_series(base[: len(base) - 3])
        return _make_series(base[3:])

    monkeypatch.setattr("analytics.lead_lag.load_returns", fake_load_returns)

    profile = compute_lead_lag_profile("SUP")
    assert profile["ticker"] == "SUP"
    assert profile["disclaimer"] == DISCLAIMER
    assert len(profile["per_lag"]) == 6
    assert profile["observed_lead"] is not None
    assert profile["observed_lead"]["lag"] == -3
    assert profile["observed_lag"] is None or profile["observed_lag"]["lag"] > 0


def test_compute_lead_lag_profile_reports_weak_relationship_for_unrelated_series(monkeypatch):
    def fake_load_returns(ticker, db_path=None):
        seed = 11 if ticker == "STLA" else 97
        return _make_series(list(np.random.default_rng(seed).normal(0, 0.02, 250)), n_dates=250)

    monkeypatch.setattr("analytics.lead_lag.load_returns", fake_load_returns)

    profile = compute_lead_lag_profile("UNRELATED")
    # Independently generated series should not show a strong relationship at any lag.
    assert all(
        abs(r["correlation"]) < 0.4 for r in profile["per_lag"] if r["correlation"] is not None
    )
