"""Citation grounder: verifies and attaches sources to synthesized claims.

Two jobs:
  1. Hallucination check — every source_item_id must exist in new_items.
     Phantom IDs are flagged with unverified=True and a warning log; the
     claim is NEVER silently dropped.
  2. URL attachment — builds a Citation object for every verified ID.
"""

from __future__ import annotations

import structlog

from pipelineradar.schemas import (
    BriefDraft,
    Citation,
    GroundedBrief,
    GroundedBriefSection,
    GroundedClaim,
    Item,
)

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


def _citation_label(item: Item) -> str:
    """Short human-readable label for a citation footnote."""
    if item.source == "clinicaltrials":
        return f"ClinicalTrials {item.source_id}"
    if item.source == "openfda":
        return f"FDA {item.source_id}"
    if item.source == "europepmc":
        return f"Europe PMC {item.source_id}"
    return f"{item.source} {item.source_id}"


class CitationGrounder:
    def ground(self, draft: BriefDraft, new_items: list[Item], run_id: str) -> GroundedBrief:
        """Return a GroundedBrief with phantom IDs flagged and URLs attached."""
        item_map: dict[str, Item] = {str(item.id): item for item in new_items}

        grounded_sections: list[GroundedBriefSection] = []
        for section in draft.sections:
            grounded_claims: list[GroundedClaim] = []
            for claim in section.claims:
                citations: list[Citation] = []
                unverified = False

                for item_id in claim.source_item_ids:
                    item = item_map.get(item_id)
                    if item is None:
                        log.warning(
                            "citation_grounder.phantom_id",
                            run_id=run_id,
                            claim_text=claim.text[:80],
                            phantom_id=item_id,
                        )
                        unverified = True
                    else:
                        citations.append(
                            Citation(
                                item_id=item_id,
                                label=_citation_label(item),
                                url=item.url,
                            )
                        )

                grounded_claims.append(
                    GroundedClaim(
                        text=claim.text,
                        source_item_ids=claim.source_item_ids,
                        confidence=claim.confidence,
                        citations=citations,
                        unverified=unverified,
                    )
                )

            if grounded_claims:
                grounded_sections.append(
                    GroundedBriefSection(heading=section.heading, claims=grounded_claims)
                )

        return GroundedBrief(
            therapeutic_area=draft.therapeutic_area,
            sections=grounded_sections,
            generated_at=draft.generated_at,
            model_used=draft.model_used,
            run_id=run_id,
        )
