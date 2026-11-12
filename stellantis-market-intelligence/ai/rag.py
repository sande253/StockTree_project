"""Local RAG pipeline (Phase 20): retrieve indexed evidence, then ask Groq's LLM API to answer
using only that evidence, with citations.

Requires a GROQ_API_KEY environment variable (see .env.example). This project does not call
any LLM without first retrieving and grounding the answer in indexed sources (ai/retrieval.py);
if no relevant sources are found, no LLM call is made at all and an explicit "no evidence"
message is returned instead (never fabricate an answer - Phase 28).
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

from ai.prompts import NO_EVIDENCE_ANSWER, SYSTEM_PROMPT, build_user_prompt
from ai.retrieval import DEFAULT_TOP_K, retrieve
from ai.vector_store import DEFAULT_INDEX_DIR

logger = logging.getLogger(__name__)

# As of writing, a small/fast Groq-hosted model. Check https://console.groq.com/docs/models
# for the current catalog if this model id has since been retired - override via GROQ_MODEL.
DEFAULT_MODEL = "openai/gpt-oss-20b"


class RagConfigError(RuntimeError):
    """Raised when the RAG pipeline is missing required configuration (e.g. GROQ_API_KEY)."""


def _load_api_key() -> str:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RagConfigError(
            "GROQ_API_KEY is not set. Add it to your .env file or environment "
            "(see .env.example) to enable the AI investigation features."
        )
    return api_key


def answer_question(
    question: str,
    top_k: int = DEFAULT_TOP_K,
    model: str | None = None,
    index_dir: Path | str = DEFAULT_INDEX_DIR,
    db_path: Path | str | None = None,
    context_sources: list[dict[str, Any]] | None = None,
    history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Full Phase 20 pipeline: retrieve evidence -> ask Groq to answer using only that evidence."""
    history = history or []
    retrieval_query = " ".join(
        [turn["content"] for turn in history[-4:] if turn["role"] == "user"] + [question]
    )
    chunks = list(context_sources or []) + retrieve(retrieval_query, top_k=top_k, index_dir=index_dir, db_path=db_path)
    if not chunks:
        return {"answer": NO_EVIDENCE_ANSWER, "sources": []}

    from groq import Groq

    api_key = _load_api_key()
    client = Groq(api_key=api_key)

    try:
        completion = client.chat.completions.create(
            model=model or os.environ.get("GROQ_MODEL", DEFAULT_MODEL),
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(question, chunks, history=history)},
            ],
            temperature=0.0,
        )
        answer_text = completion.choices[0].message.content
    except Exception as exc:  # noqa: BLE001 - any LLM/API failure must degrade gracefully, not crash
        logger.warning("Groq completion failed: %s", exc)
        return {
            "answer": "Data unavailable - the AI service could not be reached. "
            "Relevant sources were found but could not be summarized; see sources below.",
            "sources": chunks,
            "error": str(exc),
        }

    references = re.findall(r"\[(\d+)\]", answer_text or "")
    valid_references = bool(references) and all(1 <= int(reference) <= len(chunks) for reference in references)
    if not valid_references:
        evidence = "\n\n".join(
            f"[{index}] {chunk.get('text', '')[:1200]}" for index, chunk in enumerate(chunks[:5], 1)
        )
        return {
            "answer": "The AI summary was withheld because its source references were missing or invalid. "
            "Available source excerpts (not independently verified conclusions):\n\n" + evidence,
            "sources": chunks,
            "citation_status": "rejected",
        }
    return {"answer": answer_text, "sources": chunks, "citation_status": "references_checked"}
