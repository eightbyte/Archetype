"""The live predicates for entries and links - written once (P3-3, D25, plan section 2, ruling 9).

D25 made deleting a bible entry a soft delete, exactly as D22 made deleting a chapter one. That
buys back the recovery path and costs one predicate, which is cheap **only if there is one of
it**. This module is that one place.

Two predicates, and the second is the one that bites:

``LIVE_ENTRY``
    An entry is live when ``deleted_at IS NULL``. That is the whole of it.

``live_link(...)``
    A link is live when **the link is not deleted and neither endpoint is deleted**. Three
    conditions, always all three.

The three-way one is the Phase 2 lesson one table wider. Forgetting a leg puts a soft-deleted
character back into a relationship view and, in Phase 8, into the interaction matrix - where it
surfaces as a wrong chart and is reported as a Phase 8 bug, two phases away from the query that
caused it. So the SQL is built here and spliced in, rather than typed out per query, and one test
asserts absence from every read path together.

Neither predicate is a filter a caller may opt out of casually. ``include_deleted`` exists on the
entry reads because the restore surface needs it and for no other reason.
"""

from __future__ import annotations

from typing import Final

__all__ = [
    "LIVE_ENTRY",
    "LIVE_LINK",
    "live_link",
]

#: An entry is live when this holds. Qualify it with the table alias when a query joins.
LIVE_ENTRY: Final[str] = "deleted_at IS NULL"

#: The three-way predicate over the default table names, for a query that joins ``entry_link`` to
#: ``entry`` twice under the aliases ``from_e`` and ``to_e``.
LIVE_LINK: Final[str] = (
    "entry_link.deleted_at IS NULL AND from_e.deleted_at IS NULL AND to_e.deleted_at IS NULL"
)


def live_link(*, link: str = "entry_link", from_entry: str, to_entry: str) -> str:
    """The three-way live-link predicate over the given aliases.

    Args:
        link: The alias the ``entry_link`` row is reachable as.
        from_entry: The alias the ``from_entry`` end's ``entry`` row is reachable as.
        to_entry: The alias the ``to_entry`` end's ``entry`` row is reachable as.

    Returns:
        A SQL boolean expression. Every argument is an identifier this package chooses, never
        user input - the aliases in a query are written by the query's author.
    """
    return (
        f"{link}.deleted_at IS NULL "
        f"AND {from_entry}.deleted_at IS NULL "
        f"AND {to_entry}.deleted_at IS NULL"
    )
