"""Run the dependency-ordered refresh with durable, truthful stage reporting."""

from __future__ import annotations

import argparse
import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from ingestion.quality import check_data_quality, configured_tickers
from storage.duckdb import get_connection

logger = logging.getLogger(__name__)
DEFAULT_REPORT = Path("data/reports/pipeline-latest.json")


def _write_report(report: dict[str, Any], path: Path) -> None:
    from storage.artifacts import write_json

    write_json(path, report)


def run_pipeline(
    *,
    days: int = 365,
    full: bool = False,
    db_path: Path | str | None = None,
    report_path: Path | str = DEFAULT_REPORT,
    backup_before: bool = True,
) -> dict[str, Any]:
    if days < 120:
        raise ValueError("Use at least 120 calendar days for the 60-session analytics warm-up")
    from storage.duckdb import get_duckdb_path

    warehouse = Path(db_path) if db_path is not None else get_duckdb_path()
    existing_warehouse = warehouse.exists()
    warehouse.parent.mkdir(parents=True, exist_ok=True)
    lock_path = warehouse.with_suffix(warehouse.suffix + ".pipeline.lock")
    report_path = Path(report_path)
    report: dict[str, Any] = {
        "run_id": uuid4().hex, "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "warehouse": str(warehouse.resolve()), "stages": [],
    }
    try:
        lock = lock_path.open("x", encoding="utf-8")
    except FileExistsError as exc:
        raise RuntimeError(
            f"Another refresh is active ({lock_path}). If a previous run crashed, "
            "verify it has stopped before removing this lock."
        ) from exc

    def stage(name: str, action: Callable[[], Any]) -> Any:
        entry: dict[str, Any] = {"name": name, "status": "running"}
        report["stages"].append(entry)
        _write_report(report, report_path)
        logger.info("Starting %s", name)
        try:
            result = action()
            entry.update(status="succeeded", result=result)
            return result
        except Exception as exc:
            entry.update(status="failed", error=str(exc))
            logger.exception("Stage %s failed", name)
            return None
        finally:
            _write_report(report, report_path)

    try:
        with lock:
            lock.write(report["run_id"])
            lock.flush()
            try:
                conn = get_connection(warehouse)
                conn.close()
            except Exception as exc:
                raise RuntimeError(
                    "Cannot open the warehouse for refresh. Stop the application first if it "
                    "holds a DuckDB lock, then retry."
                ) from exc

            from storage.load_companies import load_companies_config, upsert_companies
            from relationships.graph import load_and_store_relationships
            from ingestion.market_data import ingest_price_history
            from ingestion.news import ingest_all_sources
            from analytics.features import compute_and_store_price_features
            from analytics.correlation import compute_and_store_universe_correlations
            from events.detector import detect_and_store_events, enrich_events
            from analytics.event_study import run_event_study
            from events.fingerprint import build_and_store_fingerprints
            from ai.vector_store import build_vector_store

            if backup_before and existing_warehouse:
                from storage.backup import backup_warehouse, verify_backup

                def create_backup():
                    result = backup_warehouse(warehouse)
                    verify_backup(result["path"])
                    return result

                if stage("backup", create_backup) is None:
                    raise RuntimeError("Pre-refresh backup failed; refresh aborted without changing data")

            stage("companies", lambda: upsert_companies(load_companies_config(), db_path=warehouse))
            stage("relationships", lambda: load_and_store_relationships(db_path=warehouse))
            today = date.today()
            for ticker in configured_tickers():
                start = today - timedelta(days=days)
                conn = get_connection(warehouse)
                try:
                    count, latest = conn.execute(
                        "SELECT count(*), max(date) FROM price_data WHERE ticker = ? AND interval = '1d'",
                        [ticker],
                    ).fetchone()
                finally:
                    conn.close()
                if not full and count >= 60 and latest is not None:
                    start = max(start, min(latest - timedelta(days=7), today - timedelta(days=7)))
                stage(f"prices:{ticker}", lambda ticker=ticker, start=start: ingest_price_history(
                    ticker, start.isoformat(), today.isoformat(), db_path=warehouse
                ))

            news = stage("news", lambda: ingest_all_sources(db_path=warehouse))
            if news is not None and (
                not news["sources_configured"] or news["sources_failed"] or not news["articles_persisted"]
            ):
                report["stages"][-1].update(status="degraded", error="Some feeds failed or returned no articles")

            for ticker in configured_tickers():
                stage(f"features:{ticker}", lambda ticker=ticker: compute_and_store_price_features(
                    ticker, db_path=warehouse
                ))
            correlations = stage("correlations", lambda: compute_and_store_universe_correlations(db_path=warehouse))
            if correlations is not None and correlations["skipped"]:
                report["stages"][-1].update(status="degraded", error=f"Skipped: {correlations['skipped']}")
            stage("events", lambda: detect_and_store_events("STLA", db_path=warehouse))
            conn = get_connection(warehouse)
            try:
                event_ids = [row[0] for row in conn.execute(
                    "SELECT event_id FROM market_events WHERE ticker = 'STLA' ORDER BY event_date"
                ).fetchall()]
            finally:
                conn.close()
            for event_id in event_ids:
                stage(f"event-study:{event_id}", lambda event_id=event_id: run_event_study(
                    event_id, db_path=warehouse
                ))
            stage("event-context", lambda: enrich_events("STLA", db_path=warehouse))
            stage("fingerprints", lambda: build_and_store_fingerprints(db_path=warehouse))
            stage("search-index", lambda: build_vector_store(db_path=warehouse))
            quality = stage("quality", lambda: check_data_quality(warehouse))
            report["quality"] = quality
            report["status"] = "succeeded" if (
                quality is not None and quality["status"] == "ready"
                and all(entry["status"] == "succeeded" for entry in report["stages"])
            ) else "degraded"
    except Exception as exc:
        report.update(status="failed", error=str(exc))
        logger.exception("Pipeline failed")
    finally:
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        try:
            _write_report(report, report_path)
            _write_report(report, report_path.parent / f"pipeline-{report['run_id']}.json")
        finally:
            lock_path.unlink(missing_ok=True)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--full", action="store_true", help="Re-download the full lookback instead of an overlap")
    parser.add_argument("--check-only", action="store_true", help="Check stored data without fetching providers")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.check_only:
        quality = check_data_quality()
        print(json.dumps(quality, indent=2))
        return 0 if quality["status"] == "ready" else 1
    result = run_pipeline(days=args.days, full=args.full)
    print(json.dumps(result, indent=2, default=str))
    return 0 if result["status"] == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())