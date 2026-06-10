"""Tests for EntityResolver — the three-layer entity disambiguation strategy.

All tests are fully synchronous with respect to I/O: DB and LLM calls are
mocked so no network or Supabase connection is required.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from pipelineradar.resolve.entity_resolver import EntityResolver
from pipelineradar.schemas import Entity, EntityKind


def _make_entity(canonical: str, kind: EntityKind = EntityKind.drug) -> Entity:
    return Entity(id=uuid4(), canonical_name=canonical, kind=kind, aliases=[])


def _make_db(
    lookup_return: Entity | None = None,
    candidates: list[Entity] | None = None,
) -> MagicMock:
    db = MagicMock()
    db.lookup_entity.return_value = lookup_return
    db.fetch_entities_by_kind.return_value = candidates or []
    db.upsert_entity.side_effect = lambda e: e  # echo back the entity
    return db


def _make_llm(answer: str = "NEW") -> AsyncMock:
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value=answer)
    return llm


# ── Layer 1: alias map hit (no DB, no LLM) ────────────────────────────────────


@pytest.mark.asyncio
async def test_alias_hit_no_db_call() -> None:
    """'keytruda' resolves to 'pembrolizumab' via alias map; DB is never called."""
    pembrolizumab = _make_entity("pembrolizumab")
    db = _make_db(lookup_return=pembrolizumab)
    llm = _make_llm()

    resolver = EntityResolver(db, llm)
    entity = await resolver.resolve("keytruda", "drug")

    assert entity.canonical_name == "pembrolizumab"
    # DB was queried with the canonical alias-mapped name
    db.lookup_entity.assert_called_once_with("pembrolizumab", EntityKind.drug)
    llm.complete.assert_not_called()


@pytest.mark.asyncio
async def test_alias_company_msd() -> None:
    """'MSD' resolves to 'merck sharp & dohme' via company alias map."""
    msd_entity = _make_entity("merck sharp & dohme", EntityKind.company)
    db = _make_db(lookup_return=msd_entity)
    llm = _make_llm()

    resolver = EntityResolver(db, llm)
    entity = await resolver.resolve("MSD", "company")

    assert entity.canonical_name == "merck sharp & dohme"
    llm.complete.assert_not_called()


# ── Layer 2: DB registry hit (no LLM) ────────────────────────────────────────


@pytest.mark.asyncio
async def test_db_hit_no_llm_call() -> None:
    """Name already in registry: returns the existing entity without LLM."""
    existing = _make_entity("nivolumab")
    db = _make_db(lookup_return=existing)
    llm = _make_llm()

    resolver = EntityResolver(db, llm)
    entity = await resolver.resolve("nivolumab", "drug")

    assert entity.id == existing.id
    assert entity.canonical_name == "nivolumab"
    llm.complete.assert_not_called()


# ── Layer 3: LLM fallback (cached on second call) ────────────────────────────


@pytest.mark.asyncio
async def test_llm_fallback_cached() -> None:
    """Unknown name goes to LLM on first call; second call uses in-process cache."""
    candidate = _make_entity("pembrolizumab")
    db = _make_db(lookup_return=None, candidates=[candidate])
    llm = _make_llm(answer="pembrolizumab")

    resolver = EntityResolver(db, llm)

    # First call — LLM is invoked
    entity1 = await resolver.resolve("mk-3475", "drug")
    assert entity1.canonical_name == "pembrolizumab"
    assert llm.complete.call_count == 1

    # Second call for the same name — cache hit, LLM NOT called again
    entity2 = await resolver.resolve("mk-3475", "drug")
    assert entity2.id == entity1.id
    assert llm.complete.call_count == 1  # still 1


@pytest.mark.asyncio
async def test_llm_new_entity_created() -> None:
    """When LLM returns NEW, a fresh entity is inserted into the DB."""
    db = _make_db(lookup_return=None, candidates=[])
    llm = _make_llm(answer="NEW")

    resolver = EntityResolver(db, llm)
    entity = await resolver.resolve("some-novel-drug-xyz", "drug")

    assert entity.canonical_name == "some-novel-drug-xyz"
    db.upsert_entity.assert_called_once()
    inserted: Entity = db.upsert_entity.call_args[0][0]
    assert inserted.kind == EntityKind.drug
