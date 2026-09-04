"""P3-3 - ``EntryStore``: the uniform record, its filters, and its refusals (D25, D26).

The point of D26 is that seven kinds cost one store, one search, and one form. So the first test
here rounds every one of the seven through the same three calls, and every refusal below is
asserted to have written **nothing** - ``attributes_json`` is a blob in storage but it is not a
free-form bag, and the moment it becomes one the served definition stops describing what is
actually in the file.
"""

from __future__ import annotations

import pytest

from archetype.bible.entries import (
    MAX_BODY_BYTES,
    MAX_NAME_CHARS,
    MAX_SUMMARY_CHARS,
    SEARCH_LIMIT,
    EntryNotFoundError,
    EntryOrigin,
    EntryStatus,
    EntryStore,
    StaleEntryVersionError,
)
from archetype.bible.schema import ENTRY_KINDS, EntryKind, InvalidAttributesError

from .conftest import sample_value

# -- the uniform record ------------------------------------------------------------------------


def test_every_kind_round_trips_through_one_store(entries: EntryStore) -> None:
    """D26's whole claim, asserted directly: one store serves all seven."""
    made = {}
    for definition in ENTRY_KINDS:
        attributes = {
            field.name: sample_value(field) for field in definition.fields if field.required
        }
        entry = entries.create(definition.kind, f"A {definition.label}", attributes=attributes)
        made[definition.kind] = entry.id
        assert entry.kind == definition.kind
        assert entry.revision == 1
        assert entry.status == EntryStatus.ACCEPTED, "everything a person types is accepted"
        assert entry.origin == EntryOrigin.USER, "origin is always user in Phase 3"
        assert entry.needs_review is False

    assert len(entries.list()) == len(ENTRY_KINDS)
    for kind, entry_id in made.items():
        assert entries.get(entry_id).kind == kind
        assert [e.kind for e in entries.list(kind=kind)] == [kind]


def test_counts_by_kind_reports_every_kind_including_the_empty_ones(entries: EntryStore) -> None:
    entries.create(EntryKind.CHARACTER, "Mira")
    entries.create(EntryKind.CHARACTER, "Elias")
    entries.create(EntryKind.PLACE, "The Harbour")

    counts = entries.counts_by_kind()
    assert counts["character"] == 2
    assert counts["place"] == 1
    assert counts["item"] == 0, "a kind with no entries answers zero rather than being absent"
    assert set(counts) == {definition.kind for definition in ENTRY_KINDS}


def test_a_name_is_not_an_identifier(entries: EntryStore) -> None:
    """The bible is not a namespace, and stories give two people the same name on purpose."""
    first = entries.create(EntryKind.CHARACTER, "Mira")
    second = entries.create(EntryKind.CHARACTER, "Mira")
    assert first.id != second.id
    assert len(entries.list()) == 2


def test_attributes_round_trip_for_all_six_field_types(entries: EntryStore) -> None:
    place = entries.create(EntryKind.PLACE, "The Harbour")
    character = entries.create(
        EntryKind.CHARACTER,
        "Mira",
        attributes={
            "aliases": ["the harbourmaster's girl", "Mir"],  # list_of_text
            "role": "protagonist",  # enum
            "pronouns": "she/her",  # text
            "appearance": "Weather-worn, and younger than she looks.",  # long_text
            "home": place.id,  # entry_ref
        },
    )
    event = entries.create(
        EntryKind.EVENT,
        "The boats stay in",
        attributes={"story_time": {"label": "the third grey morning", "sort_key": 3}},
    )

    read = entries.get(character.id)
    assert read.attributes["aliases"] == ["the harbourmaster's girl", "Mir"]
    assert read.attributes["role"] == "protagonist"
    assert read.attributes["home"] == place.id
    assert entries.get(event.id).attributes["story_time"] == {
        "label": "the third grey morning",
        "sort_key": 3.0,
    }


def test_an_emptied_field_is_an_absent_field(entries: EntryStore) -> None:
    """Two ways to say nothing would give the client no way to choose between them."""
    entry = entries.create(
        EntryKind.CHARACTER, "Mira", attributes={"pronouns": "", "aliases": [], "role": None}
    )
    assert entry.attributes == {}


