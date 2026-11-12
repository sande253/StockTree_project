"""News/Event correlation - search, rank, and link news to STLA events (Phase 10).

For every significant event (Phase 4 `market_events`, optionally classified by Phase 9):
1. Search news around the event date (reuses Phase 9's `find_nearby_news`).
2. Rank candidate articles by relevance (topical keyword overlap + time proximity).
3. Persist the ranked links as evidence (`event_news`).
4. Build a hedged, evidence-only "potential catalyst" narrative for human/report consumption.

This module never claims an article *caused* a price movement. Output wording always
uses hedged phrasing ("associated with", "possible catalyst", "occurred around",
"documented explanation") per the master prompt's non-negotiable analytical principles.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from events.classifier import DEFAULT_CONFIG_PATH, find_nearby_news, load_classification_rules

DEFAULT_WINDOW_DAYS = 5
MAX_SUPPORTING_SOURCES = 3


def _keyword_match_count(text: str, keywords: list[str]) -> int:
    text_lower = (text or "").lower()
    return sum(1 for kw in keywords if kw in text_lower)


def rank_articles_for_event(
    ticker: str,
    event_date: Any,
    event_type: str | None,
    rules: dict[str, list[str]] | None = None,
    window_days: int = DEFAULT_WINDOW_DAYS,
    db_path: Path | str | None = None,
) -> pd.DataFrame:
    """Rank nearby news articles by relevance to one event.

    relevance_score = topical keyword overlap (for the event's classified category, if any)
    + a time-proximity bonus that favors articles published closer to the event date.
    Returns an empty DataFrame if no nearby articles are found.
    """
    articles = find_nearby_news(ticker, event_date, window_days=window_days, db_path=db_path)
    if articles.empty:
        return articles

    rules = rules if rules is not None else load_classification_rules()
    keywords = rules.get(event_type, []) if event_type else []

    days_offset = []
    keyword_matches = []
    relevance_scores = []
    for row in articles.itertuples(index=False):
        article_date = pd.Timestamp(row.timestamp).date() if pd.notna(row.timestamp) else event_date
        offset = (article_date - event_date).days
        matches = _keyword_match_count(f"{row.title} {row.summary or ''}", keywords)
        proximity_bonus = 1.0 / (1.0 + abs(offset))
        days_offset.append(offset)
        keyword_matches.append(matches)
        relevance_scores.append(matches + proximity_bonus)

    ranked = articles.copy()
    ranked["days_offset"] = days_offset
    ranked["keyword_matches"] = keyword_matches
    ranked["relevance_score"] = relevance_scores
    return ranked.sort_values("relevance_score", ascending=False).reset_index(drop=True)


def persist_event_news(event_id: str, ranked_articles: pd.DataFrame, db_path: Path | str | None = None) -> int:
    """Upsert the ranked (article -> event) evidence links into `event_news`."""
    from storage.duckdb import get_connection

    if ranked_articles.empty:
        return 0

    links = pd.DataFrame(
        {
            "event_id": event_id,
            "article_id": ranked_articles["article_id"],
            "relevance_rank": range(1, len(ranked_articles) + 1),
            "relevance_score": ranked_articles["relevance_score"],
        }
    )

    conn = get_connection(db_path)
    try:
        conn.register("event_news_rows", links)
        conn.execute(
            """
            INSERT INTO event_news (event_id, article_id, relevance_rank, relevance_score)
            SELECT event_id, article_id, relevance_rank, relevance_score FROM event_news_rows
            ON CONFLICT (event_id, article_id) DO UPDATE SET
                relevance_rank = excluded.relevance_rank,
                relevance_score = excluded.relevance_score
            """
        )
        conn.unregister("event_news_rows")
        return len(links)
    finally:
        conn.close()


def build_catalyst_summary(
    event_id: str,
    event_date: Any,
    ticker: str,
    movement: float,
    event_type: str | None,
    ranked_articles: pd.DataFrame,
) -> dict[str, Any]:
    """Build a hedged, evidence-only narrative summary for one event. Never asserts causation."""
    if ranked_articles.empty:
        return {
            "event_id": event_id,
            "event_date": event_date,
            "ticker": ticker,
            "movement": movement,
            "event_type": event_type or "Other",
            "potential_catalyst": "No documented explanation found in ingested news sources.",
            "supporting_sources": [],
        }

    top = ranked_articles.iloc[0]
    supporting = ranked_articles.head(MAX_SUPPORTING_SOURCES)
    return {
        "event_id": event_id,
        "event_date": event_date,
        "ticker": ticker,
        "movement": movement,
        "event_type": event_type or "Other",
        "potential_catalyst": (
            f"A possible catalyst associated with this movement, documented in news that occurred "
            f"around the event date, is: {top['title']!r} ({top['source']})."
        ),
        "supporting_sources": [f"{row.source}: {row.title}" for row in supporting.itertuples(index=False)],
    }


def load_events_needing_correlation(ticker: str, db_path: Path | str | None = None) -> pd.DataFrame:
    """Load `market_events` for `ticker` that do not yet have any `event_news` links."""
    from storage.duckdb import get_connection, normalize_date_column

    conn = get_connection(db_path)
    try:
        df = conn.execute(
            """
            SELECT m.event_id, m.event_date, m.ticker, m."return" AS movement, m.event_type
            FROM market_events m
            LEFT JOIN event_news n ON n.event_id = m.event_id
            WHERE m.ticker = ? AND n.event_id IS NULL
            ORDER BY m.event_date
            """,
            [ticker],
        ).fetchdf()
    finally:
        conn.close()
    return normalize_date_column(df, column="event_date")


def correlate_event_news_and_store(
    ticker: str,
    window_days: int = DEFAULT_WINDOW_DAYS,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    db_path: Path | str | None = None,
) -> list[dict[str, Any]]:
    """Full Phase 10 pipeline for one ticker: find pending events -> rank -> persist -> summarize."""
    rules = load_classification_rules(config_path)
    pending = load_events_needing_correlation(ticker, db_path=db_path)

    summaries: list[dict[str, Any]] = []
    for row in pending.itertuples(index=False):
        ranked = rank_articles_for_event(
            ticker, row.event_date, row.event_type, rules=rules, window_days=window_days, db_path=db_path
        )
        persist_event_news(row.event_id, ranked, db_path=db_path)
        summaries.append(
            build_catalyst_summary(row.event_id, row.event_date, ticker, row.movement, row.event_type, ranked)
        )
    return summaries
