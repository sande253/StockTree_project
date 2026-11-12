"""Correlation analysis: every company in the universe vs a reference ticker (Phase 5).

IMPORTANT: this computes a historical STATISTICAL relationship only. It is
never evidence of a documented BUSINESS relationship (see Phase 11/12), and
correlation here must never be presented as causation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

MIN_SAMPLE_SIZE = 10
DEFAULT_ROLLING_WINDOW = 20


def pearson_correlation(x: pd.Series, y: pd.Series) -> dict[str, Any]:
    """Pearson correlation with a 95% confidence interval (Fisher z-transform)."""
    aligned = pd.concat([x, y], axis=1).dropna()
    n = len(aligned)
    if n < MIN_SAMPLE_SIZE:
        return {"correlation": None, "p_value": None, "sample_size": n, "ci_low": None, "ci_high": None}

    r, p_value = stats.pearsonr(aligned.iloc[:, 0], aligned.iloc[:, 1])
    r_clamped = max(min(r, 0.999999), -0.999999)
    z = np.arctanh(r_clamped)
    se = 1.0 / np.sqrt(n - 3)
    ci_low = float(np.tanh(z - 1.96 * se))
    ci_high = float(np.tanh(z + 1.96 * se))
    return {
        "correlation": float(r),
        "p_value": float(p_value),
        "sample_size": n,
        "ci_low": ci_low,
        "ci_high": ci_high,
    }


def spearman_correlation(x: pd.Series, y: pd.Series) -> dict[str, Any]:
    """Spearman rank correlation."""
    aligned = pd.concat([x, y], axis=1).dropna()
    n = len(aligned)
    if n < MIN_SAMPLE_SIZE:
        return {"correlation": None, "p_value": None, "sample_size": n}
    rho, p_value = stats.spearmanr(aligned.iloc[:, 0], aligned.iloc[:, 1])
    return {"correlation": float(rho), "p_value": float(p_value), "sample_size": n}


def rolling_correlation(x: pd.Series, y: pd.Series, window: int) -> pd.Series:
    """Rolling Pearson correlation over a trailing `window`-period span."""
    aligned = pd.concat([x, y], axis=1).dropna()
    return aligned.iloc[:, 0].rolling(window=window, min_periods=window).corr(aligned.iloc[:, 1])


def beta_and_r2(company_returns: pd.Series, reference_returns: pd.Series) -> dict[str, Any]:
    """OLS regression of company returns on reference-ticker returns: beta, alpha, R^2, p-value."""
    aligned = pd.concat([company_returns, reference_returns], axis=1).dropna()
    n = len(aligned)
    if n < MIN_SAMPLE_SIZE:
        return {"beta": None, "alpha": None, "r_squared": None, "p_value": None, "sample_size": n}

    x = aligned.iloc[:, 1].to_numpy()  # reference ticker (e.g. STLA)
    y = aligned.iloc[:, 0].to_numpy()  # company
    result = stats.linregress(x, y)
    return {
        "beta": float(result.slope),
        "alpha": float(result.intercept),
        "r_squared": float(result.rvalue**2),
        "p_value": float(result.pvalue),
        "sample_size": n,
    }


def load_returns(ticker: str, db_path: Path | str | None = None) -> pd.Series:
    """Load the stored Phase 3 daily-return series for a ticker, indexed by date."""
    from storage.duckdb import get_connection, normalize_date_column

    conn = get_connection(db_path)
    try:
        df = conn.execute(
            "SELECT date, daily_return FROM price_features WHERE ticker = ? ORDER BY date",
            [ticker],
        ).fetchdf()
    finally:
        conn.close()
    df = normalize_date_column(df)
    return df.set_index("date")["daily_return"]


def compute_company_correlation(
    ticker: str,
    reference_ticker: str = "STLA",
    rolling_window: int = DEFAULT_ROLLING_WINDOW,
    db_path: Path | str | None = None,
) -> tuple[dict[str, Any], pd.DataFrame] | None:
    """Compute the full Phase 5 correlation profile for one company vs the reference ticker."""
    company_returns = load_returns(ticker, db_path=db_path)
    reference_returns = load_returns(reference_ticker, db_path=db_path)
    if company_returns.empty or reference_returns.empty:
        return None

    pearson = pearson_correlation(company_returns, reference_returns)
    spearman = spearman_correlation(company_returns, reference_returns)
    beta_stats = beta_and_r2(company_returns, reference_returns)

    record = {
        "ticker": ticker,
        "reference_ticker": reference_ticker,
        "pearson_correlation": pearson["correlation"],
        "pearson_p_value": pearson["p_value"],
        "pearson_ci_low": pearson["ci_low"],
        "pearson_ci_high": pearson["ci_high"],
        "spearman_correlation": spearman["correlation"],
        "spearman_p_value": spearman["p_value"],
        "beta": beta_stats["beta"],
        "alpha": beta_stats["alpha"],
        "r_squared": beta_stats["r_squared"],
        "beta_p_value": beta_stats["p_value"],
        "sample_size": pearson["sample_size"],
    }

    rolling = rolling_correlation(company_returns, reference_returns, rolling_window).dropna()
    rolling_df = rolling.reset_index()
    rolling_df.columns = ["date", "rolling_correlation"]
    rolling_df["ticker"] = ticker
    rolling_df["reference_ticker"] = reference_ticker
    rolling_df["lookback_window"] = rolling_window

    return record, rolling_df


def persist_correlation(record: dict[str, Any], db_path: Path | str | None = None) -> None:
    """Upsert one company's full-sample correlation profile into `correlations`."""
    from storage.duckdb import get_connection

    conn = get_connection(db_path)
    try:
        conn.execute(
            """
            INSERT INTO correlations
                (ticker, reference_ticker, pearson_correlation, pearson_p_value,
                 pearson_ci_low, pearson_ci_high, spearman_correlation, spearman_p_value,
                 beta, alpha, r_squared, beta_p_value, sample_size)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (ticker, reference_ticker) DO UPDATE SET
                pearson_correlation = excluded.pearson_correlation,
                pearson_p_value = excluded.pearson_p_value,
                pearson_ci_low = excluded.pearson_ci_low,
                pearson_ci_high = excluded.pearson_ci_high,
                spearman_correlation = excluded.spearman_correlation,
                spearman_p_value = excluded.spearman_p_value,
                beta = excluded.beta,
                alpha = excluded.alpha,
                r_squared = excluded.r_squared,
                beta_p_value = excluded.beta_p_value,
                sample_size = excluded.sample_size,
                computed_at = now()
            """,
            [
                record["ticker"],
                record["reference_ticker"],
                record["pearson_correlation"],
                record["pearson_p_value"],
                record["pearson_ci_low"],
                record["pearson_ci_high"],
                record["spearman_correlation"],
                record["spearman_p_value"],
                record["beta"],
                record["alpha"],
                record["r_squared"],
                record["beta_p_value"],
                record["sample_size"],
            ],
        )
    finally:
        conn.close()


