"""Tests for CitationGrounder — hallucination check + URL attachment.

All tests use synthetic BriefDraft and Item data; no DB or LLM calls.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from pipelineradar.deliver.markdown import render_brief
from pipelineradar.detect.hashing import stable_hash_fields
from pipelineradar.schemas import (
    BriefDraft,
    BriefSection,
    Claim,
    Item,
    ItemType,
)
from pipelineradar.synthesize.citation_grounder import CitationGrounder


def _item(source: str = "clinicaltrials", source_id: str = "NCT001") -> Item:
    title = f"Study {source_id}"
    return Item(
        id=uuid4(),
        source=source,
        source_id=source_id,
        item_type=ItemType.clinical_trial,
        title=title,
        summary="Background.",
        url=f"https://clinicaltrials.gov/study/{source_id}",
        content_hash=stable_hash_fields(title, "Background.", None),
    )


def _draft(item_ids: list[str], heading: str = "Clinical Trials") -> BriefDraft:
    return BriefDraft(
        therapeutic_area="oncology",
        sections=[
            BriefSection(
                heading=heading,
                claims=[
                    Claim(
                        text="A study is ongoing.",
                        source_item_ids=item_ids,
                        confidence=0.9,
                    )
                ],
            )
        ],
        generated_at=datetime(2026, 6, 10, tzinfo=UTC),
        model_used="test-model",
    )


# ── valid item_id → citations attached, unverified=False ─────────────────────


def test_valid_id_attaches_citation() -> None:
    item = _item()
    draft = _draft([str(item.id)])
    grounder = CitationGrounder()
    grounded = grounder.ground(draft, [item], run_id="run-001")

    assert len(grounded.sections) == 1
    claim = grounded.sections[0].claims[0]
    assert claim.unverified is False
    assert len(claim.citations) == 1
    assert claim.citations[0].url == item.url
    assert "NCT001" in claim.citations[0].label


# ── phantom item_id → unverified=True, claim NOT dropped ─────────────────────


def test_phantom_id_marks_unverified() -> None:
    item = _item()
    phantom_id = str(uuid4())  # not in new_items
    draft = _draft([phantom_id])
    grounder = CitationGrounder()
    grounded = grounder.ground(draft, [item], run_id="run-002")

    claim = grounded.sections[0].claims[0]
    assert claim.unverified is True
    assert len(claim.citations) == 0
    # Claim text is preserved — NOT silently dropped
    assert "ongoing" in claim.text


# ── mixed: one valid + one phantom ───────────────────────────────────────────


def test_mixed_ids_partial_citations() -> None:
    item = _item()
    phantom_id = str(uuid4())
    draft = _draft([str(item.id), phantom_id])
    grounder = CitationGrounder()
    grounded = grounder.ground(draft, [item], run_id="run-003")

    claim = grounded.sections[0].claims[0]
    assert claim.unverified is True
    assert len(claim.citations) == 1  # only the valid one gets a Citation
    assert claim.citations[0].item_id == str(item.id)


# ── rendered markdown contains ⚠ for unverified claims ───────────────────────


def test_markdown_shows_unverified_warning() -> None:
    phantom_id = str(uuid4())
    draft = _draft([phantom_id])
    grounder = CitationGrounder()
    grounded = grounder.ground(draft, [], run_id="run-004")

    md = render_brief(grounded, run_id="run-004")
    assert "⚠ UNVERIFIED" in md
    assert "review before distributing" in md


# ── rendered markdown sources section has links ───────────────────────────────


def test_markdown_sources_section() -> None:
    item = _item(source="europepmc", source_id="35123456")
    item = item.model_copy(update={"url": "https://europepmc.org/article/MED/35123456"})
    draft = _draft([str(item.id)])
    grounder = CitationGrounder()
    grounded = grounder.ground(draft, [item], run_id="run-005")

    md = render_brief(grounded, run_id="run-005")
    assert "### Sources" in md
    assert "europepmc.org" in md
    assert "35123456" in md
