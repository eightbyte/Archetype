"""P3-6 - ``LinkStore``: the vocabulary's refusals, symmetry, and the three-way live predicate.

Two of these tests carry more weight than the rest.

``test_a_deleted_entry_is_absent_from_every_link_read_path_together`` is ruling 9's, asserted the
way ``test_chapters.py`` asserts D22's: **together**, in one test, across every path that reads a
link - ``for_entry`` from each end, the project list, ``edges``, the counts, and the dependent
computation D27 flags from. A predicate that leaks in one query is invisible until it is expensive,
and in Phase 8 it surfaces as a wrong interaction chart reported as a Phase 8 bug.

``test_a_symmetric_relation_is_stored_once_and_read_from_both_ends`` is ruling 7's. Two rows for
one symmetric relation can disagree, and Phase 8's adjacency matrix would double-count them.
"""

from __future__ import annotations

import pytest

from archetype.bible.entries import EntryNotFoundError, EntryStore
from archetype.bible.links import DuplicateLinkError, LinkEnd, LinkNotFoundError, LinkStore
from archetype.bible.schema import (
    MAX_STORY_TIME_CHARS,
    RELATIONS,
    EntryKind,
    InvalidAttributesError,
    relation_for,
)
from archetype.bible.storytime import events_from_entries, order_events


@pytest.fixture
def cast(entries: EntryStore) -> dict[str, str]:
    """One entry of every kind a relation in the vocabulary joins, by kind name."""
    return {
        EntryKind.CHARACTER: entries.create(EntryKind.CHARACTER, "Mira").id,
        EntryKind.PLACE: entries.create(EntryKind.PLACE, "The Harbour").id,
        EntryKind.ITEM: entries.create(EntryKind.ITEM, "The Ledger").id,
        EntryKind.FACTION: entries.create(EntryKind.FACTION, "The Guild").id,
        EntryKind.EVENT: entries.create(EntryKind.EVENT, "The Fire").id,
        EntryKind.THREAD: entries.create(EntryKind.THREAD, "Who set it").id,
        EntryKind.FACT: entries.create(
            EntryKind.FACT, "Iron does not float", attributes={"statement": "Iron does not float."}
        ).id,
    }


# -- the vocabulary ------------------------------------------------------------------------------


def test_every_relation_in_the_vocabulary_can_actually_be_built(
    links: LinkStore, entries: EntryStore, cast: dict[str, str]
) -> None:
    """A relation nobody can build is a relation nobody has checked (D26).

    One link per relation, using the first kind each declares on each side - so a definition that
    names a kind it may not join fails here rather than in a form months later.
    """
    for definition in RELATIONS:
        from_kind, to_kind = definition.from_kinds[0], definition.to_kinds[0]
        # `precedes` and any other same-kind relation needs a second entry of that kind.
        target = (
            entries.create(to_kind, f"A second {to_kind} for {definition.relation}").id
            if from_kind == to_kind
            else cast[to_kind]
        )
        link = links.create(cast[from_kind], definition.relation, target)
        assert link.relation == definition.relation
        assert link.id.startswith("lnk_")


def test_a_relation_outside_the_vocabulary_is_refused_and_writes_nothing(
    links: LinkStore, cast: dict[str, str]
) -> None:
    with pytest.raises(InvalidAttributesError) as raised:
        links.create(cast[EntryKind.CHARACTER], "haunts", cast[EntryKind.PLACE])
    assert raised.value.field == "relation"
    assert links.list() == []


def test_a_relation_is_refused_between_kinds_it_does_not_join(
    links: LinkStore, cast: dict[str, str]
) -> None:
    """Step 5 of the acceptance run: a place cannot know an item."""
    with pytest.raises(InvalidAttributesError) as raised:
        links.create(cast[EntryKind.PLACE], "knows", cast[EntryKind.ITEM])
    assert raised.value.field == "relation"
    assert links.list() == []


def test_an_asymmetric_relation_is_refused_backwards_rather_than_reversed(
    links: LinkStore, cast: dict[str, str]
) -> None:
    """``member_of`` runs character to faction. Faction to character is a different statement."""
    with pytest.raises(InvalidAttributesError):
        links.create(cast[EntryKind.FACTION], "member_of", cast[EntryKind.CHARACTER])
    assert links.list() == []


