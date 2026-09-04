"""P3-8 - story-time ordering: the corpus, the contradictions, and the invariant (D28, D9).

The corpus (``fixtures/bible/storytime/cases.json``) is written from ``specs/bible.md`` section 7,
not recorded from :mod:`archetype.bible.storytime` - the P2-8 discipline, which is the only thing
that makes a corpus evidence rather than a transcript.

Two properties are asserted **once over every case** rather than per case, so a case added later is
covered without anyone remembering (the P2-8 rule):

* every returned order respects every edge that is not inside a reported cycle;
* every event lands in exactly one of ``order`` and ``unplaced`` - nothing is dropped, and nothing
  is counted twice.
"""

from __future__ import annotations

from typing import Any

import pytest

from archetype.bible.storytime import (
    ContradictionKind,
    Ordering,
    StoryEvent,
    era_ranks,
    events_from_entries,
    order_events,
    story_event,
)

from .conftest import load_storytime_cases

CASES = load_storytime_cases()
CASE_IDS = [case["name"] for case in CASES]

#: The cases that say something about eras. Filtered rather than skipped, so a run reports what
#: it covered instead of a column of skips nobody reads.
ERA_CASES = [case for case in CASES if "eras" in case]
ERA_CASE_IDS = [case["name"] for case in ERA_CASES]


def build(case: dict[str, Any]) -> tuple[list[StoryEvent], list[tuple[str, str]]]:
    """One case's input, in the shape the module takes."""
    events = [
        StoryEvent(
            id=event["id"],
            name=event.get("name", ""),
            label=event.get("label", ""),
            sort_key=event.get("sort_key"),
            era=event.get("era"),
        )
        for event in case["events"]
    ]
    return events, [(edge[0], edge[1]) for edge in case["edges"]]


def stated(contradictions: list[dict[str, Any]]) -> set[tuple[str, frozenset[str]]]:
    """A case's contradictions as a comparable set.

    Membership rather than sequence: which member a cycle is listed from is an implementation
    detail, while *which events are in it* is the answer.
    """
    return {(item["kind"], frozenset(item["events"])) for item in contradictions}


def reported(ordering: Ordering) -> set[tuple[str, frozenset[str]]]:
    return {(item.kind, frozenset(item.events)) for item in ordering.contradictions}


def cycle_members(ordering: Ordering) -> set[str]:
    """Every event inside a reported cycle - the only events an order may disagree about."""
    return {
        event
        for item in ordering.contradictions
        if item.kind == ContradictionKind.CYCLE
        for event in item.events
    }


# -- the corpus ---------------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_the_corpus_orders_exactly_as_the_specification_says(case: dict[str, Any]) -> None:
    events, edges = build(case)
    ordering = order_events(events, edges)

    assert list(ordering.order) == case["order"], case["why"]
    assert sorted(ordering.unplaced) == sorted(case["unplaced"]), case["why"]
    assert reported(ordering) == stated(case["contradictions"]), case["why"]


@pytest.mark.parametrize("case", ERA_CASES, ids=ERA_CASE_IDS)
def test_the_corpus_ranks_eras_as_the_specification_says(case: dict[str, Any]) -> None:
    events, _ = build(case)
    assert era_ranks(events) == case["eras"], case["why"]


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_two_runs_never_disagree(case: dict[str, Any]) -> None:
    """The stable fallback, asserted rather than assumed - a set iteration order would break it."""
    events, edges = build(case)
    assert order_events(events, edges) == order_events(events, edges)


# -- the properties, over every case at once ------------------------------------------------------


def test_every_order_respects_every_edge_outside_a_cycle() -> None:
    """The invariant ``specs/bible.md`` section 7 states, over the whole corpus.

    A cycle's own edges are the only ones a returned order may violate - they cannot all be
    satisfied, which is what makes them a cycle.
    """
    for case in CASES:
        events, edges = build(case)
        ordering = order_events(events, edges)
        position = {event_id: index for index, event_id in enumerate(ordering.order)}
        looping = cycle_members(ordering)
        known = {event.id for event in events}
        for tail, head in edges:
            if tail not in known or head not in known or tail in looping and head in looping:
                continue
            assert position[tail] < position[head], (
                f"{case['name']}: {tail} precedes {head}, and the order disagrees"
            )


