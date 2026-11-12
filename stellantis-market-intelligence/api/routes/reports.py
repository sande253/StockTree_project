"""Reports API routes (Phase 25)."""
from __future__ import annotations

from flask import Blueprint, jsonify, request, Response

from reports.generator import generate_event_report, format_report_text

reports_bp = Blueprint("reports", __name__)


@reports_bp.get("/reports/event/<event_id>")
def get_event_report(event_id: str):
    """Generate and return a structured business report for an event.
    
    Query params:
        format: 'json' (default) or 'text'
    """
    report = generate_event_report(event_id)
    
    if "error" in report:
        return jsonify(report), 404
    
    format_type = request.args.get('format', 'json')
    
    if format_type == 'text':
        text_report = format_report_text(report)
        return Response(text_report, mimetype='text/plain')
    
    return jsonify(report)
