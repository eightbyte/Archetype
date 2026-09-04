"""P2-7 - the anchor store, re-resolution on write, and the cost of it.

Group A proved that a soft delete leaves anchor rows alone; this proves the other half of D21:
that a **text** write re-resolves them, inside the transaction that wrote it, and reports what
moved. The rules themselves are tested against the corpus in ``test_anchors.py``; what is here
is what only storage can show - that the answers reach the rows, that a refused write leaves
none of them, and that doing it on every autosave stays affordable.
"""

from __future__ import annotations

import time

import pytest

from archetype.manuscript.anchors.records import as_record
from archetype.manuscript.anchors.resolve import (
    RESOLUTION_BUDGET_MS,
    AnchorRangeError,
    AnchorRecord,
    context_for,
    extract,
    resolve_all,
)
from archetype.manuscript.anchors.status import AnchorStatus
from archetype.manuscript.anchors.store import (
    MAX_LABEL_LENGTH,
    AnchorNotFoundError,
    AnchorStore,
    clean_label,
)
from archetype.manuscript.documents import (
    Document,
    DocumentNotFoundError,
    DocumentStore,
    StaleVersionError,
)
from archetype.manuscript.projection import project, text_offset_to_pm_position
from archetype.manuscript.snapshots import SnapshotReason, SnapshotStore
from archetype.projects.store import ProjectHandle

from .conftest import build_blocks

HARBOUR = [
    "The harbour was grey and the Kestrel rode low in it.",
    "Marlow watched from the quay, saying nothing at all.",
    "He did not look back.",
]


@pytest.fixture
def anchors(project: ProjectHandle) -> AnchorStore:
    return AnchorStore(project)


@pytest.fixture
def chapter(documents: DocumentStore) -> Document:
    return documents.create("Arrival", content=build_blocks(HARBOUR))


def range_over(document: Document, passage: str) -> tuple[int, int]:
    """The ProseMirror range a client selecting ``passage`` would send."""
    projection = project(document.content)
    text_from = projection.text_plain.index(passage)
    from_pos = text_offset_to_pm_position(projection, text_from)
    to_pos = text_offset_to_pm_position(projection, text_from + len(passage))
    assert from_pos is not None and to_pos is not None
    return from_pos, to_pos


def anchor_on(store: AnchorStore, document: Document, passage: str, **kwargs):
    from_pos, to_pos = range_over(document, passage)
    return store.create(
        document.meta.id,
        from_pos=from_pos,
        to_pos=to_pos,
        version=document.meta.version,
        **kwargs,
    )


# -- creating ---------------------------------------------------------------------------------


def test_the_server_derives_the_quote_and_its_context(
    anchors: AnchorStore, chapter: Document
) -> None:
    """The client sends where, never what. It is not asked what the manuscript says."""
    anchor = anchor_on(anchors, chapter, "the Kestrel rode low", label="the ship")

    assert anchor.quote == "the Kestrel rode low"
    assert anchor.prefix == "The harbour was grey and "
    assert anchor.suffix.startswith(" in it.")
    assert anchor.status == AnchorStatus.OK
    assert anchor.label == "the ship"
    assert anchor.document_version == chapter.meta.version
    assert anchor.id.startswith("anc_")


def test_a_create_against_a_stale_version_writes_nothing(
    anchors: AnchorStore, chapter: Document
) -> None:
    """An anchor over text that has since changed is an anchor over text nobody looked at."""
    from_pos, to_pos = range_over(chapter, "the Kestrel rode low")

    with pytest.raises(StaleVersionError):
        anchors.create(chapter.meta.id, from_pos=from_pos, to_pos=to_pos, version=99)

    assert anchors.list_for_project() == []


def test_a_refused_range_writes_nothing(anchors: AnchorStore, chapter: Document) -> None:
    with pytest.raises(AnchorRangeError):
        anchors.create(chapter.meta.id, from_pos=4, to_pos=4, version=chapter.meta.version)

    assert anchors.list_for_project() == []


def test_creating_on_a_missing_document_is_refused(anchors: AnchorStore) -> None:
    with pytest.raises(DocumentNotFoundError):
        anchors.create("doc_nothing", from_pos=1, to_pos=5, version=1)


