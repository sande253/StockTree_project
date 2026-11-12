"""GET /historical-events."""

from __future__ import annotations

from flask import Blueprint, jsonify

from api.services import historical_service

historical_bp = Blueprint("historical", __name__)


@historical_bp.get("/historical-events")
def list_historical_events():
    return jsonify(historical_service.get_all_historical_events())
