"""The stored anchor, and the one place a row becomes one (P2-7).

Its own module because two modules that must not import each other both need it:
:mod:`.rewrite` is what :class:`~archetype.manuscript.documents.DocumentStore` calls inside a
save's transaction, and :mod:`.store` is the repository that imports the document store back for
its errors. The record they pass sits under both.

``status`` on an :class:`Anchor` is the **effective** status - what a reader sees, with
``orphaned`` already derived from the owning document's ``deleted_at`` (D22). The stored column
holds only the text answer; :func:`anchor_from_row` is where the two are reconciled, and it
refuses a stored ``orphaned`` rather than passing it through.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, replace
from typing import Any

from .resolve import AnchorRecord, Resolution, Suggestion
from .status import effective_status

__all__ = [
    "ANCHOR_COLUMNS",
    "Anchor",
    "anchor_from_row",
    "as_record",
]

#: Every column of the ``anchor`` table, in the order the row mapper reads them. Qualified,
#: because most reads join ``document`` to derive ``orphaned``.
ANCHOR_COLUMNS = (
    "anchor.id, anchor.project_id, anchor.document_id, anchor.from_pos, anchor.to_pos, "
    "anchor.quote, anchor.prefix, anchor.suffix, anchor.status, anchor.label, "
    "anchor.document_version, anchor.created_at, anchor.updated_at, anchor.checked_at"
)


@dataclass(frozen=True, slots=True)
class Anchor:
    """One anchor as a reader sees it."""

    id: str
    project_id: str
    document_id: str
    from_pos: int
    to_pos: int
    quote: str
    prefix: str
    suffix: str
    #: ``ok`` | ``stale`` | ``orphaned`` - the last two derived, never both stored.
    status: str
    label: str
    document_version: int
    created_at: str
    updated_at: str
    checked_at: str
    #: Where the passage may have gone, when this anchor is ``stale`` and the surroundings say
    #: so. Never applied by anything on the server (``specs/anchors.md`` section 6).
    suggestion: Suggestion | None = None

    def with_resolution(self, resolution: Resolution, *, checked_at: str) -> Anchor:
        """This anchor as the resolver now sees it. Does not touch storage."""
        return replace(
            self,
            from_pos=resolution.from_pos,
            to_pos=resolution.to_pos,
            status=resolution.status,
            suggestion=resolution.suggestion,
            checked_at=checked_at,
        )

    def to_dict(self) -> dict[str, Any]:
        suggestion = self.suggestion
        return {
            "id": self.id,
            "project_id": self.project_id,
            "document_id": self.document_id,
            "from_pos": self.from_pos,
            "to_pos": self.to_pos,
            "quote": self.quote,
            "prefix": self.prefix,
            "suffix": self.suffix,
            "status": self.status,
            "label": self.label,
            "document_version": self.document_version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "checked_at": self.checked_at,
            "suggestion": None
            if suggestion is None
            else {
                "from_pos": suggestion.from_pos,
                "to_pos": suggestion.to_pos,
                "text": suggestion.text,
            },
        }


def anchor_from_row(row: sqlite3.Row, *, document_deleted_at: str | None) -> Anchor:
    """One row, with ``orphaned`` derived from the document it belongs to.

    Raises:
        ValueError: If the stored status is not one the resolver writes. A stored ``orphaned``
            means something wrote the derived answer back into the row, which would destroy the
            text answer restoring the chapter has to return to.
    """
    return Anchor(
        id=row["id"],
        project_id=row["project_id"],
        document_id=row["document_id"],
        from_pos=int(row["from_pos"]),
        to_pos=int(row["to_pos"]),
        quote=row["quote"],
        prefix=row["prefix"],
        suffix=row["suffix"],
        status=effective_status(row["status"], document_deleted_at),
        label=row["label"],
        document_version=int(row["document_version"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        checked_at=row["checked_at"],
    )


def as_record(anchor: Anchor) -> AnchorRecord:
    """What the resolver needs from an anchor: a range, a quote, and its surroundings."""
    return AnchorRecord(
        from_pos=anchor.from_pos,
        to_pos=anchor.to_pos,
        quote=anchor.quote,
        prefix=anchor.prefix,
        suffix=anchor.suffix,
    )
