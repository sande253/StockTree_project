"""Pydantic request/response models for the API layer (Phase 24)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class InvestigateRequest(BaseModel):
    event_id: str = Field(min_length=1)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=1200)


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1200)
    event_id: str | None = None
    history: list[ChatTurn] = Field(default_factory=list, max_length=8)
