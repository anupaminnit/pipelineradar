"""Europe PMC literature ingestion client.

Fetches recent publications matching watchlist terms from the Europe PMC REST
search API (no auth required). Filters by publication date and paginates via
cursor-based pagination.

Phase 1: implement EuropePMCClient(BaseIngestClient) with fetch_publications().
"""

from __future__ import annotations

# Phase 1: implement EuropePMCClient
