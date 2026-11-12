"""Phase 8 - News Ingestion tests."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from ingestion.news import (
    deduplicate_articles,
    ingest_all_sources,
    load_sources,
    parse_feed,
    persist_articles,
)

TICKERS_BY_NAME = {"Stellantis N.V.": "STLA", "Stellantis": "STLA", "Ford Motor Company": "F"}

RSS_SAMPLE = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Example Feed</title>
    <item>
      <title>Stellantis N.V. announces new factory</title>
      <link>https://example.com/articles/1</link>
      <description>Stellantis N.V. said it will build a new plant.</description>
      <pubDate>Mon, 02 Jan 2026 10:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Unrelated market update</title>
      <link>https://example.com/articles/2</link>
      <description>General market commentary with no company mention.</description>
      <pubDate>Mon, 02 Jan 2026 11:00:00 GMT</pubDate>
    </item>
    <item>
      <title></title>
      <link></link>
      <description>Should be skipped - missing title/link.</description>
    </item>
  </channel>
</rss>
"""

ATOM_SAMPLE = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Example Atom Feed</title>
  <entry>
    <title>Ford Motor Company files annual report</title>
    <link href="https://example.com/filings/1" rel="alternate" type="text/html" />
    <summary>Ford Motor Company filed its 10-K.</summary>
    <updated>2026-01-03T12:00:00-05:00</updated>
  </entry>
</feed>
"""


def test_load_sources_returns_configured_feed():
    sources = load_sources()
    assert len(sources) >= 2
    assert any("sec.gov" in s["url"] for s in sources)
    assert any("CIK=1605484" in s["url"] and s.get("company_ticker") == "STLA" for s in sources)
    assert not any("stellantis.com/en/news/press-releases" in s["url"] for s in sources)


def test_parse_feed_handles_rss_items_with_mentions_and_skips_incomplete():
    articles = parse_feed(RSS_SAMPLE, "Example Feed", TICKERS_BY_NAME)
    assert len(articles) == 2  # the blank title/link item is skipped

    stla_article = next(a for a in articles if "Stellantis" in a["title"])
    assert stla_article["mentioned_companies"] == "STLA"
    assert stla_article["source"] == "Example Feed"
    assert stla_article["timestamp"] == datetime(2026, 1, 2, 10, 0, tzinfo=timezone.utc)

    unrelated = next(a for a in articles if "Unrelated" in a["title"])
    assert unrelated["mentioned_companies"] == ""


def test_parse_feed_maps_stellantis_alias_and_strips_embedded_html():
    feed = b"""<rss version='2.0'><channel><item>
      <title>Stellantis reports results</title><link>https://example.com/3</link>
      <description>Factory output <b>increased</b> in Europe.</description>
      <pubDate>Thu, 15 Oct 2026 14:00:00 +0200</pubDate>
    </item></channel></rss>"""

    article = parse_feed(feed, "Official release", TICKERS_BY_NAME)[0]

    assert article["mentioned_companies"] == "STLA"
    assert article["summary"] == "Factory output increased in Europe."


def test_parse_feed_handles_atom_entries():
    articles = parse_feed(ATOM_SAMPLE, "Example Atom Feed", TICKERS_BY_NAME)
    assert len(articles) == 1
    article = articles[0]
    assert article["url"] == "https://example.com/filings/1"
    assert article["mentioned_companies"] == "F"
    assert article["timestamp"].tzinfo is not None


def test_feed_rejects_javascript_urls_and_entity_expansion():
    from defusedxml.common import DefusedXmlException

    unsafe = b"<rss><channel><item><title>Unsafe</title><link>javascript:alert(1)</link></item></channel></rss>"
    assert parse_feed(unsafe, "test", {}) == []
    entities = b'<!DOCTYPE rss [<!ENTITY attack "expanded">]><rss><channel><item><title>&attack;</title></item></channel></rss>'
    with pytest.raises(DefusedXmlException):
        parse_feed(entities, "test", {})


def test_parse_feed_is_deterministic_for_dedup_key():
    first = parse_feed(RSS_SAMPLE, "Example Feed", TICKERS_BY_NAME)
    second = parse_feed(RSS_SAMPLE, "Example Feed", TICKERS_BY_NAME)
    assert [a["article_id"] for a in first] == [a["article_id"] for a in second]


def test_deduplicate_articles_drops_repeated_article_id():
    articles = parse_feed(RSS_SAMPLE, "Example Feed", TICKERS_BY_NAME)
    duplicated = articles + articles
    deduped = deduplicate_articles(duplicated)
    assert len(deduped) == len(articles)


def test_persist_articles_round_trip(tmp_path):
    db_path = tmp_path / "test.duckdb"
    articles = parse_feed(RSS_SAMPLE, "Example Feed", TICKERS_BY_NAME)

    inserted = persist_articles(articles, db_path=db_path)
    assert inserted == len(articles)

    # Re-persisting (e.g. a re-run) must not duplicate rows (idempotent upsert).
    inserted_again = persist_articles(articles, db_path=db_path)
    assert inserted_again == len(articles)

    import duckdb

    conn = duckdb.connect(str(db_path))
    try:
        count = conn.execute("SELECT COUNT(*) FROM news").fetchone()[0]
        assert count == len(articles)
    finally:
        conn.close()


def test_persist_articles_handles_empty_list(tmp_path):
    db_path = tmp_path / "empty.duckdb"
    assert persist_articles([], db_path=db_path) == 0


def test_ingest_all_sources_tags_issuer_specific_filings(tmp_path, monkeypatch):
  source_config = tmp_path / "sources.yaml"
  source_config.write_text(
    "sources:\n  - name: SEC issuer filings\n    url: https://example.com/feed\n    company_ticker: STLA\n",
    encoding="utf-8",
  )
  feed = b"""<feed xmlns='http://www.w3.org/2005/Atom'><entry>
    <title>6-K - Report of foreign issuer</title>
    <link href='https://example.com/filing' />
    <summary>Quarterly results exhibit</summary>
    <updated>2026-10-15T14:00:00Z</updated>
  </entry></feed>"""
  monkeypatch.setattr("ingestion.news.fetch_feed", lambda *_: feed)

  result = ingest_all_sources(config_path=source_config, db_path=tmp_path / "news.duckdb")

  from storage.duckdb import get_connection

  conn = get_connection(tmp_path / "news.duckdb")
  try:
    mentioned = conn.execute("SELECT mentioned_companies FROM news").fetchone()[0]
  finally:
    conn.close()
  assert result["articles_persisted"] == 1
  assert mentioned == "STLA"
  assert result["source_results"][0]["status"] == "succeeded"
  conn = get_connection(tmp_path / "news.duckdb")
  try:
    source_url, retrieved_at, checksum = conn.execute(
        "SELECT source_url, retrieved_at, content_sha256 FROM news"
    ).fetchone()
    assert source_url == "https://example.com/feed"
    assert retrieved_at is not None
    assert len(checksum) == 64
  finally:
    conn.close()