def test_creating_on_a_deleted_chapter_is_refused(
    anchors: AnchorStore, documents: DocumentStore, chapter: Document
) -> None:
    """A soft-deleted chapter is gone from every ordinary path, and this is one of them."""
    from_pos, to_pos = range_over(chapter, "the Kestrel rode low")
    documents.delete(chapter.meta.id)

    with pytest.raises(DocumentNotFoundError):
        anchors.create(
            chapter.meta.id, from_pos=from_pos, to_pos=to_pos, version=chapter.meta.version
        )


@pytest.mark.parametrize("label", ["  spaced  ", "x" * MAX_LABEL_LENGTH])
def test_a_label_is_trimmed_and_bounded(label: str) -> None:
    assert clean_label(label) == label.strip()


def test_an_overlong_label_is_refused(anchors: AnchorStore, chapter: Document) -> None:
    with pytest.raises(ValueError, match=str(MAX_LABEL_LENGTH)):
        anchor_on(anchors, chapter, "the Kestrel rode low", label="x" * (MAX_LABEL_LENGTH + 1))


# -- reading ----------------------------------------------------------------------------------


def test_a_document_read_resolves_without_persisting(
    anchors: AnchorStore, project: ProjectHandle, chapter: Document
) -> None:
    """A file changed behind the app's back reports what is true now, and stays as it was."""
    anchor = anchor_on(anchors, chapter, "the Kestrel rode low")

    with project.connect() as conn:
        conn.execute("BEGIN")
        conn.execute(
            "UPDATE document SET content_json = ?, text_plain = ? WHERE id = ?",
            ('{"type":"doc","content":[]}', "", chapter.meta.id),
        )
        conn.execute("COMMIT")

    (read,) = anchors.list_for_document(chapter.meta.id)
    assert read.status == AnchorStatus.STALE

    # Nothing was written: the stored row still holds the last write's answer.
    assert anchors.get(anchor.id).status == AnchorStatus.OK


def test_reading_a_missing_or_deleted_document_is_refused(
    anchors: AnchorStore, documents: DocumentStore, chapter: Document
) -> None:
    with pytest.raises(DocumentNotFoundError):
        anchors.list_for_document("doc_nothing")

    documents.delete(chapter.meta.id)
    with pytest.raises(DocumentNotFoundError):
        anchors.list_for_document(chapter.meta.id)


def test_the_project_list_spans_chapters_in_order(
    anchors: AnchorStore, documents: DocumentStore, chapter: Document
) -> None:
    second = documents.create("Departure", content=build_blocks(["The tide turned at dawn."]))
    first_anchor = anchor_on(anchors, chapter, "the Kestrel rode low")
    second_anchor = anchor_on(anchors, second, "tide turned at dawn")

    assert [one.id for one in anchors.list_for_project()] == [
        first_anchor.id,
        second_anchor.id,
    ]


def test_the_status_filter_reads_the_effective_status(
    anchors: AnchorStore, documents: DocumentStore, chapter: Document
) -> None:
    """``orphaned`` is a join, not a column - which is the price A1 recorded for deriving it."""
    anchor = anchor_on(anchors, chapter, "the Kestrel rode low")

    assert [one.id for one in anchors.list_for_project(status=AnchorStatus.OK)] == [anchor.id]
    assert anchors.list_for_project(status=AnchorStatus.ORPHANED) == []

    documents.delete(chapter.meta.id)

    assert anchors.list_for_project(status=AnchorStatus.OK) == []
    assert [one.id for one in anchors.list_for_project(status=AnchorStatus.ORPHANED)] == [anchor.id]


def test_an_unknown_status_filter_is_refused(anchors: AnchorStore) -> None:
    with pytest.raises(ValueError, match="not an anchor status"):
        anchors.list_for_project(status="whatever")


def test_getting_a_missing_anchor_is_refused(anchors: AnchorStore) -> None:
    with pytest.raises(AnchorNotFoundError):
        anchors.get("anc_nothing")


# -- re-linking, labelling, removing -------------------------------------------------------------


