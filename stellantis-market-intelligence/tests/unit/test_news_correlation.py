"""Phase 10 - News/Event Correlation tests."""

from __future__ import annotations

from datetime import date, datetime, timezone

import duckdb
import pandas as pd
import pytest

from events.news_correlation import (
    build_catalyst_summary,
    correlate_event_news_and_store,
    load_events_needing_correlation,
    persist_event_news,
    rank_articles_for_event,
)

RULES = {"Production": ["production cut", "plant shutdown"]}


def _insert_news(db_path, *, article_id, title, mentioned, timestamp, source="Test Source", summary=None):
    from storage.duckdb import get_connection

    get_connection(db_path).close()  # ensure schema exists
    conn = duckdb.connect(str(db_path))
    try:
        conn.execute(
            'INSERT INTO news (article_id, title, source, "timestamp", url, summary, mentioned_companies) '
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [article_id, title, source, timestamp, f"https://example.com/{article_id}", summary or title, mentioned],
        )
    finally:
        conn.close()


def test_rank_articles_for_event_scores_keyword_and_proximity_matches(tmp_path):
    db_path = tmp_path / "test.duckdb"
    _insert_news(
        db_path,
        article_id="near-topical",
        title="Stellantis announces a production cut amid plant shutdown",
        mentioned="STLA",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    _insert_news(
        db_path,
        article_id="far-generic",
        title="Stellantis holds investor call",
        mentioned="STLA",
        timestamp=datetime(2026, 1, 4, tzinfo=timezone.utc),
    )

    ranked = rank_articles_for_event("STLA", date(2026, 1, 1), "Production", rules=RULES, db_path=db_path)

    assert list(ranked["article_id"]) == ["near-topical", "far-generic"]
    assert ranked.iloc[0]["keyword_matches"] == 2
    assert ranked.iloc[0]["relevance_score"] > ranked.iloc[1]["relevance_score"]


def test_rank_articles_for_event_returns_empty_frame_when_no_news(tmp_path):
    db_path = tmp_path / "test.duckdb"
    from storage.duckdb import get_connection

    get_connection(db_path).close()
    ranked = rank_articles_for_event("STLA", date(2026, 1, 1), None, db_path=db_path)
    assert ranked.empty


def test_persist_event_news_round_trip(tmp_path):
    db_path = tmp_path / "test.duckdb"
    _insert_news(
        db_path, article_id="a1", title="Stellantis news", mentioned="STLA",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    ranked = rank_articles_for_event("STLA", date(2026, 1, 1), None, db_path=db_path)

    inserted = persist_event_news("STLA-2026-01-01", ranked, db_path=db_path)
    assert inserted == 1

    conn = duckdb.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT relevance_rank FROM event_news WHERE event_id = 'STLA-2026-01-01' AND article_id = 'a1'"
        ).fetchone()
    finally:
        conn.close()
    assert row[0] == 1


def test_build_catalyst_summary_uses_hedged_wording_with_articles():
    ranked = pd.DataFrame(
        {
            "article_id": ["a1"],
            "title": ["Stellantis announces production cut"],
            "source": ["Example Source"],
            "relevance_score": [2.5],
        }
    )
    summary = build_catalyst_summary("STLA-2026-01-01", date(2026, 1, 1), "STLA", -0.08, "Production", ranked)

    assert "possible catalyst" in summary["potential_catalyst"]
    assert "Example Source" in summary["supporting_sources"][0]
    assert summary["event_type"] == "Production"


def test_build_catalyst_summary_handles_no_evidence_without_fabricating():
    summary = build_catalyst_summary(
        "STLA-2026-01-01", date(2026, 1, 1), "STLA", -0.08, None, pd.DataFrame()
    )
    assert summary["potential_catalyst"] == "No documented explanation found in ingested news sources."
    assert summary["supporting_sources"] == []
    assert summary["event_type"] == "Other"


def test_correlate_event_news_and_store_persists_links_and_skips_already_linked(tmp_path):
    db_path = tmp_path / "test.duckdb"
    from storage.duckdb import get_connection

    conn = get_connection(db_path)
    conn.execute(
        """
        INSERT INTO market_events
            (event_id, event_date, ticker, "return", severity, direction, detection_method, combined_score, event_type)
        VALUES ('STLA-2026-01-01', '2026-01-01', 'STLA', -0.08, 'high', 'negative', 'absolute_return', 0.25, 'Production')
        """
    )
    conn.close()
    _insert_news(
        db_path,
        article_id="a1",
        title="Stellantis announces a production cut",
        mentioned="STLA",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    summaries = correlate_event_news_and_store("STLA", db_path=db_path)
    assert len(summaries) == 1
    assert summaries[0]["event_id"] == "STLA-2026-01-01"
    assert "possible catalyst" in summaries[0]["potential_catalyst"]

    # Second run must not re-process the already-linked event.
    pending = load_events_needing_correlation("STLA", db_path=db_path)
    assert pending.empty
