"""Europe PMC literature ingestion client.

Queries the Europe PMC REST search API (no auth) for publications matching
each watchlist drug. Uses cursorMark-based pagination and returns full-record
results (resultType=core) so that abstracts are included.
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

_BASE_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
_PAGE_SIZE = 100


def _parse_pmc_date(date_str: str | None) -> datetime | None:
    if not date_str:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(date_str, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def normalize_publication(raw: dict[str, Any]) -> Item:
    """Map a single Europe PMC result record to a canonical Item."""
    pmid: str = raw.get("pmid") or ""
    pmcid: str = raw.get("pmcid") or ""
    source_code: str = raw.get("source") or "MED"
    record_id: str = pmid or raw.get("id") or ""

    title: str = raw.get("title") or ""
    abstract: str = raw.get("abstractText") or ""
    date_str: str = raw.get("firstPublicationDate") or raw.get("pubYear") or ""
    published_at = _parse_pmc_date(date_str)

    if pmcid:
        pmcid_digits = pmcid.replace("PMC", "")
        url = f"https://europepmc.org/article/PMC/{pmcid_digits}"
    elif pmid:
        url = f"https://europepmc.org/article/{source_code}/{pmid}"
    else:
        url = f"https://europepmc.org/search?query={record_id}"

    return Item(
        source="europepmc",
        source_id=record_id,
        item_type=ItemType.publication,
        title=title,
        summary=abstract,
        url=url,
        published_at=published_at,
        raw=raw,
        content_hash=stable_hash_fields(title, abstract, published_at),
    )


_MAX_PAGES = 3  # 300 records/term for Phase 1; increase for production


class EuropePMCClient(BaseIngestClient):
    source = "europepmc"

    async def _fetch_query(self, query: str) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        cursor = "*"
        pages = 0

        while pages < _MAX_PAGES:
            params: dict[str, Any] = {
                "query": query,
                "format": "json",
                "resultType": "lite",
                "pageSize": _PAGE_SIZE,
                "cursorMark": cursor,
            }

            data = await self._get(_BASE_URL, params=params)
            result_list: dict[str, Any] = data.get("resultList") or {}
            results: list[dict[str, Any]] = result_list.get("result") or []
            records.extend(results)
            pages += 1

            next_cursor: str = data.get("nextCursorMark") or ""
            if not results or next_cursor == cursor:
                break
            cursor = next_cursor

        return records

    async def fetch_publications(self, watchlist: WatchlistConfig) -> list[Item]:
        """Fetch publications for all watchlist drugs."""
        seen_ids: set[str] = set()
        raw_records: list[dict[str, Any]] = []

        # Search each drug; also include target names for relevant context
        terms = list(watchlist.drugs) + list(watchlist.targets)
        queries = [f'"{term}" AND (SRC:MED OR SRC:PPR)' for term in terms]

        results = await asyncio.gather(
            *[self._fetch_query(q) for q in queries],
            return_exceptions=True,
        )

        for term, result in zip(terms, results, strict=False):
            if isinstance(result, BaseException):
                log.warning("europepmc.query_failed", term=term, error=str(result))
                continue
            for record in result:
                rid: str = record.get("pmid") or record.get("id") or ""
                if rid and rid not in seen_ids:
                    seen_ids.add(rid)
                    raw_records.append(record)

        items = [normalize_publication(r) for r in raw_records]
        log.info("europepmc.fetched", count=len(items))
        return items
