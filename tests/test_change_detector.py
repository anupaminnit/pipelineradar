"""Tests for ChangeDetector — deterministic new/changed item detection.

DB calls are mocked; no network or Supabase connection required.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from pipelineradar.detect.change_detector import ChangeDetector
from pipelineradar.detect.hashing import stable_hash
from pipelineradar.schemas import Item, ItemType


def _item(
    source: str = "clinicaltrials",
    source_id: str = "NCT001",
    title: str = "A Study",
    summary: str = "Background text",
    published_at: datetime | None = None,
) -> Item:
    from pipelineradar.detect.hashing import stable_hash_fields

    return Item(
        source=source,
        source_id=source_id,
        item_type=ItemType.clinical_trial,
        title=title,
        summary=summary,
        published_at=published_at,
        content_hash=stable_hash_fields(title, summary, published_at),
    )


def _make_db(stored_hashes: dict[tuple[str, str], str] | None = None) -> MagicMock:
    db = MagicMock()
    db.get_item_hashes.return_value = stored_hashes or {}
    db.upsert_items.return_value = 0
    return db


# ── new item (not in DB) ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_new_item_returned() -> None:
    """Item with no stored hash is returned as new."""
    item = _item()
    db = _make_db(stored_hashes={})

    detector = ChangeDetector(db)
    new_items = await detector.filter_new([item])

    assert len(new_items) == 1
    assert new_items[0].source_id == item.source_id
    db.upsert_items.assert_called_once()


# ── seen item (same hash) ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_seen_item_not_returned() -> None:
    """Item whose stable hash matches the stored hash is NOT returned."""
    item = _item()
    stored = {(item.source, item.source_id): stable_hash(item)}
    db = _make_db(stored_hashes=stored)

    detector = ChangeDetector(db)
    new_items = await detector.filter_new([item])

    assert new_items == []
    # All items are still upserted (so entity_ids / stable hash are current)
    db.upsert_items.assert_called_once()


# ── same source_id, changed content ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_changed_item_returned() -> None:
    """Item whose content changed (different stable hash) is returned as new."""
    item = _item(title="Updated title", summary="New abstract")
    # Simulate DB having the OLD hash
    old_hash = stable_hash(_item(title="Original title", summary="Old abstract"))
    stored = {(item.source, item.source_id): old_hash}
    db = _make_db(stored_hashes=stored)

    detector = ChangeDetector(db)
    new_items = await detector.filter_new([item])

    assert len(new_items) == 1
    assert new_items[0].source_id == item.source_id


# ── empty input ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_input_returns_empty() -> None:
    db = _make_db()
    detector = ChangeDetector(db)
    result = await detector.filter_new([])
    assert result == []
    db.get_item_hashes.assert_not_called()
