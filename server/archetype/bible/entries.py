"""``EntryStore`` - the uniform bible record, its history, and the retcon flag (P3-3, P3-4).

Scoped by the same :class:`~archetype.projects.store.ProjectHandle` every other store is, and
carrying every rule, because a route carries none (api-contract section 1).

One table serves all seven kinds (D26). The difference between a character and a place is ``kind``
plus the contents of ``attributes_json``, validated here against
:mod:`archetype.bible.schema` - which is the *only* place that field list is written down.

Three rules run through the whole module, and each is a promise ``specs/bible.md`` makes:

**Every write records a revision, holding the entry's full state after the change.** Revision 1 is
the creation. Nothing is deduplicated and nothing is pruned, which is the deliberate opposite of
D23's ``handover`` snapshot on both counts: that is 300 KB nobody asked for, and this is two
kilobytes somebody typed. Reading any past state is one row, not a replay.

**Only a write marked as a retcon flags anything** (D27). The store computes the answer - true
when ``name``, ``attributes_json``, or ``status`` changed - and the request may override it in
either direction. A dependent is an entry joined by a **live** link, in either direction, and
nothing else: a dependency the data does not know about is not flagged, and prose mentions are not
links. Clearing a review flag is never itself a retcon, or the queue would refill itself as it was
worked through.

**Deleting is a soft delete** (D25). Every read filters ``LIVE_ENTRY`` by default, and the
three-way link predicate lives beside it in :mod:`archetype.bible.predicates` - one place, so
that adding a query and forgetting a leg is a visible omission rather than an invisible one.

The concurrency guard is D19's, applied unchanged: ``entry.revision`` is monotonic, an update
presents the revision it was read at, and a stale one is refused with nothing written.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Final

from ..ids import IdPrefix, new_id
from ..projects.db import transaction, utc_now
from ..projects.store import ProjectHandle
from .predicates import LIVE_ENTRY, live_link
from .schema import ENTRY_KINDS, KindLookup, definition_for, validate

__all__ = [
    "MAX_BODY_BYTES",
    "MAX_NAME_CHARS",
    "MAX_REASON_CHARS",
    "MAX_SUMMARY_CHARS",
    "SEARCH_LIMIT",
    "Entry",
    "EntryError",
    "EntryNotFoundError",
    "EntryOrigin",
    "EntryRevision",
    "EntryStatus",
    "EntryStore",
    "RevisionMeta",
    "RevisionNotFoundError",
    "StaleEntryVersionError",
    "UNSET",
    "WriteResult",
]

# -- constants (specs/bible.md section 5) -------------------------------------------------------

#: Matches the chapter and project title limit. A name is a name.
MAX_NAME_CHARS: Final[int] = 200

#: One line, generously read. It is what a Phase 6 context budget spends on an entry, so it is
#: bounded on purpose rather than by taste.
MAX_SUMMARY_CHARS: Final[int] = 500

#: An entry is a note, not a manuscript - the manuscript limit is 2 MB and lives on ``document``.
#: 64 KB is some ten thousand words of notes, and refuses a chapter pasted into the wrong box.
MAX_BODY_BYTES: Final[int] = 64 * 1024

#: A revision ``reason`` and an entry's ``review_reason``.
MAX_REASON_CHARS: Final[int] = 500

#: The cap on the ``q`` filter's result set (plan section 2, ruling 4). A bible is hundreds of
#: rows; a filter that cannot say "there are more" is lying, so the cap is real and reported.
SEARCH_LIMIT: Final[int] = 200


class EntryStatus:
    """The proposal lifecycle. Only ``ACCEPTED`` has a writer in Phase 3."""

    PROPOSED: Final[str] = "proposed"
    ACCEPTED: Final[str] = "accepted"
    REJECTED: Final[str] = "rejected"
    SUPERSEDED: Final[str] = "superseded"

    ALL: Final[frozenset[str]] = frozenset({"proposed", "accepted", "rejected", "superseded"})


class EntryOrigin:
    """Who produced the record. Always ``USER`` in Phase 3; ``AGENT`` is Phase 7's (D5)."""

    USER: Final[str] = "user"
    AGENT: Final[str] = "agent"

    ALL: Final[frozenset[str]] = frozenset({"user", "agent"})