def test_an_endpoint_that_does_not_exist_is_refused(links: LinkStore, cast: dict[str, str]) -> None:
    with pytest.raises(EntryNotFoundError):
        links.create(cast[EntryKind.CHARACTER], "member_of", "ent_nothing")
    assert links.list() == []


def test_an_endpoint_that_is_deleted_is_refused(
    links: LinkStore, entries: EntryStore, cast: dict[str, str]
) -> None:
    entries.delete(cast[EntryKind.FACTION])
    with pytest.raises(EntryNotFoundError):
        links.create(cast[EntryKind.CHARACTER], "member_of", cast[EntryKind.FACTION])
    assert links.list() == []


def test_an_entry_cannot_be_linked_to_itself(links: LinkStore, cast: dict[str, str]) -> None:
    """A self-link would make an entry its own dependent, which is not a relationship."""
    with pytest.raises(InvalidAttributesError) as raised:
        links.create(cast[EntryKind.CHARACTER], "knows", cast[EntryKind.CHARACTER])
    assert raised.value.field == "to_entry"
    assert links.list() == []


def test_a_duplicate_live_link_is_refused_and_names_the_one_that_exists(
    links: LinkStore, cast: dict[str, str]
) -> None:
    first = links.create(cast[EntryKind.CHARACTER], "member_of", cast[EntryKind.FACTION])
    with pytest.raises(DuplicateLinkError) as raised:
        links.create(cast[EntryKind.CHARACTER], "member_of", cast[EntryKind.FACTION])
    assert raised.value.link_id == first.id
    assert len(links.list()) == 1


def test_a_symmetric_relation_refuses_the_same_pair_in_either_order(
    links: LinkStore, entries: EntryStore, cast: dict[str, str]
) -> None:
    other = entries.create(EntryKind.CHARACTER, "Elias").id
    links.create(cast[EntryKind.CHARACTER], "knows", other)
    with pytest.raises(DuplicateLinkError):
        links.create(other, "knows", cast[EntryKind.CHARACTER])
    assert len(links.list()) == 1


def test_a_deleted_link_does_not_block_saying_it_again(
    links: LinkStore, cast: dict[str, str]
) -> None:
    first = links.create(cast[EntryKind.CHARACTER], "member_of", cast[EntryKind.FACTION])
    links.delete(first.id)
    again = links.create(cast[EntryKind.CHARACTER], "member_of", cast[EntryKind.FACTION])
    assert again.id != first.id
    assert [link.id for link in links.list()] == [again.id]


# -- symmetry and direction ------------------------------------------------------------------------


def test_a_symmetric_relation_is_stored_once_and_read_from_both_ends(
    links: LinkStore, entries: EntryStore, cast: dict[str, str]
) -> None:
    """Ruling 7. One row; each end sees it once, and the label reads the same both ways."""
    mira = cast[EntryKind.CHARACTER]
    elias = entries.create(EntryKind.CHARACTER, "Elias").id
    link = links.create(mira, "knows", elias)

    from_mira = links.for_entry(mira)
    from_elias = links.for_entry(elias)
    assert [view.link.id for view in from_mira] == [link.id]
    assert [view.link.id for view in from_elias] == [link.id]
    assert from_mira[0].end == LinkEnd.FROM
    assert from_elias[0].end == LinkEnd.TO
    assert from_mira[0].other_id == elias
    assert from_elias[0].other_id == mira
    assert from_mira[0].label == from_elias[0].label == relation_for("knows").label


def test_an_asymmetric_link_reads_differently_from_each_end(
    links: LinkStore, cast: dict[str, str]
) -> None:
    definition = relation_for("member_of")
    links.create(cast[EntryKind.CHARACTER], "member_of", cast[EntryKind.FACTION])

    character_view = links.for_entry(cast[EntryKind.CHARACTER])[0]
    faction_view = links.for_entry(cast[EntryKind.FACTION])[0]
    assert character_view.label == definition.label
    assert faction_view.label == definition.inverse_label
    assert character_view.other_name == "The Guild"
    assert faction_view.other_name == "Mira"
    assert faction_view.other_kind == EntryKind.CHARACTER


def test_for_entry_returns_both_directions_in_one_answer(
    links: LinkStore, entries: EntryStore, cast: dict[str, str]
) -> None:
    mira = cast[EntryKind.CHARACTER]
    elias = entries.create(EntryKind.CHARACTER, "Elias").id
    links.create(mira, "member_of", cast[EntryKind.FACTION])
    links.create(mira, "knows", elias)
    links.create(cast[EntryKind.FACT], "concerns", mira)

    views = links.for_entry(mira)
    assert len(views) == 3
    assert {view.end for view in views} == {LinkEnd.FROM, LinkEnd.TO}
    assert [view.link.relation for view in views] == ["concerns", "knows", "member_of"]