def test_every_event_is_either_ordered_or_unplaced_and_never_both() -> None:
    """Nothing is dropped and nothing is invented, over every case at once (D9)."""
    for case in CASES:
        events, edges = build(case)
        ordering = order_events(events, edges)
        ids = [event.id for event in events]
        assert sorted([*ordering.order, *ordering.unplaced]) == sorted(ids), case["name"]
        assert not set(ordering.order) & set(ordering.unplaced), case["name"]


def test_no_contradiction_has_a_kind_the_vocabulary_does_not_declare() -> None:
    """Exactly two kinds and no others (D28), asserted over everything the corpus produces."""
    for case in CASES:
        events, edges = build(case)
        for item in order_events(events, edges).contradictions:
            assert item.kind in ContradictionKind.ALL
            assert item.detail, "a contradiction nobody can read is a contradiction nobody fixes"


# -- reading an event out of an entry's attributes ------------------------------------------------


def test_story_event_reads_the_three_parts_and_nothing_else() -> None:
    event = story_event(
        "ent_x",
        "The flood",
        {"story_time": {"label": "the third night", "sort_key": 3, "era": "Before"}},
    )
    assert event == StoryEvent(
        id="ent_x", name="The flood", label="the third night", sort_key=3.0, era="Before"
    )


def test_an_event_with_no_story_time_attribute_carries_no_placement() -> None:
    for attributes in ({}, None, {"event_type": "scene"}, {"story_time": {}}):
        event = story_event("ent_x", "Unplaced", attributes)
        assert event.sort_key is None
        assert event.label == ""
        assert event.era is None


def test_events_from_entries_takes_anything_with_an_id_a_name_and_attributes(entries) -> None:
    """The adapter is structural on purpose: the pure module must not import the store."""
    first = entries.create("event", "The fire", attributes={"story_time": {"sort_key": 1}})
    second = entries.create("event", "The inquest", attributes={"story_time": {"sort_key": 2}})

    events = events_from_entries([first, second])
    assert [event.id for event in events] == [first.id, second.id]
    assert order_events(events, []).order == (first.id, second.id)


# -- the edges of the module, beyond the corpus ---------------------------------------------------


def test_a_thousand_events_in_a_chain_do_not_exhaust_the_stack() -> None:
    """The cycle finder is iterative for this reason: a manuscript may be one long sequence."""
    events = [StoryEvent(id=f"e{index}") for index in range(1000)]
    edges = [(f"e{index}", f"e{index + 1}") for index in range(999)]

    ordering = order_events(events, edges)
    assert list(ordering.order) == [event.id for event in events]
    assert ordering.contradictions == ()


def test_a_cycle_of_a_thousand_events_is_one_contradiction_and_still_ordered() -> None:
    events = [StoryEvent(id=f"e{index}") for index in range(1000)]
    edges = [(f"e{index}", f"e{(index + 1) % 1000}") for index in range(1000)]

    ordering = order_events(events, edges)
    assert len(ordering.contradictions) == 1
    assert ordering.contradictions[0].kind == ContradictionKind.CYCLE
    assert len(ordering.contradictions[0].events) == 1000
    assert sorted(ordering.order) == sorted(event.id for event in events)


def test_an_era_ranks_by_its_least_key_however_the_events_arrive() -> None:
    events = [
        StoryEvent(id="a", sort_key=40, era="Before"),
        StoryEvent(id="b", sort_key=5, era="Before"),
        StoryEvent(id="c", era="Myth"),
    ]
    assert era_ranks(events) == {"Before": 5, "Myth": None}
    assert era_ranks(list(reversed(events))) == {"Before": 5, "Myth": None}
