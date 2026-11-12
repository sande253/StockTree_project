"""Phase 21 - AI Investigation Agent tests."""

from __future__ import annotations

import duckdb
import pytest

from ai.agent import (
    STANDARD_UNCERTAINTIES,
    compile_uncertainties,
    investigate_event,
)
from ai.vector_store import build_vector_store
from relationships.graph import Relationship, persist_relationships


def _seed_market_event(db_path, event_id="STLA-2026-01-01", event_date="2026-01-01", event_type="Production"):
    from storage.duckdb import get_connection

    conn = get_connection(db_path)
    conn.execute(
        """
        INSERT INTO market_events
            (event_id, event_date, ticker, "return", severity, direction, detection_method,
             combined_score, event_type, event_description, market_return, sector_return, classification)
        VALUES (?, ?, 'STLA', -0.08, 'high', 'negative', 'absolute_return', 0.25, ?,
                'Stellantis announces a production cut', -0.004, -0.015, 'stla_specific')
        """,
        [event_id, event_date, event_type],
    )
    conn.close()


def _seed_relationship(db_path):
    rel = Relationship(
        source_entity="STLA",
        target_entity="Peugeot",
        target_entity_type="brand",
        relationship_type="brand",
        confidence="high",
        date_discovered="2026-10-04",
        source="Stellantis official corporate site",
        evidence_url="https://www.stellantis.com/en/brands",
    )
    persist_relationships([rel], db_path=db_path)


def test_investigate_event_returns_none_for_unknown_event(tmp_path):
    db_path = tmp_path / "test.duckdb"
    from storage.duckdb import get_connection

    get_connection(db_path).close()
    assert investigate_event("UNKNOWN", db_path=db_path) is None


def test_investigate_event_produces_all_sections_without_groq_configured(tmp_path, monkeypatch):
    db_path = tmp_path / "test.duckdb"
    index_dir = tmp_path / "vector_store"
    monkeypatch.setenv("GROQ_API_KEY", "")

    _seed_market_event(db_path)
    _seed_relationship(db_path)
    build_vector_store(db_path=db_path, index_dir=index_dir)

    result = investigate_event("STLA-2026-01-01", db_path=db_path, index_dir=index_dir)

    assert result["event_summary"]["ticker"] == "STLA"
    assert result["event_summary"]["event_type"] == "Production"
    assert result["market_context"]["classification"] == "stla_specific"
    assert result["likely_catalyst"]["movement"] == pytest.approx(-0.08)
    assert len(result["potentially_affected_companies"]) == 1
    assert result["potentially_affected_companies"][0]["entity_id"] == "Peugeot"
    assert len(result["business_relationships"]) == 1
    assert len(result["historical_market_sensitivity"]) == 1
    assert isinstance(result["supply_chain_exposure"], list)
    assert isinstance(result["similar_historical_events"], list)
    assert isinstance(result["supporting_evidence"], list)
    assert set(STANDARD_UNCERTAINTIES) <= set(result["uncertainties"])
    # No GROQ_API_KEY configured -> synthesis gracefully skipped, not an error.
    assert result["ai_synthesis"] is None


def test_compile_uncertainties_flags_no_affected_companies_and_no_catalyst():
    sections = {
        "potentially_affected_companies": [],
        "likely_catalyst": {"event_type": "Other", "supporting_sources": []},
        "similar_historical_events": [],
    }
    notes = compile_uncertainties(sections)
    assert any("No companies with a documented relationship" in n for n in notes)
    assert any("No classified event type" in n for n in notes)
    assert any("Not enough historical events" in n for n in notes)


@pytest.mark.parametrize("narrative,accepted", [
    ("A source-associated observation [1].", True),
    ("Unsupported narrative without citations.", False),
    ("Invalid source [999].", False),
    ("", False),
])
def test_investigate_event_checks_groq_citations(tmp_path, monkeypatch, narrative, accepted):
    db_path = tmp_path / "test.duckdb"
    index_dir = tmp_path / "vector_store"
    monkeypatch.setenv("GROQ_API_KEY", "test-key")

    _seed_market_event(db_path)
    _seed_relationship(db_path)
    build_vector_store(db_path=db_path, index_dir=index_dir)

    class _FakeMessage:
        content = narrative

    class _FakeChoice:
        message = _FakeMessage()

    class _FakeCompletion:
        choices = [_FakeChoice()]

    class _FakeChatCompletions:
        def create(self, **kwargs):
            return _FakeCompletion()

    class _FakeChat:
        completions = _FakeChatCompletions()

    class _FakeGroqClient:
        def __init__(self, api_key=None):
            self.chat = _FakeChat()

    monkeypatch.setattr("groq.Groq", _FakeGroqClient)

    result = investigate_event("STLA-2026-01-01", db_path=db_path, index_dir=index_dir)
    assert result["ai_synthesis"] == (narrative if accepted else None)
