"""Entity resolver: maps raw name mentions to canonical Entity rows.

Three-layer strategy (fastest-first, stop on first hit):
  1. Normalise + alias map  — deterministic, no I/O
  2. DB registry lookup     — fast, no LLM tokens
  3. LLM disambiguation     — fallback; result is cached to DB + in-memory
"""

from __future__ import annotations

import structlog

from pipelineradar.db.client import SupabaseClient
from pipelineradar.llm.provider import LLMProvider
from pipelineradar.resolve.aliases import apply_alias, normalise, normalise_company
from pipelineradar.schemas import Entity, EntityKind

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

_LLM_CANDIDATE_LIMIT = 20


class EntityResolver:
    def __init__(self, db: SupabaseClient, llm: LLMProvider) -> None:
        self._db = db
        self._llm = llm
        # In-process cache keyed by (canonical_name, kind) so the same entity
        # is not looked up twice within one pipeline run.
        self._cache: dict[tuple[str, str], Entity] = {}

    async def resolve(self, raw_name: str, kind: str, context: str = "") -> Entity:
        """Return the canonical Entity for raw_name, creating one if needed."""
        norm = normalise_company(raw_name) if kind == "company" else normalise(raw_name)
        canonical = apply_alias(norm, kind)

        cache_key = (canonical, kind)
        if cache_key in self._cache:
            return self._cache[cache_key]

        # ── Layer 2: DB lookup ────────────────────────────────────────────────
        entity_kind = EntityKind(kind)
        entity = self._db.lookup_entity(canonical, entity_kind)
        if entity is not None:
            log.debug("entity_resolver.db_hit", canonical=canonical, kind=kind)
            self._cache[cache_key] = entity
            return entity

        # ── Layer 3: LLM disambiguation ───────────────────────────────────────
        candidates = self._db.fetch_entities_by_kind(entity_kind)
        if candidates:
            entity = await self._llm_resolve(raw_name, canonical, entity_kind, candidates, context)
        else:
            entity = self._make_new(canonical, entity_kind, raw_name)

        entity = self._db.upsert_entity(entity)
        self._cache[cache_key] = entity
        log.info(
            "entity_resolver.resolved",
            raw=raw_name,
            canonical=entity.canonical_name,
            kind=kind,
        )
        return entity

    # ── private helpers ───────────────────────────────────────────────────────

    async def _llm_resolve(
        self,
        raw_name: str,
        normalised: str,
        kind: EntityKind,
        candidates: list[Entity],
        context: str,
    ) -> Entity:
        top = candidates[:_LLM_CANDIDATE_LIMIT]
        lines = "\n".join(
            f"{i + 1}. {e.canonical_name}"
            + (f" (also known as: {', '.join(e.aliases)})" if e.aliases else "")
            for i, e in enumerate(top)
        )
        system = (
            "You are an entity-disambiguation assistant for a life-sciences pipeline. "
            "Given a raw mention and a numbered list of known canonical entities, "
            "respond with ONLY the canonical name of the best match, "
            "or the single word NEW if none match."
        )
        user = (
            f"Raw mention: {raw_name!r}\n"
            f"Kind: {kind}\n"
            f"Context: {context or 'none'}\n\n"
            f"Known entities:\n{lines}\n\n"
            "Reply with ONLY the canonical name from the list, or NEW."
        )
        answer = (await self._llm.complete(system=system, user=user, max_tokens=64)).lower()

        for entity in top:
            if entity.canonical_name.lower() == answer:
                return entity

        return self._make_new(normalised, kind, raw_name)

    def _make_new(self, canonical: str, kind: EntityKind, raw_name: str) -> Entity:
        aliases = [] if raw_name.lower() == canonical else [raw_name.lower()]
        return Entity(canonical_name=canonical, kind=kind, aliases=aliases)
