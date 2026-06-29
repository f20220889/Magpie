"""Pydantic domain models for the knowledge base and discovery runs."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class Domain(BaseModel):
    id: int | None = None
    name: str
    weight: float = 1.0
    created_at: datetime | None = None


class Skill(BaseModel):
    id: int | None = None
    domain_id: int
    name: str
    proficiency: int = 1  # 1..5
    created_at: datetime | None = None


class LearnedTopic(BaseModel):
    id: int | None = None
    title: str
    summary: str
    source_url: str | None = None
    tags: list[str] = Field(default_factory=list)
    domain_id: int | None = None
    learned_at: datetime | None = None


class CardStatus(str, Enum):
    surfaced = "surfaced"
    dismissed = "dismissed"
    learned = "learned"


class TopicCard(BaseModel):
    id: int | None = None
    run_id: int | None = None
    title: str
    overview: str
    why_relevant: str
    links: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    source_url: str | None = None
    recency: str | None = None
    relevance_score: float = 0.0
    status: CardStatus = CardStatus.surfaced
