"""P3-4 - revisions, the retcon rule, and the review queue (D27).

The half of ``EntryStore`` that makes an edit recoverable and its consequences visible. Two
things here are the phase's exit criterion 2, and both are easy to get subtly wrong in opposite
directions:

* **flag too much** and the queue is noise within a day, which is the failure the mechanism
  exists to prevent - so an edit to a body flags nobody, and clearing a review flags nobody;
* **flag too little** and Phase 7's continuity findings are computed against records nobody was
  told to re-check - so an attribute edit flags every live link-neighbour in *both* directions.

``make_link`` inserts link rows directly; ``LinkStore`` is P3-6. What is under test here is D27's
dependent rule over the rows, not the store that will later write them.
"""

from __future__ import annotations

import pytest

from archetype.bible.entries import (
    RETCON_FIELDS,
    EntryStore,
    RevisionNotFoundError,
    StaleEntryVersionError,
)
from archetype.bible.schema import EntryKind

# -- every write records a revision --------------------------------------------------------------


def test_revision_one_is_the_creation(entries: EntryStore) -> None:
    """History is complete from the beginning, so "restore the original" is an ordinary restore."""
    entry = entries.create(EntryKind.CHARACTER, "Mira", summary="Counts the boats.")
    history = entries.revisions(entry.id)

    assert [meta.revision for meta in history] == [1]
    assert entries.revision(entry.id, 1).state["name"] == "Mira"
    assert entries.revision(entry.id, 1).state["summary"] == "Counts the boats."


def test_every_write_appends_a_revision_and_nothing_is_pruned(entries: EntryStore) -> None:
    """The deliberate opposite of D23 on both counts: nothing deduplicated, nothing pruned."""
    entry = entries.create(EntryKind.CHARACTER, "Mira")
    revision = entry.revision
    for index in range(30):
        revision = entries.update(entry.id, revision, summary=f"Take {index}.").revision

    history = entries.revisions(entry.id)
    assert [meta.revision for meta in history] == list(range(31, 0, -1)), "newest first, all kept"


def test_an_identical_write_is_not_deduplicated(entries: EntryStore) -> None:
    entry = entries.create(EntryKind.CHARACTER, "Mira", summary="Same.")
    entries.update(entry.id, entry.revision, summary="Same.")
    assert len(entries.revisions(entry.id)) == 2


def test_a_revision_holds_the_state_after_the_change(entries: EntryStore) -> None:
    """Revision *n* is what the entry was at revision *n* - one row to read, not a replay."""
    entry = entries.create(EntryKind.CHARACTER, "Mira", summary="First.")
    entries.update(entry.id, entry.revision, summary="Second.")

    assert entries.revision(entry.id, 1).state["summary"] == "First."
    assert entries.revision(entry.id, 2).state["summary"] == "Second."


def test_revisions_returns_metadata_only(entries: EntryStore) -> None:
    """``SnapshotStore.list``'s discipline, one table over: a history list carries no states."""
    entry = entries.create(EntryKind.CHARACTER, "Mira")
    meta = entries.revisions(entry.id)[0]
    assert not hasattr(meta, "state")
    assert not hasattr(meta, "snapshot_json")


def test_a_deleted_entrys_history_is_still_readable(entries: EntryStore) -> None:
    """It is exactly what someone deciding whether to restore it wants to see."""
    entry = entries.create(EntryKind.CHARACTER, "Mira")
    entries.delete(entry.id)
    assert [meta.reason for meta in entries.revisions(entry.id)] == ["deleted", ""]


def test_an_unknown_revision_is_not_found(entries: EntryStore) -> None:
    entry = entries.create(EntryKind.CHARACTER, "Mira")
    with pytest.raises(RevisionNotFoundError):
        entries.revision(entry.id, 99)


# -- restoring a revision ------------------------------------------------------------------------


def test_restoring_a_revision_reproduces_that_state_exactly(entries: EntryStore) -> None:
    entry = entries.create(
        EntryKind.CHARACTER, "Mira", summary="First.", attributes={"role": "protagonist"}
    )
    second = entries.update(
        entry.id, entry.revision, name="Mira Vance", summary="Second.", attributes={"role": "minor"}
    )

    restored = entries.restore_revision(entry.id, 1, second.revision)

    assert restored.entry.name == "Mira"
    assert restored.entry.summary == "First."
    assert restored.entry.attributes == {"role": "protagonist"}