# -- refusals, each writing nothing --------------------------------------------------------------


def test_an_unknown_kind_is_refused(entries: EntryStore) -> None:
    with pytest.raises(InvalidAttributesError, match="unknown entry kind"):
        entries.create("dragon", "Smaug")
    assert entries.list() == []


def test_an_undeclared_attribute_is_refused_rather_than_dropped(entries: EntryStore) -> None:
    with pytest.raises(InvalidAttributesError, match="favourite_colour") as caught:
        entries.create(EntryKind.CHARACTER, "Mira", attributes={"favourite_colour": "grey"})
    assert caught.value.field == "favourite_colour", "the message names the field (step 3)"
    assert entries.list() == [], "nothing was written"


def test_an_attribute_of_the_wrong_type_is_refused(entries: EntryStore) -> None:
    with pytest.raises(InvalidAttributesError, match="expected a list of strings"):
        entries.create(EntryKind.CHARACTER, "Mira", attributes={"aliases": "Mir"})
    with pytest.raises(InvalidAttributesError, match="expected a string"):
        entries.create(EntryKind.CHARACTER, "Mira", attributes={"pronouns": 7})
    assert entries.list() == []


def test_an_enum_value_outside_its_declared_set_is_refused(entries: EntryStore) -> None:
    with pytest.raises(InvalidAttributesError, match="not one of") as caught:
        entries.create(EntryKind.CHARACTER, "Mira", attributes={"role": "narrator"})
    assert caught.value.field == "role"
    assert entries.list() == []


def test_an_entry_ref_to_the_wrong_kind_is_refused(entries: EntryStore) -> None:
    item = entries.create(EntryKind.ITEM, "The letter")
    with pytest.raises(InvalidAttributesError, match="points at a item"):
        entries.create(EntryKind.CHARACTER, "Mira", attributes={"home": item.id})
    assert [entry.name for entry in entries.list()] == ["The letter"]


def test_an_entry_ref_to_nothing_is_refused(entries: EntryStore) -> None:
    with pytest.raises(InvalidAttributesError, match="no live entry"):
        entries.create(EntryKind.CHARACTER, "Mira", attributes={"home": "ent_absent00000"})


def test_an_entry_ref_to_a_deleted_entry_is_refused(entries: EntryStore) -> None:
    place = entries.create(EntryKind.PLACE, "The Harbour")
    entries.delete(place.id)
    with pytest.raises(InvalidAttributesError, match="no live entry"):
        entries.create(EntryKind.CHARACTER, "Mira", attributes={"home": place.id})


def test_a_required_field_is_required(entries: EntryStore) -> None:
    with pytest.raises(InvalidAttributesError, match="statement: is required"):
        entries.create(EntryKind.FACT, "The tide")
    assert entries.list() == []


def test_a_blank_or_oversized_name_is_refused(entries: EntryStore) -> None:
    with pytest.raises(ValueError, match="name may not be blank"):
        entries.create(EntryKind.CHARACTER, "   ")
    with pytest.raises(ValueError, match="over the 200-character limit"):
        entries.create(EntryKind.CHARACTER, "M" * (MAX_NAME_CHARS + 1))
    assert entries.list() == []


def test_an_oversized_summary_or_body_is_refused(entries: EntryStore) -> None:
    with pytest.raises(ValueError, match="summary is"):
        entries.create(EntryKind.CHARACTER, "Mira", summary="s" * (MAX_SUMMARY_CHARS + 1))
    with pytest.raises(ValueError, match="an entry is a note, not a manuscript"):
        entries.create(EntryKind.CHARACTER, "Mira", body_md="b" * (MAX_BODY_BYTES + 1))
    assert entries.list() == []


def test_an_unknown_status_is_refused(entries: EntryStore) -> None:
    with pytest.raises(ValueError, match="unknown status"):
        entries.create(EntryKind.CHARACTER, "Mira", status="probably")
    assert entries.list() == []


# -- update, and the D19 guard -------------------------------------------------------------------


