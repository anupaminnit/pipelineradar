"""Shared async HTTP client with retry and exponential back-off.

Every source-specific ingestion client inherits from BaseIngestClient so that
retry logic, timeout settings, and structured error handling live in one place.

Phase 1: implement BaseIngestClient wrapping httpx.AsyncClient with tenacity
retry (3 attempts, exponential back-off, jitter) and a per-source typed error.
"""

from __future__ import annotations

# Phase 1: implement BaseIngestClient


class IngestError(Exception):
    """Raised when a source fetch fails after all retries."""

    def __init__(self, source: str, message: str) -> None:
        self.source = source
        super().__init__(f"[{source}] {message}")
