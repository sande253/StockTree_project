"""Phase 20 - Local RAG tests."""

from __future__ import annotations

import pytest

from ai.prompts import NO_EVIDENCE_ANSWER, SYSTEM_PROMPT, build_user_prompt, format_sources
from ai.rag import RagConfigError, answer_question


SAMPLE_CHUNKS = [
    {
        "document_type": "relationship_evidence",
        "company": "Peugeot",
        "source": "Stellantis official corporate site",
        "text": "Peugeot is one of Stellantis's 14 owned automotive brands.",
    }
]


def test_format_sources_numbers_and_labels_each_chunk():
    block = format_sources(SAMPLE_CHUNKS)
    assert block.startswith("[1] (relationship_evidence, company=Peugeot")
    assert "Peugeot is one of Stellantis's 14 owned automotive brands." in block


def test_format_sources_preserves_evidence_url():
    block = format_sources([{
        **SAMPLE_CHUNKS[0],
        "url": "https://www.stellantis.com/en/brands",
    }])
    assert "url=https://www.stellantis.com/en/brands" in block


def test_build_user_prompt_includes_question_and_sources():
    prompt = build_user_prompt("What is the relationship between STLA and Peugeot?", SAMPLE_CHUNKS)
    assert "What is the relationship between STLA and Peugeot?" in prompt
    assert "[1]" in prompt
    assert "untrusted data" in SYSTEM_PROMPT


def test_answer_question_returns_no_evidence_message_without_calling_llm(monkeypatch):
    monkeypatch.setattr("ai.rag.retrieve", lambda *a, **k: [])
    result = answer_question("Unanswerable question")
    assert result == {"answer": NO_EVIDENCE_ANSWER, "sources": []}


def test_answer_question_raises_config_error_without_api_key(monkeypatch):
    monkeypatch.setattr("ai.rag.retrieve", lambda *a, **k: SAMPLE_CHUNKS)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr("dotenv.load_dotenv", lambda: None, raising=False)

    with pytest.raises(RagConfigError):
        answer_question("What is the relationship between STLA and Peugeot?")


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeCompletion:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


class _FakeChatCompletions:
    def __init__(self, response_text, captured_calls):
        self._response_text = response_text
        self._captured_calls = captured_calls

    def create(self, **kwargs):
        self._captured_calls.append(kwargs)
        return _FakeCompletion(self._response_text)


class _FakeChat:
    def __init__(self, response_text, captured_calls):
        self.completions = _FakeChatCompletions(response_text, captured_calls)


class _FakeGroqClient:
    def __init__(self, api_key=None, response_text="Peugeot is a Stellantis-owned brand [1].", captured_calls=None):
        self.chat = _FakeChat(response_text, captured_calls if captured_calls is not None else [])


def test_answer_question_returns_grounded_answer_with_sources(monkeypatch):
    monkeypatch.setattr("ai.rag.retrieve", lambda *a, **k: SAMPLE_CHUNKS)
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    captured_calls = []
    monkeypatch.setattr("groq.Groq", lambda api_key=None: _FakeGroqClient(api_key, captured_calls=captured_calls))

    result = answer_question("What is the relationship between STLA and Peugeot?")
    assert result["answer"] == "Peugeot is a Stellantis-owned brand [1]."
    assert result["sources"] == SAMPLE_CHUNKS
    assert captured_calls[0]["messages"][0]["role"] == "system"


def test_answer_question_adds_database_context_and_limits_history_to_context(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    captured_calls = []
    monkeypatch.setattr("ai.rag.retrieve", lambda *a, **k: [])
    monkeypatch.setattr("groq.Groq", lambda api_key=None: _FakeGroqClient(api_key, captured_calls=captured_calls))
    context = [{
        "document_type": "market_event",
        "source": "Stored event record",
        "text": "STLA returned -8% on the event date.",
    }]

    result = answer_question(
        "How large was the move?",
        context_sources=context,
        history=[{"role": "user", "content": "Tell me about the latest event."}],
    )

    prompt = captured_calls[0]["messages"][1]["content"]
    assert result["sources"] == context
    assert "STLA returned -8% on the event date." in prompt
    assert "Tell me about the latest event." in prompt
    assert "it is not evidence" in prompt


@pytest.mark.parametrize("answer", ["Uncited conclusion.", "A claim [0].", "A claim [2].", "A claim [1] and [99].", ""])
def test_answer_question_withholds_invalid_citations(monkeypatch, answer):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setattr("ai.rag.retrieve", lambda *args, **kwargs: SAMPLE_CHUNKS)
    monkeypatch.setattr("groq.Groq", lambda **kwargs: _FakeGroqClient(response_text=answer))
    result = answer_question("What is documented?")
    assert result["citation_status"] == "rejected"
    assert "summary was withheld" in result["answer"]
    assert result["sources"] == SAMPLE_CHUNKS


def test_answer_question_degrades_gracefully_when_groq_call_fails(monkeypatch):
    monkeypatch.setattr("ai.rag.retrieve", lambda *a, **k: SAMPLE_CHUNKS)
    monkeypatch.setenv("GROQ_API_KEY", "test-key")

    class _RaisingClient:
        def __init__(self, api_key=None):
            self.chat = self

        @property
        def completions(self):
            return self

        def create(self, **kwargs):
            raise RuntimeError("simulated network failure")

    monkeypatch.setattr("groq.Groq", lambda api_key=None: _RaisingClient(api_key))

    result = answer_question("What is the relationship between STLA and Peugeot?")
    assert "Data unavailable" in result["answer"]
    assert result["sources"] == SAMPLE_CHUNKS
    assert "simulated network failure" in result["error"]
