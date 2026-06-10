"""Brief synthesis agent.

Takes new_items and produces one BriefDraft per therapeutic area that has
at least one new item. LLM output is parsed and validated before returning;
JSON parse failures are logged and skipped gracefully.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime

import structlog

from pipelineradar.config import WatchlistConfig
from pipelineradar.llm.provider import LLMProvider
from pipelineradar.schemas import BriefDraft, BriefSection, Claim, Item
from pipelineradar.synthesize.prompts import build_synthesis_prompt

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

# Cap items per TA: keeps prompt ≤ ~4k tokens and output ≤ ~1.5k tokens.
_MAX_ITEMS_PER_TA = 20
_MAX_TOKENS = 4096

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


class BriefSynthesizer:
    def __init__(self, llm: LLMProvider, model_name: str = "claude-haiku-4-5-20251001") -> None:
        self._llm = llm
        self._model_name = model_name

    async def synthesize(
        self, new_items: list[Item], watchlist: WatchlistConfig
    ) -> list[BriefDraft]:
        """Return one BriefDraft per TA that has at least one new item."""
        drafts: list[BriefDraft] = []
        for ta in watchlist.therapeutic_areas:
            # Phase 3: all items belong to the single configured TA.
            # Phase 5+ will add per-TA item tagging.
            ta_items = _select_items(new_items, limit=_MAX_ITEMS_PER_TA)
            if not ta_items:
                log.info("brief_synthesizer.no_items", therapeutic_area=ta)
                continue

            draft = await self._synthesize_ta(ta_items, ta)
            if draft.sections:
                drafts.append(draft)
                log.info(
                    "brief_synthesizer.draft_ready",
                    therapeutic_area=ta,
                    sections=len(draft.sections),
                    claims=sum(len(s.claims) for s in draft.sections),
                )
            else:
                log.warning("brief_synthesizer.empty_draft", therapeutic_area=ta)

        return drafts

    # ── private ───────────────────────────────────────────────────────────────

    async def _synthesize_ta(self, items: list[Item], ta: str) -> BriefDraft:
        system, user = build_synthesis_prompt(items, ta)
        raw = await self._llm.complete(system=system, user=user, max_tokens=_MAX_TOKENS)
        sections = _parse_sections(raw, ta)
        return BriefDraft(
            therapeutic_area=ta,
            sections=sections,
            generated_at=datetime.now(tz=UTC),
            model_used=self._model_name,
        )


# ── helpers ────────────────────────────────────────────────────────────────────


def _select_items(items: list[Item], limit: int) -> list[Item]:
    """Return the most recently ingested items up to limit, preferring variety."""
    sorted_items = sorted(items, key=lambda x: x.ingested_at, reverse=True)
    return sorted_items[:limit]


def _parse_sections(raw: str, ta: str) -> list[BriefSection]:
    """Extract and validate sections from raw LLM text.

    Falls back to empty list on any parse error so the graph keeps running.
    """
    text = raw.strip()

    # The model should return bare JSON, but defensively strip code fences.
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
        text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Try to extract the first {...} block
        m = _JSON_BLOCK_RE.search(text)
        if not m:
            log.error("brief_synthesizer.json_parse_failed", ta=ta, raw=text[:200])
            return []
        try:
            data = json.loads(m.group())
        except json.JSONDecodeError:
            log.error("brief_synthesizer.json_extract_failed", ta=ta)
            return []

    raw_sections: list[object] = data.get("sections") or []
    sections: list[BriefSection] = []
    for sec in raw_sections:
        if not isinstance(sec, dict):
            continue
        heading = str(sec.get("heading") or "")
        raw_claims: list[object] = sec.get("claims") or []
        claims: list[Claim] = []
        for c in raw_claims:
            if not isinstance(c, dict):
                continue
            text_val = str(c.get("text") or "")
            ids = [str(x) for x in (c.get("source_item_ids") or [])]
            try:
                conf = float(c.get("confidence") or 0.0)
            except (TypeError, ValueError):
                conf = 0.0
            if text_val and ids:
                claims.append(Claim(text=text_val, source_item_ids=ids, confidence=conf))
        if claims:
            sections.append(BriefSection(heading=heading, claims=claims))

    return sections
