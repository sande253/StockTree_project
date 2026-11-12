"""Evidence-grounded chat answers and deterministic investigation visuals."""

from __future__ import annotations

import json
import re
from datetime import timedelta
from typing import Any

from ai.rag import RagConfigError, answer_question
from api.services import event_service, price_service, relationship_service
from storage.duckdb import get_connection
from storage.repository import list_companies, list_events

RELATIONSHIP_TERMS = re.compile(r"relationship|supplier|partner|brand|connected|network|ownership", re.I)
IMPACT_TERMS = re.compile(r"impact|affected|exposure|sensitive|reaction|investigate|rank", re.I)
HISTORY_TERMS = re.compile(r"similar|historical|history|previous|past event", re.I)
CORRELATION_TERMS = re.compile(r"correlation|correlated|beta|r-squared|statistical|co-mov|move together", re.I)
PRICE_TERMS = re.compile(r"price|close|trading|return|volatility|drawdown|trend|performance", re.I)
NEWS_TERMS = re.compile(r"why|catalyst|news|announcement|reason|recall|earnings|production|press release", re.I)
COMPANY_TERMS = re.compile(r"company|companies|ticker|universe|track|competitor|supplier", re.I)


def _source(document_type: str, source: str, text: str, company: str | None = None, url: str | None = None) -> dict[str, Any]:
    return {
        "document_type": document_type,
        "source": source,
        "text": text[:1400],
        "company": company,
        "url": url,
        "score": 1.0,
    }


def _matching_tickers(question_context: str, companies: list[dict[str, Any]]) -> list[str]:
    matches = []
    for company in companies:
        ticker = company["ticker"]
        name = company.get("company_name", "")
        aliases = [ticker, ticker.split(".")[0]]
        name_parts = name.split()
        if name_parts:
            aliases.extend((name_parts[0], " ".join(name_parts[:2])))
        if any(
            re.search(rf"(?<![\w]){re.escape(alias)}(?![\w])", question_context, re.IGNORECASE)
            for alias in aliases
            if alias
        ):
            matches.append(ticker)
    return matches


def _correlation_sources(tickers: list[str]) -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        where = "AND c.ticker IN (" + ",".join("?" for _ in tickers) + ")" if tickers else ""
        rows = conn.execute(
            f"""
            SELECT c.ticker, co.company_name, c.pearson_correlation, c.pearson_p_value,
                   c.pearson_ci_low, c.pearson_ci_high, c.spearman_correlation,
                   c.beta, c.r_squared, c.sample_size
            FROM correlations c LEFT JOIN companies co ON co.ticker = c.ticker
            WHERE c.reference_ticker = 'STLA' {where}
            ORDER BY abs(c.pearson_correlation) DESC NULLS LAST
            LIMIT 8
            """,
            tickers,
        ).fetchall()
    finally:
        conn.close()

    if not rows and tickers:
        return [_source(
            "statistical_relationship_availability",
            "Stored correlation analysis",
            f"No stored correlation profile is available for {', '.join(tickers)} vs STLA. "
            "A profile requires enough overlapping daily return observations.",
        )]
    sources = []
    for row in rows:
        source = _source(
            "statistical_relationship",
            "Stored daily-return correlation analysis",
            f"{row[1] or row[0]} ({row[0]}) vs STLA: Pearson r={row[2]}, p={row[3]}, "
            f"95% CI=[{row[4]}, {row[5]}], Spearman rho={row[6]}, beta={row[7]}, "
            f"R-squared={row[8]}, sample size n={row[9]}. This is historical co-movement, "
            "not evidence of a business relationship or causation.",
            company=row[0],
        )
        source["correlation"] = row[2]
        sources.append(source)
    return sources


