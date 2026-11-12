"""POST /investigate."""

from __future__ import annotations

from flask import Blueprint, jsonify, request
from pydantic import ValidationError

from api.models import InvestigateRequest
from api.services import investigation_service

investigate_bp = Blueprint("investigate", __name__)


@investigate_bp.post("/investigate")
def investigate():
    try:
        payload = InvestigateRequest.model_validate(request.get_json(force=True, silent=True) or {})
    except ValidationError as exc:
        return jsonify({"error": "Invalid request", "details": exc.errors()}), 400

    result = investigation_service.investigate(payload.event_id)
    if result is None:
        return jsonify({"error": f"Unknown event_id {payload.event_id!r}"}), 404
    return jsonify(result)
