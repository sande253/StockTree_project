"""GET /network."""

from __future__ import annotations

from flask import Blueprint, jsonify

from api.services import relationship_service

network_bp = Blueprint("network", __name__)


@network_bp.get("/network")
def get_network():
    return jsonify(relationship_service.get_network())
