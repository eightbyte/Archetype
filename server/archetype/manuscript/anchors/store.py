"""The anchor repository: creating, reading, re-linking, and deleting anchors (P2-7).

Scoped by a :class:`~archetype.projects.store.ProjectHandle`, like every other store here, and
carrying every rule that matters so the routes stay thin and Phase 6's agent gets the same
behaviour without going through HTTP.

**The server derives the quote and its context; the client sends only a range.** A create or a
re-link carries ``{from_pos, to_pos, version}`` and nothing else: the text comes out of the
*stored* content through the block index (:func:`~.resolve.extract`), so a client cannot create
an anchor whose quote disagrees with the manuscript, because it is never asked what the
manuscript says. A range presented against a stale version is refused with the same
:class:`~archetype.manuscript.documents.StaleVersionError` a save raises - an anchor over text
that has since changed is an anchor over text nobody looked at (D19).

Reading, and how fresh an answer is
-----------------------------------

:meth:`AnchorStore.list_for_document` **re-resolves on read** without persisting, so a document
opened after its file changed behind the app's back reports what is true now rather than what
was true at the last write. The stored columns are a cache of the last write's answer; the
resolver is the answer.

:meth:`AnchorStore.list_for_project` does not, deliberately. It is the triage list behind the
*Marks* tab, and re-resolving it would mean projecting every chapter in the manuscript to draw
one panel - the thing D2 and P1-5 exist to prevent. It reports the cached answers with
``orphaned`` derived, which is refreshed for a chapter the moment it is opened or saved.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from ...ids import IdPrefix, new_id
from ...projects.db import transaction, utc_now
from ...projects.store import ProjectHandle
from ..documents import LIVE_ONLY, DocumentNotFoundError, StaleVersionError
from ..projection import Projection, project
from .records import ANCHOR_COLUMNS, Anchor, anchor_from_row, as_record
from .resolve import Extraction, context_for, extract, resolve
from .status import ALL_STATUSES, EFFECTIVE_STATUS_SQL

__all__ = ["MAX_LABEL_LENGTH", "AnchorNotFoundError", "AnchorStore", "clean_label"]

#: An anchor's label is the writer's note on it, not a title. Long enough for a sentence.
MAX_LABEL_LENGTH = 200

_JOINED = "FROM anchor JOIN document ON document.id = anchor.document_id"
_ORDERED = "ORDER BY document.order_index, anchor.from_pos, anchor.id"


class AnchorNotFoundError(RuntimeError):
    """No anchor with that id exists in this project."""


def clean_label(label: str) -> str:
    """Trim a label and check its length. An empty label is ordinary, not an error.

    Raises:
        ValueError: If the label is longer than :data:`MAX_LABEL_LENGTH`.
    """
    label = label.strip()
    if len(label) > MAX_LABEL_LENGTH:
        raise ValueError(f"an anchor label must be at most {MAX_LABEL_LENGTH} characters")
    return label


class AnchorStore:
    """Read and write the anchors of one project."""

    def __init__(self, handle: ProjectHandle) -> None:
        self.handle = handle

    # -- reading ----------------------------------------------------------------------------

    def get(self, anchor_id: str) -> Anchor:
        """One anchor, with ``orphaned`` derived from the chapter it lives in.

        Raises:
            AnchorNotFoundError: If this project holds no such anchor.
        """
        with self.handle.connect() as conn:
            return self._require(conn, anchor_id)

    def list_for_document(self, document_id: str) -> list[Anchor]:
        """One document's anchors, **resolved on read** and not persisted.

        Raises:
            DocumentNotFoundError: If this project holds no such live document.
        """
        with self.handle.connect() as conn:
            document = conn.execute(
                f"SELECT content_json FROM document WHERE id = ? AND project_id = ? AND "
                f"{LIVE_ONLY}",
                (document_id, self.handle.id),
            ).fetchone()
            if document is None:
                raise DocumentNotFoundError(
                    f"no document {document_id!r} in project {self.handle.id}"
                )
            rows = conn.execute(
                f"SELECT {ANCHOR_COLUMNS} {_JOINED} "
                "WHERE anchor.document_id = ? AND anchor.project_id = ? "
                "ORDER BY anchor.from_pos, anchor.id",
                (document_id, self.handle.id),
            ).fetchall()

        anchors = [anchor_from_row(row, document_deleted_at=None) for row in rows]
        if not anchors:
            return []

        now = utc_now()
        context = context_for(project(json.loads(document["content_json"])))
        return [
            anchor.with_resolution(resolve(as_record(anchor), context), checked_at=now)
            for anchor in anchors
        ]

    def list_for_project(self, *, status: str | None = None) -> list[Anchor]:
        """Every anchor in the project, in chapter order, optionally filtered by status.

        The status filter runs over the **effective** status, so ``orphaned`` selects the
        anchors of soft-deleted chapters - which is how the *Marks* tab finds what needs
        attention. That join is the price of not storing a status nobody established (D22).

        Raises:
            ValueError: If ``status`` is not one a reader can see.
        """
        if status is not None and status not in ALL_STATUSES:
            raise ValueError(f"{status!r} is not an anchor status; expected {sorted(ALL_STATUSES)}")

        clause = "" if status is None else f" AND {EFFECTIVE_STATUS_SQL} = ?"
        parameters: tuple[Any, ...] = (self.handle.id, status) if status else (self.handle.id,)
        with self.handle.connect() as conn:
            rows = conn.execute(
                f"SELECT {ANCHOR_COLUMNS}, document.deleted_at AS document_deleted_at "
                f"{_JOINED} WHERE anchor.project_id = ?{clause} {_ORDERED}",
                parameters,
            ).fetchall()
        return [
            anchor_from_row(row, document_deleted_at=row["document_deleted_at"]) for row in rows
        ]

    # -- writing ----------------------------------------------------------------------------

    def create(
        self,
        document_id: str,
        *,
        from_pos: int,
        to_pos: int,
        version: int,
        label: str = "",
    ) -> Anchor:
        """Anchor a range of one document's text.

        Raises:
            DocumentNotFoundError: If this project holds no such live document.
            StaleVersionError: If ``version`` is not the document's current one (D19).
            AnchorRangeError: For every refusal in ``specs/anchors.md`` section 8.
            ValueError: If the label is too long.
        """
        with self.handle.connect() as conn, transaction(conn):
            return self.create_within(
                conn, document_id, from_pos=from_pos, to_pos=to_pos, version=version, label=label
            )

    def create_within(
        self,
        conn: sqlite3.Connection,
        document_id: str,
        *,
        from_pos: int,
        to_pos: int,
        version: int,
        label: str = "",
    ) -> Anchor:
        """The same create, inside a transaction the caller already owns.

        It exists for the one operation that has to mint an anchor and write something else
        atomically: Phase 3's *Add to bible* creates an anchor, an entry, and the citation joining
        them in **one** transaction, so that a stale document version leaves none of the three
        behind (``specs/bible.md`` section 8). Two connections cannot do that, and a second insert
        elsewhere would be a second path by which an anchor is minted - which is exactly what
        phase-3-plan section 2, ruling 8 forbids.

        So :meth:`create` is this method plus a transaction, and there is still one place where
        an ``anchor`` row is written.

        Raises:
            As :meth:`create`.
        """
        resolved_label = clean_label(label)
        anchor_id = new_id(IdPrefix.ANCHOR)
        now = utc_now()

        projection = self._guarded_projection(conn, document_id, version)
        found = extract(projection, from_pos, to_pos)
        conn.execute(
            "INSERT INTO anchor (id, project_id, document_id, from_pos, to_pos, quote, "
            "prefix, suffix, status, label, document_version, created_at, updated_at, "
            "checked_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ok', ?, ?, ?, ?, ?)",
            (
                anchor_id,
                self.handle.id,
                document_id,
                found.from_pos,
                found.to_pos,
                found.quote,
                found.prefix,
                found.suffix,
                resolved_label,
                version,
                now,
                now,
                now,
            ),
        )
        return self._require(conn, anchor_id)

    def relink(self, anchor_id: str, *, from_pos: int, to_pos: int, version: int) -> Anchor:
        """Point an existing anchor at a new range, re-deriving its quote and context.

        The repair path for a ``stale`` anchor, and the same one whether the writer accepted a
        suggestion or selected the text themselves - the server is told a range either way, and
        nothing here knows which it was. Nothing is ever repaired automatically.

        Raises:
            AnchorNotFoundError: If this project holds no such anchor.
            DocumentNotFoundError: If its document is soft-deleted or gone. An orphaned anchor
                is repaired by restoring its chapter, not by re-linking it.
            StaleVersionError: If ``version`` is not the document's current one (D19).
            AnchorRangeError: For every refusal in ``specs/anchors.md`` section 8.
        """
        now = utc_now()
        with self.handle.connect() as conn, transaction(conn):
            anchor = self._require(conn, anchor_id)
            projection = self._guarded_projection(conn, anchor.document_id, version)
            found = extract(projection, from_pos, to_pos)
            self._write_range(conn, anchor_id, found, version=version, now=now)
            return self._require(conn, anchor_id)

    def set_label(self, anchor_id: str, label: str) -> Anchor:
        """Change an anchor's label. Not a text change, so no version is presented for it.

        Raises:
            AnchorNotFoundError: If this project holds no such anchor.
            ValueError: If the label is too long.
        """
        resolved = clean_label(label)
        now = utc_now()
        with self.handle.connect() as conn, transaction(conn):
            self._require(conn, anchor_id)
            conn.execute(
                "UPDATE anchor SET label = ?, updated_at = ? WHERE id = ? AND project_id = ?",
                (resolved, now, anchor_id, self.handle.id),
            )
            return self._require(conn, anchor_id)

    def delete(self, anchor_id: str) -> None:
        """Remove an anchor. The only way one ever goes away (``specs/anchors.md`` section 9).

        Its **citations go with it, and the entries stay** (``specs/bible.md`` section 8): a bible
        entry keeps what a person typed and loses one reason to believe it. The two rows are
        removed in one transaction, because a citation pointing at an anchor that is gone is a
        broken foreign key, not a stale view.

        Raises:
            AnchorNotFoundError: If this project holds no such anchor.
        """
        # Deferred because the bible imports the manuscript: a citation is *of* an anchor, so
        # that is the static edge. An anchor's deletion happening to clear citations is the
        # incidental direction, and it is the one that gives way - the rule documents.py already
        # follows for the snapshot a delete records.
        from ...bible.citations import uncite_anchor_within

        with self.handle.connect() as conn, transaction(conn):
            self._require(conn, anchor_id)
            uncite_anchor_within(conn, anchor_id)
            conn.execute(
                "DELETE FROM anchor WHERE id = ? AND project_id = ?",
                (anchor_id, self.handle.id),
            )

    # -- internals ---------------------------------------------------------------------------

    def _require(self, conn: sqlite3.Connection, anchor_id: str) -> Anchor:
        row = conn.execute(
            f"SELECT {ANCHOR_COLUMNS}, document.deleted_at AS document_deleted_at {_JOINED} "
            "WHERE anchor.id = ? AND anchor.project_id = ?",
            (anchor_id, self.handle.id),
        ).fetchone()
        if row is None:
            raise AnchorNotFoundError(f"no anchor {anchor_id!r} in project {self.handle.id}")
        return anchor_from_row(row, document_deleted_at=row["document_deleted_at"])

    def _guarded_projection(
        self, conn: sqlite3.Connection, document_id: str, version: int
    ) -> Projection:
        """The live document's projection, refusing a range presented against a stale version.

        The guard is read under the write lock, inside the caller's transaction, for the same
        reason the save protocol's is (P1-6): a guard checked outside one is a race.
        """
        row = conn.execute(
            "SELECT content_json, version, updated_at FROM document "
            f"WHERE id = ? AND project_id = ? AND {LIVE_ONLY}",
            (document_id, self.handle.id),
        ).fetchone()
        if row is None:
            raise DocumentNotFoundError(f"no document {document_id!r} in project {self.handle.id}")

        stored_version = int(row["version"])
        if stored_version != version:
            raise StaleVersionError(
                document_id=document_id,
                presented=version,
                current_version=stored_version,
                updated_at=row["updated_at"],
            )
        return project(json.loads(row["content_json"]))

    def _write_range(
        self,
        conn: sqlite3.Connection,
        anchor_id: str,
        found: Extraction,
        *,
        version: int,
        now: str,
    ) -> None:
        """Store a freshly derived range. A re-linked anchor is ``ok`` by construction."""
        conn.execute(
            "UPDATE anchor SET from_pos = ?, to_pos = ?, quote = ?, prefix = ?, suffix = ?, "
            "status = 'ok', document_version = ?, updated_at = ?, checked_at = ? "
            "WHERE id = ? AND project_id = ?",
            (
                found.from_pos,
                found.to_pos,
                found.quote,
                found.prefix,
                found.suffix,
                version,
                now,
                now,
                anchor_id,
                self.handle.id,
            ),
        )
