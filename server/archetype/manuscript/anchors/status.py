"""The anchor status vocabulary, and the one rule that derives it (P2-1, D21, D22).

An anchor has three statuses on the wire and **two** in storage:

``ok``
    The anchor's quote was found, unambiguously, in the document as it now is.
``stale``
    It was not. The positions are left where they were and a suggestion may be offered, but
    nothing is ever repointed on the anchor's behalf (phase-2-plan section 2, ruling 2).
``orphaned``
    The document the anchor lives in is soft-deleted (D22). Nothing is wrong with the anchor;
    the chapter is simply away.

``anchor.status`` stores the **text-match** answer only - ``ok`` or ``stale``. ``orphaned`` is
derived here, on every read, from the owning document's ``deleted_at``.

That split is what makes deleting and restoring a chapter cheap and exactly correct. A soft
delete changes no manuscript text, so an anchor's cached text answer is as true while its
chapter is away as it was before it went; restoring the chapter therefore needs no re-resolution
and cannot invent a status the resolver never produced. Writing ``orphaned`` into the row would
destroy the answer the resolver gave, leaving restore with nothing honest to write back
(phase-2-plan section 7).

The resolver (P2-6) produces the stored half. This module owns the derived half, and both the
Python and the SQL form of the rule live here so the two cannot drift.
"""

from __future__ import annotations

from typing import Final

__all__ = [
    "ALL_STATUSES",
    "EFFECTIVE_STATUS_SQL",
    "STORED_STATUSES",
    "AnchorStatus",
    "effective_status",
]


class AnchorStatus:
    """The status vocabulary. ``ORPHANED`` is derived, never stored."""

    OK: Final[str] = "ok"
    STALE: Final[str] = "stale"
    ORPHANED: Final[str] = "orphaned"


#: What ``anchor.status`` may hold. A row carrying anything else is a bug in the resolver.
STORED_STATUSES: Final[frozenset[str]] = frozenset({AnchorStatus.OK, AnchorStatus.STALE})

#: What a reader may see, including the derived one.
ALL_STATUSES: Final[frozenset[str]] = STORED_STATUSES | {AnchorStatus.ORPHANED}

#: The same rule as SQL, for queries that read anchors joined to their document.
#:
#: Expects the two tables to be reachable as ``anchor`` and ``document`` - either by their own
#: names or by an alias. Selected as ``status`` so a row reads the derived answer under the
#: column name the caller expects, and the stored one is not silently returned in its place.
EFFECTIVE_STATUS_SQL: Final[str] = (
    "CASE WHEN document.deleted_at IS NULL THEN anchor.status ELSE 'orphaned' END"
)


def effective_status(stored_status: str, document_deleted_at: str | None) -> str:
    """The status a reader sees, given the stored one and the document's ``deleted_at``.

    Args:
        stored_status: ``anchor.status`` as written by the resolver.
        document_deleted_at: The owning document's ``deleted_at``; ``None`` when it is live.

    Raises:
        ValueError: If ``stored_status`` is not one of :data:`STORED_STATUSES`. A stored
            ``orphaned`` is the specific mistake this guards against - it means something wrote
            the derived answer back into the row.
    """
    if stored_status not in STORED_STATUSES:
        raise ValueError(
            f"anchor.status holds {stored_status!r}; only {sorted(STORED_STATUSES)} are stored "
            "("
            f"{AnchorStatus.ORPHANED!r} is derived from the document's deleted_at, never written"
            ")"
        )
    return AnchorStatus.ORPHANED if document_deleted_at is not None else stored_status
