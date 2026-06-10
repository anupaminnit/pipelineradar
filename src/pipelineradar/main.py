"""PipelineRadar entrypoint.

Usage:
  python -m pipelineradar.main --dry-run   # verify config + DB, then exit
  python -m pipelineradar.main --once      # run the full pipeline once (Phase 3+)
"""

from __future__ import annotations

import argparse
import sys

import structlog
from pydantic import ValidationError

from pipelineradar.config import get_settings
from pipelineradar.db.client import get_client

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.JSONRenderer(),
    ],
    cache_logger_on_first_use=True,
)

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


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
        log.error("not_implemented", flag="--once", phase="Phase 3+")
        sys.exit(1)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
