"""Pydantic v2 models for every value that crosses a module boundary.

Item      — a normalized record from any ingestion source
Entity    — a resolved canonical entity (drug, company, target, indication)
Run       — bookkeeping state for a single pipeline execution
Brief     — a synthesized intelligence brief for one therapeutic area
RunState  — top-level LangGraph state passed between nodes
"""

import uuid as _uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


def _now_utc() -> datetime:
    return datetime.now(tz=UTC)


class EntityKind(StrEnum):
    drug = "drug"
    company = "company"
    target = "target"
    indication = "indication"


class Entity(BaseModel):
    id: UUID = Field(default_factory=_uuid.uuid4)
    kind: EntityKind
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    external_ids: dict[str, str] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_now_utc)


class ItemType(StrEnum):
    clinical_trial = "clinical_trial"
    drug_approval = "drug_approval"
    publication = "publication"


class Item(BaseModel):
    id: UUID = Field(default_factory=_uuid.uuid4)
    source: str
    source_id: str
    item_type: ItemType
    title: str
    summary: str = ""
    url: str = ""
    entity_ids: list[UUID] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)
    published_at: datetime | None = None
    ingested_at: datetime = Field(default_factory=_now_utc)
    content_hash: str


class RunStatus(StrEnum):
    running = "running"
    completed = "completed"
    failed = "failed"


class Run(BaseModel):
    id: UUID = Field(default_factory=_uuid.uuid4)
    started_at: datetime = Field(default_factory=_now_utc)
    finished_at: datetime | None = None
    status: RunStatus = RunStatus.running
    items_seen: int = 0
    items_new: int = 0


class Brief(BaseModel):
    id: UUID = Field(default_factory=_uuid.uuid4)
    run_id: UUID
    therapeutic_area: str
    body_md: str
    citations: list[dict[str, str]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now_utc)


# ── Phase 3: synthesis models ──────────────────────────────────────────────────


class Claim(BaseModel):
    text: str
    source_item_ids: list[str]  # UUID strings of items supporting this claim
    confidence: float  # LLM's own estimate, 0.0–1.0


class BriefSection(BaseModel):
    heading: str
    claims: list[Claim]


class BriefDraft(BaseModel):
    """Raw LLM output before citation grounding."""

    therapeutic_area: str
    sections: list[BriefSection]
    generated_at: datetime = Field(default_factory=_now_utc)
    model_used: str


class Citation(BaseModel):
    item_id: str
    label: str  # e.g. "ClinicalTrials NCT05123456"
    url: str


class GroundedClaim(BaseModel):
    text: str
    source_item_ids: list[str]
    confidence: float
    citations: list[Citation] = Field(default_factory=list)
    unverified: bool = False  # True if any source_item_id was not in new_items


class GroundedBriefSection(BaseModel):
    heading: str
    claims: list[GroundedClaim]


class GroundedBrief(BaseModel):
    """BriefDraft after hallucination check and URL attachment."""

    therapeutic_area: str
    sections: list[GroundedBriefSection]
    generated_at: datetime
    model_used: str
    run_id: str


class RunState(BaseModel):
    """Top-level state threaded through the LangGraph pipeline."""

    run: Run
    items: list[Item] = Field(default_factory=list)
    resolved_items: list[Item] = Field(default_factory=list)
    new_items: list[Item] = Field(default_factory=list)
    entities: list[Entity] = Field(default_factory=list)
    draft_briefs: list[BriefDraft] = Field(default_factory=list)
    grounded_briefs: list[GroundedBrief] = Field(default_factory=list)
    briefs: list[Brief] = Field(default_factory=list)
    markdown_output: str = ""
    errors: list[str] = Field(default_factory=list)