def test_for_entry_is_empty_rather_than_an_error_for_an_entry_that_is_not_there(
    links: LinkStore,
) -> None:
    assert links.for_entry("ent_nothing") == []


# -- bounds and attributes ---------------------------------------------------------------------


def test_bounds_are_stored_and_never_interpreted(links: LinkStore, cast: dict[str, str]) -> None:
    link = links.create(
        cast[EntryKind.CHARACTER],
        "member_of",
        cast[EntryKind.FACTION],
        since="the spring after the fire",
        until="Midwinter, 1204",
    )
    assert link.since == "the spring after the fire"
    assert link.until == "Midwinter, 1204"
    assert links.get(link.id).since == link.since


def test_an_oversized_bound_is_refused_with_nothing_written(
    links: LinkStore, cast: dict[str, str]
) -> None:
    with pytest.raises(ValueError):
        links.create(
            cast[EntryKind.CHARACTER],
            "member_of",
            cast[EntryKind.FACTION],
            since="x" * (MAX_STORY_TIME_CHARS + 1),
        )
    assert links.list() == []


def test_update_changes_the_bounds_and_leaves_everything_else(
    links: LinkStore, cast: dict[str, str]
) -> None:
    link = links.create(
        cast[EntryKind.CHARACTER], "member_of", cast[EntryKind.FACTION], since="early"
    )
    changed = links.update(link.id, since="later", until="until the end")

    assert changed.since == "later"
    assert changed.until == "until the end"
    assert changed.from_entry == link.from_entry
    assert changed.to_entry == link.to_entry
    assert changed.relation == link.relation


def test_a_bound_not_presented_is_not_blanked(links: LinkStore, cast: dict[str, str]) -> None:
    link = links.create(
        cast[EntryKind.CHARACTER], "member_of", cast[EntryKind.FACTION], since="early"
    )
    assert links.update(link.id, until="late").since == "early"


def test_a_bound_presented_as_none_is_cleared(links: LinkStore, cast: dict[str, str]) -> None:
    link = links.create(
        cast[EntryKind.CHARACTER], "member_of", cast[EntryKind.FACTION], since="early"
    )
    assert links.update(link.id, since=None).since is None


def test_attributes_must_be_an_object(links: LinkStore, cast: dict[str, str]) -> None:
    with pytest.raises(InvalidAttributesError):
        links.create(
            cast[EntryKind.CHARACTER],
            "member_of",
            cast[EntryKind.FACTION],
            attributes=["not", "an", "object"],  # type: ignore[arg-type]
        )
    assert links.list() == []


# -- soft delete and restore (D25) ---------------------------------------------------------------


def test_delete_hides_a_link_from_every_read_and_restore_brings_it_back(
    links: LinkStore, cast: dict[str, str]
) -> None:
    link = links.create(cast[EntryKind.CHARACTER], "member_of", cast[EntryKind.FACTION])

    deleted = links.delete(link.id)
    assert deleted.deleted_at is not None
    assert links.list() == []
    assert links.for_entry(cast[EntryKind.CHARACTER]) == []
    assert links.counts_by_relation() == {}
    with pytest.raises(LinkNotFoundError):
        links.get(link.id)
    assert links.get(link.id, include_deleted=True).id == link.id

    restored = links.restore(link.id)
    assert restored.deleted_at is None
    assert [view.link.id for view in links.for_entry(cast[EntryKind.CHARACTER])] == [link.id]


def test_deleting_a_link_twice_is_refused_rather_than_silently_repeated(
    links: LinkStore, cast: dict[str, str]
) -> None:
    link = links.create(cast[EntryKind.CHARACTER], "member_of", cast[EntryKind.FACTION])
    links.delete(link.id)
    with pytest.raises(LinkNotFoundError):
        links.delete(link.id)


def test_restoring_a_live_link_is_a_no_op(links: LinkStore, cast: dict[str, str]) -> None:
    link = links.create(cast[EntryKind.CHARACTER], "member_of", cast[EntryKind.FACTION])
    assert links.restore(link.id).updated_at == link.updated_at


