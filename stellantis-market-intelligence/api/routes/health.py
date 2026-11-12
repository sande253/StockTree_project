"""GET /health - Enhanced health check with detailed system status."""

from __future__ import annotations

import time
from pathlib import Path

from flask import Blueprint, jsonify
import duckdb

from storage.duckdb import get_connection

health_bp = Blueprint("health", __name__)


def get_health_status() -> dict:
    """Get detailed health status for internal use."""
    health_status = {
        "status": "healthy",
        "timestamp": time.time(),
        "components": {}
    }
    
    # Check database
    try:
        conn = get_connection()
        try:
            result = conn.execute("SELECT 1").fetchone()
        finally:
            conn.close()
        health_status["components"]["database"] = {
            "status": "healthy" if result and result[0] == 1 else "degraded",
            "type": "DuckDB"
        }
    except Exception as e:
        health_status["components"]["database"] = {
            "status": "unhealthy",
            "error": str(e)
        }
        health_status["status"] = "degraded"
    
    # Check data directories
    data_dirs = ["data/raw", "data/processed", "data/warehouse", "data/vector_store"]
    missing_dirs = [d for d in data_dirs if not Path(d).exists()]
    
    health_status["components"]["storage"] = {
        "status": "healthy" if not missing_dirs else "degraded",
        "missing_directories": missing_dirs if missing_dirs else None
    }
    if missing_dirs and health_status["status"] == "healthy":
        health_status["status"] = "degraded"
    
    # Check logs directory
    logs_dir = Path("logs")
    health_status["components"]["logging"] = {
        "status": "healthy" if logs_dir.exists() else "degraded",
        "writable": logs_dir.exists() and logs_dir.is_dir()
    }
    
    # Vector store status
    from ai.vector_store import index_available

    index_exists = index_available()
    health_status["components"]["vector_store"] = {
        "status": "healthy" if index_exists else "not_initialized",
        "index_exists": index_exists
    }
    try:
        from ingestion.quality import check_data_quality

        quality = check_data_quality()
        health_status["components"]["data"] = quality
        if quality["status"] != "ready" or not index_exists:
            health_status["status"] = "degraded"
    except Exception:
        health_status["components"]["data"] = {"status": "unavailable"}
        health_status["status"] = "degraded"
    
    return health_status


@health_bp.get("/health")
def health():
    """Basic health check endpoint."""
    return jsonify({"status": "ok", "timestamp": time.time()})


@health_bp.get("/health/detailed")
def detailed_health():
    """Detailed health check with component status."""
    return jsonify(get_health_status())


@health_bp.get("/health/ready")
def readiness():
    """Readiness is distinct from process liveness: empty/stale data is not ready."""
    status = get_health_status()
    return jsonify(status), 200 if status["status"] == "healthy" else 503


