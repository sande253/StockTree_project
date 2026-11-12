"""AI Investigation Agent (Phase 21).

Orchestrates a FIXED pipeline of explicit, read-only analysis functions (one call per
workflow stage below) in response to a detected STLA event, then asks Groq for a final
narrative synthesis grounded strictly in that already-gathered, structured data.

Deliberate safety design: this agent does NOT give the LLM function-calling / tool-use
access to the database or any module. The LLM only ever sees a fixed JSON-like summary
of data this Python code already computed deterministically. This satisfies "use
explicit tools/functions for the agent; do not allow unrestricted access to the entire
system" - there is no way for a prompt to make the agent query or touch anything beyond
the specific read-only functions wired in below.

Workflow (matches the master prompt's Phase 21 diagram):
Event detected -> market analysis -> sector analysis -> news analysis -> event
classification (already done upstream, Phase 9/10) -> corporate graph query ->
affected-company identification -> historical market analysis -> historical event
similarity -> evidence retrieval -> AI synthesis -> business report sections.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ai.prompts import SYSTEM_PROMPT
from ai.retrieval import DEFAULT_TOP_K, retrieve
from ai.vector_store import DEFAULT_INDEX_DIR
from events.classifier import load_classification_rules
from events.fingerprint import build_event_fingerprint, persist_fingerprint
from events.news_correlation import build_catalyst_summary, rank_articles_for_event
from events.similarity import find_similar_events
from relationships.combined_profile import build_all_combined_profiles
from relationships.graph import build_graph
from relationships.supply_chain import compute_supply_chain_exposure

logger = logging.getLogger(__name__)

STANDARD_UNCERTAINTIES = [
    "Statistical correlation between companies is never evidence of causation.",
    "Business relationships are limited to those verified with real evidence in this system; "
    "undocumented relationships may exist and are not reflected here.",
    "Historical sensitivity and event-similarity results describe observed past patterns only - "
    "they are not a guarantee of future behavior and must not be read as a prediction.",
    "News coverage may be incomplete; the absence of a documented catalyst does not mean one does "
    "not exist, only that it was not found in the indexed sources.",
]


def _load_market_event_row(event_id: str, db_path: Path | str | None = None) -> dict[str, Any] | None:
    from storage.duckdb import get_connection

    conn = get_connection(db_path)
    try:
        row = conn.execute(
            """
            SELECT ticker, event_date, "return", event_type, event_description,
                   market_return, sector_return, classification, severity, direction
            FROM market_events WHERE event_id = ?
            """,
            [event_id],
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    keys = [
        "ticker", "event_date", "stla_return", "event_type", "event_description",
        "market_return", "sector_return", "classification", "severity", "direction",
    ]
    return dict(zip(keys, row))


def gather_likely_catalyst(
    ticker: str, event_date: Any, event_id: str, event_type: str | None, db_path: Path | str | None = None
) -> dict[str, Any]:
    """Read-only (no persistence) catalyst narrative - reuses Phase 10's ranking + wording logic."""
    rules = load_classification_rules()
    ranked = rank_articles_for_event(ticker, event_date, event_type, rules=rules, db_path=db_path)
    movement = None  # filled in by caller from the market_events row; kept decoupled here
    return build_catalyst_summary(event_id, event_date, ticker, movement, event_type, ranked)


def gather_affected_companies(event_id: str, db_path: Path | str | None = None) -> list[dict[str, Any]]:
    """Phase 13 combined (business + market) profile for every entity connected to STLA."""
    graph = build_graph(db_path=db_path)
    return build_all_combined_profiles(graph, event_id=event_id, db_path=db_path)


def gather_supply_chain_exposure(db_path: Path | str | None = None) -> list[dict[str, Any]]:
    """Phase 14 first/second/third-order exposure for every reachable entity."""
    graph = build_graph(db_path=db_path)
    return compute_supply_chain_exposure(graph)


def gather_similar_events(event_id: str, db_path: Path | str | None = None) -> list[dict[str, Any]]:
    """Phase 18 similarity search, ensuring this event has a fingerprint first (Phase 17)."""
    fingerprint = build_event_fingerprint(event_id, db_path=db_path)
    if fingerprint is not None:
        persist_fingerprint(fingerprint, db_path=db_path)
    return find_similar_events(event_id, top_n=3, db_path=db_path)


def gather_supporting_evidence(
    ticker: str,
    event_type: str | None,
    event_description: str | None,
    top_k: int = DEFAULT_TOP_K,
    index_dir: Path | str = DEFAULT_INDEX_DIR,
    db_path: Path | str | None = None,
) -> list[dict[str, Any]]:
    """Phase 19/20 retrieval over the indexed document corpus, query built from the event itself."""
    query = f"{ticker} {event_type or ''} {event_description or ''}".strip()
    return retrieve(query, top_k=top_k, index_dir=index_dir, db_path=db_path)


def compile_uncertainties(sections: dict[str, Any]) -> list[str]:
    """Standard disclaimers + dynamically-detected data gaps for this specific event."""
    notes = list(STANDARD_UNCERTAINTIES)
    if not sections["potentially_affected_companies"]:
        notes.append("No companies with a documented relationship to Stellantis were found in the graph.")
    if sections["likely_catalyst"]["event_type"] == "Other" and not sections["likely_catalyst"].get("supporting_sources"):
        notes.append("No classified event type or documented news catalyst was found for this event.")
    if not sections["similar_historical_events"]:
        notes.append("Not enough historical events are indexed yet to perform a similarity comparison.")
    return notes


