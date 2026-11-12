"""Free/public news & filings ingestion (Phase 8).

Sources are configured in config/sources.yaml (RSS 2.0 and Atom feeds only -
"public company announcements / press releases / public financial-news sources
where permitted"). Implements deduplication, normalization, timestamp
normalization, and source tracking. A single failing source must not abort
ingestion of the others (see Phase 28 error handling).
"""

from __future__ import annotations

import hashlib
import html
import logging
import os
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from html.parser import HTMLParser

from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException
import yaml

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path("config/sources.yaml")
ATOM_NS = "{http://www.w3.org/2005/Atom}"
# SEC and similar providers require an identifying User-Agent on requests.
DEFAULT_USER_AGENT = "stellantis-market-intelligence research-prototype (local, no-reply@example.invalid)"


def _safe_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.hostname) and not parsed.username


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


class NewsIngestionError(RuntimeError):
    """Raised when a news source cannot be fetched after retries."""


def load_sources(config_path: Path | str = DEFAULT_CONFIG_PATH) -> list[dict[str, Any]]:
    """Load configured news/filings sources from YAML."""
    path = Path(config_path)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    return [source for source in (raw.get("sources", []) or []) if source.get("enabled", True)]


def _make_article_id(url: str, title: str) -> str:
    """Deterministic id (hash of url+title) - the dedup/idempotency key."""
    digest = hashlib.sha256(f"{url}|{title}".encode("utf-8")).hexdigest()
    return digest[:24]