def test_relinking_re_derives_the_quote_and_returns_it_to_ok(
    anchors: AnchorStore, documents: DocumentStore, chapter: Document
) -> None:
    anchor = anchor_on(anchors, chapter, "the Kestrel rode low")
    edited = build_blocks(["The harbour was grey and the Kestrel sat low in it.", *HARBOUR[1:]])
    saved = documents.save_content(chapter.meta.id, edited, chapter.meta.version)
    assert saved.anchors[0].status == AnchorStatus.STALE

    current = documents.get(chapter.meta.id)
    from_pos, to_pos = range_over(current, "the Kestrel sat low")
    repaired = anchors.relink(
        anchor.id, from_pos=from_pos, to_pos=to_pos, version=current.meta.version
    )

    assert repaired.status == AnchorStatus.OK
    assert repaired.quote == "the Kestrel sat low"
    assert repaired.document_version == current.meta.version


def test_a_relink_against_a_stale_version_writes_nothing(
    anchors: AnchorStore, chapter: Document
) -> None:
    anchor = anchor_on(anchors, chapter, "the Kestrel rode low")
    from_pos, to_pos = range_over(chapter, "Marlow watched")

    with pytest.raises(StaleVersionError):
        anchors.relink(anchor.id, from_pos=from_pos, to_pos=to_pos, version=99)

    assert anchors.get(anchor.id).quote == "the Kestrel rode low"


def test_a_relink_with_a_refused_range_writes_nothing(
    anchors: AnchorStore, chapter: Document
) -> None:
    anchor = anchor_on(anchors, chapter, "the Kestrel rode low")

    with pytest.raises(AnchorRangeError):
        anchors.relink(anchor.id, from_pos=6, to_pos=6, version=chapter.meta.version)

    assert anchors.get(anchor.id).quote == "the Kestrel rode low"


def test_an_orphaned_anchor_is_repaired_by_restoring_its_chapter_not_by_relinking(
    anchors: AnchorStore, documents: DocumentStore, chapter: Document
) -> None:
    anchor = anchor_on(anchors, chapter, "the Kestrel rode low")
    from_pos, to_pos = range_over(chapter, "Marlow watched")
    documents.delete(chapter.meta.id)

    assert anchors.get(anchor.id).status == AnchorStatus.ORPHANED
    with pytest.raises(DocumentNotFoundError):
        anchors.relink(anchor.id, from_pos=from_pos, to_pos=to_pos, version=1)

    documents.restore(chapter.meta.id)
    assert anchors.get(anchor.id).status == AnchorStatus.OK


def test_a_label_changes_without_a_version(anchors: AnchorStore, chapter: Document) -> None:
    """Not a text change, so nothing about the document's version is at stake."""
    anchor = anchor_on(anchors, chapter, "the Kestrel rode low")
    relabelled = anchors.set_label(anchor.id, "  the ship  ")

    assert relabelled.label == "the ship"
    assert (relabelled.from_pos, relabelled.to_pos) == (anchor.from_pos, anchor.to_pos)


def test_deleting_an_anchor_removes_it(anchors: AnchorStore, chapter: Document) -> None:
    anchor = anchor_on(anchors, chapter, "the Kestrel rode low")
    anchors.delete(anchor.id)

    assert anchors.list_for_project() == []
    with pytest.raises(AnchorNotFoundError):
        anchors.delete(anchor.id)


# -- re-resolution on write (D21) ---------------------------------------------------------------


def test_a_save_moves_the_anchors_it_should_and_reports_them(
    anchors: AnchorStore, documents: DocumentStore, chapter: Document
) -> None:
    anchor = anchor_on(anchors, chapter, "the Kestrel rode low")
    moved = documents.save_content(
        chapter.meta.id,
        build_blocks(["A week earlier, nothing had happened.", *HARBOUR]),
        chapter.meta.version,
    )

    (reported,) = moved.anchors
    assert reported.id == anchor.id
    assert reported.status == AnchorStatus.OK
    assert reported.from_pos > anchor.from_pos

    stored = anchors.get(anchor.id)
    assert (stored.from_pos, stored.to_pos) == (reported.from_pos, reported.to_pos)
    assert stored.document_version == moved.version


def test_a_save_that_moves_nothing_reports_no_anchors(
    anchors: AnchorStore, documents: DocumentStore, chapter: Document
) -> None:
    """The ordinary answer while someone types above their anchors rather than through them."""
    anchor_on(anchors, chapter, "the Kestrel rode low")
    result = documents.save_content(
        chapter.meta.id, build_blocks([*HARBOUR, "The tide turned."]), chapter.meta.version
    )

    assert result.anchors == ()


