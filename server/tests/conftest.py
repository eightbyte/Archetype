"""Shared pytest fixtures (P1-8).

Every test runs against ``tmp_path``. Nothing here touches the network, a real model, or a real
API key (outline section 8).

What lives where:

* ``tests/fakes/`` - code that stands in for a real collaborator (``FakeProvider`` and
  ``FakeEmbedder`` arrive in Phases 4 and 5). Empty of fakes in Phase 1, because Phase 1 has no
  collaborator to fake: SQLite runs for real against ``tmp_path``.
* ``tests/fixtures/`` - static data: database files at known schema versions, the shared
  projection cases, and the contract fixtures the frontend suite reads.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from archetype.app import create_app
from archetype.config import CONFIG_FILE_ENV_VAR, Settings, reset_settings_cache
from archetype.manuscript.documents import DocumentStore
from archetype.projects import ProjectHandle, ProjectStore, open_migrated

FIXTURES_DIR = Path(__file__).parent / "fixtures"
DB_FIXTURES_DIR = FIXTURES_DIR / "db"
PROJECTION_FIXTURES_DIR = FIXTURES_DIR / "projection"
CONTRACT_FIXTURES_DIR = FIXTURES_DIR / "contract"


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
    """Settings pointed at the temporary data root, with no frontend mounted.

    ``web_dist`` is pinned off (P1-14) so the suite says the same thing whether or not the
    developer has run ``npm run build``. The tests that care about the static mount are in
    ``test_static.py`` and build their own bundle.
    """
    return Settings(data_dir=data_dir, web_dist=None)


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


# -- the application ------------------------------------------------------------------------


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    """An application over the temporary data root."""
    return create_app(settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    """An HTTP client for the application, raising nothing the browser would not see.

    ``raise_server_exceptions=False`` so a test can assert on the ``500`` envelope instead of
    catching the exception the way the test client would otherwise re-raise it (P1-13).
    """
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


# -- factories ------------------------------------------------------------------------------


@pytest.fixture
def make_project(store: ProjectStore):
    """Create a project and return its handle. ``make_project("The Long Road")``."""

    def factory(title: str = "Test Manuscript") -> ProjectHandle:
        return store.create(title)

    return factory


@pytest.fixture
def project(make_project) -> ProjectHandle:
    """One project, no documents."""
    return make_project()


@pytest.fixture
def documents(project: ProjectHandle) -> DocumentStore:
    """The document store for :func:`project`."""
    return DocumentStore(project)


@pytest.fixture
def make_document(documents: DocumentStore):
    """Create a chapter in :func:`project`, optionally from prose.

    ``make_document(title="Arrival", paragraphs=["The harbour was grey."], headings=[(1, "One")])``
    builds a real ProseMirror document rather than making each test hand-write one.
    """

    def factory(
        title: str | None = None,
        *,
        paragraphs: list[str] | None = None,
        headings: list[tuple[int, str]] | None = None,
    ):
        content = None
        if paragraphs is not None or headings is not None:
            content = build_document(paragraphs=paragraphs, headings=headings)
        return documents.create(title, content=content)

    return factory


def build_document(
    *,
    paragraphs: list[str] | None = None,
    headings: list[tuple[int, str]] | None = None,
) -> dict[str, Any]:
    """A ProseMirror document with the given headings first, then the given paragraphs."""
    nodes: list[dict[str, Any]] = []
    for level, text in headings or []:
        nodes.append({"type": "heading", "attrs": {"level": level}, "content": [text_node(text)]})
    for text in paragraphs or []:
        nodes.append({"type": "paragraph", "content": [text_node(text)]})
    return {"type": "doc", "content": nodes or [{"type": "paragraph"}]}


def text_node(text: str, marks: list[str] | None = None) -> dict[str, Any]:
    """One inline text node, optionally carrying marks."""
    node: dict[str, Any] = {"type": "text", "text": text}
    if marks:
        node["marks"] = [{"type": mark} for mark in marks]
    return node


# -- shared fixture data --------------------------------------------------------------------


def load_projection_cases() -> list[dict[str, Any]]:
    """The projection cases both suites run against (P1-7).

    The same file is read by ``web/src/__tests__/projection.test.ts``, so a rule that changes on
    one side and not the other fails a test rather than confusing a writer's table of contents.
    """
    raw = (PROJECTION_FIXTURES_DIR / "cases.json").read_text(encoding="utf-8")
    return json.loads(raw)["cases"]
