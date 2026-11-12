"""Reusable return/volatility metric functions (Phase 3).

All functions are pure (operate on and return pandas Series) so they can be
reused across phases (event detection, event study, regime detection, ...).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def daily_return(prices: pd.Series) -> pd.Series:
    """Simple period-over-period percentage return."""
    return prices.pct_change()


def log_return(prices: pd.Series) -> pd.Series:
    """Natural-log return: ln(P_t / P_t-1)."""
    return np.log(prices / prices.shift(1))


def rolling_return(prices: pd.Series, window: int) -> pd.Series:
    """Percentage return over a trailing `window`-period span."""
    return prices.pct_change(periods=window)


def rolling_mean(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window, min_periods=window).mean()


def rolling_std(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window, min_periods=window).std()


def rolling_volatility(
    returns: pd.Series, window: int, annualize: bool = False, periods_per_year: int = 252
) -> pd.Series:
    """Rolling standard deviation of returns, optionally annualized."""
    vol = rolling_std(returns, window)
    if annualize:
        vol = vol * np.sqrt(periods_per_year)
    return vol


def zscore(series: pd.Series, window: int) -> pd.Series:
    """Rolling z-score: (x - rolling_mean) / rolling_std."""
    mean = rolling_mean(series, window)
    std = rolling_std(series, window)
    return (series - mean) / std


def drawdown(prices: pd.Series) -> pd.Series:
    """Percentage drop from the running peak price (always <= 0)."""
    running_max = prices.cummax()
    return prices / running_max - 1.0


def volume_change(volume: pd.Series) -> pd.Series:
    return volume.pct_change()


def volume_zscore(volume: pd.Series, window: int) -> pd.Series:
    return zscore(volume, window)
