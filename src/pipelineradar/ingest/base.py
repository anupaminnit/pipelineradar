"""Shared async HTTP client with retry and exponential back-off.

Every source-specific client subclasses BaseIngestClient to inherit retry
logic, timeouts, and structured error handling. One failing source must not
abort the run — callers catch IngestError and continue.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Self

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    wait_random,
)


class IngestError(Exception):
    """Raised when a source fetch fails after all retries."""

    def __init__(self, source: str, message: str) -> None:
        self.source = source
        super().__init__(f"[{source}] {message}")


def compute_content_hash(raw: dict[str, Any]) -> str:
    """SHA-256 of the stable JSON serialisation of a raw record."""
    payload = json.dumps(raw, sort_keys=True, default=str).encode()
    return hashlib.sha256(payload).hexdigest()


class BaseIngestClient:
    """Async HTTP client with 3-attempt exponential back-off."""

    source: str = ""

    def __init__(self, timeout: float = 30.0) -> None:
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            follow_redirects=True,
            headers={"User-Agent": "PipelineRadar/0.1 (+https://github.com/pipelineradar)"},
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self._client.aclose()

    async def _get(self, url: str, params: dict[str, Any] | None = None) -> Any:
        """GET with automatic retry on transient errors and rate-limits."""
        last_exc: Exception = IngestError(self.source, f"Failed: {url}")
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=10) + wait_random(0, 1),
            retry=retry_if_exception_type((httpx.RequestError, IngestError)),
            reraise=True,
        ):
            with attempt:
                try:
                    resp = await self._client.get(url, params=params)
                    if resp.status_code == 429:
                        raise IngestError(self.source, f"Rate limited: {url}")
                    resp.raise_for_status()
                    return resp.json()
                except httpx.HTTPStatusError as exc:
                    last_exc = IngestError(
                        self.source,
                        f"HTTP {exc.response.status_code}: {url}",
                    )
                    raise last_exc from exc
                except httpx.RequestError as exc:
                    last_exc = IngestError(self.source, f"Request error: {exc}")
                    raise last_exc from exc
        raise last_exc
