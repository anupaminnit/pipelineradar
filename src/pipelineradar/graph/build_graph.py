"""Graph wiring: assembles the LangGraph StateGraph from node functions.

Topology:
  ingest_clinicaltrials ─┐
  ingest_openfda         ├─▶ normalize ─▶ resolve_entities ─▶ detect_changes
  ingest_europepmc       ┘                                         │
                                                    (new items?) ──┤
                                                                   ▼
                                          deliver ◀── ground_citations ◀── synthesize_brief

Phase 3: implement build_graph() -> CompiledStateGraph.
"""

from __future__ import annotations

# Phase 3: implement build_graph
