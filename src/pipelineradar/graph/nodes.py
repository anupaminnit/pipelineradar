"""LangGraph node factory functions for the full PipelineRadar pipeline.

Every node is returned by a factory that closes over its dependencies (db, llm,
settings) so the node callable itself has the signature LangGraph expects:
  async def node(state: PipelineState) -> dict[str, Any]
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from pipelineradar.config import WatchlistConfig
from pipelineradar.db.client import SupabaseClient
from pipelineradar.deliver.markdown import brief_to_db_model, render_brief
from pipelineradar.detect.change_detector import ChangeDetector
from pipelineradar.graph.state import PipelineState
from pipelineradar.ingest.clinicaltrials import ClinicalTrialsClient
from pipelineradar.ingest.europepmc import EuropePMCClient
from pipelineradar.ingest.openfda import OpenFDAClient
from pipelineradar.llm.provider import LLMProvider
from pipelineradar.resolve.aliases import DRUG_ALIASES, normalise_company
from pipelineradar.resolve.entity_resolver import EntityResolver
from pipelineradar.schemas import Brief, BriefDraft, Entity, GroundedBrief, Item
from pipelineradar.synthesize.brief_agent import BriefSynthesizer
from pipelineradar.synthesize.citation_grounder import CitationGrounder

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


# ── ingest ────────────────────────────────────────────────────────────────────


def make_ingest_all(watchlist: WatchlistConfig, openfda_api_key: str | None) -> Any:
    """Return an async node that fetches from all three sources concurrently."""

    async def ingest_all(state: PipelineState) -> dict[str, Any]:
        all_items: list[Item] = []
        errors: list[str] = list(state["errors"])

        async with (
            ClinicalTrialsClient() as ct,
            OpenFDAClient() as fda,
            EuropePMCClient() as pmc,
        ):
            ct_res, fda_res, pmc_res = await asyncio.gather(
                ct.fetch_studies(watchlist),
                fda.fetch_approvals(watchlist, openfda_api_key),
                pmc.fetch_publications(watchlist),
                return_exceptions=True,
            )

        for source, result in [
            ("clinicaltrials", ct_res),
            ("openfda", fda_res),
            ("europepmc", pmc_res),
        ]:
            if isinstance(result, BaseException):
                msg = f"{source}: {result}"
                log.error("node.ingest.source_failed", source=source, error=str(result))
                errors.append(msg)
            else:
                fetched: list[Item] = list(result)
                all_items.extend(fetched)
                log.info(
                    "node.ingest.source_ok",
                    run_id=str(state["run"].id),
                    source=source,
                    count=len(fetched),
                )

        log.info("node.ingest_all", run_id=str(state["run"].id), total=len(all_items))
        return {"items": all_items, "errors": errors}

    return ingest_all


# ── entity resolution ─────────────────────────────────────────────────────────


def make_resolve_entities(
    db: SupabaseClient, llm: LLMProvider, watchlist: WatchlistConfig
) -> Any:
    """Return an async node that resolves entity mentions in each item."""

    async def resolve_entities(state: PipelineState) -> dict[str, Any]:
        resolver = EntityResolver(db, llm)
        items: list[Item] = state["items"]

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


# ── change detection ──────────────────────────────────────────────────────────


def make_detect_changes(db: SupabaseClient) -> Any:
    """Return an async node that filters resolved_items to only new/changed ones."""

    async def detect_changes(state: PipelineState) -> dict[str, Any]:
        resolved: list[Item] = state["resolved_items"]

        if state.get("ignore_seen"):
            # Demo/test mode: treat everything as new without DB lookup.
            # upsert so entity_ids are persisted.
            db.upsert_items(resolved)
            log.info(
                "node.detect_changes",
                run_id=str(state["run"].id),
                items_seen=len(resolved),
                items_new=len(resolved),
                mode="ignore_seen",
            )
            return {"new_items": resolved}

        detector = ChangeDetector(db)
        new_items = await detector.filter_new(resolved)
        log.info(
            "node.detect_changes",
            run_id=str(state["run"].id),
            items_seen=len(resolved),
            items_new=len(new_items),
        )
        return {"new_items": new_items}

    return detect_changes


# ── nothing new ───────────────────────────────────────────────────────────────


def log_nothing_new(state: PipelineState) -> dict[str, Any]:
    log.info(
        "node.log_nothing_new",
        run_id=str(state["run"].id),
        message="no new or changed items — skipping synthesis",
    )
    return {}


# ── synthesis ─────────────────────────────────────────────────────────────────


def make_synthesize_brief(llm: LLMProvider, watchlist: WatchlistConfig) -> Any:
    """Return an async node that synthesizes BriefDrafts from new_items."""

    async def synthesize_brief(state: PipelineState) -> dict[str, Any]:
        synthesizer = BriefSynthesizer(llm)
        new_items: list[Item] = state["new_items"]
        drafts: list[BriefDraft] = await synthesizer.synthesize(new_items, watchlist)
        log.info(
            "node.synthesize_brief",
            run_id=str(state["run"].id),
            drafts=len(drafts),
        )
        return {"draft_briefs": drafts}

    return synthesize_brief


# ── citation grounding ────────────────────────────────────────────────────────


def ground_citations(state: PipelineState) -> dict[str, Any]:
    grounder = CitationGrounder()
    run_id = str(state["run"].id)
    new_items: list[Item] = state["new_items"]
    grounded: list[GroundedBrief] = []

    for draft in state["draft_briefs"]:
        gb = grounder.ground(draft, new_items, run_id)
        grounded.append(gb)

    total_claims = sum(len(s.claims) for g in grounded for s in g.sections)
    unverified = sum(
        1 for g in grounded for s in g.sections for c in s.claims if c.unverified
    )
    log.info(
        "node.ground_citations",
        run_id=run_id,
        grounded_briefs=len(grounded),
        total_claims=total_claims,
        unverified_claims=unverified,
    )
    return {"grounded_briefs": grounded}


# ── render + persist ──────────────────────────────────────────────────────────


def render_markdown(state: PipelineState) -> dict[str, Any]:
    run_id = str(state["run"].id)
    parts: list[str] = []
    for grounded in state["grounded_briefs"]:
        md = render_brief(grounded, run_id)
        parts.append(md)
    combined = "\n\n---\n\n".join(parts)
    log.info("node.render_markdown", run_id=run_id, chars=len(combined))
    return {"markdown_output": combined}


def make_persist_brief(db: SupabaseClient) -> Any:
    """Return a node that writes all grounded briefs to the briefs table."""

    def persist_brief(state: PipelineState) -> dict[str, Any]:
        run_id = str(state["run"].id)
        saved: list[Brief] = []
        for grounded, markdown in zip(
            state["grounded_briefs"],
            # split combined markdown back per brief on separator
            state["markdown_output"].split("\n\n---\n\n"),
            strict=False,
        ):
            brief = brief_to_db_model(grounded, markdown, run_id)
            db.upsert_brief(brief)
            saved.append(brief)
            log.info(
                "node.persist_brief",
                run_id=run_id,
                therapeutic_area=brief.therapeutic_area,
                brief_id=str(brief.id),
            )
        return {"briefs": saved}

    return persist_brief


def make_log_run_complete(db: SupabaseClient) -> Any:
    """Return a node that finalises the run row and logs completion."""

    from pipelineradar.schemas import RunStatus

    def log_run_complete(state: PipelineState) -> dict[str, Any]:
        run_id = state["run"].id
        new_items = state["new_items"]
        items = state["items"]
        db.finish_run(
            run_id,
            items_seen=len(items),
            items_new=len(new_items),
            status=RunStatus.completed,
        )
        log.info(
            "node.run_complete",
            run_id=str(run_id),
            items_seen=len(items),
            items_new=len(new_items),
            briefs=len(state["briefs"]),
        )
        return {}

    return log_run_complete
