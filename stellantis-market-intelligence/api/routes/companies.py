"""GET /companies, GET /companies/<ticker>."""

from __future__ import annotations

from flask import Blueprint, jsonify

from api.services import company_service

companies_bp = Blueprint("companies", __name__)


@companies_bp.get("/companies")
def list_companies():
    return jsonify(company_service.get_all_companies())


@companies_bp.get("/companies/<ticker>")
def get_company(ticker: str):
    company = company_service.get_company_by_ticker(ticker)
    if company is None:
        return jsonify({"error": f"Unknown ticker {ticker!r}"}), 404
    return jsonify(company)