def test_restoring_appends_to_history_rather_than_rewriting_it(entries: EntryStore) -> None:
    """``SnapshotStore.restore``'s rule, one table over: a restore is an ordinary edit."""
    entry = entries.create(EntryKind.CHARACTER, "Mira", summary="First.")
    second = entries.update(entry.id, entry.revision, summary="Second.")

    restored = entries.restore_revision(entry.id, 1, second.revision)

    assert restored.revision == 3, "a new revision at the top, not a rewind"
    assert [meta.revision for meta in entries.revisions(entry.id)] == [3, 2, 1]
    assert entries.revision(entry.id, 2).state["summary"] == "Second.", "history is intact"
    assert entries.revisions(entry.id)[0].reason == "restored revision 1"


def test_restoring_computes_its_own_retcon_answer(entries: EntryStore, make_link) -> None:
    """Because it goes through ``update``, and for no other reason."""
    mira = entries.create(EntryKind.CHARACTER, "Mira", attributes={"role": "protagonist"})
    elias = entries.create(EntryKind.CHARACTER, "Elias")
    make_link(mira.id, elias.id, relation="knows")

    second = entries.update(mira.id, mira.revision, attributes={"role": "minor"})
    entries.clear_review(elias.id, entries.get(elias.id).revision)

    restored = entries.restore_revision(mira.id, 1, second.revision)

    assert restored.retcon is True, "the attributes moved back, which is a move"
    assert restored.flagged == (elias.id,)
    assert entries.get(elias.id).needs_review is True


def test_a_stale_revision_refuses_a_restore(entries: EntryStore) -> None:
    entry = entries.create(EntryKind.CHARACTER, "Mira", summary="First.")
    entries.update(entry.id, entry.revision, summary="Second.")
    with pytest.raises(StaleEntryVersionError):
        entries.restore_revision(entry.id, 1, 1)


# -- the retcon computation (D27) ----------------------------------------------------------------


def test_a_body_only_edit_writes_a_revision_and_flags_nobody(
    entries: EntryStore, make_link
) -> None:
    """The half of D27 that keeps the queue worth reading (acceptance step 10)."""
    mira = entries.create(EntryKind.CHARACTER, "Mira")
    elias = entries.create(EntryKind.CHARACTER, "Elias")
    make_link(mira.id, elias.id, relation="knows")

    result = entries.update(mira.id, mira.revision, body_md="She counts the boats twice.")

    assert result.retcon is False
    assert result.flagged == ()
    assert result.changed_fields == ()
    assert entries.get(elias.id).needs_review is False
    assert len(entries.revisions(mira.id)) == 2, "a revision was still written"


def test_a_summary_only_edit_flags_nobody(entries: EntryStore, make_link) -> None:
    mira = entries.create(EntryKind.CHARACTER, "Mira")
    elias = entries.create(EntryKind.CHARACTER, "Elias")
    make_link(mira.id, elias.id, relation="knows")

    assert entries.update(mira.id, mira.revision, summary="New line.").retcon is False
    assert entries.get(elias.id).needs_review is False


@pytest.mark.parametrize(
    ("field", "change"),
    [
        ("name", {"name": "Mira Vance"}),
        ("attributes_json", {"attributes": {"role": "minor"}}),
        ("status", {"status": "superseded"}),
    ],
)
def test_each_retcon_field_flags_by_default(
    entries: EntryStore, make_link, field: str, change: dict
) -> None:
    assert field in RETCON_FIELDS
    mira = entries.create(EntryKind.CHARACTER, "Mira", attributes={"role": "protagonist"})
    elias = entries.create(EntryKind.CHARACTER, "Elias")
    make_link(mira.id, elias.id, relation="knows")

    result = entries.update(mira.id, mira.revision, **change)

    assert result.retcon is True
    assert result.changed_fields == (field,)
    assert result.flagged == (elias.id,)


def test_an_attribute_edit_flags_live_neighbours_in_both_directions_and_no_one_else(
    entries: EntryStore, make_link
) -> None:
    mira = entries.create(EntryKind.CHARACTER, "Mira", attributes={"role": "protagonist"})
    elias = entries.create(EntryKind.CHARACTER, "Elias")  # mira -> elias
    crew = entries.create(EntryKind.FACTION, "The Harbour Crew")  # mira -> crew
    letter = entries.create(EntryKind.ITEM, "The letter")  # letter -> mira, the other direction
    stranger = entries.create(EntryKind.CHARACTER, "A stranger")  # unlinked

    make_link(mira.id, elias.id, relation="knows")
    make_link(mira.id, crew.id, relation="member_of")
    make_link(letter.id, mira.id, relation="concerns")

    result = entries.update(mira.id, mira.revision, attributes={"role": "minor"})

    assert set(result.flagged) == {elias.id, crew.id, letter.id}
    assert entries.get(stranger.id).needs_review is False, "nothing unlinked is flagged"
    for flagged_id in result.flagged:
        assert entries.get(flagged_id).needs_review is True


