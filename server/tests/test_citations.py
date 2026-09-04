"""P3-7 - citations: where the bible meets the manuscript (``specs/bible.md`` section 8).

The tests that matter most here are the ones about what *does not* happen:

* a stale document version refuses *Add to bible* whole - no anchor, no entry, no citation, which
  is the only reason those three writes share a transaction;
* deleting an anchor takes its citations and **leaves the entries**;
* soft-deleting an entry leaves its citations and its anchors untouched;
* deleting the *chapter* takes nothing away - the citation reads ``orphaned`` and comes back to
  what it was when the chapter is restored (D22, derived and never written).

The one thing asserted about the anchor itself is that its quote is the **server's**: a client
sends a range and a version and is never asked what the manuscript says (ruling 8).
"""

from __future__ import annotations

import pytest

from archetype.bible.citations import CitationRole, CitationStore
from archetype.bible.entries import EntryNotFoundError, EntryStore
from archetype.bible.schema import EntryKind, InvalidAttributesError
from archetype.manuscript.anchors import AnchorStatus
from archetype.manuscript.anchors.store import AnchorNotFoundError, AnchorStore
from archetype.manuscript.documents import Document, DocumentStore, StaleVersionError
from archetype.manuscript.projection import project, text_offset_to_pm_position

from .conftest import build_document

PROSE = [
    "The harbour was grey and the Kestrel rode low in it.",
    "Marlow watched from the quay, saying nothing at all.",
]


@pytest.fixture
def chapter(make_document):
    """A chapter with two paragraphs of real prose to anchor into."""
    return make_document(title="Arrival", paragraphs=PROSE)


@pytest.fixture
def anchors(project) -> AnchorStore:
    return AnchorStore(project)


def range_over(document: Document, passage: str) -> tuple[int, int]:
    """The ProseMirror range a client selecting ``passage`` would send.

    Through the projection's own conversion, as ``test_anchor_store.py`` does: hand-arithmetic
    over node sizes is a second implementation of the thing under test.
    """
    projection = project(document.content)
    text_from = projection.text_plain.index(passage)
    from_pos = text_offset_to_pm_position(projection, text_from)
    to_pos = text_offset_to_pm_position(projection, text_from + len(passage))
    assert from_pos is not None and to_pos is not None
    return from_pos, to_pos


# -- Add to bible: one transaction (ruling 8) -----------------------------------------------------


def test_an_entry_created_from_a_selection_carries_the_servers_quote(
    citations: CitationStore, chapter
) -> None:
    """Step 1 of the acceptance run. The client sent a range; the words came from the file."""
    start, end = range_over(chapter, "the Kestrel rode low")
    made = citations.create_from_range(
        chapter.meta.id,
        from_pos=start,
        to_pos=end,
        version=chapter.meta.version,
        kind=EntryKind.CHARACTER,
        name="The Kestrel's master",
    )

    assert made.entry.kind == EntryKind.CHARACTER
    assert made.entry.revision == 1
    assert made.anchor.quote == "the Kestrel rode low"
    assert made.role == CitationRole.SOURCE

    listed = citations.citations(made.entry.id)
    assert [citation.anchor.id for citation in listed] == [made.anchor.id]
    assert listed[0].document_id == chapter.meta.id
    assert listed[0].document_title == "Arrival"
    assert listed[0].anchor.status == AnchorStatus.OK


def test_a_stale_version_refuses_the_whole_operation_with_nothing_written(
    citations: CitationStore, documents: DocumentStore, entries: EntryStore, chapter
) -> None:
    """Not the anchor, not the entry, not the citation - the reason the three share one write."""
    documents.save_content(
        chapter.meta.id,
        build_document(paragraphs=[*PROSE, "The tide turned."]),
        chapter.meta.version,
    )
    start, end = range_over(chapter, "the Kestrel rode low")

    with pytest.raises(StaleVersionError):
        citations.create_from_range(
            chapter.meta.id,
            from_pos=start,
            to_pos=end,
            version=chapter.meta.version,
            kind=EntryKind.CHARACTER,
            name="Nobody",
        )

    assert entries.list() == []
    assert citations.anchors.list_for_project() == []


