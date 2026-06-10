"""Tests for the normalization functions in each ingestion client.

Normalization is pure (no IO), so these tests don't need respx or a DB.
They verify that raw API records map to the correct Item fields.
"""

from datetime import UTC

from pipelineradar.ingest.base import compute_content_hash
from pipelineradar.ingest.clinicaltrials import normalize_study
from pipelineradar.ingest.europepmc import normalize_publication
from pipelineradar.ingest.openfda import normalize_approval
from pipelineradar.schemas import ItemType

# ── ClinicalTrials ────────────────────────────────────────────────────────────

_CT_STUDY: dict = {
    "protocolSection": {
        "identificationModule": {
            "nctId": "NCT04177173",
            "briefTitle": "A Study of Pembrolizumab in Adults With NSCLC",
        },
        "statusModule": {
            "overallStatus": "RECRUITING",
            "lastUpdatePostDateStruct": {"date": "2024-05-01", "type": "ACTUAL"},
        },
        "descriptionModule": {
            "briefSummary": "This study evaluates pembrolizumab monotherapy.",
        },
    }
}


def test_normalize_study_fields() -> None:
    item = normalize_study(_CT_STUDY)
    assert item.source == "clinicaltrials"
    assert item.source_id == "NCT04177173"
    assert item.item_type == ItemType.clinical_trial
    assert "Pembrolizumab" in item.title
    assert item.url == "https://clinicaltrials.gov/study/NCT04177173"
    assert item.published_at is not None
    assert item.published_at.tzinfo == UTC
    assert len(item.content_hash) == 64  # SHA-256 hex


def test_normalize_study_missing_fields() -> None:
    item = normalize_study({})
    assert item.source == "clinicaltrials"
    assert item.source_id == ""
    assert item.title == ""
    assert item.published_at is None


# ── openFDA ───────────────────────────────────────────────────────────────────

_FDA_RECORD: dict = {
    "application_number": "BLA125514",
    "sponsor_name": "MERCK SHARP DOHME LLC",
    "openfda": {
        "brand_name": ["KEYTRUDA"],
        "generic_name": ["PEMBROLIZUMAB"],
    },
    "submissions": [
        {
            "submission_type": "ORIG",
            "submission_number": "1",
            "submission_status": "AP",
            "submission_status_date": "20140910",
        }
    ],
}


def test_normalize_approval_fields() -> None:
    item = normalize_approval(_FDA_RECORD)
    assert item.source == "openfda"
    assert item.source_id == "BLA125514"
    assert item.item_type == ItemType.drug_approval
    assert "KEYTRUDA" in item.title
    assert "PEMBROLIZUMAB" in item.title
    assert item.published_at is not None
    assert item.published_at.year == 2014


def test_normalize_approval_missing_openfda() -> None:
    item = normalize_approval({"application_number": "NDA999999"})
    assert item.source_id == "NDA999999"
    assert item.item_type == ItemType.drug_approval


# ── Europe PMC ────────────────────────────────────────────────────────────────

_PMC_RECORD: dict = {
    "id": "35123456",
    "source": "MED",
    "pmid": "35123456",
    "title": "Pembrolizumab plus chemotherapy in NSCLC",
    "abstractText": "Background: PD-1 blockade with pembrolizumab...",
    "firstPublicationDate": "2022-04-15",
    "journalTitle": "New England Journal of Medicine",
}


def test_normalize_publication_fields() -> None:
    item = normalize_publication(_PMC_RECORD)
    assert item.source == "europepmc"
    assert item.source_id == "35123456"
    assert item.item_type == ItemType.publication
    assert "Pembrolizumab" in item.title
    assert "PD-1" in item.summary
    assert item.url == "https://europepmc.org/article/MED/35123456"
    assert item.published_at is not None
    assert item.published_at.year == 2022


def test_normalize_publication_pmcid_url() -> None:
    record = {**_PMC_RECORD, "pmcid": "PMC9012345"}
    item = normalize_publication(record)
    assert "PMC/9012345" in item.url


# ── content hash ─────────────────────────────────────────────────────────────


def test_content_hash_deterministic() -> None:
    raw = {"a": 1, "b": [1, 2]}
    assert compute_content_hash(raw) == compute_content_hash(raw)


def test_content_hash_key_order_independent() -> None:
    a = {"x": 1, "y": 2}
    b = {"y": 2, "x": 1}
    assert compute_content_hash(a) == compute_content_hash(b)


def test_content_hash_changes_on_content_change() -> None:
    a = {"title": "Study A"}
    b = {"title": "Study B"}
    assert compute_content_hash(a) != compute_content_hash(b)
