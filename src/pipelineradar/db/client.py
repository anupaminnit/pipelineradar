"""Supabase client wrapper with typed query helpers.

All DB access goes through SupabaseClient. Raw supabase-py calls are confined
here so the rest of the codebase never imports supabase directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from supabase import Client, create_client

if TYPE_CHECKING:
    from pipelineradar.config import Settings


class SupabaseClient:
    def __init__(self, client: Client) -> None:
        self._client = client

    def healthcheck(self) -> None:
        """Verify DB connectivity and that the schema migration has been applied."""
        self._client.table("runs").select("id").limit(1).execute()


def get_client(settings: Settings) -> SupabaseClient:
    client: Client = create_client(settings.supabase_url, settings.supabase_service_key)
    return SupabaseClient(client)
