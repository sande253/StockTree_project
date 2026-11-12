"""Rule-based STLA event classification (Phase 9 - Event Classification).

Classifies already-detected price-movement events (Phase 4 `market_events`) into a
business category - Earnings, Production, Factory, Supply Chain, Partnership,
Acquisition, Recall, Regulation, EV Strategy, Battery, Technology, Management,
Labor, Geopolitical, Macro, Product Launch, Other - using keyword rules applied to
the nearest ingested news article (Phase 8 `news`) mentioning the ticker around the
event date. This is intentionally a single best-match classification; ranking
multiple candidate articles and extracting a worded "potential catalyst" is Phase 10
(News/Event Correlation). A future phase may let a local/hosted LLM assist this
rule-based pass, but it is not required for Phase 9.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

DEFAULT_CONFIG_PATH = Path("config/event_rules.yaml")
FALLBACK_CATEGORY = "Other"
DEFAULT_WINDOW_DAYS = 3

# Order defines keyword-match tie-breaking: the earlier category wins ties.
DEFAULT_CATEGORIES: list[str] = [
    "Earnings",
    "Production",
    "Factory",
    "Supply Chain",
    "Partnership",
    "Acquisition",
    "Recall",
    "Regulation",
    "EV Strategy",
    "Battery",
    "Technology",
    "Management",
    "Labor",
    "Geopolitical",
    "Macro",
    "Product Launch",
]


def load_classification_rules(config_path: Path | str = DEFAULT_CONFIG_PATH) -> dict[str, list[str]]:
    """Load {category: [keyword, ...]} from YAML, preserving the configured category order."""
    path = Path(config_path)
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    configured = raw.get("classification_keywords") or {}
    return {category: [str(k).lower() for k in keywords or []] for category, keywords in configured.items()}


def classify_text(text: str, rules: dict[str, list[str]]) -> tuple[str, list[str]]:
    """Return (category, matched_keywords) for free text, or (FALLBACK_CATEGORY, []) if nothing matches."""
    text_lower = (text or "").lower()
    best_category = FALLBACK_CATEGORY
    best_matches: list[str] = []
    for category in rules:
        matches = [kw for kw in rules[category] if kw in text_lower]
        if len(matches) > len(best_matches):
            best_category = category
            best_matches = matches
    return best_category, best_matches


def find_nearby_news(
    ticker: str,
    event_date: date,
    window_days: int = DEFAULT_WINDOW_DAYS,
    db_path: Path | str | None = None,
) -> pd.DataFrame:
    """Load news articles mentioning `ticker` within `window_days` of `event_date`, closest first."""
    from storage.duckdb import get_connection

    start = event_date - timedelta(days=window_days)
    end = event_date + timedelta(days=window_days)

    conn = get_connection(db_path)
    try:
        df = conn.execute(
            """
            SELECT article_id, title, source, "timestamp", summary
            FROM news
                        WHERE list_contains(string_split(mentioned_companies, ','), ?)
              AND CAST("timestamp" AS DATE) BETWEEN ? AND ?
                            AND "timestamp" <= CURRENT_TIMESTAMP
                            AND coalesce(timestamp_status, 'unknown') NOT IN ('missing', 'future')
            ORDER BY ABS(DATE_DIFF('day', CAST("timestamp" AS DATE), ?))
            """,
            [ticker, start, end, event_date],
        ).fetchdf()
    finally:
        conn.close()
    return df


def classify_event(
    ticker: str,
    event_date: date,
    rules: dict[str, list[str]] | None = None,
    window_days: int = DEFAULT_WINDOW_DAYS,
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    """Classify one event: find the closest nearby article (if any) and run the keyword rules on it."""
    rules = rules if rules is not None else load_classification_rules()
    articles = find_nearby_news(ticker, event_date, window_days=window_days, db_path=db_path)

    if articles.empty:
        return {"event_type": FALLBACK_CATEGORY, "event_description": None, "news_source": None}

    best = articles.iloc[0]
    text = f"{best['title']} {best['summary'] or ''}"
    event_type, _matched = classify_text(text, rules)
    return {
        "event_type": event_type,
        "event_description": best["title"],
        "news_source": best["source"],
    }


def load_unclassified_events(ticker: str, db_path: Path | str | None = None) -> pd.DataFrame:
    """Load unclassified events and uncited fallback labels that new news can improve."""
    from storage.duckdb import get_connection, normalize_date_column

    conn = get_connection(db_path)
    try:
        df = conn.execute(
            """
            SELECT event_id, event_date
            FROM market_events
                        WHERE ticker = ?
                            AND (event_type IS NULL OR (event_type = 'Other' AND news_source IS NULL))
            ORDER BY event_date
            """,
            [ticker],
        ).fetchdf()
    finally:
        conn.close()
    return normalize_date_column(df, column="event_date")


def persist_classification(
    event_id: str, classification: dict[str, Any], db_path: Path | str | None = None
) -> None:
    """Write the classification result back onto the matching `market_events` row."""
    from storage.duckdb import get_connection

    conn = get_connection(db_path)
    try:
        conn.execute(
            """
            UPDATE market_events
            SET event_type = ?, event_description = ?, news_source = ?
            WHERE event_id = ?
            """,
            [
                classification["event_type"],
                classification["event_description"],
                classification["news_source"],
                event_id,
            ],
        )
    finally:
        conn.close()


def classify_and_store_events(
    ticker: str,
    window_days: int = DEFAULT_WINDOW_DAYS,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    db_path: Path | str | None = None,
) -> int:
    """Full Phase 9 pipeline for one ticker: load unclassified events -> classify -> persist."""
    rules = load_classification_rules(config_path)
    pending = load_unclassified_events(ticker, db_path=db_path)

    for row in pending.itertuples(index=False):
        classification = classify_event(
            ticker, row.event_date, rules=rules, window_days=window_days, db_path=db_path
        )
        persist_classification(row.event_id, classification, db_path=db_path)

    return len(pending)
