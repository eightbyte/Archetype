"""P1-5, P1-6 - the document store and the save protocol (D18, D19).

The store is tested apart from HTTP because that is how the agent will reach it in Phase 6:
:meth:`DocumentStore.save_content` is the only path by which manuscript text changes, whether the
caller is a route, a test, or an accepted proposal (D12).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from archetype.ids import IdPrefix, is_id
from archetype.manuscript.documents import (
    MAX_CONTENT_BYTES,
    ContentTooLargeError,
    DocumentNotFoundError,
    DocumentStore,
    StaleVersionError,
)
from archetype.manuscript.projection import InvalidDocumentError, empty_document
from archetype.projects.store import ProjectHandle

from .conftest import build_document

PROSE = build_document(
    headings=[(1, "Arrival")],
    paragraphs=["The harbour was grey.", "He did not look back."],
)


def stored_row(handle: ProjectHandle, document_id: str) -> dict[str, Any]:
    """The raw row, read outside the store - so a test can assert nothing was written."""
    with handle.connect() as conn:
        row = conn.execute("SELECT * FROM document WHERE id = ?", (document_id,)).fetchone()
    return dict(row)


# -- creation -------------------------------------------------------------------------------


def test_a_new_document_is_an_empty_first_chapter(documents: DocumentStore) -> None:
    document = documents.create()

    assert is_id(document.meta.id, IdPrefix.DOCUMENT)
    assert document.meta.title == "Chapter 1"
    assert document.meta.kind == "chapter"
    assert document.meta.order_index == 0
    assert document.meta.version == 1
    assert document.meta.word_count == 0
    assert document.meta.headings == ()
    assert document.content == empty_document()
    assert document.meta.created_at == document.meta.updated_at


def test_chapters_are_numbered_and_appended_in_order(documents: DocumentStore) -> None:
    first, second, third = (documents.create() for _ in range(3))

    assert [doc.meta.title for doc in (first, second, third)] == [
        "Chapter 1",
        "Chapter 2",
        "Chapter 3",
    ]
    assert [doc.meta.order_index for doc in (first, second, third)] == [0, 1, 2]
    assert [meta.id for meta in documents.list_meta()] == [
        first.meta.id,
        second.meta.id,
        third.meta.id,
    ]


def test_an_explicit_title_is_trimmed(documents: DocumentStore) -> None:
    assert documents.create("  Arrival  ").meta.title == "Arrival"


@pytest.mark.parametrize("title", ["", "   ", "x" * 201])
def test_an_unusable_title_is_refused(documents: DocumentStore, title: str) -> None:
    with pytest.raises(ValueError):
        documents.create(title)


def test_creating_with_content_derives_the_projection(documents: DocumentStore) -> None:
    document = documents.create("Arrival", content=PROSE)

    assert document.meta.word_count == 10
    assert [heading.text for heading in document.meta.headings] == ["Arrival"]
    assert document.text_plain.startswith("Arrival\n\nThe harbour was grey.")


def test_creating_with_malformed_content_writes_nothing(documents: DocumentStore) -> None:
    with pytest.raises(InvalidDocumentError):
        documents.create("Arrival", content={"type": "not-a-doc"})

    assert documents.list_meta() == []


def test_creating_a_document_stamps_the_project(
    documents: DocumentStore, project: ProjectHandle
) -> None:
    """The picker sorts on ``project.updated_at``; it has to move when the project does."""
    with project.connect() as conn:
        before = conn.execute("SELECT updated_at FROM project").fetchone()["updated_at"]

    documents.create()

    with project.connect() as conn:
        after = conn.execute("SELECT updated_at FROM project").fetchone()["updated_at"]
    assert after >= before


# -- reading --------------------------------------------------------------------------------


def test_get_returns_the_content_the_list_leaves_out(documents: DocumentStore) -> None:
    created = documents.create("Arrival", content=PROSE)

    fetched = documents.get(created.meta.id)
    assert fetched.content == PROSE
    assert fetched.meta == created.meta

    (listed,) = documents.list_meta()
    assert listed == created.meta


def test_get_on_a_missing_document_is_an_error(documents: DocumentStore) -> None:
    with pytest.raises(DocumentNotFoundError):
        documents.get("doc_doesnotexist")


def test_a_document_from_another_project_is_not_visible(
    documents: DocumentStore, make_project
) -> None:
    """Scoping is enforced by the query, not by the caller remembering to pass a project id."""
    other = DocumentStore(make_project("Other Manuscript"))
    stranger = other.create("Theirs")

    with pytest.raises(DocumentNotFoundError):
        documents.get(stranger.meta.id)


def test_the_outline_spans_chapters_without_loading_content(documents: DocumentStore) -> None:
    documents.create("One", content=build_document(headings=[(1, "Arrival"), (2, "The Quay")]))
    documents.create("Two", content=build_document(headings=[(1, "Departure")]))

    outline = documents.outline()

    assert [chapter.title for chapter in outline] == ["One", "Two"]
    assert [heading.text for heading in outline[0].headings] == ["Arrival", "The Quay"]
    assert [heading.ordinal for heading in outline[0].headings] == [0, 1]
    assert [heading.text for heading in outline[1].headings] == ["Departure"]


# -- saving ---------------------------------------------------------------------------------


def test_a_correct_save_increments_the_version_and_returns_the_projection(
    documents: DocumentStore,
) -> None:
    document = documents.create()

    result = documents.save_content(document.meta.id, PROSE, version=1)

    assert result.version == 2
    assert result.word_count == 10
    assert [heading.text for heading in result.headings] == ["Arrival"]
    assert documents.get(document.meta.id).content == PROSE


def test_saves_accumulate_one_version_at_a_time(documents: DocumentStore) -> None:
    document = documents.create()
    version = document.meta.version

    for _ in range(3):
        version = documents.save_content(document.meta.id, PROSE, version=version).version

    assert version == 4
    assert documents.get(document.meta.id).meta.version == 4


def test_the_stored_projection_matches_what_the_save_returned(documents: DocumentStore) -> None:
    document = documents.create()
    result = documents.save_content(document.meta.id, PROSE, version=1)

    row = stored_row(documents.handle, document.meta.id)
    assert row["word_count"] == result.word_count
    assert json.loads(row["headings_json"]) == [h.to_dict() for h in result.headings]
    assert row["text_plain"] == documents.get(document.meta.id).text_plain


def test_a_stale_save_is_refused_and_leaves_the_row_untouched(documents: DocumentStore) -> None:
    """D19: the guard writes nothing. Asserted by reading the row back, not by trusting it."""
    document = documents.create()
    documents.save_content(document.meta.id, PROSE, version=1)
    before = stored_row(documents.handle, document.meta.id)

    later = build_document(paragraphs=["Something else entirely."])
    with pytest.raises(StaleVersionError) as caught:
        documents.save_content(document.meta.id, later, version=1)

    assert caught.value.current_version == 2
    assert caught.value.presented == 1
    assert caught.value.updated_at == before["updated_at"]
    assert stored_row(documents.handle, document.meta.id) == before


def test_a_save_from_the_future_is_refused_too(documents: DocumentStore) -> None:
    """The guard is equality, not 'at least' - a client cannot skip ahead of the store."""
    document = documents.create()

    with pytest.raises(StaleVersionError):
        documents.save_content(document.meta.id, PROSE, version=99)


def test_saving_a_missing_document_is_a_not_found(documents: DocumentStore) -> None:
    with pytest.raises(DocumentNotFoundError):
        documents.save_content("doc_doesnotexist", PROSE, version=1)


def test_malformed_content_is_rejected_before_any_write(documents: DocumentStore) -> None:
    document = documents.create()
    before = stored_row(documents.handle, document.meta.id)

    with pytest.raises(InvalidDocumentError):
        documents.save_content(document.meta.id, {"type": "doc", "content": "nope"}, version=1)

    assert stored_row(documents.handle, document.meta.id) == before


def test_oversized_content_is_rejected_before_any_write(documents: DocumentStore) -> None:
    document = documents.create()
    before = stored_row(documents.handle, document.meta.id)
    huge = build_document(paragraphs=["x" * (MAX_CONTENT_BYTES + 1)])

    with pytest.raises(ContentTooLargeError) as caught:
        documents.save_content(document.meta.id, huge, version=1)

    assert caught.value.limit == MAX_CONTENT_BYTES
    assert caught.value.size > MAX_CONTENT_BYTES
    assert stored_row(documents.handle, document.meta.id) == before


def test_the_size_check_precedes_the_version_check(documents: DocumentStore) -> None:
    """Order matters: an oversized payload must not need a correct version to be refused."""
    document = documents.create()
    huge = build_document(paragraphs=["x" * (MAX_CONTENT_BYTES + 1)])

    with pytest.raises(ContentTooLargeError):
        documents.save_content(document.meta.id, huge, version=999)


def test_saving_stamps_the_project(documents: DocumentStore, project: ProjectHandle) -> None:
    document = documents.create()
    documents.save_content(document.meta.id, PROSE, version=1)

    with project.connect() as conn:
        project_updated = conn.execute("SELECT updated_at FROM project").fetchone()["updated_at"]
    assert project_updated == documents.get(document.meta.id).meta.updated_at


def test_unicode_survives_the_round_trip(documents: DocumentStore) -> None:
    """Windows is the primary target and text handling is UTF-8 end to end (plan section 5)."""
    prose = build_document(paragraphs=["Un café, s’il vous plaît — naïve Ωmega."])
    document = documents.create(content=prose)

    fetched = documents.get(document.meta.id)
    assert fetched.content == prose
    assert "s’il" in fetched.text_plain


# -- renaming -------------------------------------------------------------------------------


def test_rename_changes_the_title_and_not_the_version(documents: DocumentStore) -> None:
    document = documents.create()

    meta = documents.rename(document.meta.id, "  Arrival  ")

    assert meta.title == "Arrival"
    assert meta.version == document.meta.version
    assert documents.get(document.meta.id).meta.title == "Arrival"


def test_rename_does_not_disturb_a_pending_save(documents: DocumentStore) -> None:
    """A rename must not cost the writer a keystroke: the in-flight version still applies."""
    document = documents.create()
    documents.rename(document.meta.id, "Arrival")

    result = documents.save_content(document.meta.id, PROSE, version=1)
    assert result.version == 2


@pytest.mark.parametrize("title", ["", "   ", "x" * 201])
def test_rename_refuses_an_unusable_title(documents: DocumentStore, title: str) -> None:
    document = documents.create()

    with pytest.raises(ValueError):
        documents.rename(document.meta.id, title)

    assert documents.get(document.meta.id).meta.title == "Chapter 1"


def test_renaming_a_missing_document_is_a_not_found(documents: DocumentStore) -> None:
    with pytest.raises(DocumentNotFoundError):
        documents.rename("doc_doesnotexist", "Arrival")
