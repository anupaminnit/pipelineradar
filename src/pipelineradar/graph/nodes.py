"""LangGraph node functions for Phase 2: entity resolution and change detection.

Each node factory returns an async callable that accepts PipelineState and
returns a partial-update dict. Dependencies (db, llm, settings) are closed
over at graph-build time so the node signature stays compatible with LangGraph.
"""

from __future__ import annotations

from typing import Any

import structlog

from pipelineradar.config import WatchlistConfig
from pipelineradar.db.client import SupabaseClient
from pipelineradar.detect.change_detector import ChangeDetector
from pipelineradar.graph.state import PipelineState
from pipelineradar.llm.provider import LLMProvider
from pipelineradar.resolve.aliases import DRUG_ALIASES, normalise_company
from pipelineradar.resolve.entity_resolver import EntityResolver
from pipelineradar.schemas import Entity, Item

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


def make_resolve_entities(
    db: SupabaseClient, llm: LLMProvider, watchlist: WatchlistConfig
) -> Any:
    """Return an async node that resolves entity mentions in each item."""

    async def resolve_entities(state: PipelineState) -> dict[str, Any]:
        resolver = EntityResolver(db, llm)
        items: list[Item] = state["items"]

        # Build full set of drug tokens to scan for (watchlist + known aliases)
        drug_tokens: set[str] = {d.lower() for d in watchlist.drugs}
        drug_tokens.update(DRUG_ALIASES.keys())

        company_norms: list[tuple[str, str]] = [
            (normalise_company(c), c) for c in watchlist.companies
        ]

        resolved: list[Item] = []
        entity_by_id: dict[str, Entity] = {}

        for item in items:
            title_lower = item.title.lower()
            entity_ids = []

            for token in drug_tokens:
                if token in title_lower:
                    entity = await resolver.resolve(token, "drug", context=item.title)
                    eid = str(entity.id)
                    if eid not in entity_by_id:
                        entity_by_id[eid] = entity
                    if entity.id not in entity_ids:
                        entity_ids.append(entity.id)

            for norm_company, raw_company in company_norms:
                if norm_company and norm_company in normalise_company(item.title):
                    entity = await resolver.resolve(raw_company, "company", context=item.title)
                    eid = str(entity.id)
                    if eid not in entity_by_id:
                        entity_by_id[eid] = entity
                    if entity.id not in entity_ids:
                        entity_ids.append(entity.id)

            resolved.append(item.model_copy(update={"entity_ids": entity_ids}))

        log.info(
            "node.resolve_entities",
            run_id=str(state["run"].id),
            items=len(resolved),
            entities=len(entity_by_id),
        )
        return {"resolved_items": resolved, "entities": list(entity_by_id.values())}

    return resolve_entities


def make_detect_changes(db: SupabaseClient) -> Any:
    """Return an async node that filters resolved_items to only new/changed ones."""

    async def detect_changes(state: PipelineState) -> dict[str, Any]:
        detector = ChangeDetector(db)
        resolved: list[Item] = state["resolved_items"]
        new_items = await detector.filter_new(resolved)
        log.info(
            "node.detect_changes",
            run_id=str(state["run"].id),
            items_seen=len(resolved),
            items_new=len(new_items),
        )
        return {"new_items": new_items}

    return detect_changes


def log_nothing_new(state: PipelineState) -> dict[str, Any]:
    log.info(
        "node.log_nothing_new",
        run_id=str(state["run"].id),
        message="no new or changed items — skipping synthesis",
    )
    return {}
