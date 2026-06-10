"""LangGraph state definition for the PipelineRadar pipeline.

PipelineState is the TypedDict used by the StateGraph. RunState is the
equivalent Pydantic model used outside the graph (cross-module boundaries).
"""

from __future__ import annotations

from typing import TypedDict

from pipelineradar.schemas import Brief, Entity, Item, Run, RunState  # noqa: F401

__all__ = ["PipelineState", "RunState"]


class PipelineState(TypedDict):
    run: Run
    items: list[Item]
    resolved_items: list[Item]
    new_items: list[Item]
    entities: list[Entity]
    briefs: list[Brief]
    errors: list[str]
