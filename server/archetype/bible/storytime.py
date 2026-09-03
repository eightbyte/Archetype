"""Story-time ordering - D28's partial order, made concrete (P3-8, D9).

**Pure**, in the sense :mod:`archetype.manuscript.projection` and
:mod:`archetype.manuscript.anchors.resolve` are: ``(events, precedes-edges) -> ordering``, no
database, no I/O, no clock. Phase 6's agent and Phase 8's timeline therefore get identical answers
without going through HTTP, and the corpus that proves it is JSON
(``tests/fixtures/bible/storytime/cases.json``), hand-written from ``specs/bible.md`` section 7
rather than recorded from this code.

Two things carry story-time information and **neither is a date**: an event's ``story_time``
attribute (a ``label`` a person reads, an optional numeric ``sort_key``, an optional ``era``) and
``precedes`` links between events. No calendar is ever parsed and none is ever required - a
secondary-world calendar does not parse, and requiring one would make story-time unusable for
exactly the manuscripts this product exists for.

What comes back
---------------

:func:`order_events` returns exactly three things and never more:

* **the order** - the events an edge or a key places, topologically sorted;
* **the unplaced** - D9's tray: an event with neither an incident edge nor a ``sort_key``. A
  ``label`` alone does not place it, because a label is for reading and never sorts;
* **the contradictions** - of which there are exactly **two kinds and no others**: a cycle in
  ``precedes``, and an edge ``A precedes B`` where both ends carry a ``sort_key`` and A's is the
  greater.

The tiebreak, from ``specs/bible.md`` section 7, in this order: an edge always wins; among events
the edges leave unordered the smaller ``sort_key`` comes first; an event with no key comes after
every event that has one; and the final fallback is the order the events were given in.

**It never invents an order.** An event it cannot place is reported as unplaced - not appended,
not dropped, not sorted by name. And a contradiction never costs the rest of the graph: a cycle is
reported *and* everything outside it is still ordered, because a timeline that refuses to draw
anything because two events disagree is a timeline nobody can use to find the disagreement.

Eras are a display grouping, not a stored entity, and :func:`era_ranks` is a separate answer for
that reason: they rank by the least ``sort_key`` among their members, an era whose members carry
no key has no rank, and that is not a contradiction.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Protocol

__all__ = [
    "STORY_TIME_FIELD",
    "ContradictionKind",
    "Ordering",
    "StoryEvent",
    "StoryTimeContradiction",
    "era_ranks",
    "events_from_entries",
    "order_events",
    "story_event",
]

#: The attribute an ``event`` carries its placement in. Declared in ``bible/schema.py``; named
#: here because this module reads it out of an attribute map and nothing else does.
STORY_TIME_FIELD: Final[str] = "story_time"


class ContradictionKind:
    """The two kinds, and there are no others (D28)."""

    #: A loop in ``precedes``: the events say they come before each other.
    CYCLE: Final[str] = "cycle"
    #: An edge ``A precedes B`` where both carry a ``sort_key`` and A's is the greater.
    SORT_KEY_INVERSION: Final[str] = "sort_key_inversion"

    ALL: Final[frozenset[str]] = frozenset({"cycle", "sort_key_inversion"})


@dataclass(frozen=True, slots=True)
class StoryEvent:
    """One event, as the ordering sees it. Everything but the id is optional."""

    id: str
    name: str = ""
    #: What a person reads as "when". Free text, and it **never sorts**.
    label: str = ""
    #: The only number in story-time. A float on purpose, so an event can be inserted between two
    #: others without renumbering (``specs/bible.md`` section 11).
    sort_key: float | None = None
    era: str | None = None


@dataclass(frozen=True, slots=True)
class StoryTimeContradiction:
    """Something the writer said that cannot all be true at once."""

    kind: str
    #: The events involved: a cycle's members in the order they close, or an inversion's two ends.
    events: tuple[str, ...]
    #: One sentence naming what disagrees, for a client that shows it beside the timeline.
    detail: str


@dataclass(frozen=True, slots=True)
class Ordering:
    """The three answers, and never a fourth."""

    order: tuple[str, ...]
    unplaced: tuple[str, ...]
    contradictions: tuple[StoryTimeContradiction, ...]


class EventLike(Protocol):
    """What :func:`events_from_entries` needs of an entry: an id, a name, and its attributes.

    A structural type rather than an import of :class:`~archetype.bible.entries.Entry`, so that
    this module stays free of the store - and of ``sqlite3`` with it. ``Entry`` satisfies it, and
    so does anything a test hands over.
    """

    @property
    def id(self) -> str: ...

    @property
    def name(self) -> str: ...

    @property
    def attributes(self) -> dict[str, Any]: ...


def story_event(entry_id: str, name: str, attributes: Mapping[str, Any] | None) -> StoryEvent:
    """One event's placement, read out of its validated ``attributes`` map.

    Trusting rather than re-validating: the map came through ``bible/schema.py``'s ``validate``,
    which has already refused anything that is not a string label, a number, and a string era. A
    second validator here would be a second opinion about the same six field types.
    """
    story_time = (attributes or {}).get(STORY_TIME_FIELD) or {}
    if not isinstance(story_time, Mapping):
        story_time = {}
    sort_key = story_time.get("sort_key")
    return StoryEvent(
        id=entry_id,
        name=name,
        label=str(story_time.get("label") or ""),
        sort_key=None if sort_key is None else float(sort_key),
        era=story_time.get("era") or None,
    )


def events_from_entries(entries: Iterable[EventLike]) -> list[StoryEvent]:
    """Every entry's placement, in the order given. The database half of a timeline is one call."""
    return [story_event(entry.id, entry.name, entry.attributes) for entry in entries]


