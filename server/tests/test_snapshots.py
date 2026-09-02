"""P2-3 - snapshot capture, retention, and restore (D23).

Two properties carry the rest. **Dedupe by hash**, so a chapter nobody touched never accumulates
history; and **restore is an ordinary save**, so it goes through the one write path with the D19
guard on it rather than around the side. The second is the one worth breaking a test over: a
restore that wrote directly would be a second way to change manuscript text, and there is not
supposed to be one (data-model section 6).
"""

from __future__ import annotations

import pytest

from archetype.ids import IdPrefix, is_id
from archetype.manuscript.documents import (
    DocumentNotFoundError,
    DocumentStore,
    StaleVersionError,
)
from archetype.manuscript.snapshots import (
    HANDOVER_RETENTION,
    MAX_LABEL_LENGTH,
    SnapshotNotFoundError,
    SnapshotReason,
    SnapshotStore,
    hash_content,
)
from archetype.projects.store import ProjectHandle

from .conftest import build_document


def edit(documents: DocumentStore, document_id: str, version: int, text: str) -> int:
    """Save one new paragraph of prose and return the new version."""
    result = documents.save_content(document_id, build_document(paragraphs=[text]), version)
    return result.version


def snapshot_count(handle: ProjectHandle, document_id: str) -> int:
    with handle.connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM snapshot WHERE document_id = ?", (document_id,)
        ).fetchone()
    return int(row["n"])


# -- capture ---------------------------------------------------------------------------------


def test_capture_records_the_documents_current_content(
    documents: DocumentStore, snapshots: SnapshotStore, make_document
) -> None:
    document = make_document("Arrival", paragraphs=["The harbour was grey."])

    meta = snapshots.capture(document.meta.id, reason=SnapshotReason.MANUAL, label="First draft")

    assert meta is not None
    assert is_id(meta.id, IdPrefix.SNAPSHOT)
    assert meta.reason == SnapshotReason.MANUAL
    assert meta.label == "First draft"
    assert meta.version == document.meta.version
    assert meta.word_count == document.meta.word_count
    assert meta.size_bytes > 0
    assert snapshots.get(meta.id).content == document.content


def test_a_deliberate_snapshot_is_never_deduped(snapshots: SnapshotStore, make_document) -> None:
    """A manual mark carries a label, and a ``pre-*`` snapshot is a recovery guarantee.

    Suppressing either because the words had not moved would throw away the one thing being
    recorded - and would leave a destructive act's only recovery copy in the prunable pool.
    """
    document = make_document("Arrival", paragraphs=["Unchanged."])

    first = snapshots.capture(document.meta.id, reason=SnapshotReason.MANUAL, label="one")
    second = snapshots.capture(document.meta.id, reason=SnapshotReason.MANUAL, label="two")
    third = snapshots.capture(document.meta.id, reason=SnapshotReason.PRE_IMPORT)

    assert None not in (first, second, third)
    assert [meta.label for meta in snapshots.list(document.meta.id)] == ["", "two", "one"]


def test_capture_dedupes_by_content_hash(
    documents: DocumentStore, snapshots: SnapshotStore, make_document, project: ProjectHandle
) -> None:
    document = make_document("Arrival", paragraphs=["The harbour was grey."])

    first = snapshots.capture(document.meta.id)
    again = snapshots.capture(document.meta.id)

    assert first is not None
    assert again is None, "an unchanged chapter must not accumulate snapshots"
    assert snapshot_count(project, document.meta.id) == 1

    edit(documents, document.meta.id, document.meta.version, "The harbour had cleared.")
    assert snapshots.capture(document.meta.id) is not None
    assert snapshot_count(project, document.meta.id) == 2


def test_dedupe_compares_against_the_newest_snapshot_only(
    documents: DocumentStore, snapshots: SnapshotStore, make_document
) -> None:
    """Reverting to earlier text is a real change and is recorded as one."""
    document = make_document("Arrival", paragraphs=["First."])
    snapshots.capture(document.meta.id)

    version = edit(documents, document.meta.id, document.meta.version, "Second.")
    snapshots.capture(document.meta.id)
    edit(documents, document.meta.id, version, "First.")

    assert snapshots.capture(document.meta.id) is not None
    assert len(snapshots.list(document.meta.id)) == 3


def test_the_history_reads_newest_first_and_never_carries_content(
    documents: DocumentStore, snapshots: SnapshotStore, make_document
) -> None:
    document = make_document("Arrival", paragraphs=["One."])
    snapshots.capture(document.meta.id, reason=SnapshotReason.MANUAL, label="one")
    version = edit(documents, document.meta.id, document.meta.version, "Two.")
    snapshots.capture(document.meta.id, reason=SnapshotReason.MANUAL, label="two")
    edit(documents, document.meta.id, version, "Three.")
    snapshots.capture(document.meta.id, reason=SnapshotReason.HANDOVER)

    history = snapshots.list(document.meta.id)

    assert [meta.reason for meta in history] == ["handover", "manual", "manual"]
    assert [meta.label for meta in history] == ["", "two", "one"]
    assert not any(hasattr(meta, "content") for meta in history)