def test_an_undeclared_attribute_refuses_the_whole_operation(
    citations: CitationStore, entries: EntryStore, chapter
) -> None:
    """The entry half refuses after the anchor half has inserted - so the rollback is the test."""
    start, end = range_over(chapter, "the Kestrel rode low")

    with pytest.raises(InvalidAttributesError):
        citations.create_from_range(
            chapter.meta.id,
            from_pos=start,
            to_pos=end,
            version=chapter.meta.version,
            kind=EntryKind.CHARACTER,
            name="Mira",
            attributes={"favourite_colour": "grey"},
        )

    assert entries.list() == []
    assert citations.anchors.list_for_project() == [], "the anchor went back with the entry"


def test_an_unknown_role_is_refused_before_anything_is_written(
    citations: CitationStore, entries: EntryStore, chapter
) -> None:
    start, end = range_over(chapter, "the Kestrel rode low")
    with pytest.raises(InvalidAttributesError) as raised:
        citations.create_from_range(
            chapter.meta.id,
            from_pos=start,
            to_pos=end,
            version=chapter.meta.version,
            kind=EntryKind.CHARACTER,
            name="Mira",
            role="footnote",
        )
    assert raised.value.field == "role"
    assert entries.list() == []
    assert citations.anchors.list_for_project() == []


# -- citing an anchor that already exists ---------------------------------------------------------


def test_cite_and_uncite_an_existing_anchor(
    citations: CitationStore, anchors: AnchorStore, make_entry, chapter
) -> None:
    entry = make_entry("Marlow")
    start, end = range_over(chapter, "Marlow watched")
    anchor = anchors.create(
        chapter.meta.id, from_pos=start, to_pos=end, version=chapter.meta.version
    )

    citation = citations.cite(entry.id, anchor.id, CitationRole.MENTION)
    assert citation.role == CitationRole.MENTION
    assert [item.anchor.id for item in citations.citations(entry.id)] == [anchor.id]

    assert citations.uncite(entry.id, anchor.id) == 1
    assert citations.citations(entry.id) == []
    assert anchors.get(anchor.id).id == anchor.id, "the anchor stays; a citation is not the anchor"


def test_one_anchor_may_be_cited_in_more_than_one_role(
    citations: CitationStore, anchors: AnchorStore, make_entry, chapter
) -> None:
    """The primary key is all three columns, so the same passage can be setup *and* payoff."""
    entry = make_entry("Marlow")
    start, end = range_over(chapter, "the Kestrel rode low")
    anchor = anchors.create(
        chapter.meta.id, from_pos=start, to_pos=end, version=chapter.meta.version
    )

    citations.cite(entry.id, anchor.id, CitationRole.SETUP)
    citations.cite(entry.id, anchor.id, CitationRole.PAYOFF)
    assert sorted(item.role for item in citations.citations(entry.id)) == ["payoff", "setup"]

    assert citations.uncite(entry.id, anchor.id, role=CitationRole.SETUP) == 1
    assert [item.role for item in citations.citations(entry.id)] == ["payoff"]


def test_citing_the_same_thing_twice_is_not_an_error(
    citations: CitationStore, anchors: AnchorStore, make_entry, chapter
) -> None:
    entry = make_entry("Marlow")
    start, end = range_over(chapter, "the Kestrel rode low")
    anchor = anchors.create(
        chapter.meta.id, from_pos=start, to_pos=end, version=chapter.meta.version
    )

    first = citations.cite(entry.id, anchor.id)
    again = citations.cite(entry.id, anchor.id)
    assert again.created_at == first.created_at
    assert len(citations.citations(entry.id)) == 1


