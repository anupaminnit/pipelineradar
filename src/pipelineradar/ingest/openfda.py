"""openFDA drug approvals ingestion client.

Fetches recent NDA/BLA approvals from the openFDA drugsfda endpoint. An
optional API key (OPENFDA_API_KEY) raises the daily rate limit; the client
falls back gracefully to the anonymous limit when the key is absent.

Phase 1: implement OpenFDAClient(BaseIngestClient) with fetch_approvals().
"""

from __future__ import annotations

# Phase 1: implement OpenFDAClient