class _Unset:
    """The sentinel for "this field was not presented", so ``None`` can mean "clear it"."""

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "UNSET"


#: Distinguishes an omitted field from one deliberately set to a falsy value. A ``PUT`` that does
#: not mention ``summary`` must not blank it.
UNSET: Final[_Unset] = _Unset()

_FIRST_REVISION: Final[int] = 1

_COLUMNS: Final[str] = (
    "id, project_id, kind, name, summary, body_md, attributes_json, status, origin, "
    "revision, needs_review, review_reason, created_at, updated_at, deleted_at"
)

_ORDERED: Final[str] = "ORDER BY name COLLATE NOCASE, created_at, id"

#: The fields whose change makes a write a retcon by default (D27). ``summary`` and ``body_md``
#: are deliberately absent: fixing a typo in a body must not flag every neighbour, because a
#: noisy flag is an ignored flag.
RETCON_FIELDS: Final[tuple[str, ...]] = ("name", "attributes_json", "status")


class EntryError(RuntimeError):
    """A bible entry operation could not be completed."""


class EntryNotFoundError(EntryError):
    """No live entry with that id exists in this project."""


class RevisionNotFoundError(EntryError):
    """That entry has no such revision."""


class StaleEntryVersionError(EntryError):
    """The write presented a revision that is not the stored one (D19, ruling 3).

    Nothing was written. Carries what the client needs to decide what to do next: the revision
    the entry is actually at, and when it last changed. The client stops, says so, and offers the
    server's copy - it never merges.
    """

    def __init__(
        self, entry_id: str, presented: int, current_revision: int, updated_at: str
    ) -> None:
        super().__init__(
            f"entry {entry_id} is at revision {current_revision}, not {presented}; "
            "reload before saving"
        )
        self.entry_id = entry_id
        self.presented = presented
        self.current_revision = current_revision
        self.updated_at = updated_at


@dataclass(frozen=True, slots=True)
class Entry:
    """One bible record, in the shape every kind shares."""

    id: str
    project_id: str
    kind: str
    name: str
    summary: str
    body_md: str
    attributes: dict[str, Any]
    status: str
    origin: str
    revision: int
    needs_review: bool
    review_reason: str
    created_at: str
    updated_at: str
    deleted_at: str | None = None

    def state(self) -> dict[str, Any]:
        """The entry's full state, as a revision stores it.

        Deliberately excludes ``needs_review`` and ``review_reason``: those are notes about the
        entry's *surroundings*, not claims the entry makes, and restoring a revision must not
        drag a neighbour's old disturbance back with it.
        """
        return {
            "kind": self.kind,
            "name": self.name,
            "summary": self.summary,
            "body_md": self.body_md,
            "attributes": self.attributes,
            "status": self.status,
            "origin": self.origin,
            "revision": self.revision,
            "updated_at": self.updated_at,
            "deleted_at": self.deleted_at,
        }


@dataclass(frozen=True, slots=True)
class RevisionMeta:
    """One revision's metadata. What ``revisions()`` returns - never the stored state."""

    entry_id: str
    revision: int
    revised_at: str
    reason: str
    retcon: bool
    origin: str


@dataclass(frozen=True, slots=True)
class EntryRevision:
    """One revision, with the state it recorded. For preview and restore."""

    meta: RevisionMeta
    state: dict[str, Any]


@dataclass(frozen=True, slots=True)
class WriteResult:
    """What a write did, including what it disturbed.

    ``flagged`` is the point of D27: the writer is told which entries this retcon put into the
    review queue, at the moment it happens, rather than discovering it by opening the queue.

    ``changed_fields`` is which of :data:`RETCON_FIELDS` actually moved. It is what the client's
    retcon checkbox shows as the reason it came up checked (P3-13) - a retcon is meant to be a
    visible act, and "checked because the attributes changed" is visible in a way a bare tick is
    not. It reports the *computed* answer even when the request overrode it, so an override is
    legible as an override.
    """

    entry: Entry
    revision: int
    retcon: bool
    flagged: tuple[str, ...] = ()
    changed_fields: tuple[str, ...] = ()


