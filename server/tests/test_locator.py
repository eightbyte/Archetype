"""P1-5 - resolving a bare document id to the project that holds it.

The routes that address a document without naming a project depend on this. Its cache is a hint,
never an authority, and these tests are mostly about proving that: the worst a wrong cache entry
can cost is one wasted scan, never a read or a write against the wrong manuscript.
"""

from __future__ import annotations

import shutil

import pytest

from archetype.manuscript.documents import DocumentNotFoundError, DocumentStore
from archetype.manuscript.locator import DocumentLocator
from archetype.projects.store import ProjectStore


@pytest.fixture
def locator(store: ProjectStore) -> DocumentLocator:
    return DocumentLocator(store)


def test_a_document_resolves_to_its_own_project(
    store: ProjectStore, locator: DocumentLocator
) -> None:
    first = store.create("First")
    second = store.create("Second")
    theirs = DocumentStore(second).create("Theirs")

    resolved = locator.resolve(theirs.meta.id)

    assert resolved.id == second.id
    assert resolved.id != first.id
    assert resolved.path == second.path


def test_an_unknown_document_is_a_not_found(locator: DocumentLocator) -> None:
    with pytest.raises(DocumentNotFoundError):
        locator.resolve("doc_doesnotexist")


def test_resolving_twice_does_not_rescan(
    store: ProjectStore, locator: DocumentLocator, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Autosave resolves on every keystroke's worth of idle; a scan per save would not do."""
    handle = store.create("First")
    document = DocumentStore(handle).create()
    locator.resolve(document.meta.id)

    def forbidden() -> list:
        raise AssertionError("the locator rescanned a document it had already found")

    monkeypatch.setattr(store, "list_projects", forbidden)
    assert locator.resolve(document.meta.id).id == handle.id


def test_a_stale_cache_entry_falls_back_to_a_scan(
    store: ProjectStore, locator: DocumentLocator, tmp_path
) -> None:
    """A project file moved behind the app's back must not send a save to the wrong file."""
    handle = store.create("Portable")
    document = DocumentStore(handle).create()
    locator.resolve(document.meta.id)

    moved = store.projects_dir / "moved.sqlite"
    shutil.move(str(handle.path), moved)

    resolved = locator.resolve(document.meta.id)
    assert resolved.path == moved
    assert resolved.id == handle.id


def test_a_document_whose_project_is_gone_is_a_not_found(
    store: ProjectStore, locator: DocumentLocator, tmp_path
) -> None:
    handle = store.create("Doomed")
    document = DocumentStore(handle).create()
    locator.resolve(document.meta.id)

    shutil.move(str(handle.path), tmp_path / "elsewhere.sqlite")

    with pytest.raises(DocumentNotFoundError):
        locator.resolve(document.meta.id)


def test_a_file_that_is_not_a_project_is_skipped_not_fatal(
    store: ProjectStore, locator: DocumentLocator
) -> None:
    handle = store.create("Readable")
    document = DocumentStore(handle).create()
    (store.projects_dir / "junk.sqlite").write_bytes(b"this is not a database")

    assert locator.resolve(document.meta.id).id == handle.id


def test_forget_drops_a_cached_location(store: ProjectStore, locator: DocumentLocator) -> None:
    handle = store.create("First")
    document = DocumentStore(handle).create()
    locator.resolve(document.meta.id)

    locator.forget(document.meta.id)

    # Still resolvable - forgetting costs a scan, not correctness.
    assert locator.resolve(document.meta.id).id == handle.id
