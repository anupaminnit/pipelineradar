"""Tests for config loading and watchlist parsing."""

from pathlib import Path

import pytest

from pipelineradar.config import Settings, WatchlistConfig


@pytest.fixture()
def watchlist_file(tmp_path: Path) -> Path:
    content = """
therapeutic_areas: [oncology]
drugs: [pembrolizumab, nivolumab]
companies: ["Merck Sharp & Dohme"]
targets: [PD-1]
"""
    p = tmp_path / "watchlist.yaml"
    p.write_text(content)
    return p


def test_watchlist_parses(watchlist_file: Path) -> None:
    settings = Settings(
        supabase_url="https://example.supabase.co",
        supabase_service_key="test-key",
        anthropic_api_key="test-key",
        watchlist_path=watchlist_file,
    )
    wl: WatchlistConfig = settings.watchlist
    assert "oncology" in wl.therapeutic_areas
    assert "pembrolizumab" in wl.drugs
    assert "nivolumab" in wl.drugs
    assert "PD-1" in wl.targets


def test_watchlist_config_defaults() -> None:
    wl = WatchlistConfig()
    assert wl.therapeutic_areas == []
    assert wl.drugs == []
