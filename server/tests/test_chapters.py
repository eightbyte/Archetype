"""P2-2 - chapter reorder, delete, and restore (D22).

Deleting is the item these tests exist for. A soft delete is only as good as the predicate that
hides it: one query that forgets ``deleted_at IS NULL`` puts a deleted chapter back into a count,
an outline, or an export, and it is then reported as a different bug entirely. So the absence of
a deleted chapter is asserted across **all four** read paths together, in one test, rather than
one path at a time where a gap looks like a test nobody wrote yet.
"""

from __future__ import annotations

import pytest

from archetype.manuscript.documents import (
    DocumentNotFoundError,
    DocumentStore,
    ReorderMismatchError,
)
from archetype.manuscript.snapshots import SnapshotReason, SnapshotStore
from archetype.projects.store import ProjectHandle, ProjectStore


def titles(store: DocumentStore) -> list[str]:
    return [meta.title for meta in store.list_meta()]


# -- reorder ---------------------------------------------------------------------------------


def test_reorder_rewrites_the_order_and_round_trips(
    documents: DocumentStore, make_document
) -> None:
    first, second, third = (make_document(title) for title in ("One", "Two", "Three"))

    reordered = documents.reorder([third.meta.id, first.meta.id, second.meta.id])

    assert [meta.title for meta in reordered] == ["Three", "One", "Two"]
    assert [meta.order_index for meta in reordered] == [0, 1, 2]
    assert titles(documents) == ["Three", "One", "Two"]

    documents.reorder([first.meta.id, second.meta.id, third.meta.id])
    assert titles(documents) == ["One", "Two", "Three"]


def test_reorder_does_not_bump_a_version_or_change_any_text(
    documents: DocumentStore, make_document
) -> None:
    first = make_document("One", paragraphs=["The harbour was grey."])
    second = make_document("Two")

    documents.reorder([second.meta.id, first.meta.id])

    moved = documents.get(first.meta.id)
    assert moved.meta.version == first.meta.version
    assert moved.content == first.content
    assert moved.meta.updated_at == first.meta.updated_at


@pytest.mark.parametrize(
    "make_bad,expected",
    [
        (lambda ids: ids[:-1], "missing"),
        (lambda ids: [*ids, "doc_notarealone"], "unexpected"),
        (lambda ids: [ids[0], *ids], "duplicated"),
        (lambda ids: [], "missing"),
    ],
    ids=["one-missing", "one-extra", "one-duplicated", "empty"],
)
def test_a_malformed_order_is_refused_and_writes_nothing(
    documents: DocumentStore, make_document, make_bad, expected: str
) -> None:
    ids = [make_document(title).meta.id for title in ("One", "Two", "Three")]
    before = titles(documents)

    with pytest.raises(ReorderMismatchError) as caught:
        documents.reorder(make_bad(ids))

    assert getattr(caught.value, expected), f"the error should name what was {expected}"
    assert titles(documents) == before, "a refused reorder must not have written anything"


def test_a_chapter_from_another_project_cannot_be_ordered_in(
    documents: DocumentStore, make_document, store: ProjectStore
) -> None:
    mine = make_document("Mine")
    other = DocumentStore(store.create("Another Manuscript")).create("Theirs")

    with pytest.raises(ReorderMismatchError) as caught:
        documents.reorder([mine.meta.id, other.meta.id])

    assert caught.value.unexpected == (other.meta.id,)


def test_a_deleted_chapter_is_neither_required_nor_accepted_in_an_order(
    documents: DocumentStore, make_document
) -> None:
    first, second, third = (make_document(title) for title in ("One", "Two", "Three"))
    documents.delete(second.meta.id)

    # The live set no longer holds it, so the complete list is the other two...
    documents.reorder([third.meta.id, first.meta.id])
    assert titles(documents) == ["Three", "One"]

    # ...and presenting it is presenting something that is not a live chapter.
    with pytest.raises(ReorderMismatchError):
        documents.reorder([third.meta.id, first.meta.id, second.meta.id])


# -- delete ----------------------------------------------------------------------------------


def test_delete_removes_a_chapter_from_all_four_read_paths(
    documents: DocumentStore,
    make_document,
    store: ProjectStore,
    project: ProjectHandle,
) -> None:
    kept = make_document("Kept", paragraphs=["Four words are here."])
    doomed = make_document("Doomed", paragraphs=["Six whole words are written here."])

    documents.delete(doomed.meta.id)

    # 1. the document list
    assert [meta.id for meta in documents.list_meta()] == [kept.meta.id]
    # 2. the single-document read
    with pytest.raises(DocumentNotFoundError):
        documents.get(doomed.meta.id)
    # 3. the stitched outline
    assert [chapter.document_id for chapter in documents.outline()] == [kept.meta.id]
    # 4. the project summary's chapter and word counts
    summary = store.find(project.id)
    assert summary is not None
    assert summary.chapter_count == 1
    assert summary.word_count == kept.meta.word_count


def test_a_deleted_chapter_keeps_its_row_and_its_text(
    documents: DocumentStore, make_document
) -> None:
    document = make_document("Doomed", paragraphs=["The harbour was grey."])

    meta = documents.delete(document.meta.id)

    assert meta.deleted_at is not None
    assert meta.is_deleted
    assert meta.version == document.meta.version, "a delete is not a text edit"

    still_there = documents.get(document.meta.id, include_deleted=True)
    assert still_there.content == document.content
    assert still_there.text_plain == document.text_plain


