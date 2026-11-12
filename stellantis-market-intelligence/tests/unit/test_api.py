"""Phase 23/24 - Flask API + dashboard tests."""

from __future__ import annotations

from datetime import date

import pytest

from api.main import create_app
from relationships.graph import Relationship, persist_relationships
from storage.load_companies import upsert_companies
from storage.schemas import Company


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test.duckdb"
    monkeypatch.setenv("DUCKDB_PATH", str(db_path))

    upsert_companies(
        [
            Company(
                ticker="STLA", company_name="Stellantis N.V.", exchange="NYSE",
                sector="Consumer Cyclical", industry="Auto Manufacturers", country="Netherlands",
                relationship_type="self",
            )
        ],
        db_path=db_path,
    )
    persist_relationships(
        [
            Relationship(
                source_entity="STLA", target_entity="Peugeot", target_entity_type="brand",
                relationship_type="brand", confidence="high", date_discovered=date(2026, 10, 4),
                source="Stellantis official corporate site", evidence_url="https://www.stellantis.com/en/brands",
            )
        ],
        db_path=db_path,
    )

    from storage.duckdb import get_connection

    conn = get_connection(db_path)
    conn.execute(
        """
        INSERT INTO market_events
            (event_id, event_date, ticker, "return", severity, direction, detection_method, combined_score)
        VALUES ('STLA-2026-01-01', '2026-01-01', 'STLA', -0.08, 'high', 'negative', 'absolute_return', 0.25)
        """
    )
    conn.close()

    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_health_endpoint(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "ok"
    assert "timestamp" in body


def test_event_timeline_distinguishes_missing_evidence_and_windows(client):
    response = client.get("/api/events/STLA-2026-01-01/timeline")
    assert response.status_code == 200
    timeline = response.get_json()
    assert timeline["publications"] == []
    assert "not proof of causation" in timeline["interpretation"]
    assert all(window["status"] == "incomplete" for window in timeline["windows"])
    assert client.get("/api/events/unknown/timeline").status_code == 404


def test_readiness_does_not_claim_empty_data_is_healthy(client):
    response = client.get("/api/health/ready")
    assert response.status_code == 503
    body = response.get_json()
    assert body["status"] == "degraded"
    assert body["components"]["data"]["status"] == "degraded"
    assert body["components"]["data"]["issues"]


def test_report_includes_real_dates_and_returns_for_similar_events(client, monkeypatch):
    from storage.duckdb import get_connection

    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO market_events
            (event_id, event_date, ticker, "return", severity, direction, detection_method, combined_score)
            VALUES ('STLA-2025-12-01', '2025-12-01', 'STLA', -0.06, 'high', 'negative', 'absolute_return', 0.2)"""
        )
    finally:
        conn.close()
    monkeypatch.setattr("reports.generator.find_similar_events", lambda *args, **kwargs: [{
        "event_id": "STLA-2025-12-01", "similarity": 75.0,
        "stla_return": -0.06, "event_type": "Production",
    }])
    response = client.get("/api/reports/event/STLA-2026-01-01")
    assert response.status_code == 200
    precedent = response.get_json()["historical_precedent"][0]
    assert "2025" in precedent["event_date"]
    assert precedent["stla_movement"] == -0.06
    text = client.get("/api/reports/event/STLA-2026-01-01?format=text")
    assert text.status_code == 200
    assert b"STELLANTIS MARKET IMPACT REPORT" in text.data


def test_list_and_get_company(client):
    response = client.get("/api/companies")
    assert response.status_code == 200
    assert any(c["ticker"] == "STLA" for c in response.get_json())

    response = client.get("/api/companies/STLA")
    assert response.status_code == 200
    assert response.get_json()["company_name"] == "Stellantis N.V."

    response = client.get("/api/companies/UNKNOWN")
    assert response.status_code == 404


def test_list_and_get_event(client):
    response = client.get("/api/events")
    assert response.status_code == 200
    assert len(response.get_json()) == 1

    response = client.get("/api/events/STLA-2026-01-01")
    assert response.status_code == 200

    response = client.get("/api/events/UNKNOWN")
    assert response.status_code == 404


def test_event_impact_endpoint(client):
    response = client.get("/api/events/STLA-2026-01-01/impact")
    assert response.status_code == 200
    body = response.get_json()
    assert body["event"]["event_id"] == "STLA-2026-01-01"
    assert len(body["impact"]) == 1
    assert body["impact"][0]["entity_id"] == "Peugeot"
    assert "ecosystem_exposure_score" in body["impact"][0]


def test_relationships_and_network_endpoints(client):
    response = client.get("/api/relationships")
    assert response.status_code == 200
    assert len(response.get_json()) == 1

    response = client.get("/api/network")
    assert response.status_code == 200
    body = response.get_json()
    assert any(n["id"] == "STLA" for n in body["nodes"])
    assert any(e["source"] == "STLA" and e["target"] == "Peugeot" for e in body["edges"])


def test_investigate_requires_valid_body(client):
    response = client.post("/api/investigate", json={})
    assert response.status_code == 400

    response = client.post("/api/investigate", json={"event_id": "STLA-2026-01-01"})
    assert response.status_code == 200
    assert response.get_json()["event_summary"]["event_id"] == "STLA-2026-01-01"


def test_chat_validates_question_and_returns_grounded_visual(client, monkeypatch):
    response = client.post("/api/chat", json={})
    assert response.status_code == 400

    captured = {}

    def fake_answer_question(question, context_sources, history):
        captured["question"] = question
        captured["context_sources"] = context_sources
        captured["history"] = history
        return {
            "answer": "## Event move\n\nSTLA fell **8%** [1].",
            "sources": context_sources,
        }

    monkeypatch.setattr("api.services.chat_service.answer_question", fake_answer_question)
    response = client.post(
        "/api/chat",
        json={
            "question": "What happened during this event?",
            "event_id": "STLA-2026-01-01",
            "history": [{"role": "user", "content": "Show the event."}],
        },
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["answer"].startswith("## Event move")
    assert body["visual"]["type"] == "bars"
    assert body["visual"]["labels"] == ["STLA"]
    assert body["visual"]["values"] == [-8.0]
    assert captured["history"][0]["content"] == "Show the event."
    assert captured["context_sources"][0]["document_type"] == "market_event"


def test_chat_returns_not_found_for_unknown_event(client):
    response = client.post(
        "/api/chat",
        json={"question": "What happened?", "event_id": "UNKNOWN"},
    )
    assert response.status_code == 404


def test_chat_retrieves_named_company_correlation_with_sample_size(client, monkeypatch):
    from storage.duckdb import get_connection

    conn = get_connection()
    conn.execute(
        "INSERT INTO companies (ticker, company_name, relationship_type) VALUES ('F', 'Ford Motor Company', 'oem')"
    )
    conn.execute(
        """
        INSERT INTO correlations
            (ticker, reference_ticker, pearson_correlation, pearson_p_value, pearson_ci_low,
             pearson_ci_high, spearman_correlation, beta, r_squared, sample_size)
        VALUES ('F', 'STLA', 0.71, 0.001, 0.58, 0.81, 0.66, 0.92, 0.50, 42)
        """
    )
    conn.close()
    captured = {}

    def fake_answer_question(question, context_sources, history):
        captured["sources"] = context_sources
        return {"answer": "Ford and STLA have observed daily-return co-movement [1].", "sources": context_sources}

    monkeypatch.setattr("api.services.chat_service.answer_question", fake_answer_question)
    response = client.post("/api/chat", json={"question": "What is Ford's correlation with STLA?"})

    assert response.status_code == 200
    body = response.get_json()
    stats = next(source for source in captured["sources"] if source["document_type"] == "statistical_relationship")
    assert "sample size n=42" in stats["text"]
    assert body["visual"]["labels"] == ["F"]
    assert body["visual"]["values"] == [0.71]


def test_search_requires_valid_body(client):
    response = client.post("/api/search", json={})
    assert response.status_code == 400

    response = client.post("/api/search", json={"query": "Stellantis"})
    assert response.status_code == 200


def test_dashboard_executive_overview_page_renders(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Executive Overview" in response.data


def test_dashboard_event_explorer_page_renders(client):
    response = client.get("/events")
    assert response.status_code == 200
    assert b"Event Explorer" in response.data
    assert b"Filter by date, event type, severity, or classification" in response.data


def test_ai_investigation_renders_chat_without_running_agent(client, monkeypatch):
    monkeypatch.setattr(
        "api.services.investigation_service.investigate",
        lambda *_: pytest.fail("Opening the chat page must not run an investigation."),
    )

    response = client.get("/investigate")

    assert response.status_code == 200
    assert b"STLA Investigation Copilot" in response.data
    assert b"/api/chat" in response.data
    assert b"marked.parse" in response.data
    assert b"Knowledge base" in response.data
    assert b"HTTP 403" in response.data


def test_dashboard_impact_analysis_page_renders(client):
    response = client.get("/events/STLA-2026-01-01")
    assert response.status_code == 200
    assert b"Impact Analysis" in response.data


def test_dashboard_impact_analysis_404_for_unknown_event(client):
    response = client.get("/events/UNKNOWN")
    assert response.status_code == 404


def test_system_status_counts_market_events(client):
    response = client.get("/status")
    assert response.status_code == 200
    assert b"Detected events" in response.data
    assert b">1<" in response.data


def test_event_report_uses_event_id_and_preserves_missing_benchmarks(client, monkeypatch):
    called = {}

    def fake_find_similar_events(event_id, top_n):
        called["event_id"] = event_id
        called["top_n"] = top_n
        return []

    monkeypatch.setattr("reports.generator.find_similar_events", fake_find_similar_events)

    response = client.get("/api/reports/event/STLA-2026-01-01")

    assert response.status_code == 200
    report = response.get_json()
    assert called == {"event_id": "STLA-2026-01-01", "top_n": 3}
    assert report["market_context"]["market_adjusted_return"] is None
    assert "Data unavailable" in report["market_context"]["interpretation"]
    assert "Market benchmark data unavailable for context" in report["uncertainties"]
