"""Brief synthesis agent.

Takes new_items grouped by therapeutic area and generates a grounded
per-TA intelligence brief. The LLM is given only the items from this run;
it cannot hallucinate items it was not given (enforced by grounding in
ground_citations).

Phase 3: implement BriefAgent using the LLM provider abstraction.
"""

from __future__ import annotations

# Phase 3: implement BriefAgent
