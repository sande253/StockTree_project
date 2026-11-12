"""POST /search."""

from __future__ import annotations

from flask import Blueprint, jsonify, request
from pydantic import ValidationError

from api.models import SearchRequest
from api.services import search_service

search_bp = Blueprint("search", __name__)


@search_bp.post("/search")
def search():
    try:
        payload = SearchRequest.model_validate(request.get_json(force=True, silent=True) or {})
    except ValidationError as exc:
        return jsonify({"error": "Invalid request", "details": exc.errors()}), 400

    return jsonify(search_service.search(payload.query, top_k=payload.top_k))
