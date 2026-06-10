"""Environment + watchlist configuration loader.

Loads secrets from .env and structured watchlist from config/watchlist.yaml
into typed Pydantic settings. Single source of truth for all configuration;
every other module receives a Settings instance — never reads env directly.
"""

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ScheduleConfig(BaseModel):
    cron: str = "0 7 * * *"
    timezone: str = "UTC"


class WatchlistConfig(BaseModel):
    therapeutic_areas: list[str] = Field(default_factory=list)
    drugs: list[str] = Field(default_factory=list)
    companies: list[str] = Field(default_factory=list)
    targets: list[str] = Field(default_factory=list)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Supabase — required
    supabase_url: str
    supabase_service_key: str

    # Anthropic — required
    anthropic_api_key: str

    # Optional integrations
    openfda_api_key: str | None = None
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    email_from: str | None = None
    email_to: str | None = None
    alert_to_email: str | None = None  # recipient for ALERT_TO_EMAIL env var

    # App
    watchlist_path: Path = Path("config/watchlist.yaml")
    log_level: str = "INFO"

    @property
    def watchlist(self) -> WatchlistConfig:
        raw: Any = yaml.safe_load(self.watchlist_path.read_text())
        return WatchlistConfig.model_validate(raw)


def get_settings() -> Settings:
    return Settings()
