"""DuckDB table schemas (DDL) for Stellantis Market Impact Intelligence.

Only the tables needed by the currently-implemented phases are defined here.
Later phases add more tables (events, correlations, relationships, ...).
"""

from __future__ import annotations

from dataclasses import dataclass

# Allowed coarse relationship categories for the company universe (Phase 1).
# This is NOT a documented Stellantis business relationship - see config/companies.yaml.
VALID_RELATIONSHIP_TYPES = {
    "self",
    "oem",
    "supplier_tier1",
    "supplier_tier2",
    "semiconductor",
    "battery",
    "ev",
    "adas",
    "autonomous_driving",
    "software",
    "cloud_technology",
    "logistics",
    "commodity",
    "other",
}

CREATE_COMPANIES_TABLE = """
CREATE TABLE IF NOT EXISTS companies (
    ticker             VARCHAR PRIMARY KEY,
    company_name       VARCHAR NOT NULL,
    exchange           VARCHAR,
    sector             VARCHAR,
    industry           VARCHAR,
    country            VARCHAR,
    relationship_type  VARCHAR NOT NULL,
    updated_at         TIMESTAMP NOT NULL DEFAULT current_timestamp
);
"""

# Phase 2 - Market Data Ingestion. One row per (ticker, date, interval).
CREATE_PRICE_DATA_TABLE = """
CREATE TABLE IF NOT EXISTS price_data (
    ticker       VARCHAR NOT NULL,
    date         DATE NOT NULL,
    open         DOUBLE NOT NULL,
    high         DOUBLE NOT NULL,
    low          DOUBLE NOT NULL,
    close        DOUBLE NOT NULL,
    adj_close    DOUBLE NOT NULL,
    volume       BIGINT NOT NULL,
    interval     VARCHAR NOT NULL,
    source       VARCHAR NOT NULL,
    ingested_at  TIMESTAMP NOT NULL DEFAULT current_timestamp,
    PRIMARY KEY (ticker, date, interval)
);
"""

# Phase 3 - Return & Volatility Engine. One row per (ticker, date).
CREATE_PRICE_FEATURES_TABLE = """
CREATE TABLE IF NOT EXISTS price_features (
    ticker              VARCHAR NOT NULL,
    date                DATE NOT NULL,
    daily_return        DOUBLE,
    log_return          DOUBLE,
    rolling_return      DOUBLE,
    rolling_mean        DOUBLE,
    rolling_std         DOUBLE,
    rolling_volatility  DOUBLE,
    zscore              DOUBLE,
    drawdown            DOUBLE,
    volume_change       DOUBLE,
    volume_zscore       DOUBLE,
    lookback_window     INTEGER NOT NULL,
    PRIMARY KEY (ticker, date)
);
"""

# Phase 4 - STLA Event Detection. "return" is quoted since it is a SQL keyword.
CREATE_MARKET_EVENTS_TABLE = """
CREATE TABLE IF NOT EXISTS market_events (
    event_id          VARCHAR PRIMARY KEY,
    event_date        DATE NOT NULL,
    ticker            VARCHAR NOT NULL,
    "return"          DOUBLE NOT NULL,
    z_score           DOUBLE,
    volume_z_score    DOUBLE,
    volatility        DOUBLE,
    severity          VARCHAR NOT NULL,
    direction         VARCHAR NOT NULL,
    detection_method  VARCHAR NOT NULL,
    combined_score    DOUBLE NOT NULL,
    created_at        TIMESTAMP NOT NULL DEFAULT current_timestamp
);
"""

# Phase 5 - Correlation Analysis. Full-sample statistical profile per (ticker, reference_ticker).
CREATE_CORRELATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS correlations (
    ticker                VARCHAR NOT NULL,
    reference_ticker      VARCHAR NOT NULL,
    pearson_correlation   DOUBLE,
    pearson_p_value       DOUBLE,
    pearson_ci_low        DOUBLE,
    pearson_ci_high       DOUBLE,
    spearman_correlation  DOUBLE,
    spearman_p_value      DOUBLE,
    beta                  DOUBLE,
    alpha                 DOUBLE,
    r_squared             DOUBLE,
    beta_p_value          DOUBLE,
    sample_size           INTEGER NOT NULL,
    computed_at           TIMESTAMP NOT NULL DEFAULT current_timestamp,
    PRIMARY KEY (ticker, reference_ticker)
);
"""

# Phase 5 - rolling correlation time series per (ticker, reference_ticker, date).
CREATE_ROLLING_CORRELATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS rolling_correlations (
    ticker               VARCHAR NOT NULL,
    reference_ticker     VARCHAR NOT NULL,
    date                 DATE NOT NULL,
    rolling_correlation  DOUBLE,
    lookback_window      INTEGER NOT NULL,
    PRIMARY KEY (ticker, reference_ticker, date)
);
"""

