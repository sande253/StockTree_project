"""Phase 19 - Vector Database tests."""

from __future__ import annotations

from datetime import datetime, timezone

import duckdb
import pytest

from ai.vector_store import (
    build_vector_store,
    chunk_text,
    collect_news_documents,
    load_all_chunks,
    persist_documents,
    search,
)


def _seed_news(db_path):
    from storage.duckdb import get_connection

    conn = get_connection(db_path)
    conn.execute(
        """
        INSERT INTO news (article_id, title, source, "timestamp", url, summary, mentioned_companies)
        VALUES
            ('a1', 'Stellantis announces a production cut at a European plant', 'Example Source',
             ?, 'https://example.com/a1', 'Production reduced due to weak demand', 'STLA'),
            ('a2', 'Stellantis issues a vehicle recall over a braking defect', 'Example Source',
             ?, 'https://example.com/a2', 'Safety recall affecting thousands of vehicles', 'STLA')
        """,
        [datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 2, tzinfo=timezone.utc)],
    )
    conn.close()


def test_chunk_text_splits_long_text_and_handles_empty():
    words = ["word"] * 900
    chunks = chunk_text(" ".join(words), chunk_size_words=400)
    assert len(chunks) == 3
    assert len(chunks[0].split()) == 400

    assert chunk_text("") == [""]


def test_collect_news_documents_maps_fields(tmp_path):
    db_path = tmp_path / "test.duckdb"
    _seed_news(db_path)

    docs = collect_news_documents(db_path=db_path)
    assert len(docs) == 2
    assert all(d["document_type"] == "news" for d in docs)
    assert all(d["company"] == "STLA" for d in docs)
    assert "production cut" in docs[0]["text"].lower() or "production cut" in docs[1]["text"].lower()


def test_persist_documents_creates_documents_and_chunks(tmp_path):
    db_path = tmp_path / "test.duckdb"
    _seed_news(db_path)
    docs = collect_news_documents(db_path=db_path)

    inserted = persist_documents(docs, db_path=db_path)
    assert inserted == 2

    chunks = load_all_chunks(db_path=db_path)
    assert len(chunks) == 2
    assert set(chunks["document_type"]) == {"news"}


def test_persist_documents_is_idempotent(tmp_path):
    db_path = tmp_path / "test.duckdb"
    _seed_news(db_path)
    docs = collect_news_documents(db_path=db_path)
    persist_documents(docs, db_path=db_path)
    persist_documents(docs, db_path=db_path)

    conn = duckdb.connect(str(db_path))
    try:
        count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        chunk_count = conn.execute("SELECT COUNT(*) FROM document_chunks").fetchone()[0]
    finally:
        conn.close()
    assert count == 2
    assert chunk_count == 2


def test_build_vector_store_and_search_finds_relevant_chunk(tmp_path):
    db_path = tmp_path / "test.duckdb"
    index_dir = tmp_path / "vector_store"
    _seed_news(db_path)

    stats = build_vector_store(db_path=db_path, index_dir=index_dir)
    assert stats["documents"] == 2
    assert stats["chunks"] == 2

    results = search("production cut plant", top_k=2, index_dir=index_dir, db_path=db_path)
    assert len(results) == 2
    assert results[0]["document_type"] == "news"
    assert "production" in results[0]["text"].lower()
    assert results[0]["url"].startswith("https://example.com/")
    assert results[0]["score"] >= results[1]["score"]


def test_search_returns_empty_when_index_not_built(tmp_path):
    assert search("anything", index_dir=tmp_path / "no_index") == []


def test_relationship_index_accepts_nullable_business_metadata(tmp_path):
    from relationships.graph import Relationship, persist_relationships

    database = tmp_path / "relationships.duckdb"
    persist_relationships([
        Relationship(
            source_entity="STLA", target_entity=name, target_entity_type="company",
            relationship_type="technology_partner", confidence="medium",
            date_discovered="2026-10-29", source="Primary announcement",
            evidence_url="https://example.com/announcement", geographic_exposure=geography,
        )
        for name, geography in [("Example Partner", None), ("Another Partner", "Global")]
    ], db_path=database)
    directory = tmp_path / "index"
    assert build_vector_store(db_path=database, index_dir=directory)["documents"] == 2
    results = search("Primary announcement", index_dir=directory, db_path=database)
    assert len(results) == 2
    assert all("nan" not in result["text"].split() for result in results)


def test_failed_rebuild_keeps_published_generation(tmp_path, monkeypatch):
    import pytest
    from ai.vector_store import build_vector_store, active_index_dir
    from storage.duckdb import get_connection

    database = tmp_path / "snapshot.duckdb"
    conn = get_connection(database)
    conn.execute("INSERT INTO companies (ticker, company_name, relationship_type) VALUES ('STLA', 'Stellantis', 'self')")
    conn.close()
    directory = tmp_path / "index"
    build_vector_store(database, directory)
    published = active_index_dir(directory)

    def fail_write(*args):
        raise OSError("simulated disk failure")

    monkeypatch.setattr("ai.vector_store.faiss.write_index", fail_write)
    with pytest.raises(OSError):
        build_vector_store(database, directory)
    assert active_index_dir(directory) == published
    assert search("Stellantis", index_dir=directory, db_path=database)


def test_build_index_script_uses_warehouse_corpus(monkeypatch):
    expected = {"documents": 19, "chunks": 23}
    monkeypatch.setattr("ai.vector_store.build_vector_store", lambda: expected)

    from scripts.build_vector_index import build_index

    assert build_index() == expected