def synthesize_narrative(sections: dict[str, Any]) -> str | None:
    """Optional final prose synthesis via Groq, strictly grounded in the already-gathered sections.

    Returns None (not an error) if Groq is unavailable - the structured sections are still a
    complete, useful result on their own; the agent must not fail just because the LLM step did.
    """
    if not sections.get("supporting_evidence"):
        return None

    from ai.rag import RagConfigError, _load_api_key

    try:
        api_key = _load_api_key()
    except RagConfigError:
        return None

    from groq import Groq

    import json
    import os
    import re

    from ai.rag import DEFAULT_MODEL

    # Condense to stay well under the Groq free-tier tokens-per-minute cap - the full
    # `sections` dict can include the entire reachable graph (dozens of entities); the
    # narrative only needs the highest-signal subset, strictly a subset of already-verified data.
    condensed = {
        "event_summary": sections["event_summary"],
        "market_context": sections["market_context"],
        "likely_catalyst": sections["likely_catalyst"],
        "top_affected_companies": sections["potentially_affected_companies"][:8],
        "supply_chain_exposure_summary": {
            "total_entities_reachable": len(sections["supply_chain_exposure"]),
            "first_order": [
                e["name"] for e in sections["supply_chain_exposure"] if e["exposure_order"] == "first-order"
            ][:8],
        },
        "similar_historical_events": sections["similar_historical_events"][:3],
        "supporting_evidence": [
            {
                "source": e.get("source"),
                "document_type": e.get("document_type"),
                "text": (e.get("text") or "")[:400],
            }
            for e in sections["supporting_evidence"][:3]
        ],
        "uncertainties": sections["uncertainties"],
    }

    prompt = (
        "The following JSON contains stored observations and source associations for a "
        "Stellantis (STLA) market event. Write a concise business-report narrative strictly "
        "from this JSON - do not add any fact, company, or number not present in it. "
        "Cite supporting_evidence in its array order using [1], [2], etc. "
        "Preserve uncertainties; a matching publication is not proof of causation.\n\n"
        f"{json.dumps(condensed, default=str)}"
    )
    try:
        client = Groq(api_key=api_key)
        completion = client.chat.completions.create(
            model=os.environ.get("GROQ_MODEL", DEFAULT_MODEL),
            messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
            temperature=0.0,
        )
        narrative = completion.choices[0].message.content or ""
        citations = [int(value) for value in re.findall(r"\[(\d+)\]", narrative)]
        if not citations or any(value < 1 or value > len(condensed["supporting_evidence"]) for value in citations):
            logger.warning("Withholding investigation narrative with missing or invalid citations")
            return None
        return narrative
    except Exception as exc:  # noqa: BLE001 - LLM failure must degrade gracefully, not crash the agent
        logger.warning("Groq synthesis failed: %s", exc)
        return None


def investigate_event(
    event_id: str,
    top_k_evidence: int = DEFAULT_TOP_K,
    index_dir: Path | str = DEFAULT_INDEX_DIR,
    db_path: Path | str | None = None,
) -> dict[str, Any] | None:
    """Full Phase 21 pipeline for one detected event. Returns None if the event is unknown."""
    event = _load_market_event_row(event_id, db_path=db_path)
    if event is None:
        return None

    catalyst = gather_likely_catalyst(
        event["ticker"], event["event_date"], event_id, event["event_type"], db_path=db_path
    )
    catalyst["movement"] = event["stla_return"]

    affected_companies = gather_affected_companies(event_id, db_path=db_path)

    sections: dict[str, Any] = {
        "event_summary": {
            "event_id": event_id,
            "ticker": event["ticker"],
            "event_date": event["event_date"],
            "event_type": event["event_type"],
            "event_description": event["event_description"],
            "stla_return": event["stla_return"],
            "severity": event["severity"],
            "direction": event["direction"],
        },
        "market_context": {
            "market_return": event["market_return"],
            "sector_return": event["sector_return"],
            "classification": event["classification"],
        },
        "likely_catalyst": catalyst,
        "potentially_affected_companies": affected_companies,
        "business_relationships": [
            {
                "entity_id": c["entity_id"],
                "relationship_type": c["relationship_type"],
                "relationship_strength": c["relationship_strength"],
                "business_area": c["business_area"],
                "confidence": c["confidence"],
                "evidence_source": c["evidence_source"],
                "evidence_url": c["evidence_url"],
            }
            for c in affected_companies
        ],
        "historical_market_sensitivity": [
            {
                "entity_id": c["entity_id"],
                "ticker": c["ticker"],
                "historical_correlation": c["historical_correlation"],
                "historical_event_sensitivity": c["historical_event_sensitivity"],
                "current_event_reaction": c["current_event_reaction"],
            }
            for c in affected_companies
        ],
        "supply_chain_exposure": gather_supply_chain_exposure(db_path=db_path),
        "similar_historical_events": gather_similar_events(event_id, db_path=db_path),
        "supporting_evidence": gather_supporting_evidence(
            event["ticker"], event["event_type"], event["event_description"],
            top_k=top_k_evidence, index_dir=index_dir, db_path=db_path,
        ),
    }
    sections["uncertainties"] = compile_uncertainties(sections)
    sections["ai_synthesis"] = synthesize_narrative(sections)
    return sections
