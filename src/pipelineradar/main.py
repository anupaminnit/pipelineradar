"""PipelineRadar entrypoint.

Usage:
  python -m pipelineradar.main --dry-run   # verify config + DB, then exit
  python -m pipelineradar.main --once      # run the full pipeline once
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

import structlog
from pydantic import ValidationError

from pipelineradar.config import WatchlistConfig, get_settings
from pipelineradar.db.client import get_client
from pipelineradar.graph.build_graph import build_graph
from pipelineradar.graph.state import PipelineState
from pipelineradar.ingest.clinicaltrials import ClinicalTrialsClient
from pipelineradar.ingest.europepmc import EuropePMCClient
from pipelineradar.ingest.openfda import OpenFDAClient
from pipelineradar.llm.provider import get_provider
from pipelineradar.schemas import Entity, Item, RunStatus

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.JSONRenderer(),
    ],
    cache_logger_on_first_use=True,
)

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


# ── dry-run ───────────────────────────────────────────────────────────────────


def dry_run() -> None:
    log.info("dry_run.start")

    try:
        settings = get_settings()
    except ValidationError as exc:
        log.error(
            "dry_run.config_invalid",
            errors=exc.errors(),
            hint="Copy .env.example to .env and fill in required values.",
        )
        sys.exit(1)

    wl = settings.watchlist
    log.info(
        "dry_run.config_loaded",
        therapeutic_areas=wl.therapeutic_areas,
        drugs=wl.drugs,
        companies=wl.companies,
        targets=wl.targets,
    )

    try:
        client = get_client(settings)
        client.healthcheck()
    except Exception as exc:
        log.error(
            "dry_run.db_failed",
            error=str(exc),
            hint="Check SUPABASE_URL/SUPABASE_SERVICE_KEY and confirm the migration was applied.",
        )
        sys.exit(1)

    log.info("dry_run.db_ok")
    log.info("dry_run.complete", status="ok")


# ── once ──────────────────────────────────────────────────────────────────────


async def _ingest_all(wl: WatchlistConfig, openfda_api_key: str | None) -> list[Item]:
    """Fetch from all three sources concurrently with graceful degradation."""
    all_items: list[Item] = []

    async with (
        ClinicalTrialsClient() as ct,
        OpenFDAClient() as fda,
        EuropePMCClient() as pmc,
    ):
        ct_res, fda_res, pmc_res = await asyncio.gather(
            ct.fetch_studies(wl),
            fda.fetch_approvals(wl, openfda_api_key),
            pmc.fetch_publications(wl),
            return_exceptions=True,
        )

    source_results: list[tuple[str, Any]] = [
        ("clinicaltrials", ct_res),
        ("openfda", fda_res),
        ("europepmc", pmc_res),
    ]
    for source, result in source_results:
        if isinstance(result, BaseException):
            log.error("ingest.source_failed", source=source, error=str(result))
        else:
            all_items.extend(result)
            log.info("ingest.source_ok", source=source, count=len(result))

    return all_items


async def once() -> None:
    log.info("run.start")

    try:
        settings = get_settings()
    except ValidationError as exc:
        log.error("run.config_invalid", errors=exc.errors())
        sys.exit(1)

    db = get_client(settings)
    llm = get_provider()
    run = db.create_run()
    log.info("run.created", run_id=str(run.id))

    try:
        items = await _ingest_all(settings.watchlist, settings.openfda_api_key)

        initial_state: PipelineState = {
            "run": run,
            "items": items,
            "resolved_items": [],
            "new_items": [],
            "entities": [],
            "briefs": [],
            "errors": [],
        }

        graph = build_graph(db, llm, settings.watchlist)
        final_state: PipelineState = await graph.ainvoke(initial_state)

        new_items: list[Item] = final_state["new_items"]
        entities: list[Entity] = final_state["entities"]

        db.finish_run(
            run.id,
            items_seen=len(items),
            items_new=len(new_items),
            status=RunStatus.completed,
        )
        log.info(
            "run.complete",
            items_seen=len(items),
            items_new=len(new_items),
            entities=len(entities),
        )
    except Exception as exc:
        db.finish_run(run.id, items_seen=0, items_new=0, status=RunStatus.failed)
        log.error("run.failed", error=str(exc))
        sys.exit(1)

    # ── acceptance criterion output ───────────────────────────────────────────
    by_source: dict[str, int] = {}
    for item in items:
        by_source[item.source] = by_source.get(item.source, 0) + 1

    print("\n── Phase 2 acceptance: pipeline run summary ────────────────────")
    for src, count in sorted(by_source.items()):
        print(f"  {src:20s} {count:>6d} records ingested")
    print(f"  {'items_new':20s} {len(new_items):>6d}")
    print(f"  {'entities resolved':20s} {len(entities):>6d}")

    samples = db.fetch_items(limit=5)
    print("\n── 5 most-recent items in DB ───────────────────────────────────")
    for i, row in enumerate(samples, 1):
        print(f"\n[{i}] {json.dumps(row, indent=2, default=str)}")


# ── entrypoint ────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m pipelineradar.main",
        description="PipelineRadar — autonomous life-sciences intelligence agent",
    )
    parser.add_argument("--dry-run", action="store_true", help="Verify config + DB, then exit")
    parser.add_argument("--once", action="store_true", help="Execute one full pipeline run")
    args = parser.parse_args()

    if args.dry_run:
        dry_run()
    elif args.once:
        asyncio.run(once())
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
