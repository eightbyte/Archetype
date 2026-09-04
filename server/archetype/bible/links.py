"""``LinkStore`` - the relationships between entries (P3-6, D25, D26, D9).

A link is ``(from_entry, relation, to_entry)`` plus optional story-time bounds and its own
attributes. It has its own id and its own row, which is exactly what separates it from an
``entry_ref`` *field*: only a link can be dated, and only a link appears in Phase 8's chart
(``specs/bible.md`` section 3).

Four rules run through this module, and each is one a later phase pays for if it is missed:

**A link is directed in storage and may be symmetric in meaning** (plan section 2, ruling 7).
``entry_link`` always holds one row. A relation the definition marks ``symmetric`` is stored once
and read from both ends; storing it twice would mean two rows that can disagree - one deleted and
one not, one bounded and one not - and a Phase 8 adjacency matrix that double-counts.

**Both directions come back in one answer.** :meth:`LinkStore.for_entry` returns the links running
into an entry beside the ones running out, each marked with which end the entry is on, because
every consumer wants both and computing it twice is how the two halves come to disagree.

**A link is live only when the link is not deleted and neither endpoint is deleted** (D25, ruling
9). That three-way predicate lives in :mod:`archetype.bible.predicates` and is spliced into every
read here - never retyped, because forgetting a leg puts a soft-deleted character back into a
relationship view and surfaces two phases later as a wrong chart.

**Endpoints and relation are not editable** (``specs/bible.md`` section 4). Changing either is a
delete and a create, and both are recoverable; editing them in place would let a link's own
history describe a relationship it never had - the reasoning that keeps ``kind`` immutable, one
table over. :meth:`LinkStore.update` therefore takes bounds and attributes and nothing else.

``since`` and ``until`` are free text (D9). They are stored, displayed, and **never interpreted**:
nothing in Phase 3 or Phase 8 sorts by them. The one relation that does carry ordering power is
``precedes``, and it does so through :mod:`archetype.bible.storytime`, which reads the edges rather
than the bounds.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Final

from ..ids import IdPrefix, new_id
from ..projects.db import touch_project, transaction, utc_now
from ..projects.store import ProjectHandle
from .entries import UNSET, EntryNotFoundError, Unset, clean_text
from .predicates import LIVE_ENTRY, live_link
from .schema import (
    MAX_ATTRIBUTES_BYTES,
    MAX_STORY_TIME_CHARS,
    InvalidAttributesError,
    RelationDefinition,
    relation_for,
)

__all__ = [
    "DuplicateLinkError",
    "Link",
    "LinkEnd",
    "LinkError",
    "LinkNotFoundError",
    "LinkStore",
    "LinkView",
]


class LinkEnd:
    """Which end of a link an entry is on, in the answer :meth:`LinkStore.for_entry` gives."""

    FROM: Final[str] = "from"
    TO: Final[str] = "to"

    ALL: Final[frozenset[str]] = frozenset({"from", "to"})


class LinkError(RuntimeError):
    """A link operation could not be completed."""


class LinkNotFoundError(LinkError):
    """No live link with that id exists in this project."""


class DuplicateLinkError(LinkError):
    """A live link already says this.

    Carries the existing link's id, so a client can point at the row rather than telling the
    writer that something they can see is somehow already there.
    """

    def __init__(self, message: str, *, link_id: str) -> None:
        super().__init__(message)
        self.link_id = link_id


@dataclass(frozen=True, slots=True)
class Link:
    """One relationship, as stored."""

    id: str
    project_id: str
    from_entry: str
    to_entry: str
    relation: str
    attributes: dict[str, Any]
    since: str | None
    until: str | None
    created_at: str
    updated_at: str
    deleted_at: str | None = None


@dataclass(frozen=True, slots=True)
class LinkView:
    """One link as it reads from one entry's end.

    ``label`` comes from the relation definition rather than from a table here: a relation reads
    "is a member of" from one end and "has as a member" from the other, and a symmetric one reads
    the same both ways because its definition repeats its label. Phase 8 asks the vocabulary the
    same question when it decides which relations to mirror (ruling 7).
    """

    link: Link
    #: Which end ``entry_id`` is on - :data:`LinkEnd.FROM` or :data:`LinkEnd.TO`.
    end: str
    other_id: str
    other_name: str
    other_kind: str
    label: str


_COLUMNS: Final[str] = (
    "entry_link.id, entry_link.project_id, entry_link.from_entry, entry_link.to_entry, "
    "entry_link.relation, entry_link.attributes_json, entry_link.since, entry_link.until, "
    "entry_link.created_at, entry_link.updated_at, entry_link.deleted_at"
)

#: Both endpoints, under the aliases the live predicate names.
_JOINED: Final[str] = (
    "FROM entry_link "
    "JOIN entry AS from_e ON from_e.id = entry_link.from_entry "
    "JOIN entry AS to_e ON to_e.id = entry_link.to_entry"
)

_LIVE: Final[str] = live_link(from_entry="from_e", to_entry="to_e")

_ORDERED: Final[str] = "ORDER BY entry_link.relation, entry_link.created_at, entry_link.id"


def _link_from_row(row: sqlite3.Row) -> Link:
    return Link(
        id=row["id"],
        project_id=row["project_id"],
        from_entry=row["from_entry"],
        to_entry=row["to_entry"],
        relation=row["relation"],
        attributes=json.loads(row["attributes_json"]),
        since=row["since"],
        until=row["until"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        deleted_at=row["deleted_at"],
    )


def _bound(value: str | None, *, what: str) -> str | None:
    """A story-time bound: free text, bounded in length, and empty means absent.

    Raises:
        ValueError: If it is over :data:`MAX_STORY_TIME_CHARS`.
    """
    if value is None:
        return None
    cleaned = clean_text(value, limit=MAX_STORY_TIME_CHARS, what=what)
    return cleaned or None


def _attributes(value: Any) -> dict[str, Any]:
    """A link's own attributes: an object, bounded, and otherwise uninterpreted.

    This is the one map in the bible with no declared fields, and it is deliberate rather than an
    oversight: ``specs/bible.md`` section 11 registers ``entry_link.attributes_json`` as the seam
    where Phase 8 puts relationship strength or sentiment *if its chart ever wants it*. Nothing in
    Phase 3 writes it and nothing reads it, so there is no vocabulary to validate against yet -
    only a shape and a size, so that a client cannot put a megabyte of anything in a bible row.

    Raises:
        InvalidAttributesError: If it is not an object, or is over the blob limit.
    """
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise InvalidAttributesError(
            f"link attributes must be an object, got {type(value).__name__}", field="attributes"
        )
    try:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise InvalidAttributesError(
            f"link attributes must be JSON: {exc}", field="attributes"
        ) from exc
    size = len(encoded.encode("utf-8"))
    if size > MAX_ATTRIBUTES_BYTES:
        raise InvalidAttributesError(
            f"link attributes are {size} bytes, over the {MAX_ATTRIBUTES_BYTES}-byte limit",
            field="attributes",
        )
    return dict(value)


class LinkStore:
    """Create, read, re-bound, delete, and restore the links of one project."""

    def __init__(self, handle: ProjectHandle) -> None:
        self.handle = handle

    # -- reading ------------------------------------------------------------------------------

    def get(self, link_id: str, *, include_deleted: bool = False) -> Link:
        """One link, subject to the three-way predicate.

        ``include_deleted`` relaxes only the **link's own** ``deleted_at``, never an endpoint's:
        a link whose endpoint is deleted is not a link anybody may act on, and restoring it is
        done by restoring the entry.

        Raises:
            LinkNotFoundError: If this project holds no such live link.
        """
        with self.handle.connect() as conn:
            return self._require(conn, link_id, include_deleted=include_deleted)

    def list(self, *, relation: str | None = None) -> list[Link]:
        """Every live link in the project, optionally of one relation.

        Raises:
            InvalidAttributesError: If ``relation`` is not in the closed vocabulary.
        """
        clauses = ["entry_link.project_id = ?", _LIVE]
        params: list[Any] = [self.handle.id]
        if relation is not None:
            relation_for(relation)  # refuses an unknown relation rather than returning nothing
            clauses.append("entry_link.relation = ?")
            params.append(relation)
        with self.handle.connect() as conn:
            rows = conn.execute(
                f"SELECT {_COLUMNS} {_JOINED} WHERE {' AND '.join(clauses)} {_ORDERED}", params
            ).fetchall()
        return [_link_from_row(row) for row in rows]

    def for_entry(self, entry_id: str) -> list[LinkView]:
        """One entry's links, **both directions in one answer**.

        Each is marked with which end this entry is on and reads with the label that end gives
        it. A symmetric link appears once from each side, never twice from either.

        A deleted entry - or one that never existed - has no links to show, and that is an empty
        list rather than an error: the predicate is what hides them, and a read path that raised
        instead would be a second way to answer the same question.
        """
        with self.handle.connect() as conn:
            rows = conn.execute(
                f"SELECT {_COLUMNS}, "
                "from_e.name AS from_name, from_e.kind AS from_kind, "
                "to_e.name AS to_name, to_e.kind AS to_kind "
                f"{_JOINED} "
                f"WHERE entry_link.project_id = ? AND {_LIVE} "
                "AND (entry_link.from_entry = ? OR entry_link.to_entry = ?)",
                (self.handle.id, entry_id, entry_id),
            ).fetchall()

        views: list[LinkView] = []
        for row in rows:
            link = _link_from_row(row)
            definition = relation_for(link.relation)
            outgoing = link.from_entry == entry_id
            views.append(
                LinkView(
                    link=link,
                    end=LinkEnd.FROM if outgoing else LinkEnd.TO,
                    other_id=link.to_entry if outgoing else link.from_entry,
                    other_name=row["to_name"] if outgoing else row["from_name"],
                    other_kind=row["to_kind"] if outgoing else row["from_kind"],
                    label=definition.label if outgoing else definition.inverse_label,
                )
            )
        # Sorted here rather than in SQL: the key is the *far* entry's name, which is a different
        # column on each row, and a CASE in the ORDER BY would state the direction rule twice.
        views.sort(key=lambda view: (view.link.relation, view.other_name.casefold(), view.link.id))
        return views

    def edges(self, relation: str) -> list[tuple[str, str]]:
        """Every live link of one relation as an ordered pair, for the modules that walk them.

        :mod:`archetype.bible.storytime` reads ``precedes`` through this and nothing else - the
        ordering module is pure, so the database half of a timeline is exactly this one query.

        Raises:
            InvalidAttributesError: If ``relation`` is not in the closed vocabulary.
        """
        relation_for(relation)
        with self.handle.connect() as conn:
            rows = conn.execute(
                "SELECT entry_link.from_entry AS a, entry_link.to_entry AS b "
                f"{_JOINED} "
                f"WHERE entry_link.project_id = ? AND entry_link.relation = ? AND {_LIVE} "
                "ORDER BY entry_link.created_at, entry_link.id",
                (self.handle.id, relation),
            ).fetchall()
        return [(row["a"], row["b"]) for row in rows]

    def counts_by_relation(self) -> dict[str, int]:
        """How many live links of each relation. Only the relations in play appear."""
        with self.handle.connect() as conn:
            rows = conn.execute(
                f"SELECT entry_link.relation AS relation, COUNT(*) AS n {_JOINED} "
                f"WHERE entry_link.project_id = ? AND {_LIVE} GROUP BY entry_link.relation",
                (self.handle.id,),
            ).fetchall()
        return {row["relation"]: int(row["n"]) for row in rows}

    # -- writing ------------------------------------------------------------------------------

    def create(
        self,
        from_entry: str,
        relation: str,
        to_entry: str,
        *,
        since: str | None = None,
        until: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> Link:
        """Join two entries. The argument order is the sentence: *from* **relation** *to*.

        Every refusal below writes nothing, and all of them are decided before the insert.

        Raises:
            InvalidAttributesError: If the relation is not in the vocabulary, if an endpoint's
                kind is not one the relation joins **on that side**, if the two ends are the same
                entry, or if the bounds or attributes do not fit.
            EntryNotFoundError: If an endpoint does not exist in this project, or is deleted.
            DuplicateLinkError: If a live link already says this - and, for a symmetric relation,
                if one says it in either order.
            ValueError: If a bound is too long.
        """
        definition = relation_for(relation)
        if from_entry == to_entry:
            raise InvalidAttributesError(
                "a link joins two entries; an entry cannot be linked to itself", field="to_entry"
            )
        resolved_since = _bound(since, what="since")
        resolved_until = _bound(until, what="until")
        resolved_attributes = _attributes(attributes)

        link_id = new_id(IdPrefix.LINK)
        now = utc_now()
        with self.handle.connect() as conn, transaction(conn):
            self._check_endpoints(conn, definition, from_entry, to_entry)
            self._check_duplicate(conn, definition, from_entry, to_entry)
            conn.execute(
                "INSERT INTO entry_link (id, project_id, from_entry, to_entry, relation, "
                "attributes_json, since, until, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    link_id,
                    self.handle.id,
                    from_entry,
                    to_entry,
                    relation,
                    json.dumps(resolved_attributes, ensure_ascii=False, separators=(",", ":")),
                    resolved_since,
                    resolved_until,
                    now,
                    now,
                ),
            )
            touch_project(conn, self.handle.id, now)
            return self._require(conn, link_id)

    def update(
        self,
        link_id: str,
        *,
        since: str | None | Unset = UNSET,
        until: str | None | Unset = UNSET,
        attributes: dict[str, Any] | Unset = UNSET,
    ) -> Link:
        """Change a link's bounds or its attributes. **Never its endpoints or its relation.**

        Those are absent on purpose: changing either is a delete and a create, and both are
        recoverable (``specs/bible.md`` section 4).

        No revision is presented, because a link has none. It carries no history and nothing that
        two writers could lose by overwriting - a bound is a note, and the entry it hangs off is
        where the D19 guard lives.

        Raises:
            LinkNotFoundError: If this project holds no such live link.
            InvalidAttributesError: If the attributes do not fit.
            ValueError: If a bound is too long.
        """
        now = utc_now()
        with self.handle.connect() as conn, transaction(conn):
            current = self._require(conn, link_id)
            resolved_since = (
                current.since if isinstance(since, Unset) else _bound(since, what="since")
            )
            resolved_until = (
                current.until if isinstance(until, Unset) else _bound(until, what="until")
            )
            resolved_attributes = (
                current.attributes if isinstance(attributes, Unset) else _attributes(attributes)
            )
            conn.execute(
                "UPDATE entry_link SET since = ?, until = ?, attributes_json = ?, updated_at = ? "
                "WHERE id = ? AND project_id = ?",
                (
                    resolved_since,
                    resolved_until,
                    json.dumps(resolved_attributes, ensure_ascii=False, separators=(",", ":")),
                    now,
                    link_id,
                    self.handle.id,
                ),
            )
            touch_project(conn, self.handle.id, now)
            return self._require(conn, link_id)

    def delete(self, link_id: str) -> Link:
        """Soft-delete a link (D25). Nothing cascades, and neither endpoint is touched.

        Raises:
            LinkNotFoundError: If this project holds no such live link.
        """
        now = utc_now()
        with self.handle.connect() as conn, transaction(conn):
            self._require(conn, link_id)
            conn.execute(
                "UPDATE entry_link SET deleted_at = ?, updated_at = ? WHERE id = ? "
                "AND project_id = ?",
                (now, now, link_id, self.handle.id),
            )
            touch_project(conn, self.handle.id, now)
            return self._require(conn, link_id, include_deleted=True)

    def restore(self, link_id: str) -> Link:
        """Bring a soft-deleted link back. Restoring a live one is a no-op, not an error.

        A restore is refused when a live link already says the same thing - which happens when
        the writer deleted this one, typed it again, and then undid the delete. Two identical
        live rows would double-count in Phase 8's chart, and neither would be the wrong one to
        remove.

        Raises:
            LinkNotFoundError: If this project holds no such link.
            DuplicateLinkError: If an equivalent live link now exists.
        """
        now = utc_now()
        with self.handle.connect() as conn, transaction(conn):
            current = self._require(conn, link_id, include_deleted=True)
            if current.deleted_at is None:
                return current
            self._check_duplicate(
                conn, relation_for(current.relation), current.from_entry, current.to_entry
            )
            conn.execute(
                "UPDATE entry_link SET deleted_at = NULL, updated_at = ? WHERE id = ? "
                "AND project_id = ?",
                (now, link_id, self.handle.id),
            )
            touch_project(conn, self.handle.id, now)
            return self._require(conn, link_id, include_deleted=True)

    # -- internals ----------------------------------------------------------------------------

    def _require(
        self, conn: sqlite3.Connection, link_id: str, *, include_deleted: bool = False
    ) -> Link:
        predicate = (
            live_link(from_entry="from_e", to_entry="to_e")
            if not include_deleted
            # An endpoint's deletion still hides the link: `include_deleted` is about the link's
            # own row, and a link into a deleted entry is restored by restoring the entry.
            else "from_e.deleted_at IS NULL AND to_e.deleted_at IS NULL"
        )
        row = conn.execute(
            f"SELECT {_COLUMNS} {_JOINED} "
            f"WHERE entry_link.id = ? AND entry_link.project_id = ? AND {predicate}",
            (link_id, self.handle.id),
        ).fetchone()
        if row is None:
            raise LinkNotFoundError(f"no link {link_id!r} in project {self.handle.id}")
        return _link_from_row(row)

    def _check_endpoints(
        self,
        conn: sqlite3.Connection,
        definition: RelationDefinition,
        from_entry: str,
        to_entry: str,
    ) -> None:
        """Both ends exist, are live, and are kinds this relation joins **in this direction**.

        ``member_of`` runs character to faction; faction to character is a different statement
        and is refused rather than silently reversed. A symmetric relation is legal either way
        round, which its definition decides and not this method.
        """
        kinds = {}
        for field, entry_id in (("from_entry", from_entry), ("to_entry", to_entry)):
            row = conn.execute(
                f"SELECT kind FROM entry WHERE id = ? AND project_id = ? AND {LIVE_ENTRY}",
                (entry_id, self.handle.id),
            ).fetchone()
            if row is None:
                raise EntryNotFoundError(
                    f"no live entry {entry_id!r} in project {self.handle.id} to be the "
                    f"{field.replace('_', ' ')} of a link"
                )
            kinds[field] = str(row["kind"])

        if not definition.joins(kinds["from_entry"], kinds["to_entry"]):
            raise InvalidAttributesError(
                f"{definition.relation!r} does not join a {kinds['from_entry']} to a "
                f"{kinds['to_entry']}; it runs {list(definition.from_kinds)} to "
                f"{list(definition.to_kinds)}",
                field="relation",
            )

    def _check_duplicate(
        self,
        conn: sqlite3.Connection,
        definition: RelationDefinition,
        from_entry: str,
        to_entry: str,
    ) -> None:
        """Refuse a second live row saying what one already says.

        Deliberately over the **link's own** ``deleted_at`` rather than the three-way predicate:
        two rows for the same pair are duplicates whether or not an endpoint is currently
        deleted, and letting one in while an endpoint is away would surface as a double-counted
        edge the moment that entry was restored.
        """
        pairs = [(from_entry, to_entry)]
        if definition.symmetric:
            # Stored once, read from both ends - so the same pair the other way round is the
            # same link, and a second row for it is the disagreement ruling 7 exists to prevent.
            pairs.append((to_entry, from_entry))
        for left, right in pairs:
            row = conn.execute(
                "SELECT id FROM entry_link WHERE project_id = ? AND from_entry = ? "
                "AND relation = ? AND to_entry = ? AND deleted_at IS NULL",
                (self.handle.id, left, definition.relation, right),
            ).fetchone()
            if row is not None:
                raise DuplicateLinkError(
                    f"a live {definition.relation!r} link already joins these entries",
                    link_id=str(row["id"]),
                )
