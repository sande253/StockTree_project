"""Text embeddings (Phase 19).

Uses scikit-learn TF-IDF rather than a neural embedding model: no network access is
available in this environment to download a sentence-transformers model (confirmed
with the user). Vectors are L2-normalized so a FAISS inner-product index (see
vector_store.py) is equivalent to cosine similarity search.
"""

from __future__ import annotations

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize


def fit_embedder(texts: list[str]) -> TfidfVectorizer:
    """Fit a TF-IDF vectorizer over a text corpus. No stop-word removal (short texts/labels)."""
    vectorizer = TfidfVectorizer()
    vectorizer.fit(texts)
    return vectorizer


def embed(texts: list[str], vectorizer: TfidfVectorizer) -> np.ndarray:
    """Transform text into L2-normalized, dense float32 vectors (ready for FAISS)."""
    matrix = vectorizer.transform(texts).toarray().astype("float32")
    return normalize(matrix).astype("float32")
