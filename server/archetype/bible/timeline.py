"""The database half of story-time: two reads and one pure call (P3-10, D28).

:mod:`archetype.bible.storytime` is pure and stays pure - it takes events and edges and returns
the order, the unplaced, and the contradictions. Something has to read those events and those
edges out of a project, and it is not a route: a route carries no domain logic (api-contract
section 1), and Phase 6's agent and Phase 8's timeline must get the same answer without going
through HTTP.

So this module is exactly the join, and nothing else. It holds no rule about ordering; every rule
is in ``storytime.py`` and stated in ``specs/bible.md`` section 7.

Two decisions it makes, both deliberate:

* The events are read with **no limit**. ``SEARCH_LIMIT`` caps the ``q`` filter, and a timeline
  that silently stopped at two hundred events would report a *wrong* order rather than a slow one
  (phase-3 plan section 7, ``B3``).
* The edges come from ``LinkStore.edges("precedes")``, which applies the three-way live predicate,
  so an edge to a deleted event is not a constraint anybody typed against this graph.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..projects.store import ProjectHandle
from .entries import EntryStore
from .links import LinkStore
from .schema import PRECEDES, EntryKind
from .storytime import Ordering, StoryEvent, era_ranks, events_from_entries, order_events

__all__ = ["ProjectTimeline", "project_timeline"]


@dataclass(frozen=True, slots=True)
class ProjectTimeline:
    """One project's events, ordered, with the era ranking beside the ordering.

    ``ordering`` is :class:`~archetype.bible.storytime.Ordering` unwidened - three answers and
    never a fourth (``B5``). ``events`` is every event in the project, in the order they were
    read, so a caller can put a name to an id without a second query; ``eras`` is the separate
    answer :func:`~archetype.bible.storytime.era_ranks` gives.
    """

    events: tuple[StoryEvent, ...]
    ordering: Ordering
    eras: dict[str, float | None]


def project_timeline(handle: ProjectHandle) -> ProjectTimeline:
    """Order one project's events. Two reads, one pure call, no rules of its own."""
    entries = EntryStore(handle).list(kind=EntryKind.EVENT, limit=None)
    events = tuple(events_from_entries(entries))
    edges = LinkStore(handle).edges(PRECEDES)
    return ProjectTimeline(
        events=events,
        ordering=order_events(events, edges),
        eras=era_ranks(events),
    )
