"""Citations - where the bible meets the manuscript (P3-7, ``specs/bible.md`` section 8).

A citation is a row in ``entry_anchor``: ``(entry_id, anchor_id, role)``, with the role one of
``source`` · ``mention`` · ``setup`` · ``payoff``. An entry may cite one anchor in more than one
role, which is why all three columns are the key.

This is the phase where anchors acquire their first real consumer, and where the whole Phase 2
budget either pays for itself or does not. An entry's citations carry **each anchor's current
status**, so ``stale`` stops being an abstraction: the passage that produced this entry has been
rewritten, and the writer sees that *before* trusting the entry.

Three rules, each of which a design could quietly get wrong:

**An anchor is minted through ``AnchorStore`` and by no other means** (plan section 2, ruling 8).
:meth:`CitationStore.create_from_range` is *Add to bible*: it sends a ProseMirror range and a
document version exactly as marking a passage does, and the **server** derives the quote. The
anchor, the entry, and the citation are written in **one transaction**, so a stale version is
refused with the same ``409`` a save is and nothing at all is written - not the anchor, not the
entry, not the citation.

**The two deletions do not reach each other.** Deleting an anchor removes its citations and leaves
the entries, which is why :func:`uncite_anchor_within` exists and why ``AnchorStore.delete`` calls
it inside its own transaction. Soft-deleting an entry leaves its citations and its anchors
untouched - an anchor is a fact about the manuscript, and an entry is not.

**Narrative position is derived, never stored.** It comes from the ``source`` anchor's document
``order_index`` and ``from_pos``, computed on read, so it moves when the writer reorders chapters
for free; an entry with no ``source`` anchor simply has none, which is D9's unplaced tray arriving
from the data rather than from a flag somebody has to maintain.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Final

from ..manuscript.anchors import ANCHOR_COLUMNS, Anchor, anchor_from_row
from ..manuscript.anchors.store import AnchorNotFoundError, AnchorStore
from ..manuscript.documents import LIVE_ONLY
from ..projects.db import touch_project, transaction, utc_now
from ..projects.store import ProjectHandle
from .entries import Entry, EntryStore
from .predicates import LIVE_ENTRY
from .schema import InvalidAttributesError

__all__ = [
    "Citation",
    "CitationRole",
    "CitationStore",
    "CitingEntry",
    "CreatedFromRange",
    "NarrativePosition",
    "uncite_anchor_within",
]


class CitationRole:
    """Why an entry points at a passage.

    Closed, and the four are not interchangeable: ``source`` is the passage that *produced* the
    entry and the one narrative position is derived from, while the other three are places the
    entry is visible in the manuscript.
    """

    SOURCE: Final[str] = "source"
    MENTION: Final[str] = "mention"
    SETUP: Final[str] = "setup"
    PAYOFF: Final[str] = "payoff"

    ALL: Final[frozenset[str]] = frozenset({"source", "mention", "setup", "payoff"})


@dataclass(frozen=True, slots=True)
class Citation:
    """One citation, with the anchor as it reads **now**."""

    entry_id: str
    anchor: Anchor
    role: str
    created_at: str
    #: The chapter the passage is in, for a client that shows where a citation points without
    #: fetching every document to find out.
    document_id: str
    document_title: str


@dataclass(frozen=True, slots=True)
class CitingEntry:
    """One entry that cites an anchor - the reverse view, for the *Marks* tab."""

    entry_id: str
    kind: str
    name: str
    role: str
    created_at: str


@dataclass(frozen=True, slots=True)
class NarrativePosition:
    """Where an entry sits in the book, derived from its ``source`` anchor."""

    entry_id: str
    document_id: str
    order_index: int
    from_pos: int


@dataclass(frozen=True, slots=True)
class CreatedFromRange:
    """What *Add to bible* made: an anchor, an entry, and the citation joining them."""

    entry: Entry
    anchor: Anchor
    role: str


def _check_role(role: str) -> str:
    if role not in CitationRole.ALL:
        raise InvalidAttributesError(
            f"unknown citation role {role!r}; expected one of {sorted(CitationRole.ALL)}",
            field="role",
        )
    return role


def uncite_anchor_within(conn: sqlite3.Connection, anchor_id: str) -> int:
    """Remove every citation of one anchor, inside a transaction the caller owns.

    Called by ``AnchorStore.delete`` so that removing an anchor and dropping the rows that point
    at it are one act: ``entry_anchor.anchor_id`` is a real foreign key, so a delete that skipped
    this would not leave a stale view, it would fail.

    The **entries stay**. An entry keeps what a person typed and loses one reason to believe it
    (``specs/bible.md`` section 8).

    Returns:
        How many citations went, so a caller can say what it left behind.
    """
    cursor = conn.execute("DELETE FROM entry_anchor WHERE anchor_id = ?", (anchor_id,))
    return cursor.rowcount


class CitationStore:
    """Cite, uncite, and read the citations of one project's entries."""

    def __init__(self, handle: ProjectHandle) -> None:
        self.handle = handle
        self.entries = EntryStore(handle)
        self.anchors = AnchorStore(handle)

    # -- reading ------------------------------------------------------------------------------

    def citations(self, entry_id: str) -> list[Citation]:
        """One entry's citations, in narrative order, each with the anchor's **current** status.

        The anchor rows come back in the same query as the citation rows and are built by the
        anchors package's own row mapper, so ``orphaned`` is derived exactly once, in the one
        place D22 put it - a second derivation here is how a citation would come to disagree with
        the *Marks* tab about the same anchor.

        Raises:
            EntryNotFoundError: If this project holds no such entry. Deliberately including a
                deleted one: an entry's citations are part of what a writer looks at when
                deciding whether to restore it.
        """
        with self.handle.connect() as conn:
            self.entries.require(conn, entry_id, include_deleted=True)
            return self._read(conn, entry_id)

    def entries_for_anchor(self, anchor_id: str) -> list[CitingEntry]:
        """Which entries cite this anchor - so *Marks* can say an anchor is spoken for.

        Live entries only: a soft-deleted entry is absent from every read path, and a citation
        view is one of them. It is also what makes deleting an anchor honest about what it will
        leave behind, because it will not name entries nobody can see.
        """
        with self.handle.connect() as conn:
            rows = conn.execute(
                "SELECT entry.id AS id, entry.kind AS kind, entry.name AS name, "
                "entry_anchor.role AS role, entry_anchor.created_at AS created_at "
                "FROM entry_anchor JOIN entry ON entry.id = entry_anchor.entry_id "
                f"WHERE entry_anchor.anchor_id = ? AND entry.project_id = ? AND entry.{LIVE_ENTRY} "
                "ORDER BY entry.name COLLATE NOCASE, entry_anchor.role",
                (anchor_id, self.handle.id),
            ).fetchall()
        return [
            CitingEntry(
                entry_id=row["id"],
                kind=row["kind"],
                name=row["name"],
                role=row["role"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def narrative_position(self, entry_id: str) -> NarrativePosition | None:
        """Where this entry sits in the book, or ``None`` if nothing places it.

        Derived from the ``source`` citation with the earliest position, never stored. A source
        anchor in a soft-deleted chapter places nothing: the passage is away, and a position in a
        chapter the reader cannot reach would sort the entry into a book it is not in.
        """
        return self.narrative_positions().get(entry_id)

    def narrative_positions(self) -> dict[str, NarrativePosition]:
        """Every placed entry's position, in one query, keyed by entry id.

        The list view wants all of them at once; asking per entry is the same answer N times.
        """
        with self.handle.connect() as conn:
            rows = conn.execute(
                "SELECT entry_anchor.entry_id AS entry_id, anchor.document_id AS document_id, "
                "document.order_index AS order_index, anchor.from_pos AS from_pos "
                "FROM entry_anchor "
                "JOIN anchor ON anchor.id = entry_anchor.anchor_id "
                "JOIN document ON document.id = anchor.document_id "
                "JOIN entry ON entry.id = entry_anchor.entry_id "
                f"WHERE entry.project_id = ? AND entry.{LIVE_ENTRY} AND document.{LIVE_ONLY} "
                "AND entry_anchor.role = ? "
                "ORDER BY document.order_index, anchor.from_pos",
                (self.handle.id, CitationRole.SOURCE),
            ).fetchall()

        positions: dict[str, NarrativePosition] = {}
        for row in rows:
            # Ordered by position, so the first row for an entry is its earliest source and the
            # rest are later mentions of the same claim.
            positions.setdefault(
                row["entry_id"],
                NarrativePosition(
                    entry_id=row["entry_id"],
                    document_id=row["document_id"],
                    order_index=int(row["order_index"]),
                    from_pos=int(row["from_pos"]),
                ),
            )
        return positions

    # -- writing ------------------------------------------------------------------------------

    def cite(self, entry_id: str, anchor_id: str, role: str = CitationRole.SOURCE) -> Citation:
        """Point a live entry at an existing anchor.

        Citing what is already cited in that role is a no-op rather than an error: the row says
        the same thing either way, and a writer who clicked twice has not made a mistake worth a
        message.

        Raises:
            EntryNotFoundError: If this project holds no such live entry.
            AnchorNotFoundError: If this project holds no such anchor.
            InvalidAttributesError: If the role is not one of the four.
        """
        resolved_role = _check_role(role)
        now = utc_now()
        with self.handle.connect() as conn, transaction(conn):
            self.entries.require(conn, entry_id)
            self._require_anchor(conn, anchor_id)
            conn.execute(
                "INSERT INTO entry_anchor (entry_id, anchor_id, role, created_at) "
                "VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING",
                (entry_id, anchor_id, resolved_role, now),
            )
            touch_project(conn, self.handle.id, now)
            return self._read(conn, entry_id, anchor_id=anchor_id, role=resolved_role)[0]

    def uncite(self, entry_id: str, anchor_id: str, *, role: str | None = None) -> int:
        """Remove a citation. Without a role, every role this entry cites that anchor in.

        The anchor stays - it is a fact about the manuscript, and the *Marks* tab is where one is
        removed. Removing a citation that is not there is not an error; it returns zero.

        Returns:
            How many citations went.

        Raises:
            InvalidAttributesError: If ``role`` is given and is not one of the four.
        """
        if role is not None:
            _check_role(role)
        now = utc_now()
        with self.handle.connect() as conn, transaction(conn):
            sql = "DELETE FROM entry_anchor WHERE entry_id = ? AND anchor_id = ?"
            params: list[Any] = [entry_id, anchor_id]
            if role is not None:
                sql += " AND role = ?"
                params.append(role)
            removed = conn.execute(sql, params).rowcount
            if removed:
                touch_project(conn, self.handle.id, now)
        return removed

    def create_from_range(
        self,
        document_id: str,
        *,
        from_pos: int,
        to_pos: int,
        version: int,
        kind: str,
        name: str,
        summary: str = "",
        body_md: str = "",
        attributes: dict[str, Any] | None = None,
        label: str = "",
        role: str = CitationRole.SOURCE,
    ) -> CreatedFromRange:
        """*Add to bible*: one transaction that mints an anchor, creates an entry, and cites it.

        The interaction the whole product is arranged around, in its manual form - the outline's
        "selecting text and asking a question about it". The client sends a **range and a
        version**, never a quote; the server derives the words, exactly as marking a passage does
        (plan section 2, ruling 8).

        Everything happens in one transaction, so **a refusal writes nothing at all**: a stale
        document version, an unknown kind, an attribute the kind does not declare, or a range
        that spans a scene break each leave no anchor, no entry, and no citation.

        Raises:
            DocumentNotFoundError: If this project holds no such live chapter.
            StaleVersionError: If ``version`` is not the chapter's current one (D19). The same
                ``409`` a save gets.
            AnchorRangeError: For every refusal in ``specs/anchors.md`` section 8.
            InvalidAttributesError: For an unknown kind, an undeclared attribute, or an unknown
                role.
            ValueError: For a blank or oversized name, summary, body, or label.
        """
        resolved_role = _check_role(role)
        now = utc_now()
        with self.handle.connect() as conn, transaction(conn):
            # The anchor first: it carries the D19 guard, so a stale version is refused before
            # anything is validated, let alone written.
            anchor = self.anchors.create_within(
                conn,
                document_id,
                from_pos=from_pos,
                to_pos=to_pos,
                version=version,
                label=label,
            )
            entry = self.entries.create_within(
                conn,
                kind,
                name,
                summary=summary,
                body_md=body_md,
                attributes=attributes,
                reason="created from a selection",
            )
            conn.execute(
                "INSERT INTO entry_anchor (entry_id, anchor_id, role, created_at) "
                "VALUES (?, ?, ?, ?)",
                (entry.id, anchor.id, resolved_role, now),
            )
            touch_project(conn, self.handle.id, now)
        return CreatedFromRange(entry=entry, anchor=anchor, role=resolved_role)

    # -- internals ----------------------------------------------------------------------------

    def _read(
        self,
        conn: sqlite3.Connection,
        entry_id: str,
        *,
        anchor_id: str | None = None,
        role: str | None = None,
    ) -> list[Citation]:
        """The citation query, written once, so a read and a write read back the same shape."""
        clauses = ["entry_anchor.entry_id = ?", "anchor.project_id = ?"]
        params: list[Any] = [entry_id, self.handle.id]
        if anchor_id is not None:
            clauses.append("entry_anchor.anchor_id = ?")
            params.append(anchor_id)
        if role is not None:
            clauses.append("entry_anchor.role = ?")
            params.append(role)
        rows = conn.execute(
            f"SELECT {ANCHOR_COLUMNS}, entry_anchor.entry_id AS entry_id, "
            "entry_anchor.role AS role, entry_anchor.created_at AS cited_at, "
            "document.deleted_at AS document_deleted_at, document.title AS document_title "
            "FROM entry_anchor "
            "JOIN anchor ON anchor.id = entry_anchor.anchor_id "
            "JOIN document ON document.id = anchor.document_id "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY document.order_index, anchor.from_pos, entry_anchor.role",
            params,
        ).fetchall()
        return [
            Citation(
                entry_id=row["entry_id"],
                anchor=anchor_from_row(row, document_deleted_at=row["document_deleted_at"]),
                role=row["role"],
                created_at=row["cited_at"],
                document_id=row["document_id"],
                document_title=row["document_title"],
            )
            for row in rows
        ]

    def _require_anchor(self, conn: sqlite3.Connection, anchor_id: str) -> None:
        """The anchor exists in this project. Its *status* is not a condition of citing it.

        A ``stale`` or ``orphaned`` anchor is exactly the kind a writer wants on an entry, so
        that the entry can say the passage behind it has moved.
        """
        row = conn.execute(
            "SELECT id FROM anchor WHERE id = ? AND project_id = ?",
            (anchor_id, self.handle.id),
        ).fetchone()
        if row is None:
            raise AnchorNotFoundError(f"no anchor {anchor_id!r} in project {self.handle.id}")
