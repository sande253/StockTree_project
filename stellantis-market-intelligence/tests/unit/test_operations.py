"""Recovery and scheduled-maintenance safety checks."""

import duckdb
import pytest

from storage.backup import backup_warehouse, restore_warehouse, verify_backup
from storage.duckdb import get_connection


def test_backup_restore_round_trip(tmp_path):
    source = tmp_path / "source.duckdb"
    conn = get_connection(source)
    conn.execute("INSERT INTO companies (ticker, company_name, relationship_type) VALUES ('STLA', 'Stellantis', 'self')")
    conn.close()
    backup = backup_warehouse(source, tmp_path / "backups", index_dir=None)
    assert verify_backup(backup["path"])["files"]
    restored = tmp_path / "restored.duckdb"
    result = restore_warehouse(backup["path"], restored)
    assert result["tables"] >= 10
    conn = duckdb.connect(str(restored))
    try:
        assert conn.execute("SELECT ticker FROM companies").fetchall() == [("STLA",)]
    finally:
        conn.close()
    with pytest.raises(FileExistsError):
        restore_warehouse(backup["path"], restored)


def test_backup_detects_tampering(tmp_path):
    backup = backup_warehouse(tmp_path / "source.duckdb", tmp_path / "backups", index_dir=None)
    from pathlib import Path

    schema = Path(backup["path"]) / "warehouse" / "schema.sql"
    schema.write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="verification failed"):
        verify_backup(backup["path"])


def test_browser_dependencies_are_pinned(tmp_path):
    from scripts.audit_browser_dependencies import collect_dependencies

    template = tmp_path / "test.html"
    template.write_text('<script src="https://cdn.jsdelivr.net/npm/dompurify@3.4.17/dist/purify.min.js"></script>')
    assert collect_dependencies(tmp_path)[0]["version"] == "3.4.17"
    template.write_text('<script src="https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js"></script>')
    with pytest.raises(ValueError, match="exact version"):
        collect_dependencies(tmp_path)


def test_report_publication_with_concurrent_readers(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from storage.artifacts import read_json, write_json

    report = tmp_path / "latest.json"
    write_json(report, {"status": "running"})

    def update(index):
        write_json(report, {"status": "running", "iteration": index})
        return read_json(report)["status"]

    with ThreadPoolExecutor(max_workers=8) as executor:
        assert all(status == "running" for status in executor.map(update, range(150)))


def test_maintenance_runs_in_process_and_rejects_overlap(tmp_path, monkeypatch):
    import threading
    from flask import Flask
    from api.maintenance import MaintenanceManager

    started = threading.Event()
    release = threading.Event()

    def refresh(**kwargs):
        started.set()
        assert release.wait(5)
        return {"status": "succeeded"}

    monkeypatch.setattr("ingestion.pipeline.run_pipeline", refresh)
    manager = MaintenanceManager(Flask(__name__), tmp_path)
    try:
        manager.submit()
        assert started.wait(5)
        with pytest.raises(RuntimeError, match="already running"):
            manager.submit()
        release.set()
        manager.future.result(timeout=5)
        assert manager.snapshot()["status"] == "succeeded"
        assert (tmp_path / "maintenance-latest.json").exists()
    finally:
        release.set()
        manager.shutdown()


def test_failed_maintenance_emits_persistent_alert(tmp_path, monkeypatch):
    from flask import Flask
    from api.maintenance import MaintenanceManager

    monkeypatch.setattr("ingestion.pipeline.run_pipeline", lambda **kwargs: {"status": "degraded"})
    manager = MaintenanceManager(Flask(__name__), tmp_path)
    try:
        manager.submit()
        manager.future.result(timeout=5)
        assert manager.snapshot()["status"] == "degraded"
        assert '"status": "degraded"' in (tmp_path / "alerts.jsonl").read_text()
    finally:
        manager.shutdown()