def test_the_review_reason_names_the_entry_and_the_revision(entries: EntryStore, make_link) -> None:
    """The queue tells the writer what to go and look at, not only that something happened."""
    mira = entries.create(EntryKind.CHARACTER, "Mira", attributes={"role": "protagonist"})
    elias = entries.create(EntryKind.CHARACTER, "Elias")
    make_link(mira.id, elias.id, relation="knows")

    entries.update(mira.id, mira.revision, attributes={"role": "minor"})

    reason = entries.get(elias.id).review_reason
    assert "Mira" in reason
    assert "revision 2" in reason


def test_the_newest_disturbance_replaces_the_older_reason(entries: EntryStore, make_link) -> None:
    mira = entries.create(EntryKind.CHARACTER, "Mira", attributes={"role": "protagonist"})
    ida = entries.create(EntryKind.CHARACTER, "Ida", attributes={"role": "minor"})
    elias = entries.create(EntryKind.CHARACTER, "Elias")
    make_link(mira.id, elias.id, relation="knows")
    make_link(ida.id, elias.id, relation="knows")

    entries.update(mira.id, mira.revision, attributes={"role": "minor"})
    entries.update(ida.id, ida.revision, attributes={"role": "supporting"})

    reason = entries.get(elias.id).review_reason
    assert "Ida" in reason and "Mira" not in reason


def test_flagging_writes_no_revision_on_the_dependent(entries: EntryStore, make_link) -> None:
    """``needs_review`` is a note about the surroundings, not a claim the entry makes."""
    mira = entries.create(EntryKind.CHARACTER, "Mira", attributes={"role": "protagonist"})
    elias = entries.create(EntryKind.CHARACTER, "Elias")
    make_link(mira.id, elias.id, relation="knows")

    entries.update(mira.id, mira.revision, attributes={"role": "minor"})

    assert len(entries.revisions(elias.id)) == 1, "still just its creation"
    assert entries.get(elias.id).revision == 1


def test_a_deleted_neighbour_is_not_flagged(entries: EntryStore, make_link) -> None:
    mira = entries.create(EntryKind.CHARACTER, "Mira", attributes={"role": "protagonist"})
    elias = entries.create(EntryKind.CHARACTER, "Elias")
    make_link(mira.id, elias.id, relation="knows")
    entries.delete(elias.id)

    result = entries.update(mira.id, mira.revision, attributes={"role": "minor"})

    assert result.flagged == ()
    assert entries.get(elias.id, include_deleted=True).needs_review is False


def test_a_deleted_link_does_not_carry_a_flag(entries: EntryStore, make_link) -> None:
    mira = entries.create(EntryKind.CHARACTER, "Mira", attributes={"role": "protagonist"})
    elias = entries.create(EntryKind.CHARACTER, "Elias")
    make_link(mira.id, elias.id, relation="knows", deleted=True)

    result = entries.update(mira.id, mira.revision, attributes={"role": "minor"})

    assert result.flagged == ()
    assert entries.get(elias.id).needs_review is False


def test_the_retcon_answer_can_be_forced_on_or_off(entries: EntryStore, make_link) -> None:
    """The writer sees the computed default and decides - D12's posture, on the bible."""
    mira = entries.create(EntryKind.CHARACTER, "Mira", attributes={"role": "protagonist"})
    elias = entries.create(EntryKind.CHARACTER, "Elias")
    make_link(mira.id, elias.id, relation="knows")

    forced_on = entries.update(mira.id, mira.revision, body_md="A typo, fixed.", retcon=True)
    assert forced_on.retcon is True
    assert forced_on.changed_fields == (), "the computed answer is still reported, as an override"
    assert forced_on.flagged == (elias.id,)

    entries.clear_review(elias.id, entries.get(elias.id).revision)

    forced_off = entries.update(
        mira.id, forced_on.revision, attributes={"role": "minor"}, retcon=False
    )
    assert forced_off.retcon is False
    assert forced_off.changed_fields == ("attributes_json",)
    assert forced_off.flagged == ()
    assert entries.get(elias.id).needs_review is False


def test_the_revision_records_whether_it_was_a_retcon(entries: EntryStore, make_link) -> None:
    mira = entries.create(EntryKind.CHARACTER, "Mira", attributes={"role": "protagonist"})
    elias = entries.create(EntryKind.CHARACTER, "Elias")
    make_link(mira.id, elias.id, relation="knows")

    entries.update(mira.id, mira.revision, body_md="Just a body edit.")
    entries.update(mira.id, 2, attributes={"role": "minor"})

    assert [meta.retcon for meta in entries.revisions(mira.id)] == [True, False, False]


