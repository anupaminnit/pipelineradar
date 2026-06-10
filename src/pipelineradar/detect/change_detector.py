"""Change detector: identifies items that are new or updated since last ingest.

An item is *new* if its (source, source_id) has never been stored.
An item is *changed* if its stable_hash differs from the stored content_hash.
All items (new and seen alike) are upserted so the DB stays current.
"""

from __future__ import annotations

import structlog

from pipelineradar.db.client import SupabaseClient
from pipelineradar.detect.hashing import stable_hash
from pipelineradar.schemas import Item

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


class ChangeDetector:
    def __init__(self, db: SupabaseClient) -> None:
        self._db = db

    async def filter_new(self, items: list[Item]) -> list[Item]:
        """Return items that are new or whose content changed since last ingest.

        Side-effect: upserts all items (with updated content_hash and entity_ids)
        so subsequent runs see the latest state.
        """
        if not items:
            return []

        # Compute the stable hash for each item and re-stamp content_hash.
        # This ensures the DB always stores the stable hash going forward,
        # even for rows originally written with the raw-dict hash in Phase 1.
        stamped: list[Item] = [
            item.model_copy(update={"content_hash": stable_hash(item)}) for item in items
        ]

        # Fetch stored hashes for all (source, source_id) pairs in one round-trip
        source_ids = [(item.source, item.source_id) for item in stamped]
        stored = self._db.get_item_hashes(source_ids)

        new_items: list[Item] = []
        for item in stamped:
            key = (item.source, item.source_id)
            prior_hash = stored.get(key)
            if prior_hash is None or prior_hash != item.content_hash:
                new_items.append(item)

        # Persist everything (new and seen) so entity_ids + stable hashes are saved
        self._db.upsert_items(stamped)

        log.info(
            "change_detector.filtered",
            items_total=len(stamped),
            items_new=len(new_items),
        )
        return new_items