def order_events(events: Sequence[StoryEvent], edges: Iterable[tuple[str, str]]) -> Ordering:
    """Order what can be ordered, list what cannot, and report what disagrees.

    Args:
        events: The project's events. Their order here is the final tiebreak, so a caller that
            wants a stable answer passes a stable list - which every store read already is.
        edges: ``precedes`` links as ``(from, to)`` pairs, meaning *from* comes before *to*. An
            edge naming an event that is not in ``events`` is ignored: the caller's live
            predicate has already decided which events exist, and an edge to a deleted event is
            not a constraint anybody typed against this graph.

    Returns:
        The three answers of :class:`Ordering`. Every event appears in exactly one of ``order``
        and ``unplaced``, always.
    """
    index = {event.id: position for position, event in enumerate(events)}
    by_id = {event.id: event for event in events}

    # Deduplicated, because two identical links are one constraint; a self-edge is kept, because
    # an event that precedes itself is a cycle and refusing to see it would hide a contradiction.
    kept: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for tail, head in edges:
        if tail not in by_id or head not in by_id or (tail, head) in seen:
            continue
        seen.add((tail, head))
        kept.append((tail, head))

    # Placed by an edge or by a key; a label alone places nothing, because a label is for
    # reading (specs/bible.md section 7). Every event lands in exactly one of the two lists.
    incident = {event_id for pair in kept for event_id in pair}
    placed = [event for event in events if event.id in incident or event.sort_key is not None]
    placed_ids = {event.id for event in placed}
    unplaced = tuple(event.id for event in events if event.id not in placed_ids)

    contradictions: list[StoryTimeContradiction] = []
    contradictions.extend(_inversions(kept, by_id))

    components = _components(placed, kept)
    for members in components:
        if len(members) > 1 or (members[0], members[0]) in seen:
            contradictions.append(
                StoryTimeContradiction(
                    kind=ContradictionKind.CYCLE,
                    events=tuple(members),
                    detail=_cycle_detail(members, by_id),
                )
            )

    order = _order_condensation(components, kept, by_id, index)
    return Ordering(order=order, unplaced=unplaced, contradictions=tuple(contradictions))


def era_ranks(events: Iterable[StoryEvent]) -> dict[str, float | None]:
    """Each era's rank: the **least** ``sort_key`` among its members, or ``None`` for no rank.

    An era is not a stored entity - it is a name on an event, exactly as a label is - so this is
    a grouping and not an ordering: two events in the same era are ordered by the same rules as
    any other two. An era whose members all lack a key has no rank, and **that is not a
    contradiction**; it is an era nobody has placed yet.
    """
    ranks: dict[str, float | None] = {}
    for event in events:
        if not event.era:
            continue
        if event.era not in ranks:
            ranks[event.era] = event.sort_key
        elif event.sort_key is not None:
            current = ranks[event.era]
            ranks[event.era] = event.sort_key if current is None else min(current, event.sort_key)
    return ranks


# -- internals ---------------------------------------------------------------------------------


def _priority(
    event_id: str, by_id: dict[str, StoryEvent], index: dict[str, int]
) -> tuple[int, float, int]:
    """The tiebreak, as a sort key: keyed events first by key, then everything else as given.

    ``specs/bible.md`` section 7, rules 2 to 4. Rule 1 - an edge always wins - is the topological
    sort itself, and is not expressible here.
    """
    event = by_id[event_id]
    if event.sort_key is None:
        return (1, 0.0, index[event_id])
    return (0, event.sort_key, index[event_id])


