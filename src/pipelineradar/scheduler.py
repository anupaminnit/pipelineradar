"""APScheduler autonomous pipeline loop.

PipelineScheduler wraps AsyncIOScheduler and runs the full LangGraph pipeline
on the cron schedule defined in config/watchlist.yaml. Every scheduled run
catches and logs all exceptions so the scheduler never crashes out entirely.
"""

from __future__ import annotations

import traceback
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from pipelineradar.db.client import get_client
from pipelineradar.graph.build_graph import build_graph
from pipelineradar.graph.state import PipelineState
from pipelineradar.llm.provider import get_provider
from pipelineradar.schemas import Run, RunStatus

if TYPE_CHECKING:
    from pipelineradar.config import Settings

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


class PipelineScheduler:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._scheduler = AsyncIOScheduler()

    def start(self) -> None:
        schedule = self._settings.watchlist.schedule
        trigger = CronTrigger.from_crontab(schedule.cron, timezone=schedule.timezone)

        self._scheduler.add_job(
            self._run_pipeline,
            trigger=trigger,
            id="pipeline_run",
            name="PipelineRadar scheduled run",
            misfire_grace_time=3600,
        )
        self._scheduler.start()

        next_run = self._scheduler.get_job("pipeline_run")
        next_fire = next_run.next_run_time if next_run else None
        log.info(
            "scheduler.started",
            cron=schedule.cron,
            timezone=schedule.timezone,
            next_run=str(next_fire),
        )

    def shutdown(self) -> None:
        self._scheduler.shutdown(wait=False)
        log.info("scheduler.stopped")

    async def _run_pipeline(self) -> None:
        hint_id = str(uuid.uuid4())
        started_at = datetime.now(tz=UTC)
        log.info(
            "scheduler.run_starting",
            datetime=started_at.isoformat(),
            run_id=hint_id,
        )
        try:
            await self._execute(started_at)
        except Exception:
            log.error(
                "scheduler.run_exception",
                run_id=hint_id,
                traceback=traceback.format_exc(),
            )

    async def _execute(self, started_at: datetime) -> None:
        settings = self._settings
        db = get_client(settings)
        llm = get_provider()

        run: Run = db.create_run()
        run_id = str(run.id)

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
            "ignore_seen": False,
            "force": False,
        }

        try:
            graph = build_graph(db, llm, settings.watchlist, settings.openfda_api_key)
            final_state: PipelineState = await graph.ainvoke(initial_state)
        except Exception as exc:
            db.finish_run(run.id, items_seen=0, items_new=0, status=RunStatus.failed)
            raise exc

        duration = (datetime.now(tz=UTC) - started_at).total_seconds()
        log.info(
            "scheduler.run_complete",
            run_id=run_id,
            items_seen=len(final_state.get("items", [])),
            items_new=len(final_state.get("new_items", [])),
            brief_generated=bool(final_state.get("briefs")),
            duration_seconds=round(duration, 1),
        )
