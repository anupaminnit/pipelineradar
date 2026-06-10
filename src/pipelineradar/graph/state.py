"""LangGraph state definition.

RunState (from schemas.py) is the single state object threaded through all
graph nodes. This module re-exports it as the canonical graph state type and
will add any LangGraph-specific TypedDict wrappers needed by the framework.

Phase 3: wire RunState into the LangGraph StateGraph.
"""

from __future__ import annotations

from pipelineradar.schemas import RunState

__all__ = ["RunState"]