def test_a_restore_that_would_duplicate_a_live_link_is_refused(
    links: LinkStore, cast: dict[str, str]
) -> None:
    """Delete, type it again, undo the delete - two identical rows would double-count."""
    first = links.create(cast[EntryKind.CHARACTER], "member_of", cast[EntryKind.FACTION])
    links.delete(first.id)
    links.create(cast[EntryKind.CHARACTER], "member_of", cast[EntryKind.FACTION])

    with pytest.raises(DuplicateLinkError):
        links.restore(first.id)
    assert len(links.list()) == 1


# -- the three-way live predicate (ruling 9) ------------------------------------------------------


def test_a_deleted_entry_is_absent_from_every_link_read_path_together(
    links: LinkStore, entries: EntryStore, cast: dict[str, str]
) -> None:
    """Ruling 9, asserted across every read at once - the Phase 2 lesson, one table wider.

    ``for_entry`` from both ends, the project list, ``edges``, the counts, and D27's dependent
    computation. One of them forgetting a leg is a wrong chart two phases from now.
    """
    mira = cast[EntryKind.CHARACTER]
    guild = cast[EntryKind.FACTION]
    fire = cast[EntryKind.EVENT]
    second_fire = entries.create(EntryKind.EVENT, "The second fire").id
    links.create(mira, "member_of", guild)
    links.create(fire, "precedes", second_fire)
    links.create(mira, "participates_in", fire)

    entries.delete(guild)

    assert [view.link.relation for view in links.for_entry(mira)] == ["participates_in"], (
        "the link into the deleted faction goes, and the live one stays"
    )
    assert links.for_entry(guild) == [], "a deleted entry has no links at all"
    assert [link.relation for link in links.list()] == ["participates_in", "precedes"]
    assert links.counts_by_relation() == {"precedes": 1, "participates_in": 1}
    assert entries.dependents(mira) == [fire], "a deleted neighbour is not a dependent"
    assert entries.dependents(guild) == []

    # And P3-8's ordering, which reads its edges through the same predicate.
    entries.delete(second_fire)
    assert links.edges("precedes") == []
    events = events_from_entries(entries.list(kind=EntryKind.EVENT, limit=None))
    ordering = order_events(events, links.edges("precedes"))
    assert second_fire not in ordering.order
    assert second_fire not in ordering.unplaced


def test_restoring_an_entry_brings_back_exactly_the_links_it_had(
    links: LinkStore, entries: EntryStore, cast: dict[str, str]
) -> None:
    """Nothing cascades, which is what makes a restore exact (D25).

    The link deleted in its own right stays deleted, because its own ``deleted_at`` was never
    touched by the entry's.
    """
    mira = cast[EntryKind.CHARACTER]
    kept = links.create(mira, "member_of", cast[EntryKind.FACTION])
    dropped = links.create(mira, "owns", cast[EntryKind.ITEM])
    links.delete(dropped.id)

    entries.delete(mira)
    assert links.for_entry(mira) == []

    entries.restore(mira)
    assert [view.link.id for view in links.for_entry(mira)] == [kept.id]
    assert links.get(dropped.id, include_deleted=True).deleted_at is not None


def test_a_link_into_a_deleted_entry_cannot_be_read_or_restored_by_id(
    links: LinkStore, entries: EntryStore, cast: dict[str, str]
) -> None:
    """``include_deleted`` relaxes the link's own row, never an endpoint's.

    A link whose endpoint is away is restored by restoring the entry, which is the one act that
    can make it meaningful again.
    """
    link = links.create(cast[EntryKind.CHARACTER], "member_of", cast[EntryKind.FACTION])
    entries.delete(cast[EntryKind.FACTION])

    with pytest.raises(LinkNotFoundError):
        links.get(link.id)
    with pytest.raises(LinkNotFoundError):
        links.get(link.id, include_deleted=True)


# -- what the timeline reads ---------------------------------------------------------------------


def test_edges_returns_live_precedes_pairs_and_refuses_an_unknown_relation(
    links: LinkStore, entries: EntryStore
) -> None:
    first = entries.create(EntryKind.EVENT, "The fire").id
    second = entries.create(EntryKind.EVENT, "The inquest").id
    links.create(first, "precedes", second)

    assert links.edges("precedes") == [(first, second)]
    assert links.edges("knows") == []
    with pytest.raises(InvalidAttributesError):
        links.edges("happens_during")