def test_citing_refuses_an_entry_or_an_anchor_that_is_not_there(
    citations: CitationStore, anchors: AnchorStore, make_entry, chapter
) -> None:
    entry = make_entry("Marlow")
    start, end = range_over(chapter, "the Kestrel rode low")
    anchor = anchors.create(
        chapter.meta.id, from_pos=start, to_pos=end, version=chapter.meta.version
    )

    with pytest.raises(EntryNotFoundError):
        citations.cite("ent_nothing", anchor.id)
    with pytest.raises(AnchorNotFoundError):
        citations.cite(entry.id, "anc_nothing")


def test_a_deleted_entry_cannot_be_cited(
    citations: CitationStore, anchors: AnchorStore, entries: EntryStore, make_entry, chapter
) -> None:
    entry = make_entry("Marlow")
    entries.delete(entry.id)
    start, end = range_over(chapter, "the Kestrel rode low")
    anchor = anchors.create(
        chapter.meta.id, from_pos=start, to_pos=end, version=chapter.meta.version
    )

    with pytest.raises(EntryNotFoundError):
        citations.cite(entry.id, anchor.id)


# -- the reverse view ------------------------------------------------------------------------------


def test_entries_for_anchor_names_the_live_entries_that_cite_it(
    citations: CitationStore, entries: EntryStore, chapter
) -> None:
    start, end = range_over(chapter, "the Kestrel rode low")
    made = citations.create_from_range(
        chapter.meta.id,
        from_pos=start,
        to_pos=end,
        version=chapter.meta.version,
        kind=EntryKind.CHARACTER,
        name="Mira",
    )
    other = entries.create(EntryKind.FACT, "The ship is old", attributes={"statement": "Old."})
    citations.cite(other.id, made.anchor.id, CitationRole.MENTION)

    citing = citations.entries_for_anchor(made.anchor.id)
    assert [item.name for item in citing] == ["Mira", "The ship is old"]
    assert {item.role for item in citing} == {CitationRole.SOURCE, CitationRole.MENTION}

    entries.delete(other.id)
    assert [item.name for item in citations.entries_for_anchor(made.anchor.id)] == ["Mira"]


# -- the two deletions do not reach each other -----------------------------------------------------


def test_deleting_an_anchor_removes_its_citations_and_leaves_the_entries(
    citations: CitationStore, anchors: AnchorStore, entries: EntryStore, chapter
) -> None:
    start, end = range_over(chapter, "the Kestrel rode low")
    made = citations.create_from_range(
        chapter.meta.id,
        from_pos=start,
        to_pos=end,
        version=chapter.meta.version,
        kind=EntryKind.CHARACTER,
        name="Mira",
    )

    anchors.delete(made.anchor.id)

    assert entries.get(made.entry.id).name == "Mira", "the entry stays, with one fewer reason"
    assert citations.citations(made.entry.id) == []
    assert citations.entries_for_anchor(made.anchor.id) == []


def test_soft_deleting_an_entry_leaves_its_citations_and_its_anchors(
    citations: CitationStore, anchors: AnchorStore, entries: EntryStore, chapter
) -> None:
    """An anchor is a fact about the manuscript; an entry is not."""
    start, end = range_over(chapter, "the Kestrel rode low")
    made = citations.create_from_range(
        chapter.meta.id,
        from_pos=start,
        to_pos=end,
        version=chapter.meta.version,
        kind=EntryKind.CHARACTER,
        name="Mira",
    )

    entries.delete(made.entry.id)

    assert anchors.get(made.anchor.id).quote == "the Kestrel rode low"
    assert [item.anchor.id for item in citations.citations(made.entry.id)] == [made.anchor.id]
    assert citations.entries_for_anchor(made.anchor.id) == [], "but no live entry cites it"

    entries.restore(made.entry.id)
    assert [item.name for item in citations.entries_for_anchor(made.anchor.id)] == ["Mira"]


