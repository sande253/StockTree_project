"""Vector database for the document corpus (Phase 19).

Collects short text documents from across the system (news, relationship evidence,
historical event fingerprints), persists them + their chunks to DuckDB, embeds every
chunk (TF-IDF, see ai/embeddings.py), and indexes them in a local FAISS inner-product
index for nearest-neighbor retrieval. This is index-building infrastructure only -
answering questions over retrieved documents is Phase 20 (Local RAG).
"""

from __future__ import annotations

import json
import pickle
from pathlib import Path
from typing import Any
from uuid import uuid4

import faiss
import numpy as np
import pandas as pd

from ai.embeddings import embed, fit_embedder

DEFAULT_INDEX_DIR = Path("data/vector_store")
CHUNK_SIZE_WORDS = 400


def active_index_dir(index_dir: Path | str = DEFAULT_INDEX_DIR) -> Path:
    root = Path(index_dir)
    pointer = root / "CURRENT"
    if not pointer.exists():
        return root
    generation = root / pointer.read_text(encoding="utf-8").strip()
    if generation.resolve().parent != root.resolve():
        raise ValueError("Invalid index generation pointer")
    return generation


def index_available(index_dir: Path | str = DEFAULT_INDEX_DIR) -> bool:
    try:
        active = active_index_dir(index_dir)
        return all((active / name).is_file() for name in ("index.faiss", "vectorizer.pkl", "chunk_ids.json"))
    except (OSError, ValueError):
        return False


def _none_if_missing(value: Any) -> Any:
    """Normalize pandas NaN/NaT (from a row pulled out of a mixed-dtype DataFrame) to plain None."""
    return None if pd.isna(value) else value


def collect_news_documents(db_path: Path | str | None = None) -> list[dict[str, Any]]:
    """News articles (Phase 8) as documents."""
    from storage.duckdb import get_connection

    conn = get_connection(db_path)
    try:
        df = conn.execute(
            'SELECT article_id, title, summary, source, url, "timestamp", mentioned_companies FROM news'
        ).fetchdf()
    finally:
        conn.close()

    docs = []
    for row in df.itertuples(index=False):
        company = row.mentioned_companies.split(",")[0] if row.mentioned_companies else None
        docs.append(
            {
                "document_id": f"news::{row.article_id}",
                "company": company or None,
                "event_id": None,
                "document_date": pd.Timestamp(row.timestamp).date() if pd.notna(row.timestamp) else None,
                "source": row.source,
                "source_url": row.url,
                "document_type": "news",
                "text": f"{row.title} {row.summary or ''}".strip(),
            }
        )
    return docs


def collect_relationship_documents(db_path: Path | str | None = None) -> list[dict[str, Any]]:
    """Corporate relationship evidence (Phase 11) as documents."""
    from storage.duckdb import get_connection

    conn = get_connection(db_path)
    try:
        df = conn.execute(
            """
                 SELECT relationship_id, target_entity, description, source, evidence_url,
                   date_discovered, business_area, geographic_exposure
            FROM relationships
                 WHERE lower(source) <> lower('Yahoo Finance Market Data Analysis')
            """
        ).fetchdf()
    finally:
        conn.close()

    docs = []
    for row in df.itertuples(index=False):
        text = " ".join(
            filter(None, [
                _none_if_missing(row.description),
                _none_if_missing(row.business_area),
                _none_if_missing(row.geographic_exposure),
                f"Evidence publisher: {row.source}",
                f"Evidence URL: {row.evidence_url}",
            ])
        )
        docs.append(
            {
                "document_id": f"relationship::{row.relationship_id}",
                "company": row.target_entity,
                "event_id": None,
                "document_date": row.date_discovered,
                "source": row.source,
                "source_url": row.evidence_url,
                "document_type": "relationship_evidence",
                "text": text or row.target_entity,
            }
        )
    return docs


def collect_historical_event_documents(db_path: Path | str | None = None) -> list[dict[str, Any]]:
    """Event fingerprints (Phase 17) as documents."""
    from storage.duckdb import get_connection

    conn = get_connection(db_path)
    try:
        df = conn.execute(
            """
                 SELECT h.event_id, h.ticker, h.event_type, h.event_description, h.stla_return,
                     h.sector_return, h.market_return, h.supplier_reaction, h.competitor_reaction,
                     h.commodity_reaction, h.recovery_time_days, m.event_date
            FROM historical_events h
            JOIN market_events m ON m.event_id = h.event_id
            """
        ).fetchdf()
    finally:
        conn.close()

    docs = []
    for row in df.itertuples(index=False):
        text = (
            f"Historical STLA event {row.event_id} on {row.event_date}: "
            f"type={row.event_type or 'Unclassified'}; description={row.event_description or 'not available'}; "
            f"STLA return={row.stla_return}; market return={row.market_return}; sector return={row.sector_return}; "
            f"supplier-group reaction={row.supplier_reaction}; competitor-group reaction={row.competitor_reaction}; "
            f"commodity-group reaction={row.commodity_reaction}; recovery days={row.recovery_time_days}."
        )
        docs.append(
            {
                "document_id": f"historical_event::{row.event_id}",
                "company": row.ticker,
                "event_id": row.event_id,
                "document_date": row.event_date,
                "source": "internal",
                "source_url": None,
                "document_type": "historical_event",
                "text": text,
            }
        )
    return docs


