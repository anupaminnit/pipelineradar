"""FastAPI application: manual trigger and status endpoints.

Routes:
  POST /run    — trigger a pipeline run immediately
  GET  /status — return the status of the last (or current) run

Phase 4: implement the FastAPI app and mount the scheduler lifespan.
"""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="PipelineRadar", version="0.1.0")


@app.get("/status")
async def status() -> dict[str, str]:
    """Returns API liveness. Full run status implemented in Phase 4."""
    return {"status": "ok", "phase": "0"}
