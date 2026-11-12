"""GET /prices/<ticker>."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from api.services import price_service

prices_bp = Blueprint("prices", __name__)


@prices_bp.get("/prices/<ticker>")
def get_prices(ticker: str):
    start = request.args.get("start")
    end = request.args.get("end")
    prices = price_service.get_prices(ticker, start=start, end=end)
    if not prices:
        return jsonify({"error": f"No price data found for {ticker!r}"}), 404
    return jsonify(prices)
