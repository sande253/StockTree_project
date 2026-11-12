"""Single-process background maintenance and UTC scheduling for DuckDB."""

from __future__ import annotations

import atexit
import json
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from flask import Blueprint, current_app, jsonify, request
from storage.artifacts import read_json, write_json

logger = logging.getLogger(__name__)
maintenance_bp = Blueprint("maintenance", __name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_json(path: Path, payload: dict) -> None:
    write_json(path, payload)


def send_failure_alert(state: dict, directory: Path) -> None:
    alert = {"job_id": state["job_id"], "kind": state["kind"], "status": state["status"], "timestamp": _now()}
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "alerts.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(alert) + "\n")
    logger.error("Maintenance alert: %s", alert)
    webhook = os.getenv("ALERT_WEBHOOK_URL")
    if webhook:
        from urllib.parse import urlparse
        import requests

        if urlparse(webhook).scheme != "https":
            raise ValueError("ALERT_WEBHOOK_URL must use HTTPS")
        response = requests.post(webhook, json=alert, timeout=10, allow_redirects=False)
        response.raise_for_status()


class MaintenanceManager:
    def __init__(self, app, directory: Path | str = "data/reports"):
        self.app = app
        self.directory = Path(directory)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="maintenance")
        self.lock = threading.RLock()
        self.future = None
        self.state = {"status": "idle"}
        self.scheduler = None
        latest = self.directory / "maintenance-latest.json"
        if latest.exists():
            try:
                previous = read_json(latest)
                if previous.get("status") in {"queued", "running"}:
                    previous.update(status="interrupted", finished_at=_now())
                    _atomic_json(latest, previous)
                    send_failure_alert(previous, self.directory)
                self.state = previous
            except (OSError, ValueError, KeyError):
                logger.exception("Could not recover previous maintenance status")

    def snapshot(self) -> dict:
        with self.lock:
            return json.loads(json.dumps(self.state, default=str))

    def submit(self, kind: str = "refresh", full: bool = False) -> dict:
        if kind not in {"refresh", "backup"}:
            raise ValueError("Unsupported maintenance job")
        with self.lock:
            if self.future is not None and not self.future.done():
                raise RuntimeError("A maintenance job is already running")
            self.state = {"job_id": uuid4().hex, "kind": kind, "status": "queued", "started_at": _now()}
            _atomic_json(self.directory / "maintenance-latest.json", self.state)
            self.future = self.executor.submit(self._execute, kind, full)
            return self.snapshot()

    def _execute(self, kind: str, full: bool) -> None:
        with self.app.app_context():
            with self.lock:
                self.state["status"] = "running"
                _atomic_json(self.directory / "maintenance-latest.json", self.state)
            try:
                if kind == "refresh":
                    from ingestion.pipeline import run_pipeline

                    result = run_pipeline(full=full)
                else:
                    from storage.backup import backup_warehouse, verify_backup

                    result = backup_warehouse()
                    verify_backup(result["path"])
                cache = self.app.extensions.get("dashboard_cache")
                if cache is not None:
                    cache.clear()
                with self.lock:
                    self.state.update(status=result.get("status", "succeeded"), result=result)
            except Exception:
                logger.exception("Background maintenance failed")
                with self.lock:
                    self.state.update(status="failed", error="Maintenance failed; see server logs for details")
            finally:
                with self.lock:
                    self.state["finished_at"] = _now()
                    if self.state["status"] != "succeeded":
                        try:
                            send_failure_alert(self.state, self.directory)
                        except Exception:
                            logger.exception("Alert delivery failed")
                            self.state["alert_delivery"] = "failed"
                    _atomic_json(self.directory / "maintenance-latest.json", self.state)
                    _atomic_json(self.directory / f"maintenance-{self.state['job_id']}.json", self.state)

    def shutdown(self) -> None:
        if self.scheduler is not None:
            self.scheduler.shutdown(wait=False)
        self.executor.shutdown(wait=True)


def configure_maintenance(app) -> MaintenanceManager:
    manager = MaintenanceManager(app)
    app.extensions["maintenance"] = manager
    app.register_blueprint(maintenance_bp, url_prefix="/api")
    limiter = app.extensions["request_limiter"]
    app.view_functions["maintenance.start_maintenance"] = limiter.limit("4 per minute")(
        app.view_functions["maintenance.start_maintenance"]
    )
    if os.getenv("ENABLE_SCHEDULER", "false").lower() == "true":
        from apscheduler.schedulers.background import BackgroundScheduler

        scheduler = BackgroundScheduler(timezone="UTC")

        def scheduled_refresh():
            try:
                manager.submit()
            except RuntimeError:
                logger.warning("Scheduled refresh skipped: maintenance is busy")

        scheduler.add_job(
            scheduled_refresh, "cron", hour=int(os.getenv("REFRESH_UTC_HOUR", "6")),
            minute=int(os.getenv("REFRESH_UTC_MINUTE", "0")),
            id="daily-refresh", max_instances=1, coalesce=True, misfire_grace_time=3600,
        )
        scheduler.start()
        manager.scheduler = scheduler
    atexit.register(manager.shutdown)
    return manager


@maintenance_bp.get("/maintenance")
def maintenance_status():
    manager = current_app.extensions["maintenance"]
    state = manager.snapshot()
    state["scheduler_enabled"] = manager.scheduler is not None
    state["next_run"] = None
    if manager.scheduler is not None:
        state["next_run"] = manager.scheduler.get_job("daily-refresh").next_run_time.isoformat()
    history = []
    for path in sorted(manager.directory.glob("maintenance-*.json"), key=lambda path: path.stat().st_mtime, reverse=True):
        if path.name == "maintenance-latest.json":
            continue
        try:
            record = read_json(path)
            history.append({key: record.get(key) for key in ("job_id", "kind", "status", "started_at", "finished_at")})
        except (OSError, ValueError):
            continue
        if len(history) == 10:
            break
    pipeline = {}
    try:
        pipeline = read_json(manager.directory / "pipeline-latest.json")
    except (OSError, ValueError):
        pass
    source_results = next((stage.get("result", {}).get("source_results", []) for stage in pipeline.get("stages", []) if stage["name"] == "news" and isinstance(stage.get("result"), dict)), [])
    return jsonify({
        "current": state, "history": history, "sources": source_results,
        "pipeline": {key: pipeline.get(key) for key in ("run_id", "status", "started_at", "finished_at")},
    })


@maintenance_bp.post("/maintenance/<kind>")
def start_maintenance(kind: str):
    if not current_app.config["AUTH_ENABLED"] and request.remote_addr not in {"127.0.0.1", "::1"}:
        return jsonify({"error": "Remote maintenance requires authentication"}), 403
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict) or not isinstance(body.get("full", False), bool):
        return jsonify({"error": "full must be a boolean"}), 400
    try:
        state = current_app.extensions["maintenance"].submit(kind, full=body.get("full", False))
        return jsonify(state), 202
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 409
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400