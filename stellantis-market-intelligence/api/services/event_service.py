"""Event service (Phase 24) - events + their business/market impact.

The "impact" view combines Phase 13 (business+stock profile) with Phase 22 (ecosystem
exposure score) for every company connected to STLA, for one specific event.
"""

from __future__ import annotations

from typing import Any

from storage.repository import get_event, list_events


def get_all_events(ticker: str = "STLA") -> list[dict[str, Any]]:
    return list_events(ticker=ticker)


def get_event_by_id(event_id: str) -> dict[str, Any] | None:
    return get_event(event_id)


def get_event_timeline(event_id: str, db_path=None) -> dict[str, Any] | None:
    from datetime import timedelta
    from analytics.benchmark import load_benchmarks
    from analytics.event_study import DEFAULT_OFFSETS
    from storage.duckdb import get_connection
    from storage.load_companies import load_companies_config

    conn = get_connection(db_path)
    try:
        cursor = conn.execute("SELECT * FROM market_events WHERE event_id = ?", [event_id])
        record = cursor.fetchone()
        if record is None:
            return None
        event = dict(zip([column[0] for column in cursor.description], record))
        event_date = event["event_date"]
        benchmark_tickers = [value["ticker"] for value in load_benchmarks().values()]
        tickers = list(dict.fromkeys([event["ticker"], *benchmark_tickers, "F", "GM", "QCOM"]))
        prices = []
        for ticker in tickers:
            rows = conn.execute(
                """WITH daily AS (
                    SELECT date, close, adj_close / lag(adj_close) OVER (ORDER BY date) - 1 AS daily_return
                    FROM price_data WHERE ticker = ? AND interval = '1d'
                ) SELECT date, close, daily_return FROM daily WHERE date BETWEEN ? AND ? ORDER BY date""",
                [ticker, event_date - timedelta(days=15), event_date + timedelta(days=15)],
            ).fetchall()
            prices.extend({"date": str(row[0]), "ticker": ticker, "close": row[1], "daily_return": row[2]} for row in rows)
        cursor = conn.execute(
            '''SELECT n.title, n.source, n.url, n."timestamp" AS published_at, n.source_kind,
                      n.retrieved_at, n.timestamp_status, en.relevance_rank, en.relevance_score,
                      date_diff('day', CAST(n."timestamp" AS DATE), ?) AS days_before_event
               FROM event_news en JOIN news n ON n.article_id = en.article_id
               WHERE en.event_id = ? AND n."timestamp" <= CURRENT_TIMESTAMP
               ORDER BY n."timestamp", en.relevance_rank''', [event_date, event_id],
        )
        columns = [column[0] for column in cursor.description]
        publications = [dict(zip(columns, row)) for row in cursor.fetchall()]
        for publication in publications:
            publication["match_reason"] = "Issuer mention and publication proximity; ranking may include topic keywords"
        available_after = conn.execute(
            "SELECT count(*) FROM price_data WHERE ticker = ? AND interval = '1d' AND date > ?",
            [event["ticker"], event_date],
        ).fetchone()[0]
        windows = []
        for company in load_companies_config():
            observed = {
                row[0] for row in conn.execute(
                    "SELECT day_offset FROM event_returns WHERE event_id = ? AND ticker = ? AND isfinite(cumulative_return)",
                    [event_id, company.ticker],
                ).fetchall()
            }
            missing = [offset for offset in DEFAULT_OFFSETS if offset not in observed]
            pending = [offset for offset in missing if offset > available_after]
            windows.append({
                "ticker": company.ticker, "observed": len(observed), "expected": len(DEFAULT_OFFSETS),
                "missing_offsets": missing, "pending_offsets": pending,
                "status": "complete" if not missing else "not_yet_observable" if missing == pending else "incomplete",
            })
        return {
            "event_id": event_id, "event_date": str(event_date),
            "prices": sorted(prices, key=lambda row: (row["date"], row["ticker"])),
            "publications": publications, "windows": windows,
            "interpretation": "Publication proximity and peer co-movement are associations, not proof of causation.",
        }
    finally:
        conn.close()


def get_event_impact(event_id: str) -> dict[str, Any] | None:
    event = get_event(event_id)
    if event is None:
        return None

    from ai.agent import gather_affected_companies
    from relationships.exposure_score import compute_all_exposure_scores
    from relationships.graph import build_graph

    graph = build_graph()
    affected = gather_affected_companies(event_id)
    scores_by_entity = {s["entity_id"]: s for s in compute_all_exposure_scores(graph, event_type=event["event_type"])}

    impact = [
        {**company, "ecosystem_exposure_score": scores_by_entity.get(company["entity_id"], {}).get("ecosystem_exposure_score")}
        for company in affected
    ]
    impact.sort(key=lambda c: c["ecosystem_exposure_score"] or 0, reverse=True)
    return {"event": event, "impact": impact}
