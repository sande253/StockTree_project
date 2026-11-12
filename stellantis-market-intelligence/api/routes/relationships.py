"""GET /relationships, GET /relationships/<company>."""

from __future__ import annotations

from flask import Blueprint, jsonify

from api.services import relationship_service

relationships_bp = Blueprint("relationships", __name__)


@relationships_bp.get("/relationships")
def list_relationships():
    return jsonify(relationship_service.get_all_relationships())


@relationships_bp.get("/relationships/<company>")
def get_relationships_for_company(company: str):
    relationships = relationship_service.get_relationships_for(company)
    if not relationships:
        return jsonify({"error": f"No relationships found for {company!r}"}), 404
    return jsonify(relationships)
