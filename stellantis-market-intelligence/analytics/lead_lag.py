"""Lead/Lag Analysis (Phase 15).

Tests whether a company's stock has historically moved before (lead) or after (lag)
Stellantis at several fixed horizons, by correlating STLA's return series against a
company's return series shifted by each lag. This is purely an observed historical
statistical pattern - explicitly NOT presented as guaranteed predictive behavior.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from analytics.correlation import load_returns, pearson_correlation

# Negative lag = "Company(t+lag) -> STLA(t)" (company potentially LEADS STLA).
# Positive lag = "STLA(t) -> Company(t+lag)" (company potentially LAGS STLA).
DEFAULT_LAGS: tuple[int, ...] = (-5, -3, -1, 1, 3, 5)
SIGNIFICANCE_LEVEL = 0.05
DISCLAIMER = "Observed historical correlation at specific lags only; not a guarantee of predictive behavior."


def lagged_correlation(stla_returns: pd.Series, ticker_returns: pd.Series, lag: int) -> dict[str, Any]:
    """Correlate STLA(t) against ticker(t+lag). Negative lag tests a company lead, positive a lag."""
    shifted = ticker_returns.shift(-lag)
    result = pearson_correlation(stla_returns, shifted)
    return {"lag": lag, **result}


def compute_lead_lag_profile(
    ticker: str,
    reference_ticker: str = "STLA",
    lags: tuple[int, ...] = DEFAULT_LAGS,
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    """Full Phase 15 profile for one company vs the reference ticker across all configured lags."""
    stla_returns = load_returns(reference_ticker, db_path=db_path)
    ticker_returns = load_returns(ticker, db_path=db_path)

    per_lag = [lagged_correlation(stla_returns, ticker_returns, lag) for lag in lags]

    def _is_significant(r: dict[str, Any]) -> bool:
        return r["correlation"] is not None and r["p_value"] is not None and r["p_value"] < SIGNIFICANCE_LEVEL

    significant = [r for r in per_lag if _is_significant(r)]
    lead_candidates = [r for r in significant if r["lag"] < 0]
    lag_candidates = [r for r in significant if r["lag"] > 0]

    observed_lead = max(lead_candidates, key=lambda r: abs(r["correlation"])) if lead_candidates else None
    observed_lag = max(lag_candidates, key=lambda r: abs(r["correlation"])) if lag_candidates else None

    return {
        "ticker": ticker,
        "reference_ticker": reference_ticker,
        "per_lag": per_lag,
        "observed_lead": observed_lead,
        "observed_lag": observed_lag,
        "disclaimer": DISCLAIMER,
    }