def collect_market_event_documents(db_path: Path | str | None = None) -> list[dict[str, Any]]:
    """Stored event and benchmark records, which are the factual basis for event questions."""
    from storage.duckdb import get_connection

    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            '''
            SELECT event_id, ticker, event_date, "return", event_type, event_description,
                   severity, direction, market_return, sector_return, classification
            FROM market_events ORDER BY event_date DESC
            '''
        ).fetchall()
    finally:
        conn.close()

    return [
        {
            "document_id": f"market_event::{row[0]}",
            "company": row[1],
            "event_id": row[0],
            "document_date": row[2],
            "source": "Stored market event and benchmark data",
            "source_url": None,
            "document_type": "market_event",
            "text": (
                f"STLA market event {row[0]} on {row[2]}: return={row[3]}; type={row[4] or 'Unclassified'}; "
                f"description={row[5] or 'not available'}; severity={row[6]}; direction={row[7]}; "
                f"broad market return={row[8]}; automotive sector return={row[9]}; "
                f"classification={row[10] or 'not available'}."
            ),
        }
        for row in rows
    ]


def collect_company_documents(db_path: Path | str | None = None) -> list[dict[str, Any]]:
    """Tracked-company metadata, explicitly separate from documented business relationships."""
    from storage.repository import list_companies

    return [
        {
            "document_id": f"company_universe::{company['ticker']}",
            "company": company["ticker"],
            "event_id": None,
            "document_date": None,
            "source": "Configured company universe",
            "source_url": None,
            "document_type": "company_universe",
            "text": (
                f"Tracked market-data company: {company['company_name']} ({company['ticker']}); "
                f"sector={company.get('sector')}; industry={company.get('industry')}; "
                f"country={company.get('country')}; universe category={company.get('relationship_type')}. "
                "The universe category is not evidence of a documented business relationship with Stellantis."
            ),
        }
        for company in list_companies(db_path=db_path)
    ]


def collect_correlation_documents(db_path: Path | str | None = None) -> list[dict[str, Any]]:
    """Stored market co-movement profiles with sample sizes and non-causality metadata."""
    from storage.duckdb import get_connection

    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT c.ticker, co.company_name, c.pearson_correlation, c.pearson_p_value,
                   c.pearson_ci_low, c.pearson_ci_high, c.spearman_correlation,
                   c.beta, c.r_squared, c.sample_size, c.computed_at
            FROM correlations c LEFT JOIN companies co ON co.ticker = c.ticker
            WHERE c.reference_ticker = 'STLA'
            ORDER BY c.sample_size DESC
            """
        ).fetchall()
    finally:
        conn.close()

    return [
        {
            "document_id": f"correlation::{row[0]}::STLA",
            "company": row[0],
            "event_id": None,
            "document_date": row[10],
            "source": "Stored daily-return correlation analysis",
            "source_url": None,
            "document_type": "statistical_relationship",
            "text": (
                f"Statistical relationship for {row[1] or row[0]} ({row[0]}) vs STLA: "
                f"Pearson correlation={row[2]}; p-value={row[3]}; 95% confidence interval="
                f"[{row[4]}, {row[5]}]; Spearman correlation={row[6]}; beta={row[7]}; "
                f"R-squared={row[8]}; sample size n={row[9]}. Computed at {row[10]}. "
                "This is statistical co-movement only, not evidence of a business relationship or causation."
            ),
        }
        for row in rows
    ]


def collect_all_documents(db_path: Path | str | None = None) -> list[dict[str, Any]]:
    """Every supported source document, including the structured market-data tables."""
    return (
        collect_news_documents(db_path=db_path)
        + collect_relationship_documents(db_path=db_path)
        + collect_historical_event_documents(db_path=db_path)
        + collect_market_event_documents(db_path=db_path)
        + collect_company_documents(db_path=db_path)
        + collect_correlation_documents(db_path=db_path)
    )


def chunk_text(text: str, chunk_size_words: int = CHUNK_SIZE_WORDS) -> list[str]:
    """Split text into fixed-size, non-overlapping word chunks (one chunk for short text)."""
    words = text.split()
    if not words:
        return [""]
    return [" ".join(words[i : i + chunk_size_words]) for i in range(0, len(words), chunk_size_words)]


def persist_documents(documents: list[dict[str, Any]], db_path: Path | str | None = None) -> int:
    """Upsert documents + their chunks into `documents` / `document_chunks`."""
    from storage.duckdb import get_connection

    if not documents:
        return 0

    conn = get_connection(db_path)
    try:
        for doc in documents:
            conn.execute(
                """
                INSERT INTO documents
                    (document_id, company, event_id, document_date, source, source_url, document_type, text)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (document_id) DO UPDATE SET
                    company = excluded.company,
                    event_id = excluded.event_id,
                    document_date = excluded.document_date,
                    source = excluded.source,
                    source_url = excluded.source_url,
                    document_type = excluded.document_type,
                    text = excluded.text
                """,
                [
                    doc["document_id"], doc["company"], doc["event_id"], doc["document_date"],
                    doc["source"], doc.get("source_url"), doc["document_type"], doc["text"],
                ],
            )
            conn.execute("DELETE FROM document_chunks WHERE document_id = ?", [doc["document_id"]])
            for i, chunk in enumerate(chunk_text(doc["text"])):
                conn.execute(
                    "INSERT INTO document_chunks (chunk_id, document_id, chunk_index, text) VALUES (?, ?, ?, ?)",
                    [f"{doc['document_id']}::{i}", doc["document_id"], i, chunk],
                )
        return len(documents)
    finally:
        conn.close()


def load_all_chunks(db_path: Path | str | None = None) -> pd.DataFrame:
    """All chunks joined with their parent document's metadata."""
    from storage.duckdb import get_connection

    conn = get_connection(db_path)
    try:
        df = conn.execute(
            """
                 SELECT c.chunk_id, c.document_id, c.text, d.company, d.event_id,
                     d.document_date, d.source, d.source_url, d.document_type
            FROM document_chunks c
            JOIN documents d ON d.document_id = c.document_id
            ORDER BY c.chunk_id
            """
        ).fetchdf()
    finally:
        conn.close()
    return df


