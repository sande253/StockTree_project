"""Dashboard routes (Phase 23) - server-rendered HTML pages, Flask + Jinja2, no JS framework.

All 7 pages from the master prompt: Executive Overview, Event Explorer, Impact Analysis,
Ecosystem Graph, Historical Events, AI Investigation, Evidence (+ a bonus System Status
page). Calls the same service layer as the JSON API (api/services/*) directly.
"""

from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, abort, render_template, request

from api.services import chat_service, event_service, historical_service, relationship_service, search_service
from api.services import price_service
from relationships.business_profile import build_all_profiles
from relationships.combined_profile import build_all_combined_profiles
from relationships.graph import build_graph

dashboard_bp = Blueprint(
    "dashboard", __name__, template_folder="templates", static_folder="static", static_url_path="/static/dashboard"
)

SENSITIVITY_RANK = {"High": 3, "Medium": 2, "Low": 1}


def _price_series(ticker: str, start=None, end=None, limit: int | None = None) -> list[dict]:
    """STLA price history as JSON-chart-ready {date, close} points (date coerced to plain string)."""
    kwargs = {}
    if start is not None:
        kwargs["start"] = start.strftime("%Y-%m-%d")
    if end is not None:
        kwargs["end"] = end.strftime("%Y-%m-%d")
    prices = price_service.get_prices(ticker, **kwargs)
    if limit:
        prices = prices[-limit:]
    return [{"date": p["date"].strftime("%Y-%m-%d"), "close": p["close"]} for p in prices if p.get("close") is not None]


@dashboard_bp.context_processor
def _inject_ticker():
    """Latest stored STLA close shown under the topbar on every dashboard page."""
    ticker = None
    try:
        prices = [p for p in price_service.get_prices("STLA") if p.get("close") is not None]
        if prices:
            latest = prices[-1]
            prev = prices[-2] if len(prices) > 1 else None
            change = (latest["close"] - prev["close"]) if prev else 0.0
            change_pct = (change / prev["close"] * 100) if prev and prev["close"] else 0.0
            ticker = {
                "price": latest["close"],
                "change": change,
                "change_pct": change_pct,
                "date": latest["date"].strftime("%Y-%m-%d"),
            }
    except Exception:
        ticker = None
    return {"ticker": ticker}


@dashboard_bp.get("/")
def executive_overview():
    events = event_service.get_all_events("STLA")
    latest_event = events[0] if events else None

    graph = build_graph()
    all_relationships = build_all_profiles(graph)

    top_sensitivities: list[dict] = []
    if latest_event is not None:
        combined = build_all_combined_profiles(graph, event_id=latest_event["event_id"])
        ranked = [c for c in combined if c["historical_event_sensitivity"] in SENSITIVITY_RANK]
        top_sensitivities = sorted(
            ranked, key=lambda c: SENSITIVITY_RANK[c["historical_event_sensitivity"]], reverse=True
        )[:5]

    price_history = _price_series("STLA", limit=90)

    return render_template(
        "executive_overview.html",
        latest_event=latest_event,
        num_affected=len(all_relationships),
        top_relationships=all_relationships[:5],
        top_sensitivities=top_sensitivities,
        price_history=price_history,
    )


@dashboard_bp.get("/events")
def event_explorer():
    events = event_service.get_all_events("STLA")
    return render_template("event_explorer.html", events=events)


@dashboard_bp.get("/events/<event_id>")
def impact_analysis(event_id: str):
    event = event_service.get_event_by_id(event_id)
    if event is None:
        abort(404)
    impact = event_service.get_event_impact(event_id)
    window_prices = _price_series(
        "STLA", start=event["event_date"] - timedelta(days=15), end=event["event_date"] + timedelta(days=15)
    )
    return render_template(
        "impact_analysis.html", event=event, impact=(impact or {}).get("impact", []), price_history=window_prices,
        timeline=event_service.get_event_timeline(event_id),
    )


@dashboard_bp.get("/graph")
def ecosystem_graph():
    network = relationship_service.get_network()
    relationship_types = sorted({e["relationship_type"] for e in network["edges"] if e["relationship_type"]})
    return render_template("ecosystem_graph.html", network=network, relationship_types=relationship_types)


