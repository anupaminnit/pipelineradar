"""Change detector: diffs normalised items against the seen-items store.

An item is *new* if (source, source_id) has never been ingested, OR its
content_hash changed since the last ingest. This is entirely deterministic —
no LLM involved.

Phase 2: implement ChangeDetector with detect(items) -> (new_items, updated_items).
"""

from __future__ import annotations

# Phase 2: implement ChangeDetector