def test_an_update_bumps_the_revision_and_keeps_what_it_was_not_told_about(
    entries: EntryStore,
) -> None:
    entry = entries.create(EntryKind.CHARACTER, "Mira", summary="A harbourmaster's daughter.")
    result = entries.update(entry.id, entry.revision, body_md="She counts the boats.")

    assert result.revision == 2
    assert result.entry.body_md == "She counts the boats."
    assert result.entry.summary == "A harbourmaster's daughter.", "an omitted field is untouched"
    assert result.entry.name == "Mira"


def test_a_stale_revision_is_refused_with_nothing_written(entries: EntryStore) -> None:
    entry = entries.create(EntryKind.CHARACTER, "Mira")
    entries.update(entry.id, entry.revision, summary="First.")

    with pytest.raises(StaleEntryVersionError) as caught:
        entries.update(entry.id, entry.revision, summary="Second.")

    assert caught.value.current_revision == 2
    assert caught.value.presented == 1
    assert entries.get(entry.id).summary == "First.", "the refused write changed nothing"
    assert len(entries.revisions(entry.id)) == 2, "and recorded no revision"


def test_kind_cannot_be_updated(entries: EntryStore) -> None:
    """Not discouraged - absent. There is no parameter for it (specs/bible.md section 1)."""
    entry = entries.create(EntryKind.CHARACTER, "Mira")
    with pytest.raises(TypeError):
        entries.update(entry.id, entry.revision, kind=EntryKind.PLACE)  # type: ignore[call-arg]


def test_an_update_with_bad_attributes_writes_nothing(entries: EntryStore) -> None:
    entry = entries.create(EntryKind.CHARACTER, "Mira", summary="Before.")
    with pytest.raises(InvalidAttributesError):
        entries.update(entry.id, entry.revision, summary="After.", attributes={"role": "narrator"})

    after = entries.get(entry.id)
    assert after.summary == "Before."
    assert after.revision == 1


def test_a_field_may_not_reference_its_own_entry(entries: EntryStore) -> None:
    place = entries.create(EntryKind.PLACE, "The Harbour")
    with pytest.raises(InvalidAttributesError, match="no live entry"):
        entries.update(place.id, place.revision, attributes={"region": place.id})


# -- the soft delete (D25), and the one test that holds every read path together -----------------


def test_a_deleted_entry_is_absent_from_every_read_path_together(
    entries: EntryStore, make_link
) -> None:
    """The Phase 2 lesson, one table wider (ruling 9).

    Asserted **together** rather than one query per test, because a predicate that leaks from one
    read surfaces as a wrong count and gets reported as a different bug entirely.
    """
    mira = entries.create(EntryKind.CHARACTER, "Mira", summary="Counts the boats.")
    elias = entries.create(EntryKind.CHARACTER, "Elias")
    make_link(mira.id, elias.id, relation="knows")

    entries.delete(mira.id)

    assert [e.name for e in entries.list()] == ["Elias"], "the list"
    assert entries.counts_by_kind()["character"] == 1, "the counts"
    assert entries.list(kind=EntryKind.CHARACTER) == entries.list(), "the kind filter"
    assert entries.list(q="boats") == [], "the search filter"
    assert entries.list(needs_review=False) == entries.list(), "the review queue"
    assert entries.dependents(elias.id) == [], "the link view and the dependent computation"
    with pytest.raises(EntryNotFoundError):
        entries.get(mira.id)

    assert [e.name for e in entries.list_deleted()] == ["Mira"], "but the restore surface has it"
    assert entries.get(mira.id, include_deleted=True).summary == "Counts the boats."


def test_restoring_returns_the_entry_unchanged_and_brings_its_links_back(
    entries: EntryStore, make_link
) -> None:
    mira = entries.create(EntryKind.CHARACTER, "Mira", summary="Counts the boats.")
    elias = entries.create(EntryKind.CHARACTER, "Elias")
    make_link(mira.id, elias.id, relation="knows")

    entries.delete(mira.id)
    entries.restore(mira.id)

    restored = entries.get(mira.id)
    assert restored.summary == "Counts the boats."
    assert restored.deleted_at is None
    assert entries.dependents(elias.id) == [mira.id], "the link was hidden, never removed"
    assert entries.list_deleted() == []