@dashboard_bp.get("/historical")
def historical_events():
    """Page 5 - Historical Events: browse all event fingerprints + similarity search."""
    events_by_id = {e["event_id"]: e for e in event_service.get_all_events("STLA")}
    historical = historical_service.get_all_historical_events()
    for h in historical:
        h["event_date"] = events_by_id.get(h["event_id"], {}).get("event_date")
    historical.sort(key=lambda h: h["event_date"] or "", reverse=True)

    compare_id = request.args.get("event_id") or None
    similar = historical_service.get_similar_events(compare_id, top_n=5) if compare_id else []
    for s in similar:
        s["event_date"] = events_by_id.get(s["event_id"], {}).get("event_date")

    return render_template(
        "historical_events.html", historical=historical, compare_id=compare_id, similar=similar
    )


@dashboard_bp.get("/investigate")
def ai_investigation():
    """Evidence-grounded chat for questions about stored STLA events and relationships."""
    events = event_service.get_all_events("STLA")
    requested_event_id = request.args.get("event_id")
    available_ids = {event["event_id"] for event in events}
    event_id = requested_event_id if requested_event_id in available_ids else None
    if event_id is None and events:
        event_id = events[0]["event_id"]
    return render_template(
        "ai_investigation.html", events=events, selected_event_id=event_id, coverage=chat_service.get_coverage()
    )


@dashboard_bp.get("/evidence")
def evidence():
    """Page 7 - Evidence: documented relationship evidence + indexed-document search."""
    all_relationships = relationship_service.get_all_relationships()
    query = (request.args.get("q") or "").strip()
    results = search_service.search(query, top_k=10) if query else []
    return render_template("evidence.html", relationships=all_relationships, query=query, results=results)


@dashboard_bp.get("/status")
def system_status():
    """System status and monitoring page."""
    from pathlib import Path
    from datetime import datetime
    from storage.duckdb import get_connection
    from api.routes.health import get_health_status

    health = get_health_status()
    conn = None
    try:
        conn = get_connection()
        data_stats = {
            "companies": conn.execute("SELECT COUNT(DISTINCT ticker) FROM companies").fetchone()[0],
            "price_points": f"{conn.execute('SELECT COUNT(*) FROM price_data').fetchone()[0]:,}",
            "events": conn.execute("SELECT COUNT(*) FROM market_events").fetchone()[0],
            "relationships": conn.execute(
                "SELECT COUNT(*) FROM relationships WHERE lower(source) <> lower(?)",
                ["Yahoo Finance Market Data Analysis"],
            ).fetchone()[0],
        }
        from ai.vector_store import index_available

        if index_available():
            documents = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            data_stats["vector_docs"] = f"{documents:,} indexed"
        else:
            data_stats["vector_docs"] = "Not initialized"
    except Exception:
        health["status"] = "degraded"
        health["components"]["warehouse"] = {"status": "unhealthy"}
        data_stats = {
            "companies": "Data unavailable",
            "price_points": "Data unavailable",
            "events": "Data unavailable",
            "relationships": "Data unavailable",
            "vector_docs": "Data unavailable",
        }
    finally:
        if conn is not None:
            conn.close()

    def get_dir_size(path: str) -> str:
        total = 0
        try:
            directory = Path(path)
            if not directory.exists():
                return "Data unavailable"
            for entry in directory.rglob("*"):
                if entry.is_file():
                    total += entry.stat().st_size
        except OSError:
            return "Unavailable"

        for unit in ["B", "KB", "MB", "GB"]:
            if total < 1024:
                return f"{total:.1f} {unit}"
            total /= 1024.0
        return f"{total:.1f} TB"

    resources = {
        "disk_usage": get_dir_size("data"),
        "db_size": get_dir_size("data/warehouse"),
        "log_size": get_dir_size("logs")
    }

    return render_template(
        "system_status.html",
        status=health["status"],
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        components=health["components"],
        quality=health["components"].get("data", {}),
        data_stats=data_stats,
        resources=resources
    )

