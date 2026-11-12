"""POST /chat - evidence-grounded investigation conversation."""

from __future__ import annotations

from flask import Blueprint, jsonify, request
from pydantic import ValidationError

from api.models import ChatRequest
from api.services import chat_service

chat_bp = Blueprint("chat", __name__)


@chat_bp.post("/chat")
def chat():
    try:
        payload = ChatRequest.model_validate(request.get_json(force=True, silent=True) or {})
    except ValidationError as exc:
        return jsonify({"error": "Invalid request", "details": exc.errors()}), 400

    result = chat_service.ask(
        payload.question.strip(),
        event_id=payload.event_id,
        history=[turn.model_dump() for turn in payload.history],
    )
    if result is None:
        return jsonify({"error": f"Unknown event_id {payload.event_id!r}"}), 404
    return jsonify(result)
