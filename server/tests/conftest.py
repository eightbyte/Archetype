"""Shared pytest fixtures.

Group A provides only what P1-2 through P1-4 need. The full harness - factory helpers, the
httpx client fixture, ``tests/fakes/``, and the contract fixtures - is P1-8.

Every test runs against ``tmp_path``. Nothing here touches the network, a real model, or a real
API key (outline section 8).
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from archetype.config import CONFIG_FILE_ENV_VAR, Settings, reset_settings_cache
from archetype.projects import ProjectStore, open_migrated

FIXTURES_DIR = Path(__file__).parent / "fixtures"
DB_FIXTURES_DIR = FIXTURES_DIR / "db"


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keep the developer's real environment out of the suite.

    Any stray ``ARCHETYPE_*`` variable in the shell would otherwise leak into settings tests, and
    a real ``config.yaml`` at the repo root would leak into all of them.
    """
    for name in list(os.environ):
        if name.startswith("ARCHETYPE_"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(CONFIG_FILE_ENV_VAR, str(tmp_path / "absent-config.yaml"))
    reset_settings_cache()
    yield
    reset_settings_cache()


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """A data root with the projects directory already made."""
    path = tmp_path / "data"
    (path / "projects").mkdir(parents=True)
    return path


@pytest.fixture
def settings(data_dir: Path) -> Settings:
    """Settings pointed at the temporary data root."""
    return Settings(data_dir=data_dir)


@pytest.fixture
def projects_dir(data_dir: Path) -> Path:
    return data_dir / "projects"


@pytest.fixture
def store(projects_dir: Path) -> ProjectStore:
    """A project store over an empty temporary projects directory."""
    return ProjectStore(projects_dir)


@pytest.fixture
def migrated_db(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    """An open connection to a freshly migrated project file."""
    conn = open_migrated(tmp_path / "migrated.sqlite")
    try:
        yield conn
    finally:
        conn.close()