def test_a_citation_reports_stale_after_the_passage_is_rewritten(
    citations: CitationStore, documents: DocumentStore, chapter
) -> None:
    """Step 12 of the acceptance run, at the store level. The entry itself is untouched."""
    start, end = range_over(chapter, "the Kestrel rode low")
    made = citations.create_from_range(
        chapter.meta.id,
        from_pos=start,
        to_pos=end,
        version=chapter.meta.version,
        kind=EntryKind.CHARACTER,
        name="Mira",
    )

    documents.save_content(
        chapter.meta.id,
        build_document(paragraphs=["Nothing of what was here remains.", PROSE[1]]),
        chapter.meta.version,
    )

    citation = citations.citations(made.entry.id)[0]
    assert citation.anchor.status == AnchorStatus.STALE
    assert citation.anchor.quote == "the Kestrel rode low", "the quote is what it always was"
    assert citations.entries.get(made.entry.id).revision == 1, "the entry did not change"


def test_a_deleted_chapter_makes_its_citations_orphaned_and_a_restore_undoes_it(
    citations: CitationStore, documents: DocumentStore, chapter
) -> None:
    """Step 14. ``orphaned`` is derived from the chapter, so nothing is written either way."""
    start, end = range_over(chapter, "the Kestrel rode low")
    made = citations.create_from_range(
        chapter.meta.id,
        from_pos=start,
        to_pos=end,
        version=chapter.meta.version,
        kind=EntryKind.CHARACTER,
        name="Mira",
    )

    documents.delete(chapter.meta.id)
    assert citations.citations(made.entry.id)[0].anchor.status == AnchorStatus.ORPHANED

    documents.restore(chapter.meta.id)
    assert citations.citations(made.entry.id)[0].anchor.status == AnchorStatus.OK


# -- narrative position, derived and never stored --------------------------------------------------


def test_narrative_position_follows_the_chapter_order_without_being_stored(
    citations: CitationStore, documents: DocumentStore, make_document, chapter
) -> None:
    second = make_document(title="Departure", paragraphs=PROSE)
    start, end = range_over(chapter, "the Kestrel rode low")
    first_entry = citations.create_from_range(
        chapter.meta.id,
        from_pos=start,
        to_pos=end,
        version=chapter.meta.version,
        kind=EntryKind.CHARACTER,
        name="Mira",
    ).entry
    second_entry = citations.create_from_range(
        second.meta.id,
        from_pos=start,
        to_pos=end,
        version=second.meta.version,
        kind=EntryKind.CHARACTER,
        name="Elias",
    ).entry

    before = citations.narrative_positions()
    assert before[first_entry.id].order_index < before[second_entry.id].order_index

    documents.reorder([second.meta.id, chapter.meta.id])

    after = citations.narrative_positions()
    assert after[second_entry.id].order_index < after[first_entry.id].order_index, (
        "the position moved with the chapter, and nothing was rewritten to make it"
    )


def test_an_entry_with_no_source_citation_has_no_narrative_position(
    citations: CitationStore, anchors: AnchorStore, make_entry, chapter
) -> None:
    """D9's tray, arriving from the data rather than from a flag somebody maintains."""
    entry = make_entry("Mira")
    assert citations.narrative_position(entry.id) is None

    start, end = range_over(chapter, "the Kestrel rode low")
    anchor = anchors.create(
        chapter.meta.id, from_pos=start, to_pos=end, version=chapter.meta.version
    )
    citations.cite(entry.id, anchor.id, CitationRole.MENTION)
    assert citations.narrative_position(entry.id) is None, "a mention is not a source"

    citations.cite(entry.id, anchor.id, CitationRole.SOURCE)
    assert citations.narrative_position(entry.id) is not None


def test_a_source_in_a_deleted_chapter_places_nothing(
    citations: CitationStore, documents: DocumentStore, chapter
) -> None:
    start, end = range_over(chapter, "the Kestrel rode low")
    made = citations.create_from_range(
        chapter.meta.id,
        from_pos=start,
        to_pos=end,
        version=chapter.meta.version,
        kind=EntryKind.CHARACTER,
        name="Mira",
    )
    assert citations.narrative_position(made.entry.id) is not None

    documents.delete(chapter.meta.id)
    assert citations.narrative_position(made.entry.id) is None

    documents.restore(chapter.meta.id)
    assert citations.narrative_position(made.entry.id) is not None