def test_every_anchor_is_checked_on_every_save_even_the_ones_that_did_not_move(
    anchors: AnchorStore, documents: DocumentStore, chapter: Document
) -> None:
    """A status is a statement about the text as it is now; a row nobody looked at makes none."""
    anchor = anchor_on(anchors, chapter, "the Kestrel rode low")
    result = documents.save_content(
        chapter.meta.id, build_blocks([*HARBOUR, "The tide turned."]), chapter.meta.version
    )

    stored = anchors.get(anchor.id)
    assert stored.checked_at == result.updated_at
    assert stored.updated_at == anchor.updated_at
    assert stored.document_version == result.version


def test_a_stale_anchor_keeps_the_version_its_positions_were_true_at(
    anchors: AnchorStore, documents: DocumentStore, chapter: Document
) -> None:
    anchor = anchor_on(anchors, chapter, "the Kestrel rode low")
    documents.save_content(
        chapter.meta.id,
        build_blocks(["The harbour was grey and empty.", *HARBOUR[1:]]),
        chapter.meta.version,
    )
    stored = anchors.get(anchor.id)

    assert stored.status == AnchorStatus.STALE
    assert stored.document_version == anchor.document_version
    assert (stored.from_pos, stored.to_pos) == (anchor.from_pos, anchor.to_pos)


def test_a_status_is_recomputed_not_latched(
    anchors: AnchorStore, documents: DocumentStore, chapter: Document
) -> None:
    """An undo that restores a deleted passage returns its anchor to ``ok`` on the next save."""
    anchor = anchor_on(anchors, chapter, "the Kestrel rode low")
    emptied = documents.save_content(chapter.meta.id, build_blocks([""]), chapter.meta.version)
    assert anchors.get(anchor.id).status == AnchorStatus.STALE

    documents.save_content(chapter.meta.id, build_blocks(HARBOUR), emptied.version)
    assert anchors.get(anchor.id).status == AnchorStatus.OK


def test_a_refused_save_re_resolves_nothing(
    anchors: AnchorStore, documents: DocumentStore, chapter: Document
) -> None:
    """The re-resolution rides inside the save's transaction, so a stale save leaves no trace."""
    anchor = anchor_on(anchors, chapter, "the Kestrel rode low")

    with pytest.raises(StaleVersionError):
        documents.save_content(chapter.meta.id, build_blocks([""]), 99)

    stored = anchors.get(anchor.id)
    assert stored.status == AnchorStatus.OK
    assert stored.checked_at == anchor.checked_at


def test_a_save_only_touches_its_own_document_s_anchors(
    anchors: AnchorStore, documents: DocumentStore, chapter: Document
) -> None:
    second = documents.create("Departure", content=build_blocks(["The tide turned at dawn."]))
    other = anchor_on(anchors, second, "tide turned at dawn")

    documents.save_content(
        chapter.meta.id, build_blocks(["Nothing like it."]), chapter.meta.version
    )

    assert anchors.get(other.id).checked_at == other.checked_at


def test_restoring_a_snapshot_re_resolves_the_anchors(
    anchors: AnchorStore,
    documents: DocumentStore,
    snapshots: SnapshotStore,
    chapter: Document,
) -> None:
    """A restore is an ordinary save, so it gets the ordinary re-resolution (P2-3, D21)."""
    anchor = anchor_on(anchors, chapter, "the Kestrel rode low")
    mark = snapshots.capture(chapter.meta.id, reason=SnapshotReason.MANUAL, label="before")

    emptied = documents.save_content(chapter.meta.id, build_blocks([""]), chapter.meta.version)
    assert anchors.get(anchor.id).status == AnchorStatus.STALE

    restored = snapshots.restore(mark.id, emptied.version)

    assert [one.status for one in restored.anchors] == [AnchorStatus.OK]
    assert anchors.get(anchor.id).status == AnchorStatus.OK