def test_a_deleted_chapter_is_listed_by_the_restore_surface(
    documents: DocumentStore, make_document
) -> None:
    kept = make_document("Kept")
    doomed = make_document("Doomed")
    documents.delete(doomed.meta.id)

    assert [meta.id for meta in documents.list_deleted()] == [doomed.meta.id]
    assert [meta.id for meta in documents.list_meta(include_deleted=True)] == [
        kept.meta.id,
        doomed.meta.id,
    ]


def test_delete_takes_a_pre_delete_snapshot(
    documents: DocumentStore, snapshots: SnapshotStore, make_document
) -> None:
    document = make_document("Doomed", paragraphs=["The harbour was grey."])

    documents.delete(document.meta.id)

    history = snapshots.list(document.meta.id)
    assert [snapshot.reason for snapshot in history] == [SnapshotReason.PRE_DELETE]
    assert snapshots.get(history[0].id).content == document.content


def test_deleting_a_chapter_twice_is_refused(documents: DocumentStore, make_document) -> None:
    document = make_document("Doomed")
    documents.delete(document.meta.id)

    with pytest.raises(DocumentNotFoundError):
        documents.delete(document.meta.id)


def test_a_deleted_chapter_cannot_be_written_to_or_renamed(
    documents: DocumentStore, make_document
) -> None:
    document = make_document("Doomed", paragraphs=["The harbour was grey."])
    documents.delete(document.meta.id)

    with pytest.raises(DocumentNotFoundError):
        documents.save_content(document.meta.id, document.content, document.meta.version)
    with pytest.raises(DocumentNotFoundError):
        documents.rename(document.meta.id, "A New Name")


# -- restore ---------------------------------------------------------------------------------


def test_restore_brings_a_chapter_back_with_its_text_byte_for_byte(
    documents: DocumentStore, make_document
) -> None:
    document = make_document("Doomed", paragraphs=["The harbour was grey.", "He did not look."])
    documents.delete(document.meta.id)

    meta = documents.restore(document.meta.id)

    assert meta.deleted_at is None
    assert meta.version == document.meta.version, "a restore is not a text edit"
    restored = documents.get(document.meta.id)
    assert restored.content == document.content
    assert restored.text_plain == document.text_plain
    assert restored.meta.word_count == document.meta.word_count


def test_restore_appends_at_the_end_rather_than_guessing_its_old_place(
    documents: DocumentStore, make_document
) -> None:
    first, second, third = (make_document(title) for title in ("One", "Two", "Three"))
    documents.delete(first.meta.id)
    documents.reorder([third.meta.id, second.meta.id])

    documents.restore(first.meta.id)

    assert titles(documents) == ["Three", "Two", "One"]


def test_restoring_a_live_chapter_is_a_no_op(documents: DocumentStore, make_document) -> None:
    document = make_document("Live")

    meta = documents.restore(document.meta.id)

    assert meta.deleted_at is None
    assert meta.order_index == document.meta.order_index
    assert meta.updated_at == document.meta.updated_at


def test_restoring_a_chapter_that_never_existed_is_not_found(documents: DocumentStore) -> None:
    with pytest.raises(DocumentNotFoundError):
        documents.restore("doc_notarealone")


# -- anchors across the delete (D22) ---------------------------------------------------------


def test_a_deleted_chapters_anchors_are_orphaned_and_come_back(
    documents: DocumentStore, make_document, make_anchor, read_anchor_status
) -> None:
    document = make_document("Anchored", paragraphs=["The harbour was grey."])
    resolved = make_anchor(document.meta.id, status="ok")
    unresolved = make_anchor(document.meta.id, status="stale")

    documents.delete(document.meta.id)
    assert read_anchor_status(resolved) == "orphaned"
    assert read_anchor_status(unresolved) == "orphaned"

    documents.restore(document.meta.id)
    assert read_anchor_status(resolved) == "ok"
    assert read_anchor_status(unresolved) == "stale", (
        "a soft delete changes no text, so restoring must return each anchor to the answer the "
        "resolver actually gave - not repair it and not condemn it"
    )


def test_deleting_a_chapter_writes_nothing_to_its_anchor_rows(
    documents: DocumentStore, make_document, make_anchor, project: ProjectHandle
) -> None:
    """The stored column is the resolver's answer about text, and a delete is not a text edit."""
    document = make_document("Anchored", paragraphs=["The harbour was grey."])
    anchor_id = make_anchor(document.meta.id, status="ok")

    def anchor_row() -> tuple:
        with project.connect() as conn:
            return tuple(conn.execute("SELECT * FROM anchor WHERE id = ?", (anchor_id,)).fetchone())

    before = anchor_row()
    documents.delete(document.meta.id)
    assert anchor_row() == before
    documents.restore(document.meta.id)
    assert anchor_row() == before


def test_another_chapters_anchors_are_untouched_by_a_delete(
    documents: DocumentStore, make_document, make_anchor, read_anchor_status
) -> None:
    doomed = make_document("Doomed", paragraphs=["The harbour was grey."])
    kept = make_document("Kept", paragraphs=["The harbour was grey."])
    doomed_anchor = make_anchor(doomed.meta.id)
    kept_anchor = make_anchor(kept.meta.id)

    documents.delete(doomed.meta.id)

    assert read_anchor_status(doomed_anchor) == "orphaned"
    assert read_anchor_status(kept_anchor) == "ok"