def _news_sources(event: dict[str, Any] | None, tickers: list[str]) -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        rows = []
        if event:
            rows = conn.execute(
                '''
                SELECT n.title, n.source, n."timestamp", n.url, n.summary
                FROM event_news e JOIN news n ON n.article_id = e.article_id
                WHERE e.event_id = ? ORDER BY e.relevance_rank LIMIT 6
                ''',
                [event["event_id"]],
            ).fetchall()
            if not rows:
                event_date = event["event_date"]
                rows = conn.execute(
                    '''
                    SELECT title, source, "timestamp", url, summary
                    FROM news
                    WHERE mentioned_companies LIKE '%STLA%'
                      AND CAST("timestamp" AS DATE) BETWEEN ? AND ?
                    ORDER BY ABS(DATE_DIFF('day', CAST("timestamp" AS DATE), ?)) LIMIT 6
                    ''',
                    [event_date - timedelta(days=7), event_date + timedelta(days=7), event_date],
                ).fetchall()
        elif tickers:
            clauses = " OR ".join("mentioned_companies LIKE '%' || ? || '%'" for _ in tickers)
            rows = conn.execute(
                f'''SELECT title, source, "timestamp", url, summary FROM news
                    WHERE {clauses} ORDER BY "timestamp" DESC LIMIT 6''',
                tickers,
            ).fetchall()
    finally:
        conn.close()

    return [
        _source(
            "news_article",
            f"{row[1]} · {row[2]}",
            f"{row[0]}. {row[4] or ''}",
            url=row[3],
        )
        for row in rows
    ]


def _price_data(ticker: str) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    prices = [row for row in price_service.get_prices(ticker) if row.get("close") is not None][-60:]
    points = [
        {
            "date": row["date"].strftime("%Y-%m-%d") if hasattr(row["date"], "strftime") else str(row["date"]),
            "close": float(row["close"]),
        }
        for row in prices
    ]
    if not points:
        return points, None
    change_pct = (points[-1]["close"] / points[0]["close"] - 1) * 100 if points[0]["close"] else None
    text = (
        f"{ticker} stored daily closing prices from {points[0]['date']} through {points[-1]['date']}; "
        f"first close={points[0]['close']:.2f}, latest close={points[-1]['close']:.2f}, "
        f"period change={change_pct:.2f}% across {len(points)} observations. "
        "These are historical stored prices, not real-time quotes or forecasts."
    )
    return points, _source("stored_price_history", "DuckDB daily market prices", text, company=ticker)


def _price_visual(ticker: str, points: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "type": "line",
        "title": f"{ticker} stored daily closing prices",
        "unit": "price",
        "labels": [point["date"] for point in points],
        "values": [point["close"] for point in points],
    }


