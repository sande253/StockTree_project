"""Warehouse readiness checks shared by the refresh pipeline and health API."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

from analytics.benchmark import load_benchmarks
from storage.duckdb import get_connection
from storage.load_companies import load_companies_config


def configured_tickers() -> list[str]:
    companies = [company.ticker for company in load_companies_config()]
    benchmarks = [benchmark["ticker"] for benchmark in load_benchmarks().values()]
    return list(dict.fromkeys([*companies, *benchmarks]))


def check_data_quality(
    db_path: Path | str | None = None,
    *,
    today: date | None = None,
    min_rows: int = 60,
    max_age_days: int = 7,
) -> dict[str, Any]:
    today = today or date.today()
    issues: list[str] = []
    warnings: list[str] = []
    coverage: list[dict[str, Any]] = []
    conn = get_connection(db_path)
    try:
        companies = load_companies_config()
        by_ticker = {company.ticker: company for company in companies}
        for ticker in configured_tickers():
            issue_start = len(issues)
            count, latest = conn.execute(
                "SELECT count(*), max(date) FROM price_data WHERE ticker = ? AND interval = '1d'",
                [ticker],
            ).fetchone()
            feature_count, feature_latest = conn.execute(
                "SELECT count(*), max(date) FROM price_features WHERE ticker = ?", [ticker]
            ).fetchone()
            missing_features = conn.execute(
                """SELECT count(*) FROM price_data prices
                LEFT JOIN price_features features ON prices.ticker = features.ticker
                    AND prices.date = features.date
                WHERE prices.ticker = ? AND prices.interval = '1d' AND features.date IS NULL""",
                [ticker],
            ).fetchone()[0]
            coverage.append({
                "ticker": ticker, "price_rows": count, "latest_price": str(latest) if latest else None,
                "feature_rows": feature_count,
                "latest_feature": str(feature_latest) if feature_latest else None,
                "missing_features": missing_features,
            })
            if count < min_rows:
                issues.append(f"{ticker}: only {count} daily prices; need at least {min_rows}")
            if latest is None or latest < today - timedelta(days=max_age_days):
                issues.append(f"{ticker}: missing or stale daily prices (latest: {latest})")
            if latest is not None and latest > today:
                issues.append(f"{ticker}: future-dated prices ({latest})")
            if missing_features or feature_count < min_rows or feature_latest != latest:
                issues.append(f"{ticker}: features are missing or out of date")
            company = by_ticker.get(ticker)
            reference = "^GSPC" if company and company.exchange in {"NYSE", "NASDAQ", "OTC"} else None
            if company and reference is None:
                reference = next((peer.ticker for peer in companies if peer.exchange == company.exchange and peer.ticker != ticker), None)
            gaps = []
            if reference and count:
                gaps = [str(row[0]) for row in conn.execute(
                    """SELECT date FROM price_data WHERE ticker = ? AND interval = '1d'
                       AND date >= (SELECT min(date) FROM price_data WHERE ticker = ? AND interval = '1d')
                       AND date < ?
                       EXCEPT SELECT date FROM price_data WHERE ticker = ? AND interval = '1d'
                       ORDER BY date""", [reference, ticker, today, ticker],
                ).fetchall()]
            coverage[-1].update(
                issues=issues[issue_start:], status="ready" if len(issues) == issue_start else "degraded",
                reference_ticker=reference, reference_session_gaps=gaps,
            )
            if gaps:
                warnings.append(f"{ticker}: {len(gaps)} sessions present in {reference} are absent; check listing calendars and provider coverage")

        invalid_prices = conn.execute(
            """SELECT count(*) FROM price_data WHERE interval = '1d' AND (
                NOT isfinite(open) OR NOT isfinite(high) OR NOT isfinite(low)
                OR NOT isfinite(close) OR NOT isfinite(adj_close)
                OR open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL
                OR adj_close IS NULL OR volume IS NULL OR volume < 0
                OR least(open, high, low, close, adj_close) <= 0
                OR high < greatest(open, low, close) OR low > least(open, high, close))"""
        ).fetchone()[0]
        if invalid_prices:
            issues.append(f"Warehouse contains {invalid_prices} invalid daily price rows")

        counts = {
            table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in ("companies", "market_events", "correlations", "news", "event_news",
                          "event_returns", "abnormal_returns", "historical_events",
                          "relationships", "documents", "document_chunks")
        }
        for company in load_companies_config():
            if company.ticker == "STLA":
                continue
            correlation = conn.execute(
                """SELECT count(*) FROM correlations
                WHERE ticker = ? AND reference_ticker = 'STLA' AND isfinite(pearson_correlation)""",
                [company.ticker],
            ).fetchone()[0]
            if not correlation:
                issues.append(f"{company.ticker}: no usable correlation against STLA")
        latest_news = conn.execute(
            """SELECT max("timestamp") FROM news
            WHERE list_contains(string_split(mentioned_companies, ','), 'STLA')
                AND CAST("timestamp" AS DATE) <= ?""", [today]
        ).fetchone()[0]
        if latest_news is None or latest_news.date() < today - timedelta(days=30):
            issues.append(f"No recent Stellantis news/filings (latest: {latest_news})")
        if not counts["documents"] or not counts["document_chunks"]:
            issues.append("Search corpus has not been built")
        if not counts["relationships"]:
            issues.append("Verified relationship graph has not been loaded")
        counts["verified_relationships"] = conn.execute(
            "SELECT count(*) FROM relationships WHERE lower(source) <> lower('Yahoo Finance Market Data Analysis')"
        ).fetchone()[0]
        if not counts["market_events"]:
            warnings.append("No market anomalies meet the configured thresholds; this is not missing data")
        elif not counts["event_news"]:
            warnings.append("Detected events have no matching news evidence; catalysts remain unconfirmed")
    finally:
        conn.close()
    return {
        "status": "ready" if not issues else "degraded",
        "checked_on": today.isoformat(), "issues": issues, "warnings": warnings,
        "coverage": coverage, "counts": counts,
        "latest_stellantis_news": latest_news.isoformat() if latest_news else None,
    }