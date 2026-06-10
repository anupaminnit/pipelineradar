"""openFDA drug approvals ingestion client.

Queries the openFDA drugsfda endpoint by generic_name for each drug in the
watchlist. An optional API key raises the daily rate limit from 1 000 to
120 000 requests/day; the client falls back to the anonymous limit silently
when the key is absent.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import structlog

from pipelineradar.config import WatchlistConfig
from pipelineradar.detect.hashing import stable_hash_fields
from pipelineradar.ingest.base import BaseIngestClient
from pipelineradar.schemas import Item, ItemType

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

_BASE_URL = "https://api.fda.gov/drug/drugsfda.json"
_LIMIT = 100


def _parse_fda_date(date_str: str | None) -> datetime | None:
    """Parse FDA date format YYYYMMDD."""
    if not date_str or len(date_str) < 8:
        return None
    try:
        return datetime.strptime(date_str[:8], "%Y%m%d").replace(tzinfo=UTC)
    except ValueError:
        return None


def normalize_approval(raw: dict[str, Any]) -> Item:
    """Map a single openFDA drugsfda record to a canonical Item."""
    app_number: str = raw.get("application_number") or ""
    sponsor: str = raw.get("sponsor_name") or ""
    openfda: dict[str, Any] = raw.get("openfda") or {}

    brand_names: list[str] = openfda.get("brand_name") or []
    generic_names: list[str] = openfda.get("generic_name") or []

    parts: list[str] = []
    if brand_names:
        parts.append(brand_names[0])
    if generic_names:
        parts.append(f"({generic_names[0]})")
    if sponsor:
        parts.append(f"— {sponsor}")
    title = " ".join(parts) or app_number

    summary = (
        f"FDA application {app_number}"
        + (f" | {generic_names[0]}" if generic_names else "")
        + (f" | Sponsor: {sponsor}" if sponsor else "")
    )

    # Most recent approval submission date
    submissions: list[dict[str, Any]] = raw.get("submissions") or []
    approved = [s for s in submissions if s.get("submission_status") == "AP"]
    date_str: str | None = approved[-1].get("submission_status_date") if approved else None
    published_at = _parse_fda_date(date_str)

    app_digits = "".join(c for c in app_number if c.isdigit())
    url = (
        f"https://www.accessdata.fda.gov/scripts/cder/daf/index.cfm"
        f"?event=overview.process&ApplNo={app_digits}"
    )

    return Item(
        source="openfda",
        source_id=app_number,
        item_type=ItemType.drug_approval,
        title=title,
        summary=summary,
        url=url,
        published_at=published_at,
        raw=raw,
        content_hash=stable_hash_fields(title, summary, published_at),
    )


class OpenFDAClient(BaseIngestClient):
    source = "openfda"

    async def _fetch_drug(self, drug: str, api_key: str | None) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        skip = 0

        while True:
            params: dict[str, Any] = {
                "search": f'openfda.generic_name:"{drug}"',
                "limit": _LIMIT,
                "skip": skip,
            }
            if api_key:
                params["api_key"] = api_key

            data = await self._get(_BASE_URL, params=params)
            results: list[dict[str, Any]] = data.get("results") or []
            records.extend(results)

            meta: dict[str, Any] = data.get("meta") or {}
            total: int = int(meta.get("total") or 0)
            skip += len(results)

            if not results or skip >= total or skip >= 1000:
                break

        return records

    async def fetch_approvals(
        self, watchlist: WatchlistConfig, api_key: str | None = None
    ) -> list[Item]:
        """Fetch drug approval records for all watchlist drugs."""
        seen_ids: set[str] = set()
        raw_records: list[dict[str, Any]] = []

        results = await asyncio.gather(
            *[self._fetch_drug(drug, api_key) for drug in watchlist.drugs],
            return_exceptions=True,
        )

        for drug, result in zip(watchlist.drugs, results, strict=False):
            if isinstance(result, BaseException):
                log.warning("openfda.query_failed", drug=drug, error=str(result))
                continue
            for record in result:
                app_num: str = record.get("application_number") or ""
                if app_num and app_num not in seen_ids:
                    seen_ids.add(app_num)
                    raw_records.append(record)

        items = [normalize_approval(r) for r in raw_records]
        log.info("openfda.fetched", count=len(items))
        return items