def _correlation_visual(sources: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [source for source in sources if source.get("document_type") == "statistical_relationship"]
    return {
        "type": "bars",
        "title": "Historical Pearson correlation vs STLA · not causation",
        "unit": "correlation",
        "labels": [source.get("company", "Unknown") for source in rows],
        "values": [float(source["correlation"]) for source in rows if source.get("correlation") is not None],
    }


def get_coverage() -> dict[str, Any]:
    """Small, truthful summary of the indexed data available to the copilot."""
    from ingestion.news import DEFAULT_CONFIG_PATH, load_sources
    import yaml

    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM news),
                (SELECT CAST(MAX("timestamp") AS DATE) FROM news),
                (SELECT COUNT(*) FROM market_events WHERE ticker = 'STLA'),
                (SELECT COUNT(*) FROM event_news),
                (SELECT COUNT(*) FROM relationships
                    WHERE lower(source) <> lower('Yahoo Finance Market Data Analysis')),
                (SELECT COUNT(*) FROM documents)
            """
        ).fetchone()
    finally:
        conn.close()
    return {
        "news_articles": row[0],
        "latest_news_date": row[1].isoformat() if row[1] else None,
        "events": row[2],
        "event_news_links": row[3],
        "verified_relationships": row[4],
        "indexed_documents": row[5],
        "configured_feeds": len(load_sources()),
        "unavailable_feeds": [
            f"{source.get('name', 'Unknown source')}: {source.get('unavailable_reason', 'not currently available')}"
            for source in (yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8")) or {}).get("sources", [])
            if source.get("enabled") is False
        ],
    }


def _relationship_visual(relationships: list[dict[str, Any]]) -> dict[str, Any]:
    nodes = [{"id": "STLA", "label": "Stellantis"}]
    edges = []
    for relationship in relationships:
        target = relationship.get("target_entity")
        if not target:
            continue
        nodes.append({"id": target, "label": target})
        edges.append({
            "source": "STLA",
            "target": target,
            "type": relationship.get("relationship_type", "documented"),
            "url": relationship.get("evidence_url"),
        })
    return {"type": "network", "title": "Verified relationship graph", "nodes": nodes, "edges": edges}


def _event_visual(event: dict[str, Any] | None) -> dict[str, Any]:
    if event is None:
        return {"type": "empty", "title": "Event context", "message": "Select an event to view its stored market context."}
    labels = ["STLA"]
    values = [event.get("return")]
    for label, key in (("Broad market", "market_return"), ("Automotive sector", "sector_return")):
        value = event.get(key)
        if value is not None:
            labels.append(label)
            values.append(value)
    return {
        "type": "bars",
        "title": "Event-day return comparison",
        "unit": "percent",
        "labels": labels,
        "values": [round(float(value) * 100, 3) for value in values],
    }


def _impact_visual(impact: list[dict[str, Any]]) -> dict[str, Any]:
    ranked = [row for row in impact if isinstance(row.get("ecosystem_exposure_score"), (int, float))]
    ranked = sorted(ranked, key=lambda row: row["ecosystem_exposure_score"], reverse=True)[:8]
    return {
        "type": "bars",
        "title": "Documented entities by exposure score",
        "unit": "score",
        "labels": [row["name"] for row in ranked],
        "values": [float(row["ecosystem_exposure_score"]) for row in ranked],
    }


def _history_visual(similar: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "type": "bars",
        "title": "Historical similarity (observed, not predictive)",
        "unit": "percent",
        "labels": [row["event_id"] for row in similar],
        "values": [float(row["similarity"]) for row in similar],
    }


def ask(question: str, event_id: str | None = None, history: list[dict[str, str]] | None = None) -> dict[str, Any] | None:
    """Answer from retrieved documents plus the relevant structured warehouse records."""
    event = event_service.get_event_by_id(event_id) if event_id else None
    if event_id and event is None:
        return None

    history = history or []
    question_context = " ".join(
        [turn["content"] for turn in history[-6:] if turn["role"] == "user"] + [question]
    )
    companies = list_companies()
    tickers = _matching_tickers(question_context, companies)
    context_sources: list[dict[str, Any]] = []
    if event:
        event_context = {
            key: event.get(key)
            for key in (
                "event_id", "event_date", "ticker", "return", "event_type", "event_description",
                "severity", "direction", "market_return", "sector_return", "classification",
            )
        }
        context_sources.append(_source(
            "market_event",
            "Stored market event record",
            json.dumps(event_context, default=str),
            company=event.get("ticker", "STLA"),
        ))

    if COMPANY_TERMS.search(question_context) or tickers:
        selected_companies = [company for company in companies if not tickers or company["ticker"] in tickers]
        company_text = "\n".join(
            f"{company['company_name']} ({company['ticker']}): sector={company.get('sector')}; "
            f"industry={company.get('industry')}; country={company.get('country')}; "
            f"universe category={company.get('relationship_type')}."
            for company in selected_companies
        )
        context_sources.append(_source(
            "company_universe",
            "Configured company universe",
            f"Tracked market-data companies ({len(selected_companies)} shown): {company_text}. "
            "Universe categories organize market data; they do not establish a documented business relationship.",
        ))

    correlation_sources: list[dict[str, Any]] = []
    if CORRELATION_TERMS.search(question_context) or tickers:
        correlation_sources = _correlation_sources(tickers)
        context_sources.extend(correlation_sources)

    relationships: list[dict[str, Any]] = []
    impact: list[dict[str, Any]] = []
    similar: list[dict[str, Any]] = []

    if RELATIONSHIP_TERMS.search(question_context):
        relationships = relationship_service.get_all_relationships()
        for relationship in relationships:
            text = (
                f"{relationship.get('source_entity')} has a documented {relationship.get('relationship_type')} "
                f"relationship with {relationship.get('target_entity')}. "
                f"Description: {relationship.get('description') or 'not provided'}. "
                f"Evidence publisher: {relationship.get('source')}. Evidence URL: {relationship.get('evidence_url')}."
            )
            context_sources.append(_source(
                "documented_relationship",
                str(relationship.get("source", "Relationship evidence")),
                text,
                company=relationship.get("target_entity"),
                url=relationship.get("evidence_url"),
            ))
        types = sorted({str(row.get("relationship_type")) for row in relationships})
        context_sources.append(_source(
            "relationship_dataset_summary",
            "Current verified relationship graph",
            f"The current graph contains {len(relationships)} documented direct relationships of types: "
            f"{', '.join(types) if types else 'none'}. Relationship types absent from this list are not documented in the current dataset.",
        ))

    if IMPACT_TERMS.search(question_context) and event:
        impact_result = event_service.get_event_impact(event["event_id"]) or {}
        impact = impact_result.get("impact", [])
        for row in impact[:8]:
            text = (
                f"{row.get('name')} ({row.get('ticker') or 'no public ticker'}) has documented relationship "
                f"'{row.get('relationship_type')}' with Stellantis. Historical correlation: "
                f"{row.get('historical_correlation')}. Historical event sensitivity: "
                f"{row.get('historical_event_sensitivity')}. Current event reaction: "
                f"{row.get('current_event_reaction')}. Ecosystem exposure score: "
                f"{row.get('ecosystem_exposure_score')}. Evidence: {row.get('evidence_url')}."
            )
            context_sources.append(_source(
                "event_impact_profile",
                str(row.get("evidence_source") or "Stored relationship and market profile"),
                text,
                company=row.get("name"),
                url=row.get("evidence_url"),
            ))

    if HISTORY_TERMS.search(question_context) and event:
        from events.similarity import find_similar_events

        similar = find_similar_events(event["event_id"], top_n=5)
        for row in similar:
            context_sources.append(_source(
                "historical_event_similarity",
                "Stored historical event fingerprints",
                json.dumps(row, default=str),
                company="STLA",
            ))

    if NEWS_TERMS.search(question_context) or event:
        context_sources.extend(_news_sources(event, tickers))

    price_points: list[dict[str, Any]] = []
    price_ticker = tickers[0] if tickers else "STLA"
    if PRICE_TERMS.search(question_context):
        price_points, price_source = _price_data(price_ticker)
        if price_source:
            context_sources.append(price_source)
        else:
            context_sources.append(_source(
                "price_data_availability",
                "Stored market data",
                f"No price history is stored for {price_ticker}; market prices are data unavailable.",
                company=price_ticker,
            ))

    recent_events: list[dict[str, Any]] = []
    if re.search(r"latest|last|recent|events|compare", question_context, re.I):
        recent_events = list_events(ticker="STLA")[:8]
        if recent_events:
            context_sources.append(_source(
                "recent_market_events",
                "Stored STLA event history",
                "\n".join(
                    f"{row['event_date']}: {row.get('event_type') or 'Unclassified'}, "
                    f"return={row.get('return')}, market={row.get('market_return')}, "
                    f"sector={row.get('sector_return')}, event_id={row['event_id']}"
                    for row in recent_events
                ),
                company="STLA",
            ))

    try:
        response = answer_question(question, context_sources=context_sources[:28], history=history)
    except RagConfigError:
        response = {
            "answer": "**AI answer unavailable.** Configure the Groq service to enable generated responses. "
                      "The visual panel still shows deterministic values from the selected event and verified graph.",
            "sources": context_sources,
        }

    if HISTORY_TERMS.search(question_context):
        visual = _history_visual(similar)
    elif RELATIONSHIP_TERMS.search(question_context):
        visual = _relationship_visual(relationships)
    elif PRICE_TERMS.search(question_context) and price_points:
        visual = _price_visual(price_ticker, price_points)
    elif CORRELATION_TERMS.search(question_context):
        visual = _correlation_visual(correlation_sources)
    elif IMPACT_TERMS.search(question_context) and event:
        visual = _impact_visual(impact)
    else:
        visual = _event_visual(event)

    return {
        "answer": response.get("answer") or "**Data unavailable.** The AI service returned an empty response.",
        "sources": response.get("sources", []),
        "visual": visual,
        "event_id": event_id,
    }
