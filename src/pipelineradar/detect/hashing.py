"""Stable content hash for change detection.

SHA-256 of the canonical JSON of {title, summary, published_at}.
Deliberately excludes the full raw API record so that irrelevant
metadata changes (e.g. API version fields, re-ordered keys) do not
falsely trigger change detection.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from pipelineradar.schemas import Item


def stable_hash_fields(title: str, summary: str, published_at: datetime | None) -> str:
    """Canonical hash of the three fields that carry meaningful change signal."""
    payload = {
        "published_at": published_at.isoformat() if published_at else None,
        "summary": summary,
        "title": title,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def stable_hash(item: Item) -> str:
    return stable_hash_fields(item.title, item.summary, item.published_at)
