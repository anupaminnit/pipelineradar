"""ClinicalTrials.gov v2 ingestion client.

Queries the public ClinicalTrials.gov v2 REST API (no auth) by drug name
(query.intr) and sponsor (query.spons) for every entry in the watchlist.
Paginates via pageToken until exhausted, deduplicates by NCT ID.

Note: CT.gov blocks Python's default TLS fingerprint (JA3) via its CDN WAF.
This client uses curl_cffi (Chrome TLS impersonation) instead of httpx for
the HTTP layer. The rest of the pipeline (openFDA, EuropePMC) keeps httpx.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import structlog
from curl_cffi.requests import AsyncSession
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    wait_random,
)

from pipelineradar.config import WatchlistConfig
from pipelineradar.detect.hashing import stable_hash_fields
from pipelineradar.ingest.base import BaseIngestClient, IngestError
from pipelineradar.schemas import Item, ItemType

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

_BASE_URL = "https://clinicaltrials.gov/api/v2/studies"
_PAGE_SIZE = 100


def _parse_ct_date(date_str: str | None) -> datetime | None:
    if not date_str:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m"):
        try:
            return datetime.strptime(date_str, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def normalize_study(raw: dict[str, Any]) -> Item:
    """Map a single ClinicalTrials.gov v2 study record to a canonical Item."""
    protocol = raw.get("protocolSection") or {}
    id_mod = protocol.get("identificationModule") or {}
    status_mod = protocol.get("statusModule") or {}
    desc_mod = protocol.get("descriptionModule") or {}

    nct_id: str = id_mod.get("nctId") or ""
    title: str = id_mod.get("briefTitle") or ""
    summary: str = desc_mod.get("briefSummary") or ""

    date_struct = status_mod.get("lastUpdatePostDateStruct") or {}
    published_at = _parse_ct_date(date_struct.get("date"))

    return Item(
        source="clinicaltrials",
        source_id=nct_id,
        item_type=ItemType.clinical_trial,
        title=title,
        summary=summary,
        url=f"https://clinicaltrials.gov/study/{nct_id}",
        published_at=published_at,
        raw=raw,
        content_hash=stable_hash_fields(title, summary, published_at),
    )


class ClinicalTrialsClient(BaseIngestClient):
    """CT.gov v2 client using curl_cffi to bypass CDN TLS fingerprinting."""

    source = "clinicaltrials"

    def __init__(self) -> None:
        super().__init__()  # creates httpx client (unused; kept to satisfy base class)
        self._cffi: AsyncSession[Any] | None = None

    async def __aenter__(self) -> ClinicalTrialsClient:
        self._cffi = AsyncSession(impersonate="chrome110")
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self._client.aclose()
        if self._cffi is not None:
            await self._cffi.close()

    async def _get(self, url: str, params: dict[str, Any] | None = None) -> Any:
        """GET via curl_cffi with tenacity retry."""
        if self._cffi is None:
            raise IngestError(self.source, "session not open — use as async context manager")

        session = self._cffi
        last_exc: Exception = IngestError(self.source, f"Failed: {url}")

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=10) + wait_random(0, 1),
            retry=retry_if_exception_type(IngestError),
            reraise=True,
        ):
            with attempt:
                resp = await session.get(url, params=params)
                if resp.status_code != 200:
                    last_exc = IngestError(self.source, f"HTTP {resp.status_code}: {url}")
                    raise last_exc
                return resp.json()

        raise last_exc

    async def _fetch_query(self, query_field: str, query_value: str) -> list[dict[str, Any]]:
        """Fetch all pages for one (field, value) query pair."""
        records: list[dict[str, Any]] = []
        page_token: str | None = None

        while True:
            params: dict[str, Any] = {query_field: query_value, "pageSize": _PAGE_SIZE}
            if page_token:
                params["pageToken"] = page_token

            data = await self._get(_BASE_URL, params=params)
            studies: list[dict[str, Any]] = data.get("studies") or []
            records.extend(studies)

            page_token = data.get("nextPageToken")
            if not page_token:
                break

        return records

    async def fetch_studies(self, watchlist: WatchlistConfig) -> list[Item]:
        """Fetch studies for all watchlist drugs and companies, deduplicated."""
        seen_ids: set[str] = set()
        raw_records: list[dict[str, Any]] = []

        # Phase 1: query by drug intervention only.
        # Sponsor queries (query.spons) return every trial from large companies
        # (thousands unrelated to the watched drugs) — add them in Phase 2 once
        # entity-based filtering is in place.
        queries: list[tuple[str, str]] = [("query.intr", drug) for drug in watchlist.drugs]

        results = await asyncio.gather(
            *[self._fetch_query(field, value) for field, value in queries],
            return_exceptions=True,
        )

        for (field, value), result in zip(queries, results, strict=False):
            if isinstance(result, BaseException):
                log.warning(
                    "clinicaltrials.query_failed",
                    query_field=field,
                    query_value=value,
                    error=str(result),
                )
                continue
            for study in result:
                nct_id = (
                    (study.get("protocolSection") or {})
                    .get("identificationModule", {})
                    .get("nctId", "")
                )
                if nct_id and nct_id not in seen_ids:
                    seen_ids.add(nct_id)
                    raw_records.append(study)

        items = [normalize_study(r) for r in raw_records]
        log.info("clinicaltrials.fetched", count=len(items))
        return items