def clean_text(value: str, *, limit: int, what: str, allow_empty: bool = True) -> str:
    """A trimmed single-line-ish value, bounded.

    Raises:
        ValueError: If it is blank when it may not be, or over ``limit``.
    """
    if not isinstance(value, str):
        raise ValueError(f"{what} must be a string, got {type(value).__name__}")
    cleaned = value.strip()
    if not cleaned and not allow_empty:
        raise ValueError(f"{what} may not be blank")
    if len(cleaned) > limit:
        raise ValueError(f"{what} is {len(cleaned)} characters, over the {limit}-character limit")
    return cleaned


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _entry_from_row(row: sqlite3.Row) -> Entry:
    return Entry(
        id=row["id"],
        project_id=row["project_id"],
        kind=row["kind"],
        name=row["name"],
        summary=row["summary"],
        body_md=row["body_md"],
        attributes=json.loads(row["attributes_json"]),
        status=row["status"],
        origin=row["origin"],
        revision=int(row["revision"]),
        needs_review=bool(row["needs_review"]),
        review_reason=row["review_reason"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        deleted_at=row["deleted_at"],
    )


def _revision_meta_from_row(row: sqlite3.Row) -> RevisionMeta:
    return RevisionMeta(
        entry_id=row["entry_id"],
        revision=int(row["revision"]),
        revised_at=row["revised_at"],
        reason=row["reason"],
        retcon=bool(row["retcon"]),
        origin=row["origin"],
    )


def _touch_project(conn: sqlite3.Connection, project_id: str, now: str) -> None:
    """Stamp the project's ``updated_at`` in the same transaction as the entry write.

    The picker sorts on this (P1-12). Building the bible is working on the project, so a project
    whose entry changed a minute ago must not claim it was last touched when it was created.
    """
    conn.execute("UPDATE project SET updated_at = ? WHERE id = ?", (now, project_id))


class EntryStore:
    """Create, read, update, delete, and restore the entries of one project."""

    def __init__(self, handle: ProjectHandle) -> None:
        self.handle = handle

    # -- reading ------------------------------------------------------------------------------

    def get(self, entry_id: str, *, include_deleted: bool = False) -> Entry:
        """One entry.

        Raises:
            EntryNotFoundError: If this project holds no such entry, or it is deleted and
                ``include_deleted`` is false.
        """
        with self.handle.connect() as conn:
            return self._require(conn, entry_id, include_deleted=include_deleted)

    def list(
        self,
        *,
        kind: str | None = None,
        status: str | None = None,
        needs_review: bool | None = None,
        q: str | None = None,
        include_deleted: bool = False,
    ) -> list[Entry]:
        """The project's entries, filtered.

        One method carries every filter, because the alternative is a method per combination and
        a client that has to know which one to call. The filters compose.

        ``q`` is a ``LIKE`` filter over ``name``, the ``aliases`` attribute, and ``summary`` - a
        filter, not search, and deliberately not ``/search`` (plan section 2, ruling 4). Phase 5
        owns search and owns that route name. Results are capped at :data:`SEARCH_LIMIT`.

        Raises:
            InvalidAttributesError: If ``kind`` is not one of the seven.
            ValueError: If ``status`` is not in the vocabulary.
        """
        clauses = ["project_id = ?"]
        params: list[Any] = [self.handle.id]

        if not include_deleted:
            clauses.append(LIVE_ENTRY)
        if kind is not None:
            definition_for(kind)  # refuses an unknown kind rather than returning nothing
            clauses.append("kind = ?")
            params.append(kind)
        if status is not None:
            if status not in EntryStatus.ALL:
                raise ValueError(
                    f"unknown status {status!r}; expected one of {sorted(EntryStatus.ALL)}"
                )
            clauses.append("status = ?")
            params.append(status)
        if needs_review is not None:
            clauses.append("needs_review = ?")
            params.append(1 if needs_review else 0)
        if q is not None and q.strip():
            # `aliases` is matched through the raw JSON rather than by extracting the array: the
            # blob holds it as a list of strings, and a substring of the serialized form is a
            # substring of one of them. It is a filter over a few hundred rows, not an index.
            clauses.append(
                "(name LIKE ? ESCAPE '\\' OR summary LIKE ? ESCAPE '\\' "
                "OR attributes_json LIKE ? ESCAPE '\\')"
            )
            pattern = f"%{_like_escape(q.strip())}%"
            params.extend([pattern, pattern, pattern])

        sql = f"SELECT {_COLUMNS} FROM entry WHERE {' AND '.join(clauses)} {_ORDERED} LIMIT ?"
        params.append(SEARCH_LIMIT)
        with self.handle.connect() as conn:
            return [_entry_from_row(row) for row in conn.execute(sql, params)]

    def list_deleted(self) -> list[Entry]:
        """The restore surface (D25), on the same footing as *Deleted chapters*."""
        with self.handle.connect() as conn:
            rows = conn.execute(
                f"SELECT {_COLUMNS} FROM entry WHERE project_id = ? AND deleted_at IS NOT NULL "
                "ORDER BY deleted_at DESC, name COLLATE NOCASE",
                (self.handle.id,),
            ).fetchall()
        return [_entry_from_row(row) for row in rows]

    def counts_by_kind(self) -> dict[str, int]:
        """How many live entries of each kind, so the tab answers "how many characters" without
        scrolling. Every kind appears, including the ones with none."""
        with self.handle.connect() as conn:
            rows = conn.execute(
                f"SELECT kind, COUNT(*) AS n FROM entry WHERE project_id = ? AND {LIVE_ENTRY} "
                "GROUP BY kind",
                (self.handle.id,),
            ).fetchall()
        counts = {definition.kind: 0 for definition in ENTRY_KINDS}
        for row in rows:
            counts[row["kind"]] = int(row["n"])
        return counts

    # -- writing ------------------------------------------------------------------------------

    def create(
        self,
        kind: str,
        name: str,
        *,
        summary: str = "",
        body_md: str = "",
        attributes: dict[str, Any] | None = None,
        status: str = EntryStatus.ACCEPTED,
        origin: str = EntryOrigin.USER,
        reason: str = "",
    ) -> Entry:
        """Create an entry, and revision 1 with it, in one transaction.

        Raises:
            InvalidAttributesError: For an unknown kind or an attribute the kind does not
                declare, of the wrong type, or outside a declared ``enum`` set. Nothing written.
            ValueError: For a blank or oversized name, summary, body, status, or origin.
        """
        definition_for(kind)
        resolved_name = clean_text(name, limit=MAX_NAME_CHARS, what="name", allow_empty=False)
        resolved_summary = clean_text(summary, limit=MAX_SUMMARY_CHARS, what="summary")
        resolved_body = _checked_body(body_md)
        resolved_reason = clean_text(reason, limit=MAX_REASON_CHARS, what="reason")
        _check_vocabulary(status, origin)

        entry_id = new_id(IdPrefix.ENTRY)
        now = utc_now()

        with self.handle.connect() as conn, transaction(conn):
            resolved_attributes = validate(kind, attributes, kind_of=self._kind_lookup(conn))
            conn.execute(
                "INSERT INTO entry (id, project_id, kind, name, summary, body_md, "
                "attributes_json, status, origin, revision, needs_review, review_reason, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, '', ?, ?)",
                (
                    entry_id,
                    self.handle.id,
                    kind,
                    resolved_name,
                    resolved_summary,
                    resolved_body,
                    _dump(resolved_attributes),
                    status,
                    origin,
                    _FIRST_REVISION,
                    now,
                    now,
                ),
            )
            entry = self._require(conn, entry_id)
            # Revision 1 is the creation, so history is complete from the beginning and a
            # "restore the original" is an ordinary restore rather than a special case.
            _write_revision(
                conn,
                entry,
                revised_at=now,
                reason=resolved_reason,
                retcon=False,
                origin=origin,
            )
            _touch_project(conn, self.handle.id, now)
            return entry

    def update(
        self,
        entry_id: str,
        revision: int,
        *,
        name: str | _Unset = UNSET,
        summary: str | _Unset = UNSET,
        body_md: str | _Unset = UNSET,
        attributes: dict[str, Any] | _Unset = UNSET,
        status: str | _Unset = UNSET,
        retcon: bool | None = None,
        reason: str = "",
    ) -> WriteResult:
        """Edit an entry, guarded by D19, recording a revision and computing the retcon answer.

        ``kind`` is deliberately absent: it is immutable (``specs/bible.md`` section 1). Every
        attribute the entry holds was validated against that kind's field list, so changing it
        would either destroy typed work silently or leave data the served definition does not
        describe.

        Args:
            revision: The revision the client read. A stale one is refused, nothing written.
            retcon: ``None`` takes the store's computed answer; ``True`` or ``False`` overrides
                it in that direction. The client shows the computed default with its reason, so
                a retcon is a visible act rather than a silent consequence (D12's posture).

        Raises:
            EntryNotFoundError: If this project holds no such live entry.
            StaleEntryVersionError: If ``revision`` is not the stored one (D19).
            InvalidAttributesError: If the presented attributes do not match the kind.
            ValueError: For an oversized or blank field, or an unknown status.
        """
        now = utc_now()
        resolved_reason = clean_text(reason, limit=MAX_REASON_CHARS, what="reason")

        with self.handle.connect() as conn, transaction(conn):
            current = self._require(conn, entry_id)
            # Re-read and compared under the write lock, so two saves cannot both pass the guard.
            if current.revision != revision:
                raise StaleEntryVersionError(
                    entry_id, revision, current.revision, current.updated_at
                )
            return self._write(
                conn,
                current,
                now=now,
                name=name,
                summary=summary,
                body_md=body_md,
                attributes=attributes,
                status=status,
                retcon=retcon,
                reason=resolved_reason,
            )

    def delete(self, entry_id: str) -> Entry:
        """Soft-delete an entry (D25).

        Nothing cascades. The row, its revisions, its links, and its citations all stay; the
        entry leaves every list, count, link view, and the review queue, because those all filter
        on the one predicate. A revision records the deletion, so the history says when it left.

        Deleting is **not** a retcon. The entry has not changed its claims; it has left the
        bible, and flagging its neighbours for that would fill the queue on the way to an empty
        one - the writer is deleting, not revising.

        Raises:
            EntryNotFoundError: If this project holds no such live entry.
        """
        now = utc_now()
        with self.handle.connect() as conn, transaction(conn):
            # Refuses a missing or already-deleted entry before anything is written.
            self._require(conn, entry_id)
            conn.execute(
                "UPDATE entry SET deleted_at = ?, updated_at = ?, revision = revision + 1 "
                "WHERE id = ? AND project_id = ?",
                (now, now, entry_id, self.handle.id),
            )
            entry = self._require(conn, entry_id, include_deleted=True)
            _write_revision(
                conn, entry, revised_at=now, reason="deleted", retcon=False, origin=entry.origin
            )
            _touch_project(conn, self.handle.id, now)
            return entry

    def restore(self, entry_id: str) -> Entry:
        """Bring a soft-deleted entry back, with exactly the links it had (D25).

        Its links return because nothing ever removed them: an endpoint's deletion hides a link
        through the three-way predicate rather than writing to it. A link deleted in its own
        right stays deleted, and the two are distinguishable because the link's own ``deleted_at``
        was never touched.

        Restoring a live entry is a no-op, not an error - the same rule ``DocumentStore.restore``
        follows.
        """
        now = utc_now()
        with self.handle.connect() as conn, transaction(conn):
            current = self._require(conn, entry_id, include_deleted=True)
            if current.deleted_at is None:
                return current
            conn.execute(
                "UPDATE entry SET deleted_at = NULL, updated_at = ?, revision = revision + 1 "
                "WHERE id = ? AND project_id = ?",
                (now, entry_id, self.handle.id),
            )
            entry = self._require(conn, entry_id)
            _write_revision(
                conn, entry, revised_at=now, reason="restored", retcon=False, origin=entry.origin
            )
            _touch_project(conn, self.handle.id, now)
            return entry

    # -- revisions (P3-4) ---------------------------------------------------------------------

    def revisions(self, entry_id: str) -> list[RevisionMeta]:
        """One entry's history, newest first. **Metadata only** - never the stored states.

        The discipline ``SnapshotStore.list`` already follows, and for the same reason: a history
        list is read constantly and the states are the large part of it.

        Deliberately not filtered by ``deleted_at``: the history of a deleted entry is exactly
        what someone deciding whether to restore it wants to see.
        """
        with self.handle.connect() as conn:
            self._require(conn, entry_id, include_deleted=True)
            rows = conn.execute(
                "SELECT entry_id, revision, revised_at, reason, retcon, origin "
                "FROM entry_revision WHERE entry_id = ? ORDER BY revision DESC",
                (entry_id,),
            ).fetchall()
        return [_revision_meta_from_row(row) for row in rows]

    def revision(self, entry_id: str, number: int) -> EntryRevision:
        """One revision's recorded state, for preview and diff.

        Raises:
            EntryNotFoundError: If this project holds no such entry.
            RevisionNotFoundError: If the entry has no such revision.
        """
        with self.handle.connect() as conn:
            self._require(conn, entry_id, include_deleted=True)
            row = conn.execute(
                "SELECT entry_id, revision, revised_at, reason, retcon, origin, snapshot_json "
                "FROM entry_revision WHERE entry_id = ? AND revision = ?",
                (entry_id, number),
            ).fetchone()
        if row is None:
            raise RevisionNotFoundError(f"entry {entry_id} has no revision {number}")
        return EntryRevision(
            meta=_revision_meta_from_row(row), state=json.loads(row["snapshot_json"])
        )

    def restore_revision(self, entry_id: str, number: int, revision: int) -> WriteResult:
        """Write revision ``number``'s state back, **through the ordinary update path**.

        So a restore is an ordinary edit: it bumps ``revision``, appends a new revision at the
        top of the history rather than rewriting it, is guarded by D19, and computes its own
        retcon answer. One write path, no exceptions - ``SnapshotStore.restore``'s rule, one
        table over.

        Raises:
            EntryNotFoundError, RevisionNotFoundError, StaleEntryVersionError: As above.
        """
        target = self.revision(entry_id, number)
        state = target.state
        return self.update(
            entry_id,
            revision,
            name=state["name"],
            summary=state["summary"],
            body_md=state["body_md"],
            attributes=state["attributes"],
            status=state["status"],
            reason=f"restored revision {number}",
        )

    def clear_review(self, entry_id: str, revision: int) -> WriteResult:
        """The writer says they have looked. Never a retcon - not by default, not by override.

        This is the clause that decides whether the queue is usable. Without it, clearing a flag
        on a densely linked character re-flags every one of its neighbours and the queue never
        empties; a review queue that regenerates itself as it is worked through teaches the
        writer that it does not mean anything.

        Raises:
            EntryNotFoundError: If this project holds no such live entry.
            StaleEntryVersionError: If ``revision`` is not the stored one (D19).
        """
        now = utc_now()
        with self.handle.connect() as conn, transaction(conn):
            current = self._require(conn, entry_id)
            if current.revision != revision:
                raise StaleEntryVersionError(
                    entry_id, revision, current.revision, current.updated_at
                )
            conn.execute(
                "UPDATE entry SET needs_review = 0, review_reason = '', updated_at = ?, "
                "revision = revision + 1 WHERE id = ? AND project_id = ?",
                (now, entry_id, self.handle.id),
            )
            entry = self._require(conn, entry_id)
            _write_revision(
                conn,
                entry,
                revised_at=now,
                reason="review cleared",
                retcon=False,
                origin=entry.origin,
            )
            _touch_project(conn, self.handle.id, now)
            return WriteResult(entry=entry, revision=entry.revision, retcon=False, flagged=())

    def dependents(self, entry_id: str) -> list[str]:
        """The ids a retcon to ``entry_id`` would flag, in the exact sense D27 defines.

        > A dependent is an entry joined to the changed one by a **live** link, in either
        > direction.

        Exposed rather than kept private because it is what the client shows on the retcon
        control - "this will flag four entries" - and because a definition nobody can read back
        is a definition nobody can check.
        """
        with self.handle.connect() as conn:
            return _dependents(conn, self.handle.id, entry_id)

    # -- internals ----------------------------------------------------------------------------

    def _write(
        self,
        conn: sqlite3.Connection,
        current: Entry,
        *,
        now: str,
        name: str | _Unset,
        summary: str | _Unset,
        body_md: str | _Unset,
        attributes: dict[str, Any] | _Unset,
        status: str | _Unset,
        retcon: bool | None,
        reason: str,
    ) -> WriteResult:
        """The one write path an edit and a revision restore both go through."""
        resolved_name = (
            current.name
            if isinstance(name, _Unset)
            else clean_text(name, limit=MAX_NAME_CHARS, what="name", allow_empty=False)
        )
        resolved_summary = (
            current.summary
            if isinstance(summary, _Unset)
            else clean_text(summary, limit=MAX_SUMMARY_CHARS, what="summary")
        )
        resolved_body = current.body_md if isinstance(body_md, _Unset) else _checked_body(body_md)
        resolved_status = current.status if isinstance(status, _Unset) else status
        if resolved_status not in EntryStatus.ALL:
            raise ValueError(
                f"unknown status {resolved_status!r}; expected one of {sorted(EntryStatus.ALL)}"
            )
        if isinstance(attributes, _Unset):
            resolved_attributes = current.attributes
        else:
            resolved_attributes = validate(
                current.kind, attributes, kind_of=self._kind_lookup(conn, exclude=current.id)
            )

        # The retcon computation (D27), driven by RETCON_FIELDS rather than by three hand-written
        # comparisons, so the rule is stated once and the client can be told *which* field moved.
        attributes_json = _dump(resolved_attributes)
        before = {
            "name": current.name,
            "attributes_json": _dump(current.attributes),
            "status": current.status,
        }
        after = {
            "name": resolved_name,
            "attributes_json": attributes_json,
            "status": resolved_status,
        }
        changed = tuple(name for name in RETCON_FIELDS if before[name] != after[name])
        is_retcon = bool(changed) if retcon is None else bool(retcon)

        conn.execute(
            "UPDATE entry SET name = ?, summary = ?, body_md = ?, attributes_json = ?, "
            "status = ?, revision = revision + 1, updated_at = ? WHERE id = ? AND project_id = ?",
            (
                resolved_name,
                resolved_summary,
                resolved_body,
                attributes_json,
                resolved_status,
                now,
                current.id,
                self.handle.id,
            ),
        )
        entry = self._require(conn, current.id, include_deleted=True)
        _write_revision(
            conn,
            entry,
            revised_at=now,
            reason=reason,
            retcon=is_retcon,
            origin=entry.origin,
        )

        flagged: tuple[str, ...] = ()
        if is_retcon:
            flagged = _flag_dependents(
                conn,
                project_id=self.handle.id,
                entry=entry,
                now=now,
            )
        _touch_project(conn, self.handle.id, now)
        return WriteResult(
            entry=entry,
            revision=entry.revision,
            retcon=is_retcon,
            flagged=flagged,
            changed_fields=changed,
        )

    def _require(
        self, conn: sqlite3.Connection, entry_id: str, *, include_deleted: bool = False
    ) -> Entry:
        sql = f"SELECT {_COLUMNS} FROM entry WHERE id = ? AND project_id = ?"
        if not include_deleted:
            sql += f" AND {LIVE_ENTRY}"
        row = conn.execute(sql, (entry_id, self.handle.id)).fetchone()
        if row is None:
            raise EntryNotFoundError(f"no entry {entry_id!r} in project {self.handle.id}")
        return _entry_from_row(row)

    def _kind_lookup(self, conn: sqlite3.Connection, *, exclude: str | None = None) -> KindLookup:
        """Resolve an entry id to its kind, for ``entry_ref`` validation.

        Live entries only: a field may not point at a deleted entry, for the same reason a link
        may not. ``exclude`` refuses a self-reference, which is never a meaningful field value
        and is a typo often enough to be worth catching here rather than in a form.
        """

        def kind_of(target_id: str) -> str | None:
            if exclude is not None and target_id == exclude:
                return None
            row = conn.execute(
                f"SELECT kind FROM entry WHERE id = ? AND project_id = ? AND {LIVE_ENTRY}",
                (target_id, self.handle.id),
            ).fetchone()
            return None if row is None else str(row["kind"])

        return kind_of


def _checked_body(body_md: str) -> str:
    """``body_md`` bounded by bytes rather than characters, as ``content_json`` is.

    Markdown as text, not as a schema: nothing parses it, and an entry is a note rather than a
    manuscript.
    """
    if not isinstance(body_md, str):
        raise ValueError(f"body_md must be a string, got {type(body_md).__name__}")
    size = len(body_md.encode("utf-8"))
    if size > MAX_BODY_BYTES:
        raise ValueError(
            f"body_md is {size} bytes, over the {MAX_BODY_BYTES}-byte limit; an entry is a note, "
            "not a manuscript"
        )
    return body_md


def _check_vocabulary(status: str, origin: str) -> None:
    if status not in EntryStatus.ALL:
        raise ValueError(f"unknown status {status!r}; expected one of {sorted(EntryStatus.ALL)}")
    if origin not in EntryOrigin.ALL:
        raise ValueError(f"unknown origin {origin!r}; expected one of {sorted(EntryOrigin.ALL)}")


def _like_escape(value: str) -> str:
    """Escape the ``LIKE`` wildcards so a search for ``100%`` finds ``100%``."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _write_revision(
    conn: sqlite3.Connection,
    entry: Entry,
    *,
    revised_at: str,
    reason: str,
    retcon: bool,
    origin: str,
) -> None:
    """Record the entry's full state **after** the change, at its current revision number.

    So revision *n* is what the entry was at revision *n*, and reading any past state is one row
    rather than a replay. Nothing is deduplicated and nothing is pruned.
    """
    conn.execute(
        "INSERT INTO entry_revision (entry_id, revision, revised_at, reason, retcon, origin, "
        "snapshot_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            entry.id,
            entry.revision,
            revised_at,
            reason,
            1 if retcon else 0,
            origin,
            _dump(entry.state()),
        ),
    )


def _dependents(conn: sqlite3.Connection, project_id: str, entry_id: str) -> list[str]:
    """Every entry joined to ``entry_id`` by a live link, in either direction (D27).

    One query over both directions rather than two unioned in Python: the two halves would be
    the same predicate written twice, which is the shape ruling 9 exists to prevent.
    """
    predicate = live_link(from_entry="from_e", to_entry="to_e")
    rows = conn.execute(
        "SELECT DISTINCT CASE WHEN entry_link.from_entry = :id THEN entry_link.to_entry "
        "ELSE entry_link.from_entry END AS other "
        "FROM entry_link "
        "JOIN entry AS from_e ON from_e.id = entry_link.from_entry "
        "JOIN entry AS to_e ON to_e.id = entry_link.to_entry "
        f"WHERE entry_link.project_id = :project AND {predicate} "
        "AND (entry_link.from_entry = :id OR entry_link.to_entry = :id)",
        {"id": entry_id, "project": project_id},
    ).fetchall()
    # A link from an entry to itself would name itself as its own dependent; it is refused at
    # creation, and excluded here so that this function cannot report one if one ever exists.
    return sorted({row["other"] for row in rows} - {entry_id})


def _flag_dependents(
    conn: sqlite3.Connection, *, project_id: str, entry: Entry, now: str
) -> tuple[str, ...]:
    """Set ``needs_review`` on every dependent, with a reason naming what moved.

    The reason names **the entry and the revision that caused it**, so the queue tells a writer
    what to go and look at rather than only that something happened. A dependent already flagged
    has its reason replaced: the most recent disturbance is the one worth chasing, and an entry
    accumulating reasons nobody trims is a second thing to maintain.

    Flagging writes **no revision on the dependent**. ``needs_review`` is a note about the
    entry's surroundings, not a claim it makes; a revision for it would fill a densely linked
    character's history with rows recording that a neighbour changed, which is exactly the noise
    D27 exists to keep out.
    """
    dependents = _dependents(conn, project_id, entry.id)
    if not dependents:
        return ()
    reason = clean_text(
        f"{entry.name} changed at revision {entry.revision}",
        limit=MAX_REASON_CHARS,
        what="review_reason",
    )
    conn.executemany(
        "UPDATE entry SET needs_review = 1, review_reason = ? WHERE id = ? AND project_id = ?",
        [(reason, dependent_id, project_id) for dependent_id in dependents],
    )
    return tuple(dependents)
