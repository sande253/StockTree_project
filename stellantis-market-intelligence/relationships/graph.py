"""Corporate relationship graph construction (Phase 11).

Loads evidence-backed relationships (config/relationships.yaml or the DuckDB
`relationships` table), persists them, and builds a NetworkX directed graph centered
on Stellantis. Every relationship MUST carry a real `source` and `evidence_url` -
this is enforced here, not left to convention. Never fabricate a relationship.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import networkx as nx
import pandas as pd
import yaml

from relationships.entities import STELLANTIS_ENTITY_ID
from storage.schemas import VALID_CONFIDENCE_LEVELS, VALID_ENTITY_TYPES, VALID_GRAPH_RELATIONSHIP_TYPES

DEFAULT_CONFIG_PATH = Path("config/relationships.yaml")
UNVERIFIED_MARKET_DATA_SOURCE = "Yahoo Finance Market Data Analysis"


def _none_if_missing(value: Any) -> Any:
    """Normalize pandas NaT/NaN (from a nullable DATE column read via fetchdf) to plain None."""
    return None if pd.isna(value) else value


def review_state(last_reviewed: Any, evidence_scope: Any, today: date | None = None) -> str:
    if _none_if_missing(last_reviewed) is None:
        return "unreviewed"
    if ((today or date.today()) - pd.Timestamp(last_reviewed).date()).days > 180:
        return "review_due"
    return "historical_announcement" if evidence_scope == "announcement" else "reviewed"



@dataclass(frozen=True)
class Relationship:
    """One evidence-backed edge from `source_entity` to `target_entity`."""

    source_entity: str
    target_entity: str
    target_entity_type: str
    relationship_type: str
    confidence: str
    date_discovered: date
    source: str
    evidence_url: str
    description: str | None = None
    relationship_start: date | None = None
    relationship_end: date | None = None
    business_area: str | None = None
    geographic_exposure: str | None = None
    target_entity_ticker: str | None = None
    evidence_date: date | None = None
    last_reviewed: date | None = None
    evidence_scope: str | None = None

    def __post_init__(self) -> None:
        if not self.source_entity or not self.source_entity.strip():
            raise ValueError("Relationship.source_entity must be a non-empty string")
        if not self.target_entity or not self.target_entity.strip():
            raise ValueError("Relationship.target_entity must be a non-empty string")
        if self.target_entity_type not in VALID_ENTITY_TYPES:
            raise ValueError(
                f"Relationship.target_entity_type {self.target_entity_type!r} is not one of "
                f"{sorted(VALID_ENTITY_TYPES)}"
            )
        if self.relationship_type not in VALID_GRAPH_RELATIONSHIP_TYPES:
            raise ValueError(
                f"Relationship.relationship_type {self.relationship_type!r} is not one of "
                f"{sorted(VALID_GRAPH_RELATIONSHIP_TYPES)}"
            )
        if self.confidence not in VALID_CONFIDENCE_LEVELS:
            raise ValueError(
                f"Relationship.confidence {self.confidence!r} is not one of {sorted(VALID_CONFIDENCE_LEVELS)}"
            )
        # Never fabricate a relationship: evidence is mandatory, not optional.
        if not self.source or not self.source.strip():
            raise ValueError("Relationship.source (evidence publisher) must be a non-empty string")
        if not self.evidence_url or not self.evidence_url.strip():
            raise ValueError("Relationship.evidence_url must be a non-empty, real URL")
        parsed_url = urlparse(self.evidence_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.hostname:
            raise ValueError("Relationship.evidence_url must use HTTP or HTTPS")
        if self.source.strip().casefold() == UNVERIFIED_MARKET_DATA_SOURCE.casefold():
            raise ValueError("Market-price analysis cannot substantiate a business relationship")

    @property
    def relationship_id(self) -> str:
        digest = hashlib.sha256(
            f"{self.source_entity}|{self.target_entity}|{self.relationship_type}".encode("utf-8")
        ).hexdigest()
        return digest[:24]


def load_relationships_config(config_path: Path | str = DEFAULT_CONFIG_PATH) -> list[Relationship]:
    """Parse and validate config/relationships.yaml into `Relationship` objects.

    Raises ValueError (via `Relationship.__post_init__`) for any entry missing evidence.
    """
    path = Path(config_path)
    if not path.exists():
        return []

    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    relationships: list[Relationship] = []
    for entry in raw.get("relationships", []) or []:
        relationships.append(
            Relationship(
                source_entity=str(entry.get("source_entity", STELLANTIS_ENTITY_ID)).strip(),
                target_entity=str(entry["target_entity"]).strip(),
                target_entity_type=str(entry["target_entity_type"]).strip(),
                relationship_type=str(entry["relationship_type"]).strip(),
                description=entry.get("description"),
                confidence=str(entry["confidence"]).strip(),
                relationship_start=entry.get("relationship_start"),
                relationship_end=entry.get("relationship_end"),
                date_discovered=entry["date_discovered"],
                source=str(entry["source"]).strip(),
                evidence_url=str(entry["evidence_url"]).strip(),
                business_area=entry.get("business_area"),
                geographic_exposure=entry.get("geographic_exposure"),
                target_entity_ticker=entry.get("target_entity_ticker"),
                evidence_date=entry.get("evidence_date"),
                last_reviewed=entry.get("last_reviewed"),
                evidence_scope=entry.get("evidence_scope"),
            )
        )
    return relationships


def persist_relationships(relationships: list[Relationship], db_path: Path | str | None = None) -> int:
    """Upsert validated relationships into the DuckDB `relationships` table."""
    from storage.duckdb import get_connection

    if not relationships:
        return 0

    conn = get_connection(db_path)
    try:
        for r in relationships:
            conn.execute(
                """
                INSERT INTO relationships
                    (relationship_id, source_entity, target_entity, target_entity_type, relationship_type,
                     description, confidence, relationship_start, relationship_end, date_discovered,
                     source, evidence_url, business_area, geographic_exposure, target_entity_ticker,
                     evidence_date, last_reviewed, evidence_scope)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (relationship_id) DO UPDATE SET
                    description = excluded.description,
                    confidence = excluded.confidence,
                    relationship_start = excluded.relationship_start,
                    relationship_end = excluded.relationship_end,
                    date_discovered = excluded.date_discovered,
                    source = excluded.source,
                    evidence_url = excluded.evidence_url,
                    business_area = excluded.business_area,
                    geographic_exposure = excluded.geographic_exposure,
                    target_entity_ticker = excluded.target_entity_ticker,
                    evidence_date = excluded.evidence_date,
                    last_reviewed = excluded.last_reviewed,
                    evidence_scope = excluded.evidence_scope
                """,
                [
                    r.relationship_id,
                    r.source_entity,
                    r.target_entity,
                    r.target_entity_type,
                    r.relationship_type,
                    r.description,
                    r.confidence,
                    r.relationship_start,
                    r.relationship_end,
                    r.date_discovered,
                    r.source,
                    r.evidence_url,
                    r.business_area,
                    r.geographic_exposure,
                    r.target_entity_ticker,
                    r.evidence_date,
                    r.last_reviewed,
                    r.evidence_scope,
                ],
            )
        return len(relationships)
    finally:
        conn.close()


def load_relationships(db_path: Path | str | None = None) -> pd.DataFrame:
    """Load all persisted relationships from DuckDB."""
    from storage.duckdb import get_connection

    conn = get_connection(db_path)
    try:
        df = conn.execute(
            """
            SELECT * FROM relationships
            WHERE lower(source) <> lower(?)
            ORDER BY source_entity, target_entity
            """,
            [UNVERIFIED_MARKET_DATA_SOURCE],
        ).fetchdf()
    finally:
        conn.close()
    return df


def build_graph(db_path: Path | str | None = None) -> nx.DiGraph:
    """Build a NetworkX directed graph from the persisted `relationships` table."""
    graph = nx.DiGraph()
    df = load_relationships(db_path=db_path)

    graph.add_node(STELLANTIS_ENTITY_ID, name="Stellantis N.V.", entity_type="company")

    # Ticker -> full legal/common company name, so every node carries a real name, never a bare ticker.
    from storage.repository import list_companies

    names_by_ticker = {c["ticker"]: c["company_name"] for c in list_companies(db_path=db_path) if c.get("ticker")}

    for row in df.itertuples(index=False):
        node_name = names_by_ticker.get(row.target_entity, row.target_entity)
        graph.add_node(row.target_entity, name=node_name, entity_type=row.target_entity_type)
        graph.add_edge(
            row.source_entity,
            row.target_entity,
            relationship_type=row.relationship_type,
            description=_none_if_missing(row.description),
            confidence=row.confidence,
            relationship_start=_none_if_missing(row.relationship_start),
            relationship_end=_none_if_missing(row.relationship_end),
            date_discovered=row.date_discovered,
            source=row.source,
            evidence_url=row.evidence_url,
            business_area=_none_if_missing(row.business_area),
            geographic_exposure=_none_if_missing(row.geographic_exposure),
            target_entity_ticker=_none_if_missing(row.target_entity_ticker),
            evidence_date=_none_if_missing(row.evidence_date),
            last_reviewed=_none_if_missing(row.last_reviewed),
            evidence_scope=_none_if_missing(row.evidence_scope),
            review_state=review_state(row.last_reviewed, row.evidence_scope),
        )
    return graph


def load_and_store_relationships(
    config_path: Path | str = DEFAULT_CONFIG_PATH, db_path: Path | str | None = None
) -> int:
    """Full Phase 11 pipeline: parse+validate config -> persist -> (caller may then build_graph())."""
    relationships = load_relationships_config(config_path)
    return persist_relationships(relationships, db_path=db_path)
