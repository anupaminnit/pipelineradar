"""ClinicalTrials.gov v2 ingestion client.

Fetches studies matching the watchlist from the public ClinicalTrials.gov v2
REST API (no auth required). Filters by condition / intervention / sponsor and
paginates via pageToken until the watchlist window is exhausted.

Phase 1: implement ClinicalTrialsClient(BaseIngestClient) with fetch_studies().
"""

from __future__ import annotations

# Phase 1: implement ClinicalTrialsClient
