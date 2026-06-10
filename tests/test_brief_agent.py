"""Tests for BriefSynthesizer.

The LLM is mocked so no real API calls are made. Tests verify that the
agent correctly parses LLM JSON output and handles edge cases.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from pipelineradar.config import WatchlistConfig
from pipelineradar.detect.hashing import stable_hash_fields
from pipelineradar.schemas import Item, ItemType
from pipelineradar.synthesize.brief_agent import BriefSynthesizer


def _item(
    title: str = "A Study", summary: str = "Background.", source: str = "clinicaltrials"
) -> Item:
    uid = uuid4()
    return Item(
        id=uid,
        source=source,
        source_id=str(uid)[:8],
        item_type=ItemType.clinical_trial,
        title=title,
        summary=summary,
        url=f"https://clinicaltrials.gov/study/{uid}",
        content_hash=stable_hash_fields(title, summary, None),
    )


def _watchlist(*tas: str) -> WatchlistConfig:
    return WatchlistConfig(
        therapeutic_areas=list(tas),
        drugs=["pembrolizumab"],
        companies=[],
        targets=[],
    )


def _make_llm(sections_json: str) -> AsyncMock:
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value=sections_json)
    return llm


# ── happy path: 3 items, claims reference item IDs ───────────────────────────


@pytest.mark.asyncio
async def test_synthesize_returns_draft_with_valid_ids() -> None:
    items = [_item(f"Study {i}") for i in range(3)]
    valid_id = str(items[0].id)

    response = json.dumps(
        {
            "sections": [
                {
                    "heading": "Clinical Trials",
                    "claims": [
                        {
                            "text": "A pembrolizumab trial is recruiting.",
                            "source_item_ids": [valid_id],
                            "confidence": 0.95,
                        }
                    ],
                }
            ]
        }
    )
    llm = _make_llm(response)
    synthesizer = BriefSynthesizer(llm)
    drafts = await synthesizer.synthesize(items, _watchlist("oncology"))

    assert len(drafts) == 1
    draft = drafts[0]
    assert draft.therapeutic_area == "oncology"
    assert len(draft.sections) == 1
    assert draft.sections[0].heading == "Clinical Trials"
    claim = draft.sections[0].claims[0]
    assert valid_id in claim.source_item_ids


# ── no items for TA → no draft ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_items_produces_no_draft() -> None:
    llm = _make_llm("{}")
    synthesizer = BriefSynthesizer(llm)
    drafts = await synthesizer.synthesize([], _watchlist("oncology"))
    assert drafts == []
    llm.complete.assert_not_called()


# ── malformed JSON → graceful empty draft ─────────────────────────────────────


@pytest.mark.asyncio
async def test_malformed_json_returns_empty_sections() -> None:
    llm = _make_llm("This is not JSON at all.")
    synthesizer = BriefSynthesizer(llm)
    items = [_item()]
    drafts = await synthesizer.synthesize(items, _watchlist("oncology"))
    # A draft with empty sections is not appended
    assert drafts == []


# ── model_used is propagated ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_model_used_field() -> None:
    item = _item()
    response = json.dumps(
        {
            "sections": [
                {
                    "heading": "Literature",
                    "claims": [
                        {
                            "text": "A publication was found.",
                            "source_item_ids": [str(item.id)],
                            "confidence": 0.8,
                        }
                    ],
                }
            ]
        }
    )
    synthesizer = BriefSynthesizer(_make_llm(response), model_name="test-model-v1")
    drafts = await synthesizer.synthesize([item], _watchlist("oncology"))
    assert drafts[0].model_used == "test-model-v1"