def build_vector_store(
    db_path: Path | str | None = None, index_dir: Path | str = DEFAULT_INDEX_DIR
) -> dict[str, int]:
    """Full Phase 19 pipeline: collect documents -> persist+chunk -> embed -> build FAISS index."""
    index_dir = Path(index_dir)
    index_dir.mkdir(parents=True, exist_ok=True)

    documents = collect_all_documents(db_path=db_path)
    persist_documents(documents, db_path=db_path)

    chunks = load_all_chunks(db_path=db_path)
    if chunks.empty:
        return {"documents": len(documents), "chunks": 0}

    vectorizer = fit_embedder(chunks["text"].tolist())
    vectors = embed(chunks["text"].tolist(), vectorizer)

    index = faiss.IndexFlatIP(vectors.shape[1])
    index.add(vectors)

    generation = index_dir / f"generation-{uuid4().hex}"
    generation.mkdir()
    faiss.write_index(index, str(generation / "index.faiss"))
    with open(generation / "vectorizer.pkl", "wb") as fh:
        pickle.dump(vectorizer, fh)
    with open(generation / "chunk_ids.json", "w", encoding="utf-8") as fh:
        json.dump(chunks["chunk_id"].tolist(), fh)
    (generation / "chunks.json").write_text(chunks.to_json(orient="records", date_format="iso"), encoding="utf-8")
    pointer = index_dir / f".CURRENT-{uuid4().hex}.tmp"
    pointer.write_text(generation.name, encoding="utf-8")
    pointer.replace(index_dir / "CURRENT")

    return {"documents": len(documents), "chunks": len(chunks)}


def search(
    query: str, top_k: int = 5, index_dir: Path | str = DEFAULT_INDEX_DIR, db_path: Path | str | None = None
) -> list[dict[str, Any]]:
    """Nearest-neighbor chunk search over the built index. Empty list if the index doesn't exist yet."""
    index_dir = active_index_dir(index_dir)
    index_path = index_dir / "index.faiss"
    if not index_path.exists():
        return []

    index = faiss.read_index(str(index_path))
    with open(index_dir / "vectorizer.pkl", "rb") as fh:
        vectorizer = pickle.load(fh)
    with open(index_dir / "chunk_ids.json", "r", encoding="utf-8") as fh:
        chunk_ids = json.load(fh)

    query_vector = embed([query], vectorizer)
    scores, positions = index.search(query_vector, min(top_k, len(chunk_ids)))

    snapshot = index_dir / "chunks.json"
    chunks = (
        pd.DataFrame(json.loads(snapshot.read_text(encoding="utf-8")))
        if snapshot.exists() else load_all_chunks(db_path=db_path)
    ).set_index("chunk_id")
    results = []
    for score, pos in zip(scores[0], positions[0]):
        if pos < 0:
            continue
        chunk_id = chunk_ids[pos]
        if chunk_id not in chunks.index:
            continue
        row = chunks.loc[chunk_id]
        results.append(
            {
                "chunk_id": chunk_id,
                "document_id": row["document_id"],
                "document_type": row["document_type"],
                "company": _none_if_missing(row["company"]),
                "event_id": _none_if_missing(row["event_id"]),
                "source": _none_if_missing(row["source"]),
                "url": _none_if_missing(row["source_url"]),
                "text": row["text"],
                "score": float(score),
            }
        )
    return results