def test_capture_refuses_an_unknown_reason(snapshots: SnapshotStore, make_document) -> None:
    document = make_document("Arrival")
    with pytest.raises(ValueError, match="unknown snapshot reason"):
        snapshots.capture(document.meta.id, reason="because")


def test_capture_refuses_an_oversized_label(snapshots: SnapshotStore, make_document) -> None:
    document = make_document("Arrival")
    with pytest.raises(ValueError, match="at most"):
        snapshots.capture(
            document.meta.id, reason=SnapshotReason.MANUAL, label="x" * (MAX_LABEL_LENGTH + 1)
        )


def test_capture_refuses_a_document_that_is_not_there(snapshots: SnapshotStore) -> None:
    with pytest.raises(DocumentNotFoundError):
        snapshots.capture("doc_notarealone")


def test_a_deleted_chapters_history_is_still_readable(
    documents: DocumentStore, snapshots: SnapshotStore, make_document
) -> None:
    """It is exactly what someone deciding whether to restore the chapter wants to see."""
    document = make_document("Doomed", paragraphs=["The harbour was grey."])
    marked = snapshots.capture(document.meta.id, reason=SnapshotReason.MANUAL, label="before")
    assert marked is not None

    documents.delete(document.meta.id)

    reasons = [meta.reason for meta in snapshots.list(document.meta.id)]
    assert reasons == [SnapshotReason.PRE_DELETE, SnapshotReason.MANUAL], (
        "the pre-delete copy is written even though the manual mark holds the same words: it is "
        "a recovery guarantee, not a history entry"
    )


# -- retention -------------------------------------------------------------------------------


def test_handover_snapshots_are_pruned_to_the_newest_kept(
    documents: DocumentStore, snapshots: SnapshotStore, make_document, project: ProjectHandle
) -> None:
    document = make_document("Arrival", paragraphs=["Line 0."])
    version = document.meta.version

    for index in range(1, HANDOVER_RETENTION + 6):
        snapshots.capture(document.meta.id, reason=SnapshotReason.HANDOVER)
        version = edit(documents, document.meta.id, version, f"Line {index}.")

    history = snapshots.list(document.meta.id)
    assert len(history) == HANDOVER_RETENTION
    assert {meta.reason for meta in history} == {SnapshotReason.HANDOVER}
    # The ones that survived are the newest: the first five lines are gone.
    contents = [snapshots.get(meta.id).content for meta in history]
    kept_lines = {node["content"][0]["text"] for content in contents for node in content["content"]}
    assert "Line 0." not in kept_lines
    assert f"Line {HANDOVER_RETENTION + 4}." in kept_lines


def test_manual_and_pre_snapshots_are_never_pruned(
    documents: DocumentStore, snapshots: SnapshotStore, make_document
) -> None:
    document = make_document("Arrival", paragraphs=["Line 0."])
    version = document.meta.version
    marked = snapshots.capture(document.meta.id, reason=SnapshotReason.MANUAL, label="keep me")
    assert marked is not None

    for index in range(1, HANDOVER_RETENTION + 6):
        version = edit(documents, document.meta.id, version, f"Line {index}.")
        snapshots.capture(document.meta.id, reason=SnapshotReason.HANDOVER)

    history = snapshots.list(document.meta.id)
    assert len(history) == HANDOVER_RETENTION + 1
    assert marked.id in {meta.id for meta in history}


def test_pruning_is_per_document(
    documents: DocumentStore, snapshots: SnapshotStore, make_document
) -> None:
    kept = make_document("Kept", paragraphs=["Steady."])
    busy = make_document("Busy", paragraphs=["Line 0."])
    snapshots.capture(kept.meta.id, reason=SnapshotReason.HANDOVER)

    version = busy.meta.version
    for index in range(1, HANDOVER_RETENTION + 6):
        version = edit(documents, busy.meta.id, version, f"Line {index}.")
        snapshots.capture(busy.meta.id, reason=SnapshotReason.HANDOVER)

    assert len(snapshots.list(kept.meta.id)) == 1
    assert len(snapshots.list(busy.meta.id)) == HANDOVER_RETENTION


# -- restore ---------------------------------------------------------------------------------