def test_a_retcon_does_not_flag_the_entry_that_changed(entries: EntryStore, make_link) -> None:
    mira = entries.create(EntryKind.CHARACTER, "Mira", attributes={"role": "protagonist"})
    elias = entries.create(EntryKind.CHARACTER, "Elias")
    make_link(mira.id, elias.id, relation="knows")

    result = entries.update(mira.id, mira.revision, attributes={"role": "minor"})

    assert mira.id not in result.flagged
    assert entries.get(mira.id).needs_review is False


# -- the review queue ----------------------------------------------------------------------------


def test_the_review_queue_is_exactly_the_flagged_entries_and_it_empties(
    entries: EntryStore, make_link
) -> None:
    """Exit criterion 2, and acceptance steps 8 and 9."""
    mira = entries.create(EntryKind.CHARACTER, "Mira", attributes={"role": "protagonist"})
    elias = entries.create(EntryKind.CHARACTER, "Elias")
    crew = entries.create(EntryKind.FACTION, "The Harbour Crew")
    make_link(mira.id, elias.id, relation="knows")
    make_link(mira.id, crew.id, relation="member_of")

    entries.update(mira.id, mira.revision, attributes={"role": "minor"})
    assert {e.id for e in entries.list(needs_review=True)} == {elias.id, crew.id}

    entries.clear_review(elias.id, entries.get(elias.id).revision)
    assert {e.id for e in entries.list(needs_review=True)} == {crew.id}

    entries.clear_review(crew.id, entries.get(crew.id).revision)
    assert entries.list(needs_review=True) == [], "the queue empties"


def test_clearing_a_review_flags_nothing(entries: EntryStore, make_link) -> None:
    """The clause the queue's usefulness rests on (acceptance step 9).

    Without it, clearing a flag on a densely linked character re-flags every neighbour and the
    queue regenerates itself as it is worked through.
    """
    mira = entries.create(EntryKind.CHARACTER, "Mira", attributes={"role": "protagonist"})
    neighbours = [entries.create(EntryKind.CHARACTER, f"Neighbour {n}") for n in range(5)]
    for neighbour in neighbours:
        make_link(mira.id, neighbour.id, relation="knows")

    entries.update(mira.id, mira.revision, attributes={"role": "minor"})
    assert len(entries.list(needs_review=True)) == 5

    first = entries.get(neighbours[0].id)
    result = entries.clear_review(first.id, first.revision)

    assert result.retcon is False
    assert result.flagged == ()
    assert len(entries.list(needs_review=True)) == 4, "one left the queue and none rejoined it"
    assert entries.get(mira.id).needs_review is False, "and the cleared entry's own link did not"


def test_clearing_a_review_is_guarded_and_recorded(entries: EntryStore, make_link) -> None:
    mira = entries.create(EntryKind.CHARACTER, "Mira", attributes={"role": "protagonist"})
    elias = entries.create(EntryKind.CHARACTER, "Elias")
    make_link(mira.id, elias.id, relation="knows")
    entries.update(mira.id, mira.revision, attributes={"role": "minor"})

    with pytest.raises(StaleEntryVersionError):
        entries.clear_review(elias.id, 99)
    assert entries.get(elias.id).needs_review is True, "the refused clear changed nothing"

    entries.clear_review(elias.id, entries.get(elias.id).revision)
    cleared = entries.get(elias.id)
    assert cleared.needs_review is False
    assert cleared.review_reason == ""
    assert entries.revisions(elias.id)[0].reason == "review cleared"


# -- the dependent rule, read back ----------------------------------------------------------------


def test_dependents_reports_both_directions_once_each(entries: EntryStore, make_link) -> None:
    mira = entries.create(EntryKind.CHARACTER, "Mira")
    elias = entries.create(EntryKind.CHARACTER, "Elias")
    make_link(mira.id, elias.id, relation="knows")
    make_link(elias.id, mira.id, relation="related_to")

    assert entries.dependents(mira.id) == [elias.id], "two links, one dependent"


def test_an_entry_with_no_links_has_no_dependents(entries: EntryStore) -> None:
    """The honest limit, asserted: a dependency the data does not know about is not flagged."""
    mira = entries.create(EntryKind.CHARACTER, "Mira", attributes={"role": "protagonist"})
    entries.create(EntryKind.CHARACTER, "Elias", body_md="Elias thinks of Mira constantly.")

    assert entries.dependents(mira.id) == [], "a prose mention is not a link"
    assert entries.update(mira.id, mira.revision, attributes={"role": "minor"}).flagged == ()


def test_dependents_are_scoped_to_the_project(entries: EntryStore, make_project, make_link) -> None:
    other = EntryStore(make_project("Another Manuscript"))
    mira = entries.create(EntryKind.CHARACTER, "Mira", attributes={"role": "protagonist"})
    stranger = other.create(EntryKind.CHARACTER, "A stranger from elsewhere")

    assert entries.dependents(mira.id) == []
    assert other.dependents(stranger.id) == []
