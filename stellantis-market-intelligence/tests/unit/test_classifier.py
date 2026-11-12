"""Phase 9 - Event Classification tests."""

from __future__ import annotations

from datetime import date, datetime, timezone

import duckdb
import pytest

from events.classifier import (
    FALLBACK_CATEGORY,
    classify_and_store_events,
    classify_event,
    classify_text,
    find_nearby_news,
    load_classification_rules,
)

RULES = {
    "Production": ["production cut", "plant shutdown"],
    "Recall": ["recall", "safety defect"],
}


def test_classify_text_picks_category_with_most_keyword_matches():
    text = "Stellantis announces a production cut amid a plant shutdown at its factory"
    category, matched = classify_text(text, RULES)
    assert category == "Production"
    assert set(matched) == {"production cut", "plant shutdown"}


def test_classify_text_returns_fallback_when_no_keywords_match():
    category, matched = classify_text("Stellantis holds an investor meeting", RULES)
    assert category == FALLBACK_CATEGORY
    assert matched == []


def test_load_classification_rules_loads_configured_categories():
    rules = load_classification_rules()
    assert "Earnings" in rules
    assert "recall" in rules["Recall"]


def _insert_news(db_path, *, article_id, title, mentioned, timestamp, source="Test Source"):
    conn = duckdb.connect(str(db_path))
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS news "
                      '(article_id VARCHAR PRIMARY KEY, title VARCHAR, source VARCHAR, '
                      '"timestamp" TIMESTAMPTZ, url VARCHAR, summary VARCHAR, mentioned_companies VARCHAR)')
        conn.execute(
            'INSERT INTO news (article_id, title, source, "timestamp", url, summary, mentioned_companies) '
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [article_id, title, source, timestamp, f"https://example.com/{article_id}", title, mentioned],
        )
    finally:
        conn.close()


def test_find_nearby_news_filters_by_ticker_and_window(tmp_path):
    db_path = tmp_path / "test.duckdb"
    from storage.duckdb import get_connection

    get_connection(db_path).close()  # ensure full schema (incl. news table) exists

    _insert_news(
        db_path,
        article_id="a1",
        title="Stellantis announces production cut",
        mentioned="STLA",
        timestamp=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    _insert_news(
        db_path,
        article_id="a2",
        title="Ford unrelated news",
        mentioned="F",
        timestamp=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    _insert_news(
        db_path,
        article_id="a3",
        title="Stellantis news far away in time",
        mentioned="STLA",
        timestamp=datetime(2026, 2, 1, tzinfo=timezone.utc),
    )

    results = find_nearby_news("STLA", date(2026, 1, 1), window_days=3, db_path=db_path)
    assert list(results["article_id"]) == ["a1"]


def test_classify_event_uses_closest_matching_article(tmp_path):
    db_path = tmp_path / "test.duckdb"
    from storage.duckdb import get_connection

    get_connection(db_path).close()
    _insert_news(
        db_path,
        article_id="a1",
        title="Stellantis issues a vehicle recall over a safety defect",
        mentioned="STLA",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        source="Example Source",
    )

    result = classify_event("STLA", date(2026, 1, 1), db_path=db_path)
    assert result["event_type"] == "Recall"
    assert result["event_description"] == "Stellantis issues a vehicle recall over a safety defect"
    assert result["news_source"] == "Example Source"


def test_classify_event_falls_back_when_no_news_nearby(tmp_path):
    db_path = tmp_path / "test.duckdb"
    from storage.duckdb import get_connection

    get_connection(db_path).close()

    result = classify_event("STLA", date(2026, 1, 1), db_path=db_path)
    assert result == {"event_type": FALLBACK_CATEGORY, "event_description": None, "news_source": None}


def test_classify_and_store_events_persists_event_type(tmp_path):
    db_path = tmp_path / "test.duckdb"
    from storage.duckdb import get_connection

    conn = get_connection(db_path)
    conn.execute(
        """
        INSERT INTO market_events
            (event_id, event_date, ticker, "return", severity, direction, detection_method, combined_score)
        VALUES ('STLA-2026-01-01', '2026-01-01', 'STLA', -0.08, 'high', 'negative', 'absolute_return', 0.25)
        """
    )
    conn.close()
    _insert_news(
        db_path,
        article_id="a1",
        title="Stellantis announces a production cut at a European plant",
        mentioned="STLA",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    updated = classify_and_store_events("STLA", db_path=db_path)
    assert updated == 1

    conn = duckdb.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT event_type, event_description FROM market_events WHERE event_id = 'STLA-2026-01-01'"
        ).fetchone()
    finally:
        conn.close()
    assert row[0] == "Production"
    assert row[1] == "Stellantis announces a production cut at a European plant"


def test_classify_and_store_events_revisits_uncited_other_event(tmp_path):
    db_path = tmp_path / "test.duckdb"
    from storage.duckdb import get_connection

    conn = get_connection(db_path)
    conn.execute(
        """
        INSERT INTO market_events
            (event_id, event_date, ticker, "return", severity, direction, detection_method,
             combined_score, event_type)
        VALUES ('STLA-2026-01-01', '2026-01-01', 'STLA', -0.08, 'high', 'negative',
                'absolute_return', 0.25, 'Other')
        """
    )
    conn.close()
    _insert_news(
        db_path,
        article_id="a1",
        title="Stellantis announces a production cut at a European plant",
        mentioned="STLA",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert classify_and_store_events("STLA", db_path=db_path) == 1
    conn = duckdb.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT event_type, news_source FROM market_events WHERE event_id = 'STLA-2026-01-01'"
        ).fetchone()
    finally:
        conn.close()
    assert row == ("Production", "Test Source")