def test_restore_round_trips_the_content_and_bumps_the_version(
    documents: DocumentStore, snapshots: SnapshotStore, make_document
) -> None:
    document = make_document("Arrival", headings=[(1, "Arrival")], paragraphs=["The first draft."])
    marked = snapshots.capture(document.meta.id, reason=SnapshotReason.MANUAL, label="draft one")
    assert marked is not None

    version = edit(documents, document.meta.id, document.meta.version, "Something else entirely.")

    result = snapshots.restore(marked.id, version)

    assert result.version == version + 1
    restored = documents.get(document.meta.id)
    assert restored.content == document.content
    assert restored.text_plain == document.text_plain


def test_restore_re_derives_the_projection(
    documents: DocumentStore, snapshots: SnapshotStore, make_document
) -> None:
    document = make_document(
        "Arrival", headings=[(1, "Arrival"), (2, "The harbour")], paragraphs=["Four words go here."]
    )
    marked = snapshots.capture(document.meta.id, reason=SnapshotReason.MANUAL)
    assert marked is not None
    version = edit(documents, document.meta.id, document.meta.version, "One.")

    result = snapshots.restore(marked.id, version)

    assert result.word_count == document.meta.word_count
    assert [heading.text for heading in result.headings] == ["Arrival", "The harbour"]


def test_restore_leaves_a_pre_restore_snapshot_of_what_it_replaced(
    documents: DocumentStore, snapshots: SnapshotStore, make_document
) -> None:
    document = make_document("Arrival", paragraphs=["The first draft."])
    marked = snapshots.capture(document.meta.id, reason=SnapshotReason.MANUAL)
    assert marked is not None
    version = edit(documents, document.meta.id, document.meta.version, "The replacement.")
    replaced = documents.get(document.meta.id)

    snapshots.restore(marked.id, version)

    history = snapshots.list(document.meta.id)
    assert history[0].reason == SnapshotReason.PRE_RESTORE
    assert history[0].version == version
    assert snapshots.get(history[0].id).content == replaced.content


def test_a_stale_restore_is_refused_and_writes_nothing_at_all(
    documents: DocumentStore, snapshots: SnapshotStore, make_document, project: ProjectHandle
) -> None:
    """Not even the ``pre-restore`` snapshot that was about to protect it (D19, D23)."""
    document = make_document("Arrival", paragraphs=["The first draft."])
    marked = snapshots.capture(document.meta.id, reason=SnapshotReason.MANUAL)
    assert marked is not None
    version = edit(documents, document.meta.id, document.meta.version, "The replacement.")
    before = documents.get(document.meta.id)
    count_before = snapshot_count(project, document.meta.id)

    with pytest.raises(StaleVersionError) as caught:
        snapshots.restore(marked.id, version - 1)

    assert caught.value.current_version == version
    assert documents.get(document.meta.id).content == before.content
    assert snapshot_count(project, document.meta.id) == count_before


def test_restoring_the_content_a_document_already_holds_still_bumps_the_version(
    documents: DocumentStore, snapshots: SnapshotStore, make_document
) -> None:
    """A restore is an ordinary save, and an ordinary save of identical text is still a save."""
    document = make_document("Arrival", paragraphs=["Unchanged."])
    marked = snapshots.capture(document.meta.id, reason=SnapshotReason.MANUAL)
    assert marked is not None

    result = snapshots.restore(marked.id, document.meta.version)

    assert result.version == document.meta.version + 1


def test_restore_refuses_a_snapshot_that_is_not_there(snapshots: SnapshotStore) -> None:
    with pytest.raises(SnapshotNotFoundError):
        snapshots.restore("snp_notarealone", 1)


def test_restore_refuses_a_deleted_chapter(
    documents: DocumentStore, snapshots: SnapshotStore, make_document
) -> None:
    document = make_document("Doomed", paragraphs=["The harbour was grey."])
    marked = snapshots.capture(document.meta.id, reason=SnapshotReason.MANUAL)
    assert marked is not None
    documents.delete(document.meta.id)

    with pytest.raises(DocumentNotFoundError):
        snapshots.restore(marked.id, document.meta.version)


def test_a_snapshot_from_another_project_is_not_found(
    snapshots: SnapshotStore, make_document, make_project
) -> None:
    other_handle = make_project("Another Manuscript")
    other_document = DocumentStore(other_handle).create("Theirs")
    other = SnapshotStore(other_handle).capture(
        other_document.meta.id, reason=SnapshotReason.MANUAL
    )
    assert other is not None

    with pytest.raises(SnapshotNotFoundError):
        snapshots.get(other.id)


# -- the dedupe key --------------------------------------------------------------------------


def test_hash_content_is_stable_and_distinguishing() -> None:
    one = '{"type":"doc","content":[]}'
    assert hash_content(one) == hash_content(one)
    assert hash_content(one) != hash_content(one + " ")
    assert len(hash_content(one)) == 64
