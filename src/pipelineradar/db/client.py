"""Supabase client wrapper with typed query helpers.

All DB access goes through SupabaseClient. Raw supabase-py calls are confined
here so the rest of the codebase never imports supabase directly.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from supabase import Client, create_client

from pipelineradar.schemas import Brief, Entity, EntityKind, Item, Run, RunStatus

if TYPE_CHECKING:
    from pipelineradar.config import Settings

_BATCH_SIZE = 25


class SupabaseClient:
    def __init__(self, client: Client) -> None:
        self._client = client

    # ── healthcheck ───────────────────────────────────────────────────────────

    def healthcheck(self) -> None:
        """Verify DB connectivity and confirm the migration has been applied."""
        self._client.table("runs").select("id").limit(1).execute()

    # ── runs ──────────────────────────────────────────────────────────────────

    def create_run(self) -> Run:
        """Insert a new run row with status=running and return it."""
        run = Run()
        data = run.model_dump(mode="json")
        self._client.table("runs").insert(data).execute()
        return run

    def finish_run(
        self,
        run_id: UUID,
        *,
        items_seen: int,
        items_new: int,
        status: RunStatus,
    ) -> None:
        """Update a run row to reflect completion."""
        self._client.table("runs").update(
            {
                "finished_at": datetime.now(tz=UTC).isoformat(),
                "status": status.value,
                "items_seen": items_seen,
                "items_new": items_new,
            }
        ).eq("id", str(run_id)).execute()

    # ── items ─────────────────────────────────────────────────────────────────

    def upsert_items(self, items: list[Item]) -> int:
        """Upsert items in batches, returning the total count processed."""
        if not items:
            return 0

        total = 0
        for i in range(0, len(items), _BATCH_SIZE):
            batch = items[i : i + _BATCH_SIZE]
            rows = [_item_to_row(item) for item in batch]
            self._client.table("items").upsert(
                rows,
                on_conflict="source,source_id",
            ).execute()
            total += len(batch)

        return total

    # ── entities ─────────────────────────────────────────────────────────────

    def lookup_entity(self, canonical_name: str, kind: EntityKind) -> Entity | None:
        """Return the entity matching (canonical_name, kind), or None."""
        response = (
            self._client.table("entities")
            .select("*")
            .eq("canonical_name", canonical_name)
            .eq("kind", kind.value)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        if not rows:
            return None
        return Entity.model_validate(rows[0])

    def fetch_entities_by_kind(self, kind: EntityKind) -> list[Entity]:
        """Return all entities of the given kind (for LLM disambiguation context)."""
        response = (
            self._client.table("entities")
            .select("*")
            .eq("kind", kind.value)
            .execute()
        )
        return [Entity.model_validate(row) for row in (response.data or [])]

    def upsert_entity(self, entity: Entity) -> Entity:
        """Get-or-create an entity by (canonical_name, kind); merge aliases."""
        existing = self.lookup_entity(entity.canonical_name, entity.kind)
        if existing is not None:
            merged = list({*existing.aliases, *entity.aliases})
            if set(merged) != set(existing.aliases):
                self._client.table("entities").update({"aliases": merged}).eq(
                    "id", str(existing.id)
                ).execute()
            return existing.model_copy(update={"aliases": merged})
        self._client.table("entities").insert(entity.model_dump(mode="json")).execute()
        return entity

    # ── change detection ─────────────────────────────────────────────────────

    def get_item_hashes(
        self, source_ids: list[tuple[str, str]]
    ) -> dict[tuple[str, str], str]:
        """Return {(source, source_id): content_hash} for every known pair."""
        if not source_ids:
            return {}

        by_source: dict[str, list[str]] = {}
        for source, sid in source_ids:
            by_source.setdefault(source, []).append(sid)

        result: dict[tuple[str, str], str] = {}
        for source, sids in by_source.items():
            for i in range(0, len(sids), 200):
                chunk = sids[i : i + 200]
                response = (
                    self._client.table("items")
                    .select("source,source_id,content_hash")
                    .eq("source", source)
                    .in_("source_id", chunk)
                    .execute()
                )
                for row in response.data or []:
                    r = cast(dict[str, Any], row)
                    key = (cast(str, r["source"]), cast(str, r["source_id"]))
                    result[key] = cast(str, r["content_hash"])
        return result

    # ── items ─────────────────────────────────────────────────────────────────

    def fetch_items(self, limit: int = 5) -> list[dict[str, Any]]:
        """Return the most recently ingested items for display."""
        response = (
            self._client.table("items")
            .select("source,source_id,item_type,title,url,ingested_at")
            .order("ingested_at", desc=True)
            .limit(limit)
            .execute()
        )
        return cast(list[dict[str, Any]], response.data or [])


    # ── runs (API queries) ────────────────────────────────────────────────────

    def get_run(self, run_id: UUID) -> Run | None:
        """Fetch a single run by ID, or None if not found."""
        response = (
            self._client.table("runs")
            .select("*")
            .eq("id", str(run_id))
            .limit(1)
            .execute()
        )
        rows = response.data or []
        if not rows:
            return None
        return Run.model_validate(rows[0])

    # ── briefs ────────────────────────────────────────────────────────────────

    def upsert_brief(self, brief: Brief) -> None:
        """Insert a rendered brief row; no conflict key — briefs are append-only."""
        self._client.table("briefs").insert(brief.model_dump(mode="json")).execute()

    def get_briefs(self, limit: int = 10) -> list[Brief]:
        """Return the most recent briefs (lightweight — includes all fields)."""
        response = (
            self._client.table("briefs")
            .select("*")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return [Brief.model_validate(row) for row in (response.data or [])]

    def get_brief(self, brief_id: UUID) -> Brief | None:
        """Return a single brief by ID, or None if not found."""
        response = (
            self._client.table("briefs")
            .select("*")
            .eq("id", str(brief_id))
            .limit(1)
            .execute()
        )
        rows = response.data or []
        if not rows:
            return None
        return Brief.model_validate(rows[0])

    def run_has_brief(self, run_id: UUID) -> bool:
        """Return True if at least one brief was generated for this run."""
        response = (
            self._client.table("briefs")
            .select("id")
            .eq("run_id", str(run_id))
            .limit(1)
            .execute()
        )
        return bool(response.data)


def _item_to_row(item: Item) -> dict[str, Any]:
    """Serialize an Item to a dict compatible with the Supabase REST API."""
    row = item.model_dump(mode="json")
    # uuid[] columns need a list of strings; model_dump already produces that
    # entity_ids is always [] in Phase 1 so this is safe
    return row


def get_client(settings: Settings) -> SupabaseClient:
    client: Client = create_client(settings.supabase_url, settings.supabase_service_key)
    # Explicitly pin the PostgREST auth header to the service role key so it is
    # never overridden by a GoTrue session token after client initialisation.
    client.postgrest.auth(settings.supabase_service_key)
    return SupabaseClient(client)
