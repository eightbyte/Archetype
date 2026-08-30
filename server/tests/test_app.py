"""P1-1 - the app builds and answers. Routes proper arrive in P1-5."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from archetype import __version__
from archetype.app import create_app
from archetype.config import Settings


def test_health_reports_ok_and_the_version(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_creating_the_app_prepares_the_data_directory(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "fresh-data")
    create_app(settings)
    assert settings.projects_dir.is_dir()


def test_openapi_generates_cleanly(settings: Settings) -> None:
    schema = create_app(settings).openapi()
    assert schema["info"]["title"] == "Archetype"
    assert "/api/health" in schema["paths"]
