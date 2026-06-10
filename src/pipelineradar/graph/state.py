"""LangGraph state definition for the PipelineRadar pipeline.

PipelineState is the TypedDict used by StateGraph. RunState is the equivalent
Pydantic model used at cross-module boundaries outside the graph.
"""

from __future__ import annotations

from typing import TypedDict

from pipelineradar.schemas import (  # noqa: F401
    Brief,
    BriefDraft,
    Entity,
    GroundedBrief,
    Item,
    Run,
    RunState,
)

__all__ = ["PipelineState", "RunState"]


class PipelineState(TypedDict):
    run: Run
    # ingestion / resolution / detection
    items: list[Item]
    resolved_items: list[Item]
    new_items: list[Item]
    entities: list[Entity]
    # synthesis / grounding / rendering
    draft_briefs: list[BriefDraft]
    grounded_briefs: list[GroundedBrief]
    briefs: list[Brief]
    markdown_output: str
    errors: list[str]
    # test/demo flag — bypasses hash check in detect_changes
    ignore_seen: bool
    # force flag — bypasses change detection entirely without touching DB
    force: bool