def _inversions(
    edges: Sequence[tuple[str, str]], by_id: dict[str, StoryEvent]
) -> list[StoryTimeContradiction]:
    """Edges whose two ``sort_key``s say the opposite of what the edge says.

    Reported, and then ignored: the edge still orders the pair, because a constraint a person
    typed outranks a number they typed (rule 1).
    """
    found: list[StoryTimeContradiction] = []
    for tail, head in edges:
        first, second = by_id[tail], by_id[head]
        if first.sort_key is None or second.sort_key is None:
            continue
        if first.sort_key > second.sort_key:
            found.append(
                StoryTimeContradiction(
                    kind=ContradictionKind.SORT_KEY_INVERSION,
                    events=(tail, head),
                    detail=(
                        f"{_name(first)} comes before {_name(second)}, but its sort key "
                        f"{_number(first.sort_key)} is the greater"
                    ),
                )
            )
    return found


def _components(placed: Sequence[StoryEvent], edges: Sequence[tuple[str, str]]) -> list[list[str]]:
    """The strongly connected components of the placed graph, in a deterministic order.

    Tarjan's algorithm, written iteratively so that a long chain of events cannot exhaust the
    Python stack - a manuscript is allowed to have a thousand events in a row.

    A component of more than one event **is** a cycle: every member reaches every other, so they
    all claim to come before each other. Condensing them is what lets the rest of the graph be
    ordered anyway (D28).
    """
    ids = [event.id for event in placed]
    members = set(ids)
    outgoing: dict[str, list[str]] = {event_id: [] for event_id in ids}
    for tail, head in edges:
        if tail in members and head in members:
            outgoing[tail].append(head)

    order_index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    counter = 0
    components: list[list[str]] = []

    for root in ids:
        if root in order_index:
            continue
        work: list[tuple[str, int]] = [(root, 0)]
        while work:
            node, next_child = work[-1]
            if next_child == 0:
                order_index[node] = low[node] = counter
                counter += 1
                stack.append(node)
                on_stack.add(node)
            children = outgoing[node]
            if next_child < len(children):
                work[-1] = (node, next_child + 1)
                child = children[next_child]
                if child not in order_index:
                    work.append((child, 0))
                elif child in on_stack:
                    low[node] = min(low[node], order_index[child])
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == order_index[node]:
                component: list[str] = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component.append(member)
                    if member == node:
                        break
                components.append(component)
    return components


def _order_condensation(
    components: Sequence[Sequence[str]],
    edges: Sequence[tuple[str, str]],
    by_id: dict[str, StoryEvent],
    index: dict[str, int],
) -> tuple[str, ...]:
    """Kahn's algorithm over the condensation, with the tiebreak deciding among the ready ones.

    Over components rather than events so that a cycle costs only its own members' relative
    order: everything outside it is still ordered, which is the half of D28 that makes a
    contradiction findable.
    """
    component_of = {
        event_id: number for number, members in enumerate(components) for event_id in members
    }
    successors: dict[int, set[int]] = {number: set() for number in range(len(components))}
    indegree = dict.fromkeys(range(len(components)), 0)
    for tail, head in edges:
        if tail not in component_of or head not in component_of:
            continue
        left, right = component_of[tail], component_of[head]
        if left == right or right in successors[left]:
            continue
        successors[left].add(right)
        indegree[right] += 1

    # A component's own members are ordered by the tiebreak, and its priority is its first
    # member's - so a cycle lands where its earliest event would have.
    ordered_members = [
        sorted(members, key=lambda event_id: _priority(event_id, by_id, index))
        for members in components
    ]
    priority = [
        _priority(members[0], by_id, index) if members else (1, 0.0, 0)
        for members in ordered_members
    ]

    ready = sorted(
        (number for number, degree in indegree.items() if degree == 0),
        key=lambda number: priority[number],
    )
    result: list[str] = []
    while ready:
        number = ready.pop(0)
        result.extend(ordered_members[number])
        for successor in sorted(successors[number], key=lambda other: priority[other]):
            indegree[successor] -= 1
            if indegree[successor] == 0:
                ready.append(successor)
        ready.sort(key=lambda other: priority[other])
    return tuple(result)


def _name(event: StoryEvent) -> str:
    return event.name or event.id


def _number(value: float) -> str:
    """A sort key as a person reads it: ``3`` rather than ``3.0`` when it is whole."""
    return str(int(value)) if float(value).is_integer() else str(value)


def _cycle_detail(members: Sequence[str], by_id: dict[str, StoryEvent]) -> str:
    if len(members) == 1:
        return f"{_name(by_id[members[0]])} is said to come before itself"
    names = ", ".join(_name(by_id[member]) for member in members)
    return f"these events are each said to come before the others: {names}"
