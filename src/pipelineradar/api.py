"""FastAPI application: manual trigger, status, and brief endpoints.

Routes:
  POST /run              — trigger a single pipeline run asynchronously
  POST /run/force        — trigger a force-mode run asynchronously
  GET  /status/{run_id}  — return run record from the DB
  GET  /briefs           — return 10 most recent brief summaries
  GET  /briefs/{brief_id} — return full brief including body_md

The APScheduler is started and stopped via the FastAPI lifespan handler.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any
from uuid import UUID

import structlog
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from pipelineradar.config import get_settings
from pipelineradar.db.client import SupabaseClient, get_client
from pipelineradar.graph.build_graph import build_graph
from pipelineradar.graph.state import PipelineState
from pipelineradar.llm.provider import get_provider
from pipelineradar.schemas import Run, RunStatus

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

# ── app state ─────────────────────────────────────────────────────────────────

_db: SupabaseClient | None = None
_scheduler_instance: Any = None  # PipelineScheduler — imported lazily


def _get_db() -> SupabaseClient:
    if _db is None:
        raise RuntimeError("DB not initialised — app not started")
    return _db


# ── lifespan ──────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI) -> Any:
    global _db, _scheduler_instance

    settings = get_settings()
    _db = get_client(settings)

    from pipelineradar.scheduler import PipelineScheduler

    _scheduler_instance = PipelineScheduler(settings)
    _scheduler_instance.start()

    yield

    if _scheduler_instance is not None:
        _scheduler_instance.shutdown()
    log.info("api.shutdown")


# ── app ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="PipelineRadar",
    version="0.4.0",
    description="Autonomous life-sciences intelligence agent — trigger & status API",
    lifespan=lifespan,
)


# ── response models ───────────────────────────────────────────────────────────


class RunStartedResponse(BaseModel):
    run_id: str
    status: str
    started_at: datetime
    mode: str = "normal"


class RunStatusResponse(BaseModel):
    run_id: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    items_seen: int
    items_new: int
    brief_generated: bool
    error: str | None = None


class BriefSummary(BaseModel):
    id: str
    run_id: str
    therapeutic_area: str
    created_at: datetime
    item_count: int


class BriefDetail(BaseModel):
    id: str
    run_id: str
    therapeutic_area: str
    body_md: str
    citations: list[dict[str, str]]
    created_at: datetime
    item_count: int


# ── helpers ───────────────────────────────────────────────────────────────────


async def _trigger_run(force: bool = False) -> RunStartedResponse:
    settings = get_settings()
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
        "force": force,
    }

    graph = build_graph(db, llm, settings.watchlist, settings.openfda_api_key)

    async def _run() -> None:
        try:
            await graph.ainvoke(initial_state)
        except Exception as exc:
            db.finish_run(run.id, items_seen=0, items_new=0, status=RunStatus.failed)
            log.error("api.run_failed", run_id=run_id, error=str(exc))

    asyncio.create_task(_run())
    log.info("api.run_triggered", run_id=run_id, force=force)

    return RunStartedResponse(
        run_id=run_id,
        status="started",
        started_at=run.started_at,
        mode="force" if force else "normal",
    )


# ── endpoints ─────────────────────────────────────────────────────────────────


@app.post("/run", response_model=RunStartedResponse)
async def trigger_run() -> RunStartedResponse:
    """Trigger a single pipeline run asynchronously."""
    return await _trigger_run(force=False)


@app.post("/run/force", response_model=RunStartedResponse)
async def trigger_force_run() -> RunStartedResponse:
    """Trigger a force-mode run — bypasses change detection, does not update DB state."""
    return await _trigger_run(force=True)


@app.get("/status/{run_id}", response_model=RunStatusResponse)
async def get_run_status(run_id: UUID) -> RunStatusResponse:
    """Return status and counters for a specific run."""
    db = _get_db()
    run = db.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    brief_generated = db.run_has_brief(run_id)
    error: str | None = None
    if run.status == RunStatus.failed:
        error = "Run failed — check structured logs for details"

    return RunStatusResponse(
        run_id=str(run.id),
        status=run.status.value,
        started_at=run.started_at,
        finished_at=run.finished_at,
        items_seen=run.items_seen,
        items_new=run.items_new,
        brief_generated=brief_generated,
        error=error,
    )


@app.get("/briefs", response_model=list[BriefSummary])
async def list_briefs() -> list[BriefSummary]:
    """Return the 10 most recent brief summaries (no body_md)."""
    db = _get_db()
    briefs = db.get_briefs(limit=10)
    return [
        BriefSummary(
            id=str(b.id),
            run_id=str(b.run_id),
            therapeutic_area=b.therapeutic_area,
            created_at=b.created_at,
            item_count=len({c["item_id"] for c in b.citations}),
        )
        for b in briefs
    ]


@app.get("/briefs/{brief_id}", response_model=BriefDetail)
async def get_brief(brief_id: UUID) -> BriefDetail:
    """Return a full brief including body_md and citations."""
    db = _get_db()
    brief = db.get_brief(brief_id)
    if brief is None:
        raise HTTPException(status_code=404, detail=f"Brief {brief_id} not found")

    return BriefDetail(
        id=str(brief.id),
        run_id=str(brief.run_id),
        therapeutic_area=brief.therapeutic_area,
        body_md=brief.body_md,
        citations=brief.citations,
        created_at=brief.created_at,
        item_count=len({c["item_id"] for c in brief.citations}),
    )
