"""PipelineRadar entrypoint.

Usage:
  python -m pipelineradar.main --dry-run         # verify config + DB, then exit
  python -m pipelineradar.main --once            # single full pipeline run
  python -m pipelineradar.main --once --ignore-seen  # treat all items as new
                                                     # (demo / acceptance testing)
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import structlog
from pydantic import ValidationError

from pipelineradar.config import get_settings
from pipelineradar.db.client import get_client
from pipelineradar.graph.build_graph import build_graph
from pipelineradar.graph.state import PipelineState
from pipelineradar.llm.provider import get_provider
from pipelineradar.schemas import Run, RunStatus

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
            hint="Check SUPABASE_URL/SUPABASE_SERVICE_KEY and the migration.",
        )
        sys.exit(1)

    log.info("dry_run.db_ok")
    log.info("dry_run.complete", status="ok")


# ── once ──────────────────────────────────────────────────────────────────────


async def once(ignore_seen: bool = False) -> None:
    log.info("run.start", ignore_seen=ignore_seen)

    try:
        settings = get_settings()
    except ValidationError as exc:
        log.error("run.config_invalid", errors=exc.errors())
        sys.exit(1)

    db = get_client(settings)
    llm = get_provider()
    run: Run = db.create_run()
    log.info("run.created", run_id=str(run.id))

    initial_state: PipelineState = {
        "run": run,
        "items": [],
        "resolved_items": [],
        "new_items": [],
        "entities": [],
        "draft_briefs": [],
        "grounded_briefs": [],
        "briefs": [],
        "markdown_output": "",
        "errors": [],
        "ignore_seen": ignore_seen,
    }

    try:
        graph = build_graph(db, llm, settings.watchlist, settings.openfda_api_key)
        final_state: PipelineState = await graph.ainvoke(initial_state)
    except Exception as exc:
        db.finish_run(run.id, items_seen=0, items_new=0, status=RunStatus.failed)
        log.error("run.failed", error=str(exc))
        sys.exit(1)

    # Print the brief to terminal if one was generated
    md = final_state.get("markdown_output", "")
    if md:
        print("\n" + "=" * 72)
        print(md)
        print("=" * 72 + "\n")
        print(f"Brief also written to output/brief_{run.id}.md")
    else:
        print("\nNo new items — synthesis skipped.")


# ── entrypoint ────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m pipelineradar.main",
        description="PipelineRadar — autonomous life-sciences intelligence agent",
    )
    parser.add_argument("--dry-run", action="store_true", help="Verify config + DB, then exit")
    parser.add_argument("--once", action="store_true", help="Execute one full pipeline run")
    parser.add_argument(
        "--ignore-seen",
        action="store_true",
        help="Treat all items as new (bypass hash check — for testing/demo only)",
    )
    args = parser.parse_args()

    if args.dry_run:
        dry_run()
    elif args.once:
        asyncio.run(once(ignore_seen=args.ignore_seen))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