# Phase 6 - Event Study. One row per (event_id, ticker, day_offset) around an event date.
# `day_offset` is trading days relative to the event (T0): -5, -3, -1, 0, 1, 3, 5, ...
CREATE_EVENT_RETURNS_TABLE = """
CREATE TABLE IF NOT EXISTS event_returns (
    event_id           VARCHAR NOT NULL,
    ticker             VARCHAR NOT NULL,
    event_date         DATE NOT NULL,
    day_offset         INTEGER NOT NULL,
    date               DATE NOT NULL,
    daily_return       DOUBLE,
    cumulative_return  DOUBLE,
    PRIMARY KEY (event_id, ticker, day_offset)
);
"""

# Phase 6 - abnormal return vs a simple market model (beta/alpha from `correlations`).
CREATE_ABNORMAL_RETURNS_TABLE = """
CREATE TABLE IF NOT EXISTS abnormal_returns (
    event_id         VARCHAR NOT NULL,
    ticker           VARCHAR NOT NULL,
    day_offset       INTEGER NOT NULL,
    date             DATE NOT NULL,
    actual_return    DOUBLE NOT NULL,
    expected_return  DOUBLE NOT NULL,
    abnormal_return  DOUBLE NOT NULL,
    PRIMARY KEY (event_id, ticker, day_offset)
);
"""

# Phase 8 - News/Filings Ingestion. "timestamp" is quoted since it is a SQL keyword.
CREATE_NEWS_TABLE = """
CREATE TABLE IF NOT EXISTS news (
    article_id           VARCHAR PRIMARY KEY,
    title                VARCHAR NOT NULL,
    source               VARCHAR NOT NULL,
    "timestamp"          TIMESTAMPTZ,
    url                  VARCHAR NOT NULL,
    summary              VARCHAR,
    mentioned_companies  VARCHAR,
    ingested_at          TIMESTAMP NOT NULL DEFAULT current_timestamp
);
"""

# Phase 10 - News/Event Correlation. Evidence link: which article(s) support which event,
# ranked by relevance. The hedged "potential catalyst" narrative is derived on read from this
# link table + `news` + `market_events`, not stored, so wording can evolve without a migration.
CREATE_EVENT_NEWS_TABLE = """
CREATE TABLE IF NOT EXISTS event_news (
    event_id         VARCHAR NOT NULL,
    article_id       VARCHAR NOT NULL,
    relevance_rank   INTEGER NOT NULL,
    relevance_score  DOUBLE NOT NULL,
    created_at       TIMESTAMP NOT NULL DEFAULT current_timestamp,
    PRIMARY KEY (event_id, article_id)
);
"""

# Allowed relationship categories for the corporate relationship graph (Phase 11).
# "brand" is a deliberate addition beyond the master prompt's explicit list, to represent
# Stellantis's own owned brands (an entity category the prompt explicitly asks for).
VALID_GRAPH_RELATIONSHIP_TYPES = {
    "brand",
    "supplier",
    "customer",
    "partner",
    "competitor",
    "technology_partner",
    "battery_supplier",
    "semiconductor_supplier",
    "software_partner",
    "cloud_partner",
    "logistics_partner",
    "manufacturing_partner",
    "joint_venture",
}

VALID_ENTITY_TYPES = {"company", "brand", "technology", "product", "facility", "region"}
VALID_CONFIDENCE_LEVELS = {"high", "medium", "low"}

