"""Graph wiring: assembles the LangGraph StateGraph for Phase 2.

Topology (Phase 2):
  resolve_entities → detect_changes ──(new_items > 0)──▶ END
                                     ──(new_items == 0)─▶ log_nothing_new → END

Phase 3 will insert synthesize_brief / ground_citations / deliver between
detect_changes and END on the has-new branch.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph

from pipelineradar.config import WatchlistConfig
from pipelineradar.db.client import SupabaseClient
from pipelineradar.graph.nodes import log_nothing_new, make_detect_changes, make_resolve_entities
from pipelineradar.graph.state import PipelineState
from pipelineradar.llm.provider import LLMProvider


def _route_after_detect(state: PipelineState) -> str:
    return "nothing_new" if not state["new_items"] else "has_new"


def build_graph(
    db: SupabaseClient, llm: LLMProvider, watchlist: WatchlistConfig
) -> Any:
    """Compile and return the Phase 2 pipeline graph."""
    workflow: StateGraph[PipelineState] = StateGraph(PipelineState)

    workflow.add_node("resolve_entities", make_resolve_entities(db, llm, watchlist))
    workflow.add_node("detect_changes", make_detect_changes(db))
    workflow.add_node("log_nothing_new", log_nothing_new)

    workflow.set_entry_point("resolve_entities")
    workflow.add_edge("resolve_entities", "detect_changes")
    workflow.add_conditional_edges(
        "detect_changes",
        _route_after_detect,
        {"nothing_new": "log_nothing_new", "has_new": END},
    )
    workflow.add_edge("log_nothing_new", END)

    return workflow.compile()
