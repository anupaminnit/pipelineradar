"""LangGraph node functions.

Each function maps RunState -> RunState (or a partial update dict).
Nodes are pure with respect to state; all side effects (DB writes, HTTP calls)
are explicit and logged.

Phase 3: implement ingest_clinicaltrials, ingest_openfda, ingest_europepmc,
normalize, resolve_entities, detect_changes, synthesize_brief,
ground_citations, deliver.
"""

from __future__ import annotations

# Phase 3: implement node functions