# Phase 11 - Corporate Relationship Graph. Every relationship MUST have evidence
# (source + evidence_url) - enforced in code (relationships/graph.py), not just by convention.
CREATE_RELATIONSHIPS_TABLE = """
CREATE TABLE IF NOT EXISTS relationships (
    relationship_id     VARCHAR PRIMARY KEY,
    source_entity        VARCHAR NOT NULL,
    target_entity         VARCHAR NOT NULL,
    target_entity_type   VARCHAR NOT NULL,
    relationship_type    VARCHAR NOT NULL,
    description          VARCHAR,
    confidence           VARCHAR NOT NULL,
    relationship_start   DATE,
    relationship_end     DATE,
    date_discovered       DATE NOT NULL,
    source                VARCHAR NOT NULL,
    evidence_url          VARCHAR NOT NULL,
    business_area         VARCHAR,
    geographic_exposure   VARCHAR,
    target_entity_ticker  VARCHAR,
    created_at            TIMESTAMP NOT NULL DEFAULT current_timestamp
);
"""

# Phase 11 - supplementary supporting evidence beyond a relationship's primary source/evidence_url.
CREATE_RELATIONSHIP_EVIDENCE_TABLE = """
CREATE TABLE IF NOT EXISTS relationship_evidence (
    evidence_id       VARCHAR PRIMARY KEY,
    relationship_id   VARCHAR NOT NULL,
    source            VARCHAR NOT NULL,
    evidence_url      VARCHAR NOT NULL,
    date_discovered   DATE NOT NULL,
    description       VARCHAR,
    created_at        TIMESTAMP NOT NULL DEFAULT current_timestamp
);
"""

# Phase 17 - Event Fingerprinting. One comparable "fingerprint" row per detected event,
# combining Phase 4/7/9 context with aggregate peer-group reactions and recovery time.
# This is the row later embedded for Phase 18 historical-event similarity search.
CREATE_HISTORICAL_EVENTS_TABLE = """
CREATE TABLE IF NOT EXISTS historical_events (
    event_id             VARCHAR PRIMARY KEY,
    ticker                VARCHAR NOT NULL,
    event_type            VARCHAR,
    event_description     VARCHAR,
    stla_return           DOUBLE,
    sector_return         DOUBLE,
    market_return         DOUBLE,
    supplier_reaction     DOUBLE,
    competitor_reaction   DOUBLE,
    commodity_reaction    DOUBLE,
    recovery_time_days    INTEGER,
    computed_at           TIMESTAMP NOT NULL DEFAULT current_timestamp
);
"""

# Phase 19 - Vector Database. One row per source document pulled from news/relationships/
# historical_events (or later filings/reports), with metadata for provenance/filtering.
CREATE_DOCUMENTS_TABLE = """
CREATE TABLE IF NOT EXISTS documents (
    document_id     VARCHAR PRIMARY KEY,
    company          VARCHAR,
    event_id         VARCHAR,
    document_date    DATE,
    source           VARCHAR,
    source_url       VARCHAR,
    document_type    VARCHAR NOT NULL,
    text             VARCHAR NOT NULL,
    created_at       TIMESTAMP NOT NULL DEFAULT current_timestamp
);
"""

# Phase 19 - chunks of a `documents` row (RAG retrieval granularity). For the short texts
# this project currently ingests, a document is usually a single chunk; chunking exists so
# longer future document types (full filings, reports) work without a schema change.
CREATE_DOCUMENT_CHUNKS_TABLE = """
CREATE TABLE IF NOT EXISTS document_chunks (
    chunk_id       VARCHAR PRIMARY KEY,
    document_id    VARCHAR NOT NULL,
    chunk_index    INTEGER NOT NULL,
    text           VARCHAR NOT NULL,
    created_at     TIMESTAMP NOT NULL DEFAULT current_timestamp
);
"""


@dataclass(frozen=True)
class Company:
    """A single entry in the configurable company universe (Phase 1)."""

    ticker: str
    company_name: str
    exchange: str | None
    sector: str | None
    industry: str | None
    country: str | None
    relationship_type: str

    def __post_init__(self) -> None:
        if not self.ticker or not self.ticker.strip():
            raise ValueError("Company.ticker must be a non-empty string")
        if not self.company_name or not self.company_name.strip():
            raise ValueError("Company.company_name must be a non-empty string")
        if self.relationship_type not in VALID_RELATIONSHIP_TYPES:
            raise ValueError(
                f"Company.relationship_type {self.relationship_type!r} is not one of "
                f"{sorted(VALID_RELATIONSHIP_TYPES)}"
            )
