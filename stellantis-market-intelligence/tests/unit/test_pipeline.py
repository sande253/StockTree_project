"""Deterministic readiness and pipeline failure checks; no network calls."""

from datetime import date
from pathlib import Path

import pytest

from ingestion.pipeline import run_pipeline
from ingestion.quality import check_data_quality


@pytest.fixture(autouse=True)
def project_directory(monkeypatch):
    monkeypatch.chdir(Path(__file__).resolve().parents[2])


def test_empty_warehouse_is_not_ready(tmp_path, monkeypatch):
    monkeypatch.setattr("ingestion.quality.configured_tickers", lambda: ["STLA", "^GSPC", "CARZ"])
    result = check_data_quality(tmp_path / "empty.duckdb", today=date(2026, 10, 29))
    assert result["status"] == "degraded"
    assert len(result["coverage"]) == 3
    assert any("STLA: only 0" in issue for issue in result["issues"])
    assert any("No recent Stellantis" in issue for issue in result["issues"])
    assert result["counts"]["market_events"] == 0
    assert result["coverage"][0]["status"] == "degraded"
    assert result["coverage"][0]["reference_ticker"] == "^GSPC"
    assert result["coverage"][0]["issues"]


def test_pipeline_refuses_concurrent_run(tmp_path):
    warehouse = tmp_path / "market.duckdb"
    warehouse.with_suffix(".duckdb.pipeline.lock").touch()
    with pytest.raises(RuntimeError, match="Another refresh is active"):
        run_pipeline(db_path=warehouse, report_path=tmp_path / "report.json")


def test_pipeline_rejects_insufficient_lookback(tmp_path):
    with pytest.raises(ValueError, match="at least 120"):
        run_pipeline(days=30, db_path=tmp_path / "market.duckdb")


def test_pipeline_reports_locked_database_and_releases_lock(tmp_path, monkeypatch):
    import json

    def fail_connection(*args, **kwargs):
        raise OSError("database is locked")

    monkeypatch.setattr("ingestion.pipeline.get_connection", fail_connection)
    warehouse = tmp_path / "market.duckdb"
    report = tmp_path / "report.json"
    result = run_pipeline(db_path=warehouse, report_path=report)
    assert result["status"] == "failed"
    assert "Stop the application" in result["error"]
    assert not warehouse.with_suffix(".duckdb.pipeline.lock").exists()
    assert json.loads(report.read_text())["status"] == "failed"


@pytest.mark.parametrize("fail_prices", [False, True])
def test_pipeline_stage_order_and_partial_failure(tmp_path, monkeypatch, fail_prices):
    calls = []

    def record(name, result=None):
        def action(*args, **kwargs):
            calls.append(name)
            if name == "prices" and fail_prices:
                raise RuntimeError("provider unavailable")
            return result
        return action

    monkeypatch.setattr("ingestion.pipeline.configured_tickers", lambda: ["STLA"])
    monkeypatch.setattr("storage.load_companies.upsert_companies", record("companies", 1))
    monkeypatch.setattr("relationships.graph.load_and_store_relationships", record("relationships", 1))
    monkeypatch.setattr("ingestion.market_data.ingest_price_history", record("prices", {"rows_ingested": 90}))
    monkeypatch.setattr("ingestion.news.ingest_all_sources", record("news", {
        "sources_configured": 1, "sources_failed": [], "articles_persisted": 3,
    }))
    monkeypatch.setattr("analytics.features.compute_and_store_price_features", record("features", 90))
    monkeypatch.setattr("analytics.correlation.compute_and_store_universe_correlations", record("correlations", {"skipped": []}))
    monkeypatch.setattr("events.detector.detect_and_store_events", record("events", 0))
    monkeypatch.setattr("events.detector.enrich_events", record("context"))
    monkeypatch.setattr("events.fingerprint.build_and_store_fingerprints", record("fingerprints", 0))
    monkeypatch.setattr("ai.vector_store.build_vector_store", record("index", {"chunks": 10}))
    monkeypatch.setattr("ingestion.pipeline.check_data_quality", record("quality", {"status": "ready"}))
    result = run_pipeline(db_path=tmp_path / "test.duckdb", report_path=tmp_path / "report.json")
    assert calls == ["companies", "relationships", "prices", "news", "features", "correlations",
                     "events", "context", "fingerprints", "index", "quality"]
    assert result["status"] == ("degraded" if fail_prices else "succeeded")
    if fail_prices:
        failed = next(entry for entry in result["stages"] if entry["name"] == "prices:STLA")
        assert failed["status"] == "failed"
        assert failed["error"] == "provider unavailable"


def test_legacy_single_ticker_command_calls_real_ingestor(monkeypatch):
    import sys
    from scripts import ingest_market_data

    calls = []
    monkeypatch.setattr(ingest_market_data, "ingest_price_history", lambda **kwargs: calls.append(kwargs))
    monkeypatch.setattr(sys, "argv", ["ingest_market_data", "--ticker", "STLA", "--days", "180"])
    ingest_market_data.main()
    assert calls[0]["ticker"] == "STLA"
    assert calls[0]["interval"] == "1d"
    assert "start" in calls[0] and "end" in calls[0]
    companies = ingest_market_data.load_companies()
    assert any(company["ticker"] == "ON" for company in companies)