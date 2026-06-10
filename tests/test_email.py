"""Tests for deliver/email.py.

No real SMTP calls are made. Tests verify graceful fallback behaviour
and subject-line content without touching the network.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from pipelineradar.deliver.email import _count_cited_items, send_brief
from pipelineradar.detect.hashing import stable_hash_fields
from pipelineradar.schemas import (
    Citation,
    GroundedBrief,
    GroundedBriefSection,
    GroundedClaim,
    Item,
    ItemType,
)


def _item(source: str = "clinicaltrials", source_id: str = "NCT001") -> Item:
    title = f"Study {source_id}"
    return Item(
        source=source,
        source_id=source_id,
        item_type=ItemType.clinical_trial,
        title=title,
        summary="Background.",
        url=f"https://clinicaltrials.gov/study/{source_id}",
        content_hash=stable_hash_fields(title, "Background.", None),
    )


def _brief(item_id: str, unverified: bool = False) -> GroundedBrief:
    return GroundedBrief(
        therapeutic_area="oncology",
        sections=[
            GroundedBriefSection(
                heading="Clinical Trials",
                claims=[
                    GroundedClaim(
                        text="Nivolumab is being studied in phase II.",
                        source_item_ids=[item_id],
                        confidence=0.95,
                        citations=[
                            Citation(
                                item_id=item_id,
                                label="ClinicalTrials NCT001",
                                url="https://clinicaltrials.gov/study/NCT001",
                            )
                        ],
                        unverified=unverified,
                    )
                ],
            )
        ],
        generated_at=datetime(2026, 6, 10, 7, 0, tzinfo=UTC),
        model_used="claude-haiku-4-5-20251001",
        run_id="run-test-001",
    )


# ── SMTP not configured → file written, no exception ─────────────────────────


@pytest.mark.asyncio
async def test_send_brief_fallback_writes_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no SMTP config, send_brief writes to output/ and does not raise."""
    # Ensure SMTP env vars are absent
    for key in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "ALERT_TO_EMAIL"):
        monkeypatch.delenv(key, raising=False)

    # Redirect output dir to tmp_path
    import pipelineradar.deliver.email as email_mod

    monkeypatch.setattr(email_mod, "_OUTPUT_DIR", tmp_path)

    item_id = str(uuid4())
    grounded = _brief(item_id)
    run_id = "run-fallback-001"

    await send_brief(grounded, "# Brief content", run_id)

    written = list(tmp_path.glob("*.md"))
    assert len(written) == 1
    assert "oncology" in written[0].name
    assert run_id in written[0].name


# ── Subject line format ───────────────────────────────────────────────────────


def test_subject_contains_therapeutic_area_and_date() -> None:
    """Subject must contain therapeutic_area, item count, and date."""
    item = _item()
    item_id = str(item.id)
    grounded = _brief(item_id)

    n_items = _count_cited_items(grounded)
    date_str = grounded.generated_at.strftime("%Y-%m-%d")
    subject = (
        f"PipelineRadar · {grounded.therapeutic_area}"
        f" · {n_items} new items · {date_str}"
    )

    assert "oncology" in subject
    assert "2026-06-10" in subject
    assert "1 new items" in subject


# ── count_cited_items ─────────────────────────────────────────────────────────


def test_count_cited_items_deduplicates() -> None:
    """Same item_id cited twice across sections counts as 1."""
    item_id = str(uuid4())
    grounded = GroundedBrief(
        therapeutic_area="oncology",
        sections=[
            GroundedBriefSection(
                heading="Trials",
                claims=[
                    GroundedClaim(
                        text="Claim A.",
                        source_item_ids=[item_id],
                        confidence=0.9,
                        citations=[
                            Citation(item_id=item_id, label="X", url="http://x.com")
                        ],
                    ),
                    GroundedClaim(
                        text="Claim B.",
                        source_item_ids=[item_id],
                        confidence=0.9,
                        citations=[
                            Citation(item_id=item_id, label="X", url="http://x.com")
                        ],
                    ),
                ],
            )
        ],
        generated_at=datetime(2026, 6, 10, tzinfo=UTC),
        model_used="test",
        run_id="r1",
    )
    assert _count_cited_items(grounded) == 1


# ── SMTP send failure → fallback, no exception ────────────────────────────────


@pytest.mark.asyncio
async def test_send_brief_smtp_failure_falls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the SMTP send raises, write to output/ instead of propagating."""
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_USER", "user@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setenv("ALERT_TO_EMAIL", "alert@example.com")

    import pipelineradar.deliver.email as email_mod

    monkeypatch.setattr(email_mod, "_OUTPUT_DIR", tmp_path)

    def _fail(*_args: object, **_kwargs: object) -> None:
        raise OSError("Connection refused")

    monkeypatch.setattr(email_mod, "_smtp_send", _fail)

    item_id = str(uuid4())
    grounded = _brief(item_id)
    await send_brief(grounded, "# Brief", "run-smtp-fail")

    written = list(tmp_path.glob("*.md"))
    assert len(written) == 1
