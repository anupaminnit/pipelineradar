"""Tests for FastAPI endpoints.

Uses httpx.AsyncClient with the ASGI transport to avoid starting a real server.
The Supabase client and scheduler are patched out so no real DB or network calls
are made.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from pipelineradar.schemas import Run, RunStatus

# ── fixtures ──────────────────────────────────────────────────────────────────


def _make_mock_db(run: Run | None = None) -> MagicMock:
    db = MagicMock()
    db.create_run.return_value = run or Run()
    db.get_run.return_value = run
    db.run_has_brief.return_value = False
    db.get_briefs.return_value = []
    db.get_brief.return_value = None
    db.finish_run.return_value = None
    return db


def _make_mock_llm() -> MagicMock:
    return MagicMock()


@pytest.fixture()
def app_with_mocks() -> Any:
    """Return the FastAPI app with DB, LLM, and scheduler all mocked out."""
    import pipelineradar.api as api_mod

    mock_db = _make_mock_db()
    mock_llm = _make_mock_llm()
    mock_scheduler = MagicMock()
    mock_scheduler.start.return_value = None
    mock_scheduler.shutdown.return_value = None

    # Patch module-level _db so _get_db() returns our mock
    with (
        patch.object(api_mod, "_db", mock_db),
        patch("pipelineradar.api.get_client", return_value=mock_db),
        patch("pipelineradar.api.get_provider", return_value=mock_llm),
        patch("pipelineradar.api.get_settings"),
        patch("pipelineradar.scheduler.PipelineScheduler", return_value=mock_scheduler),
    ):
        yield api_mod.app, mock_db


# ── POST /run → 200 with run_id ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_run_returns_run_id(app_with_mocks: Any) -> None:
    app, mock_db = app_with_mocks
    run = Run()
    mock_db.create_run.return_value = run

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch("pipelineradar.api.build_graph") as mock_graph_factory:
            mock_graph = MagicMock()
            mock_graph.ainvoke = MagicMock(return_value=None)
            mock_graph_factory.return_value = mock_graph

            resp = await client.post("/run")

    assert resp.status_code == 200
    body = resp.json()
    assert "run_id" in body
    assert body["status"] == "started"


# ── GET /status/{run_id} → 404 for unknown run ───────────────────────────────


@pytest.mark.asyncio
async def test_get_status_unknown_run_returns_404(app_with_mocks: Any) -> None:
    app, mock_db = app_with_mocks
    mock_db.get_run.return_value = None

    unknown_id = str(uuid4())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/status/{unknown_id}")

    assert resp.status_code == 404


# ── GET /status/{run_id} → 200 for known run ─────────────────────────────────


@pytest.mark.asyncio
async def test_get_status_known_run_returns_200(app_with_mocks: Any) -> None:
    app, mock_db = app_with_mocks
    run = Run(
        status=RunStatus.completed,
        finished_at=datetime.now(tz=UTC),
        items_seen=100,
        items_new=5,
    )
    mock_db.get_run.return_value = run
    mock_db.run_has_brief.return_value = True

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/status/{run.id}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "completed"
    assert body["items_seen"] == 100
    assert body["brief_generated"] is True


# ── GET /briefs → 200, returns a list (may be empty) ─────────────────────────


@pytest.mark.asyncio
async def test_get_briefs_returns_list(app_with_mocks: Any) -> None:
    app, mock_db = app_with_mocks
    mock_db.get_briefs.return_value = []

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/briefs")

    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ── GET /briefs/{id} → 404 for unknown brief ─────────────────────────────────


@pytest.mark.asyncio
async def test_get_brief_unknown_returns_404(app_with_mocks: Any) -> None:
    app, mock_db = app_with_mocks
    mock_db.get_brief.return_value = None

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/briefs/{uuid4()}")

    assert resp.status_code == 404


# ── POST /run/force → 200 with mode=force ────────────────────────────────────


@pytest.mark.asyncio
async def test_post_run_force_returns_force_mode(app_with_mocks: Any) -> None:
    app, mock_db = app_with_mocks
    run = Run()
    mock_db.create_run.return_value = run

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch("pipelineradar.api.build_graph") as mock_graph_factory:
            mock_graph = MagicMock()
            mock_graph.ainvoke = MagicMock(return_value=None)
            mock_graph_factory.return_value = mock_graph

            resp = await client.post("/run/force")

    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "force"