def persist_rolling_correlations(rolling_df: pd.DataFrame, db_path: Path | str | None = None) -> int:
    """Upsert a company's rolling-correlation time series into `rolling_correlations`."""
    from storage.duckdb import get_connection

    if rolling_df.empty:
        return 0

    conn = get_connection(db_path)
    try:
        conn.register("rolling_rows", rolling_df)
        conn.execute(
            """
            INSERT INTO rolling_correlations
                (ticker, reference_ticker, date, rolling_correlation, lookback_window)
            SELECT ticker, reference_ticker, date, rolling_correlation, lookback_window
            FROM rolling_rows
            ON CONFLICT (ticker, reference_ticker, date) DO UPDATE SET
                rolling_correlation = excluded.rolling_correlation,
                lookback_window = excluded.lookback_window
            """
        )
        conn.unregister("rolling_rows")
        return len(rolling_df)
    finally:
        conn.close()


def compute_and_store_universe_correlations(
    reference_ticker: str = "STLA",
    rolling_window: int = DEFAULT_ROLLING_WINDOW,
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    """Phase 5 pipeline: correlate every OTHER company in the universe against `reference_ticker`.

    Companies with no ingested price data are skipped (not an error) and reported in `skipped`.
    """
    from storage.load_companies import load_companies_config

    companies = load_companies_config()
    processed: list[str] = []
    skipped: list[str] = []

    for company in companies:
        if company.ticker == reference_ticker:
            continue
        result = compute_company_correlation(
            company.ticker, reference_ticker=reference_ticker, rolling_window=rolling_window, db_path=db_path
        )
        if result is None:
            skipped.append(company.ticker)
            continue
        record, rolling_df = result
        persist_correlation(record, db_path=db_path)
        persist_rolling_correlations(rolling_df, db_path=db_path)
        processed.append(company.ticker)

    return {"processed": processed, "skipped": skipped}
