"""Business report generator (Phase 25).

Generates professional market impact reports for significant STLA events.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from api.services import event_service, relationship_service
from relationships.combined_profile import build_all_combined_profiles
from relationships.graph import build_graph
from events.similarity import find_similar_events


def generate_event_report(event_id: str) -> dict[str, Any]:
    """Generate a comprehensive business report for a STLA event.
    
    Args:
        event_id: Event identifier
        
    Returns:
        Structured report dictionary
    """
    event = event_service.get_event_by_id(event_id)
    if not event:
        return {"error": "Event not found"}
    
    impact = event_service.get_event_impact(event_id)
    affected_companies = (impact or {}).get("impact", [])
    
    graph = build_graph()
    combined_profiles = build_all_combined_profiles(graph, event_id=event_id)
    
    # Find similar historical events
    similar_events = find_similar_events(event_id, top_n=3)
    similar_dates = {
        historical["event_id"]: historical["event_date"]
        for historical in event_service.get_all_events("STLA")
    }

    market_return = event.get("market_return")
    sector_return = event.get("sector_return")
    
    report = {
        "report_id": f"STLA-REPORT-{event_id}",
        "generated_at": datetime.now().isoformat(),
        "event_summary": {
            "event_id": event_id,
            "date": event["event_date"],
            "type": event.get("event_type", "Unclassified"),
            "severity": event.get("severity", "Unknown"),
            "stla_movement": event["return"],
        },
        "market_context": {
            "stla_return": event["return"],
            "market_return": market_return,
            "sector_return": sector_return,
            "market_adjusted_return": event["return"] - market_return if market_return is not None else None,
            "interpretation": _interpret_market_context(event)
        },
        "catalyst": {
            "classification": event.get("classification", "Not yet analyzed"),
            "description": event.get("event_description", ""),
            "source": event.get("source", "Market data")
        },
        "affected_companies": [
            {
                "name": c["name"],
                "ticker": c.get("ticker"),
                "relationship": c["relationship_type"],
                "relationship_strength": c["relationship_strength"],
                "historical_sensitivity": c.get("historical_event_sensitivity", "Unknown"),
                "current_reaction": c.get("current_event_reaction"),
                "exposure_score": c.get("ecosystem_exposure_score", 0),
                "evidence": c.get("evidence_url")
            }
            for c in affected_companies[:10]  # Top 10
        ],
        "business_connections": [
            {
                "company": c["name"],
                "relationship": c["relationship_type"],
                "strength": c["relationship_strength"],
                "evidence": c.get("evidence_url") or c.get("evidence_source")
            }
            for c in combined_profiles[:5]  # Top 5 documented relationships
        ],
        "historical_precedent": [
            {
                "event_date": similar_dates.get(e["event_id"]),
                "similarity_score": e.get("similarity", 0),
                "stla_movement": e["stla_return"],
                "event_type": e.get("event_type", "Unclassified")
            }
            for e in similar_events
        ],
        "key_findings": _generate_key_findings(event, affected_companies),
        "uncertainties": _generate_uncertainties(event, affected_companies),
        "metadata": {
            "report_version": "1.0",
            "analysis_date": datetime.now().isoformat(),
            "data_sources": ["Market data", "Corporate relationships", "Event database"]
        }
    }
    
    return report


def _interpret_market_context(event: dict) -> str:
    """Describe benchmark differences without implying a causal explanation."""
    stla_return = event["return"]
    market_return = event.get("market_return")
    sector_return = event.get("sector_return")
    if market_return is None and sector_return is None:
        return "Data unavailable: neither market nor sector benchmark is available for comparison."

    market_gap = abs(stla_return - market_return) if market_return is not None else None
    sector_gap = abs(stla_return - sector_return) if sector_return is not None else None
    if market_gap is not None and market_gap < 0.02 and sector_gap is not None and sector_gap < 0.02:
        return "STLA moved within 2 percentage points of both available benchmarks; this does not establish a cause."
    if sector_gap is not None and sector_gap < 0.02:
        return "STLA moved within 2 percentage points of the sector benchmark; this does not establish a cause."
    if market_gap is not None and market_gap < 0.02:
        return "STLA moved within 2 percentage points of the market benchmark; this does not establish a cause."
    return "STLA diverged from the available benchmark return(s); the difference alone does not identify a cause."


def _generate_key_findings(event: dict, affected_companies: list) -> list[str]:
    """Generate key findings from the analysis."""
    findings = []
    
    # Event magnitude
    if abs(event["return"]) > 0.05:
        direction = "declined" if event["return"] < 0 else "increased"
        findings.append(
            f"STLA {direction} {abs(event['return'])*100:.1f}% on {event['event_date']}, "
            f"classified as {event.get('severity', 'significant')} event"
        )
    
    # Documented relationships
    high_sensitivity = [c for c in affected_companies 
                       if c.get("historical_event_sensitivity") == "High"]
    if high_sensitivity:
        findings.append(
            f"{len(high_sensitivity)} companies with documented relationships showed "
            f"high historical sensitivity to similar events"
        )
    
    # Market context
    market_return = event.get("market_return")
    if market_return is not None and abs(event["return"] - market_return) > 0.03:
        findings.append(
            f"STLA's return differed from the broad market by "
            f"{abs(event['return'] - market_return)*100:.1f} percentage points; this difference does not establish attribution."
        )
    
    return findings


def _generate_uncertainties(event: dict, affected_companies: list) -> list[str]:
    """Document analysis uncertainties."""
    uncertainties = []
    
    if not event.get("classification"):
        uncertainties.append("Event catalyst not yet definitively identified")
    
    if event.get("market_return") is None:
        uncertainties.append("Market benchmark data unavailable for context")

    if event.get("sector_return") is None:
        uncertainties.append("Sector benchmark data unavailable for context")
    
    insufficient_data = [c for c in affected_companies 
                        if c.get("historical_correlation") == "Insufficient data"]
    if insufficient_data:
        uncertainties.append(
            f"{len(insufficient_data)} companies lack sufficient historical data "
            f"for robust statistical analysis"
        )
    
    if not affected_companies:
        uncertainties.append("No companies with documented relationships identified")
    
    return uncertainties


def format_report_text(report: dict) -> str:
    """Format report as readable text."""
    lines = [
        "=" * 80,
        "STELLANTIS MARKET IMPACT REPORT",
        "=" * 80,
        "",
        f"Report ID: {report['report_id']}",
        f"Generated: {report['generated_at']}",
        "",
        "EVENT SUMMARY",
        "-" * 80,
        f"Date: {report['event_summary']['date']}",
        f"Type: {report['event_summary']['type']}",
        f"Severity: {report['event_summary']['severity']}",
        f"STLA Movement: {report['event_summary']['stla_movement']*100:.2f}%",
        "",
        "MARKET CONTEXT",
        "-" * 80,
        f"STLA Return: {report['market_context']['stla_return']*100:.2f}%",
        f"Market Return: {report['market_context']['market_return']*100:.2f}%"
        if report["market_context"]["market_return"] is not None
        else "Market Return: Data unavailable",
        f"Sector Return: {report['market_context']['sector_return']*100:.2f}%"
        if report["market_context"]["sector_return"] is not None
        else "Sector Return: Data unavailable",
        f"Market-Adjusted Return: {report['market_context']['market_adjusted_return']*100:.2f}%"
        if report["market_context"]["market_adjusted_return"] is not None
        else "Market-Adjusted Return: Data unavailable",
        "",
        f"Interpretation: {report['market_context']['interpretation']}",
        "",
    ]
    
    if report["affected_companies"]:
        lines.extend([
            "POTENTIALLY AFFECTED COMPANIES",
            "-" * 80,
        ])
        for company in report["affected_companies"][:5]:
            lines.extend([
                f"\n{company['name']} ({company.get('ticker', 'N/A')})",
                f"  Relationship: {company['relationship']} ({company['relationship_strength']})",
                f"  Historical Sensitivity: {company['historical_sensitivity']}",
                f"  Exposure Score: {company['exposure_score']}/100",
            ])
        lines.append("")
    
    if report["key_findings"]:
        lines.extend([
            "KEY FINDINGS",
            "-" * 80,
        ])
        for i, finding in enumerate(report["key_findings"], 1):
            lines.append(f"{i}. {finding}")
        lines.append("")
    
    if report["uncertainties"]:
        lines.extend([
            "UNCERTAINTIES",
            "-" * 80,
        ])
        for i, uncertainty in enumerate(report["uncertainties"], 1):
            lines.append(f"{i}. {uncertainty}")
        lines.append("")
    
    lines.extend([
        "=" * 80,
        "This is a market intelligence / research tool only.",
        "Not an investment recommendation system.",
        "=" * 80,
    ])
    
    return "\n".join(lines)
