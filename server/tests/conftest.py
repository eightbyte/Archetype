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
from archetype.bible.entries import Entry, EntryStore
from archetype.bible.schema import EntryKind
from archetype.config import CONFIG_FILE_ENV_VAR, Settings, reset_settings_cache
from archetype.ids import IdPrefix, new_id
from archetype.manuscript.anchors import EFFECTIVE_STATUS_SQL
from archetype.manuscript.documents import DocumentStore
from archetype.manuscript.snapshots import SnapshotStore
from archetype.projects import ProjectHandle, ProjectStore, open_migrated
from archetype.projects.db import transaction, utc_now

FIXTURES_DIR = Path(__file__).parent / "fixtures"
DB_FIXTURES_DIR = FIXTURES_DIR / "db"
PROJECTION_FIXTURES_DIR = FIXTURES_DIR / "projection"
CONTRACT_FIXTURES_DIR = FIXTURES_DIR / "contract"
ANCHOR_FIXTURES_DIR = FIXTURES_DIR / "anchors"
MARKDOWN_FIXTURES_DIR = FIXTURES_DIR / "markdown"
SCHEMA_FIXTURES_DIR = FIXTURES_DIR / "schema"


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


@pytest.fixture
def snapshots(project: ProjectHandle) -> SnapshotStore:
    """The snapshot store for :func:`project` (P2-3)."""
    return SnapshotStore(project)


@pytest.fixture
def make_anchor(project: ProjectHandle):
    """Insert an anchor row directly, and return its id (P2-1).

    Deliberately SQL rather than :class:`~archetype.manuscript.anchors.store.AnchorStore`, even
    now that one exists: what ``test_chapters.py`` and ``test_anchor_status.py`` are about is the
    derivation rule over a row, and going through the store would make those tests depend on the
    resolver agreeing with them about the text. The store has its own tests.
    """

    def factory(
        document_id: str,
        *,
        quote: str = "the harbour was grey",
        status: str = "ok",
        from_pos: int = 1,
        to_pos: int = 21,
        version: int = 1,
    ) -> str:
        anchor_id = new_id(IdPrefix.ANCHOR)
        now = utc_now()
        with project.connect() as conn, transaction(conn):
            conn.execute(
                "INSERT INTO anchor (id, project_id, document_id, from_pos, to_pos, quote, "
                "prefix, suffix, status, label, document_version, created_at, updated_at, "
                "checked_at) VALUES (?, ?, ?, ?, ?, ?, '', '', ?, '', ?, ?, ?, ?)",
                (
                    anchor_id,
                    project.id,
                    document_id,
                    from_pos,
                    to_pos,
                    quote,
                    status,
                    version,
                    now,
                    now,
                    now,
                ),
            )
        return anchor_id

    return factory


# -- the bible (Phase 3) --------------------------------------------------------------------


@pytest.fixture
def entries(project: ProjectHandle) -> EntryStore:
    """The entry store for :func:`project` (P3-3)."""
    return EntryStore(project)


@pytest.fixture
def make_entry(entries: EntryStore):
    """Create an entry, defaulting to a character. ``make_entry("Mira", kind="place")``."""

    def factory(name: str = "Mira", *, kind: str = EntryKind.CHARACTER, **fields) -> Entry:
        return entries.create(kind, name, **fields)

    return factory


@pytest.fixture
def make_link(project: ProjectHandle):
    """Insert a link row directly, and return its id.

    Deliberately SQL: ``LinkStore`` is P3-6 and Group A must be able to prove D27's dependent
    rule without it. When the store arrives, this fixture stays - the same argument
    :func:`make_anchor` makes, one table over: what these tests are about is the predicate over
    a row, not the store's refusals, which have their own tests.
    """

    def factory(
        from_entry: str,
        to_entry: str,
        *,
        relation: str = "knows",
        deleted: bool = False,
    ) -> str:
        link_id = new_id(IdPrefix.LINK)
        now = utc_now()
        with project.connect() as conn, transaction(conn):
            conn.execute(
                "INSERT INTO entry_link (id, project_id, from_entry, to_entry, relation, "
                "attributes_json, created_at, updated_at, deleted_at) "
                "VALUES (?, ?, ?, ?, ?, '{}', ?, ?, ?)",
                (
                    link_id,
                    project.id,
                    from_entry,
                    to_entry,
                    relation,
                    now,
                    now,
                    now if deleted else None,
                ),
            )
        return link_id

    return factory


@pytest.fixture
def read_anchor_status(project: ProjectHandle):
    """The status a reader sees for one anchor, derived exactly as the code derives it (D22)."""

    def read(anchor_id: str) -> str:
        with project.connect() as conn:
            row = conn.execute(
                f"SELECT {EFFECTIVE_STATUS_SQL} AS status FROM anchor "
                "JOIN document ON document.id = anchor.document_id WHERE anchor.id = ?",
                (anchor_id,),
            ).fetchone()
        return row["status"]

    return read


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


def build_blocks(blocks: list[str]) -> dict[str, Any]:
    """A document from the compact block notation the anchor corpus uses (P2-8).

    A plain string is a paragraph, ``"---"`` is a ``horizontalRule``, and a newline inside a
    string is a ``hardBreak``. The node vocabulary itself is the projection corpus's business;
    these cases are about text, and spelling every one of them as ProseMirror JSON would bury
    the passage each case is actually about.
    """
    nodes: list[dict[str, Any]] = []
    for block in blocks:
        if block == "---":
            nodes.append({"type": "horizontalRule"})
            continue
        content: list[dict[str, Any]] = []
        for index, line in enumerate(block.split("\n")):
            if index:
                content.append({"type": "hardBreak"})
            if line:
                content.append(text_node(line))
        nodes.append({"type": "paragraph", "content": content})
    return {"type": "doc", "content": nodes or [{"type": "paragraph"}]}


def load_anchor_cases() -> list[dict[str, Any]]:
    """The anchor corpus (P2-8), written from ``specs/anchors.md`` rather than from the code."""
    raw = (ANCHOR_FIXTURES_DIR / "cases.json").read_text(encoding="utf-8")
    return json.loads(raw)["cases"]


def load_projection_cases() -> list[dict[str, Any]]:
    """The projection cases both suites run against (P1-7).

    The same file is read by ``web/src/__tests__/projection.test.ts``, so a rule that changes on
    one side and not the other fails a test rather than confusing a writer's table of contents.
    """
    raw = (PROJECTION_FIXTURES_DIR / "cases.json").read_text(encoding="utf-8")
    return json.loads(raw)["cases"]


def load_markdown_cases() -> list[dict[str, Any]]:
    """The Markdown round-trip corpus (P2-13, P2-14).

    Both halves are asserted against it: the exact Markdown a document exports to, and the
    document that Markdown imports back as. Hand-written from the syntax the serializer's
    docstring fixes, so a serializer and a parser that quietly agreed with each other on
    something neither document describes would still fail.
    """
    raw = (MARKDOWN_FIXTURES_DIR / "cases.json").read_text(encoding="utf-8")
    return json.loads(raw)["cases"]


def load_closed_schema() -> dict[str, Any]:
    """The closed schema both suites hold themselves to (P1-10, D1).

    The same file is read by ``web/src/__tests__/schema.test.ts`` against the schema TipTap
    builds, so a node added to the editor and not to the serializer fails a test on each side.
    """
    raw = (SCHEMA_FIXTURES_DIR / "closed_schema.json").read_text(encoding="utf-8")
    return json.loads(raw)