def test_a_link_deleted_in_its_own_right_stays_deleted_through_a_restore(
    entries: EntryStore, make_link
) -> None:
    """Nothing cascades, which is exactly what makes restore exact."""
    mira = entries.create(EntryKind.CHARACTER, "Mira")
    elias = entries.create(EntryKind.CHARACTER, "Elias")
    ida = entries.create(EntryKind.CHARACTER, "Ida")
    make_link(mira.id, elias.id, relation="knows")
    make_link(mira.id, ida.id, relation="knows", deleted=True)

    entries.delete(mira.id)
    entries.restore(mira.id)

    assert entries.dependents(mira.id) == [elias.id]


def test_restoring_a_live_entry_is_a_no_op(entries: EntryStore) -> None:
    entry = entries.create(EntryKind.CHARACTER, "Mira")
    assert entries.restore(entry.id).revision == entry.revision


def test_deleting_a_deleted_entry_is_refused(entries: EntryStore) -> None:
    entry = entries.create(EntryKind.CHARACTER, "Mira")
    entries.delete(entry.id)
    with pytest.raises(EntryNotFoundError):
        entries.delete(entry.id)


# -- the filters (ruling 4) ----------------------------------------------------------------------


def test_the_filters_compose(entries: EntryStore) -> None:
    entries.create(EntryKind.CHARACTER, "Mira", summary="Counts the boats.")
    entries.create(EntryKind.CHARACTER, "Elias", summary="Keeps the letter.")
    entries.create(EntryKind.PLACE, "The Harbour", summary="Grey, and counting.")

    assert [e.name for e in entries.list(kind=EntryKind.CHARACTER)] == ["Elias", "Mira"]
    assert [e.name for e in entries.list(q="count")] == ["Mira", "The Harbour"]
    assert [e.name for e in entries.list(kind=EntryKind.CHARACTER, q="count")] == ["Mira"]


def test_the_search_filter_reads_name_aliases_and_summary(entries: EntryStore) -> None:
    entries.create(EntryKind.CHARACTER, "Mira", attributes={"aliases": ["the harbourmaster"]})
    entries.create(EntryKind.CHARACTER, "Elias", summary="Kept the harbour letter.")
    entries.create(EntryKind.PLACE, "The Harbour")

    assert {e.name for e in entries.list(q="harbour")} == {"Mira", "Elias", "The Harbour"}
    assert {e.name for e in entries.list(q="Mira")} == {"Mira"}


def test_the_search_filter_treats_wildcards_as_characters(entries: EntryStore) -> None:
    """A search for ``100%`` finds ``100%``, not everything."""
    entries.create(EntryKind.FACT, "Tithe", attributes={"statement": "A 100% tithe."})
    entries.create(EntryKind.FACT, "Other", attributes={"statement": "Nothing like it."})

    assert [e.name for e in entries.list(q="100%")] == ["Tithe"]
    # A bare wildcard is a character too: it finds the one entry that literally contains one,
    # rather than matching every row the way an unescaped LIKE pattern would.
    assert [e.name for e in entries.list(q="%")] == ["Tithe"]
    assert [e.name for e in entries.list(q="_")] == []


def test_the_search_filter_is_capped(entries: EntryStore) -> None:
    """A bible is hundreds of rows, and the cap is real rather than aspirational."""
    for index in range(SEARCH_LIMIT + 5):
        entries.create(EntryKind.CHARACTER, f"Extra {index:04d}")
    assert len(entries.list()) == SEARCH_LIMIT


def test_an_unknown_filter_value_is_refused_rather_than_returning_nothing(
    entries: EntryStore,
) -> None:
    """An empty list would read as "there are no dragons" rather than "dragon is not a kind"."""
    with pytest.raises(InvalidAttributesError, match="unknown entry kind"):
        entries.list(kind="dragon")
    with pytest.raises(ValueError, match="unknown status"):
        entries.list(status="probably")


def test_a_missing_entry_is_not_found(entries: EntryStore) -> None:
    with pytest.raises(EntryNotFoundError):
        entries.get("ent_absent00000")
