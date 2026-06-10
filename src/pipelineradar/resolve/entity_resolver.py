"""Entity resolver: maps raw mentions to canonical Entity rows.

Strategy (Phase 2):
  1. Exact-match and normalised-string-match against the entities registry.
  2. For unresolved residue, LLM disambiguation with the top-k candidates as
     context; result cached back into the registry.

This hybrid approach keeps the hot path deterministic (no LLM tokens spent on
names we already know) while handling novel or ambiguous names gracefully.
"""

from __future__ import annotations

# Phase 2: implement EntityResolver
