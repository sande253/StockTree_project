"""GET /events, GET /events/<event_id>, GET /events/<event_id>/impact."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from api.services import event_service

events_bp = Blueprint("events", __name__)


@events_bp.get("/events")
def list_events():
    ticker = request.args.get("ticker", "STLA")
    return jsonify(event_service.get_all_events(ticker=ticker))


@events_bp.get("/events/<event_id>")
def get_event(event_id: str):
    event = event_service.get_event_by_id(event_id)
    if event is None:
        return jsonify({"error": f"Unknown event_id {event_id!r}"}), 404
    return jsonify(event)


@events_bp.get("/events/<event_id>/impact")
def get_event_impact(event_id: str):
    impact = event_service.get_event_impact(event_id)
    if impact is None:
        return jsonify({"error": f"Unknown event_id {event_id!r}"}), 404
    return jsonify(impact)


@events_bp.get("/events/<event_id>/timeline")
def get_event_timeline(event_id: str):
    timeline = event_service.get_event_timeline(event_id)
    if timeline is None:
        return jsonify({"error": "Unknown event"}), 404
    return jsonify(timeline)
