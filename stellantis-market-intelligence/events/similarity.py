"""Historical Event Similarity (Phase 18).

Builds a composite "embedding" for each stored event fingerprint (Phase 17
`historical_events`) - combining its numeric reaction profile with a text
representation of its event_type/description - and finds the most similar past
events to a given one via cosine similarity. This is a historical-pattern lookup
only: similarity is never treated as, or presented as, a price prediction.

Note: uses scikit-learn's TF-IDF + standardization rather than a neural embedding
model, since no network access / model download is assumed to be available here.
Phase 19/20 introduce a general-purpose neural-embedding vector store (sentence
transformers + FAISS) for the wider document corpus (news, filings, reports); this
lightweight approach is sufficient for the small, structured `historical_events` set
and avoids pulling in a large model download for a single feature.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.preprocessing import StandardScaler, normalize

NUMERIC_FIELDS = [
    "stla_return",
    "sector_return",
    "market_return",
    "supplier_reaction",
    "competitor_reaction",
    "commodity_reaction",
    "recovery_time_days",
]
MIN_EVENTS_FOR_SIMILARITY = 2
MIN_VARYING_NUMERIC_FIELDS = 2


def load_historical_events(db_path: Path | str | None = None) -> pd.DataFrame:
    """Load every stored Phase 17 event fingerprint."""
    from storage.duckdb import get_connection

    conn = get_connection(db_path)
    try:
        df = conn.execute("SELECT * FROM historical_events ORDER BY event_id").fetchdf()
    finally:
        conn.close()
    return df


def build_feature_matrix(events: pd.DataFrame) -> np.ndarray:
    """Composite embedding: L2-normalized [standardized numeric fields | TF-IDF text], concatenated."""
    numeric = events[NUMERIC_FIELDS].apply(pd.to_numeric, errors="coerce").astype("float64")
    numeric = numeric.fillna(numeric.mean()).fillna(0.0)
    numeric_scaled = StandardScaler().fit_transform(numeric.to_numpy())
    numeric_scaled = normalize(numeric_scaled)

    text = (events["event_type"].fillna("") + " " + events["event_description"].fillna("")).tolist()
    try:
        # No stop-word removal: event_type/description are short category labels and headlines,
        # not prose, so common words like "other" (a real event_type value) must stay in-vocabulary.
        tfidf = TfidfVectorizer().fit_transform(text).toarray()
        tfidf = normalize(tfidf) if tfidf.size else tfidf
    except ValueError:
        # All documents were empty/whitespace-only (e.g. no classified event_type/description yet).
        tfidf = np.zeros((len(events), 0))

    return np.hstack([numeric_scaled, tfidf])


def _has_distinguishing_features(events: pd.DataFrame) -> bool:
    numeric = events[NUMERIC_FIELDS].apply(pd.to_numeric, errors="coerce")
    varying_fields = sum(numeric[field].nunique(dropna=True) > 1 for field in NUMERIC_FIELDS)
    text_values = (
        events["event_type"].fillna("") + " " + events["event_description"].fillna("")
    ).map(lambda value: " ".join(value.split()).casefold())
    return varying_fields >= MIN_VARYING_NUMERIC_FIELDS or text_values.nunique() > 1


def find_similar_events(
    event_id: str, top_n: int = 3, db_path: Path | str | None = None
) -> list[dict[str, Any]]:
    """The `top_n` most similar past events to `event_id`, by composite embedding cosine similarity."""
    events = load_historical_events(db_path=db_path)
    if event_id not in set(events["event_id"]) or len(events) < MIN_EVENTS_FOR_SIMILARITY:
        return []
    if not _has_distinguishing_features(events):
        return []

    matrix = build_feature_matrix(events)
    idx = events.index[events["event_id"] == event_id][0]
    similarities = cosine_similarity(matrix[idx : idx + 1], matrix)[0]

    results = []
    for i, row in events.iterrows():
        if i == idx:
            continue
        results.append(
            {
                "event_id": row["event_id"],
                "similarity": round(float(similarities[i]) * 100, 1),
                "event_type": row["event_type"],
                "event_description": row["event_description"],
                "stla_return": row["stla_return"],
            }
        )
    results.sort(key=lambda r: r["similarity"], reverse=True)
    return results[:top_n]
