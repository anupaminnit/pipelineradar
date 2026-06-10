"""Full LangGraph pipeline for PipelineRadar Phase 3.

Topology:
  ingest_all
      │
  resolve_entities
      │
  detect_changes ──(items_new == 0)──▶ log_nothing_new ──▶ END
      │ (items_new > 0)
  synthesize_brief
      │
  ground_citations
      │
  render_markdown
      │
  persist_brief
      │
  log_run_complete ──▶ END
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph

from pipelineradar.config import WatchlistConfig
from pipelineradar.db.client import SupabaseClient
from pipelineradar.graph.nodes import (
    ground_citations,
    log_nothing_new,
    make_detect_changes,
    make_ingest_all,
    make_log_run_complete,
    make_persist_brief,
    make_resolve_entities,
    make_synthesize_brief,
    render_markdown,
)
from pipelineradar.graph.state import PipelineState
from pipelineradar.llm.provider import LLMProvider


def _route_after_detect(state: PipelineState) -> str:
    return "nothing_new" if not state["new_items"] else "has_new"


def build_graph(
    db: SupabaseClient,
    llm: LLMProvider,
    watchlist: WatchlistConfig,
    openfda_api_key: str | None = None,
) -> Any:
    """Compile and return the full Phase 3 pipeline graph."""
    workflow: StateGraph[PipelineState] = StateGraph(PipelineState)

    workflow.add_node("ingest_all", make_ingest_all(watchlist, openfda_api_key))
    workflow.add_node("resolve_entities", make_resolve_entities(db, llm, watchlist))
    workflow.add_node("detect_changes", make_detect_changes(db))
    workflow.add_node("log_nothing_new", log_nothing_new)
    workflow.add_node("synthesize_brief", make_synthesize_brief(llm, watchlist))
    workflow.add_node("ground_citations", ground_citations)
    workflow.add_node("render_markdown", render_markdown)
    workflow.add_node("persist_brief", make_persist_brief(db))
    workflow.add_node("log_run_complete", make_log_run_complete(db))

    workflow.set_entry_point("ingest_all")
    workflow.add_edge("ingest_all", "resolve_entities")
    workflow.add_edge("resolve_entities", "detect_changes")
    workflow.add_conditional_edges(
        "detect_changes",
        _route_after_detect,
        {"nothing_new": "log_nothing_new", "has_new": "synthesize_brief"},
    )
    workflow.add_edge("log_nothing_new", END)
    workflow.add_edge("synthesize_brief", "ground_citations")
    workflow.add_edge("ground_citations", "render_markdown")
    workflow.add_edge("render_markdown", "persist_brief")
    workflow.add_edge("persist_brief", "log_run_complete")
    workflow.add_edge("log_run_complete", END)

    return workflow.compile()