def _parse_rfc822_timestamp(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_iso_timestamp(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _mentioned_companies(text: str, tickers_by_name: dict[str, str]) -> list[str]:
    """Match company names and explicit aliases without substring false positives."""
    return sorted({
        ticker
        for name, ticker in tickers_by_name.items()
        if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text, flags=re.IGNORECASE)
    })


def _clean_text(raw: str | None, max_len: int = 2000) -> str:
    parser = _HTMLTextExtractor()
    parser.feed(html.unescape(raw or ""))
    return " ".join(" ".join(parser.parts).split())[:max_len]


def parse_feed(xml_bytes: bytes, source_name: str, tickers_by_name: dict[str, str]) -> list[dict[str, Any]]:
    """Parse a feed (RSS 2.0 <item> or Atom <entry>) into normalized article dicts."""
    root = ET.fromstring(xml_bytes)
    articles: list[dict[str, Any]] = []

    for item in root.iter("item"):
        title = _clean_text(item.findtext("title"))
        link = (item.findtext("link") or "").strip()
        if not title or not _safe_url(link):
            continue
        description_element = item.find("description")
        description = _clean_text(
            "".join(description_element.itertext()) if description_element is not None else ""
        )
        timestamp = _parse_rfc822_timestamp(item.findtext("pubDate"))
        articles.append(_build_article(title, link, source_name, timestamp, description, tickers_by_name))

    for entry in root.iter(f"{ATOM_NS}entry"):
        title = _clean_text(entry.findtext(f"{ATOM_NS}title"))
        links = entry.findall(f"{ATOM_NS}link")
        link_el = next((link for link in links if link.get("rel", "alternate") == "alternate"), None)
        link = (link_el.get("href") or "").strip() if link_el is not None else ""
        if not title or not _safe_url(link):
            continue
        summary_element = entry.find(f"{ATOM_NS}summary")
        summary = _clean_text(
            "".join(summary_element.itertext()) if summary_element is not None else ""
        )
        timestamp = _parse_iso_timestamp(entry.findtext(f"{ATOM_NS}updated"))
        articles.append(_build_article(title, link, source_name, timestamp, summary, tickers_by_name))

    return articles


def _build_article(
    title: str,
    link: str,
    source_name: str,
    timestamp: datetime | None,
    summary: str,
    tickers_by_name: dict[str, str],
) -> dict[str, Any]:
    return {
        "article_id": _make_article_id(link, title),
        "title": title,
        "source": source_name,
        "timestamp": timestamp,
        "url": link,
        "summary": summary,
        "mentioned_companies": ",".join(_mentioned_companies(f"{title} {summary}", tickers_by_name)),
        "content_sha256": hashlib.sha256(f"{title}\n{summary}".encode("utf-8")).hexdigest(),
        "timestamp_status": "missing" if timestamp is None else (
            "future" if timestamp > datetime.now(timezone.utc) else "published"
        ),
    }


def fetch_feed(url: str, max_retries: int = 3, timeout_seconds: float = 10.0) -> bytes:
    """Download a feed's raw bytes, retrying transient failures."""
    import requests

    if not _safe_url(url):
        raise NewsIngestionError("Feed URL must use HTTP or HTTPS")
    headers = {"User-Agent": os.getenv("NEWS_USER_AGENT", DEFAULT_USER_AGENT)}
    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            response = requests.get(url, timeout=timeout_seconds, headers=headers)
            response.raise_for_status()
            return response.content
        except Exception as exc:  # noqa: BLE001 - any failure here is a retryable transport error
            last_error = exc
            logger.warning("Feed fetch attempt %d/%d failed for %s: %s", attempt, max_retries, url, exc)
            if attempt < max_retries:
                time.sleep(1.0 * attempt)
    raise NewsIngestionError(f"Failed to fetch feed {url!r} after {max_retries} attempts") from last_error


def deduplicate_articles(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop articles with a repeated `article_id` (same url+title), keeping the first."""
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for article in articles:
        if article["article_id"] in seen:
            continue
        seen.add(article["article_id"])
        deduped.append(article)
    return deduped


def persist_articles(articles: list[dict[str, Any]], db_path: Path | str | None = None) -> int:
    """Upsert normalized articles into the DuckDB `news` table."""
    import pandas as pd

    from storage.duckdb import get_connection

    if not articles:
        return 0

    df = pd.DataFrame(articles)
    for column, default in {
        "source_kind": "news", "source_url": None,
        "retrieved_at": datetime.now(timezone.utc), "content_sha256": None,
        "timestamp_status": "unknown",
    }.items():
        if column not in df:
            df[column] = default
    conn = get_connection(db_path)
    try:
        conn.register("news_rows", df)
        conn.execute(
            """
            INSERT INTO news
                (article_id, title, source, "timestamp", url, summary, mentioned_companies,
                 source_kind, source_url, retrieved_at, content_sha256, timestamp_status)
            SELECT article_id, title, source, "timestamp", url, summary, mentioned_companies,
                   source_kind, source_url, retrieved_at, content_sha256, timestamp_status
            FROM news_rows
            ON CONFLICT (article_id) DO UPDATE SET
                title = excluded.title,
                "timestamp" = excluded."timestamp",
                summary = excluded.summary,
                mentioned_companies = excluded.mentioned_companies,
                source_kind = excluded.source_kind,
                source_url = excluded.source_url,
                retrieved_at = excluded.retrieved_at,
                content_sha256 = excluded.content_sha256,
                timestamp_status = excluded.timestamp_status
            """
        )
        conn.unregister("news_rows")
        return len(df)
    finally:
        conn.close()


def ingest_all_sources(
    config_path: Path | str = DEFAULT_CONFIG_PATH, db_path: Path | str | None = None
) -> dict[str, Any]:
    """Full Phase 8 pipeline: fetch each configured source -> parse -> dedup -> persist.

    A single failing source is logged and skipped, never aborting the whole run.
    """
    from storage.load_companies import load_companies_config

    tickers_by_name = {c.company_name: c.ticker for c in load_companies_config()}
    tickers_by_name.update({"Stellantis": "STLA", "STLA": "STLA"})
    try:
        from relationships.graph import load_relationships_config

        tickers_by_name.update({
            relationship.target_entity: "STLA"
            for relationship in load_relationships_config()
            if relationship.target_entity_type == "brand"
        })
    except (KeyError, TypeError, ValueError):
        logger.warning("Could not load brand aliases for news mention detection", exc_info=True)
    sources = load_sources(config_path)

    all_articles: list[dict[str, Any]] = []
    failed_sources: list[str] = []
    source_results: list[dict[str, Any]] = []
    for source in sources:
        name = source.get("name", source.get("url", "unknown"))
        try:
            raw = fetch_feed(source["url"])
            articles = parse_feed(raw, name, tickers_by_name)
            for article in articles:
                article.update(
                    source_kind=source.get("kind", "filing" if "sec.gov" in source["url"] else "news"),
                    source_url=source["url"], retrieved_at=datetime.now(timezone.utc),
                )
            company_ticker = source.get("company_ticker")
            if company_ticker:
                for article in articles:
                    mentioned = set(filter(None, article["mentioned_companies"].split(",")))
                    mentioned.add(str(company_ticker))
                    article["mentioned_companies"] = ",".join(sorted(mentioned))
            all_articles.extend(articles)
            published = [article["timestamp"] for article in articles if article["timestamp"] is not None]
            source_results.append({
                "name": name, "url": source["url"], "status": "succeeded" if articles else "empty",
                "articles": len(articles), "latest_publication": max(published).isoformat() if published else None,
            })
        except (NewsIngestionError, ET.ParseError, DefusedXmlException) as exc:
            logger.warning("Skipping source %s: %s", name, exc)
            failed_sources.append(name)
            source_results.append({"name": name, "url": source.get("url"), "status": "failed", "articles": 0})

    deduped = deduplicate_articles(all_articles)
    inserted = persist_articles(deduped, db_path=db_path)
    return {
        "sources_configured": len(sources),
        "sources_failed": failed_sources,
        "articles_fetched": len(all_articles),
        "articles_after_dedup": len(deduped),
        "articles_persisted": inserted,
        "source_results": source_results,
    }