def test_a_deleted_chapter_s_anchors_are_orphaned_and_come_back_as_they_were(
    anchors: AnchorStore, documents: DocumentStore, chapter: Document
) -> None:
    """Delete and restore write nothing to an anchor row, so nothing about it is invented."""
    kept = anchor_on(anchors, chapter, "the Kestrel rode low")
    documents.save_content(
        chapter.meta.id,
        build_blocks(["The harbour was grey and empty.", *HARBOUR[1:]]),
        chapter.meta.version,
    )
    before_delete = anchors.get(kept.id)
    assert before_delete.status == AnchorStatus.STALE

    documents.delete(chapter.meta.id)
    assert anchors.get(kept.id).status == AnchorStatus.ORPHANED

    documents.restore(chapter.meta.id)
    assert anchors.get(kept.id) == before_delete


# -- the cost of doing this on every autosave ---------------------------------------------------


def test_resolution_stays_inside_its_budget() -> None:
    """200 anchors over 100,000 characters, median of five runs (``specs/anchors.md`` § 3).

    It exists to catch a **change of algorithmic class**, not to benchmark a machine, so it is
    set generously and a failure means the resolver got cleverer and slower. The pure pass is
    what is timed: adding SQLite to the measurement would make a resolver regression look like
    disk noise, and it is the resolver this guards.

    The worst realistic case is timed, not the best: one paragraph inserted at the top moves
    every anchor, so not one of the two hundred can take the fast path.
    """
    paragraph = (
        "The harbour was grey and the {name} rode low in it while the tide went out and the "
        "gulls stood along the rail and did not move at all that morning, and the ropes lay "
        "coiled on the boards where the crew had left them the night before, and the lanterns "
        "in the customs house had not yet been put out, and nobody on the quay said a word "
        "about any of it until the bell rang the hour and the whole harbour seemed to shift "
        "an inch and settle again into the grey it had been."
    )
    tail = (
        " Afterwards the {mark} watch came up from below and stood about the deck without "
        "speaking, and the water under the hull was the colour of the sky, and the whole of it "
        "went on being that colour for a long while, which is the sort of morning it was."
    )
    blocks = [
        paragraph.format(name=f"vessel{index:03d}") + tail.format(mark=f"marker{index:03d}")
        for index in range(200)
    ]
    before = project(build_blocks(blocks))
    assert len(before.text_plain) > 100_000

    records: list[AnchorRecord] = []
    for index in range(200):
        text_from = before.text_plain.index(f"vessel{index:03d}")
        from_pos = text_offset_to_pm_position(before, text_from - 4)
        to_pos = text_offset_to_pm_position(before, text_from + 9)
        assert from_pos is not None and to_pos is not None
        found = extract(before, from_pos, to_pos)
        records.append(
            AnchorRecord(
                from_pos=found.from_pos,
                to_pos=found.to_pos,
                quote=found.quote,
                prefix=found.prefix,
                suffix=found.suffix,
            )
        )

    after = project(build_blocks(["A week earlier, nothing had happened at all.", *blocks]))
    timings: list[float] = []
    for _ in range(5):
        started = time.perf_counter()
        resolutions = resolve_all(records, after)
        timings.append((time.perf_counter() - started) * 1000)

    assert all(one.status == AnchorStatus.OK for one in resolutions)
    assert all(one.step > 1 for one in resolutions)
    median = sorted(timings)[2]
    assert median < RESOLUTION_BUDGET_MS, f"{median:.1f}ms over a {RESOLUTION_BUDGET_MS}ms budget"


def test_the_normalised_text_is_built_once_per_pass() -> None:
    """What keeps a pass linear in the number of anchors rather than quadratic."""
    projection = project(build_blocks(HARBOUR))
    context = context_for(projection)

    assert context.text.normal == "The harbour was grey and the Kestrel rode low in it. " + (
        "Marlow watched from the quay, saying nothing at all. He did not look back."
    )
    assert len(context.text.starts) == len(context.text.normal)


def test_a_stored_anchor_becomes_the_record_the_resolver_wants(
    anchors: AnchorStore, chapter: Document
) -> None:
    anchor = anchor_on(anchors, chapter, "the Kestrel rode low")
    record = as_record(anchor)

    assert record == AnchorRecord(
        from_pos=anchor.from_pos,
        to_pos=anchor.to_pos,
        quote=anchor.quote,
        prefix=anchor.prefix,
        suffix=anchor.suffix,
    )
