"""Documents: the repository layer over one project's chapters (P1-5, P1-6).

Scoped by a :class:`~archetype.projects.store.ProjectHandle` - "which project" is answered once,
at the edge, and nothing here builds a path by hand.

:meth:`DocumentStore.save_content` is the **only** path by which manuscript text changes. That is
what makes "the writer owns the words" structural rather than aspirational: the agent, when it
arrives, proposes edits that the user accepts, and acceptance comes back through this method like
any other save (D12). It is also where the D19 version guard lives - a save presenting a stale
version writes nothing and raises :class:`StaleVersionError`.

The derived projection (``text_plain``, the heading list, ``word_count``) is computed here, from
:mod:`archetype.manuscript.projection`, on every write. The server's answer is authoritative
(D18); the client's mirror is for liveness between saves.

Ordering and deletion (P2-2, D22)
---------------------------------

Chapters are ordered by ``order_index`` and **deleting one is a soft delete**: ``deleted_at``
goes from ``NULL`` to a timestamp, and the row and its text stay exactly where they were. Every
read path in this module filters ``deleted_at IS NULL``, and so does the project summary's
chapter and word count in :mod:`archetype.projects.store` - one predicate, applied in every
place a deleted chapter could otherwise leak back into a list, an outline, or a count.

A deleted chapter's anchors read as ``orphaned`` without anything being written to them; the
rule lives in :mod:`archetype.manuscript.anchors.status` and is derived from this column.

None of :meth:`DocumentStore.reorder`, :meth:`DocumentStore.delete`, or
:meth:`DocumentStore.restore` bumps a document's content ``version``. None of them is a text
edit, which is the rule :meth:`DocumentStore.rename` already follows: invalidating an in-flight
autosave over a move or a title would cost the writer a keystroke.

Anchors (P2-7, D21)
-------------------

A text write is the one thing that can move an anchor, so :meth:`DocumentStore.save_content`
re-resolves the document's anchors inside its own transaction and reports the ones that moved on
:class:`SaveResult`. That is D18's rule applied to anchors: the server owns the derived truth,
the client mirrors it for liveness. The re-resolution lives in
:mod:`archetype.manuscript.anchors.rewrite` so that this module can call it without the anchor
store - which needs this module's errors - having to be importable from here.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from ..ids import IdPrefix, new_id
from ..projects.db import transaction, utc_now
from ..projects.store import ProjectHandle
from .anchors.records import Anchor
from .anchors.rewrite import resolve_within
from .projection import Heading, InvalidDocumentError, Projection, empty_document, project

__all__ = [
    "DEFAULT_KIND",
    "LIVE_ONLY",
    "MAX_CONTENT_BYTES",
    "MAX_TITLE_LENGTH",
    "ContentTooLargeError",
    "Document",
    "DocumentError",
    "DocumentMeta",
    "DocumentNotFoundError",
    "DocumentStore",
    "InvalidDocumentError",
    "OutlineChapter",
    "ReorderMismatchError",
    "SaveResult",
    "StaleVersionError",
]

#: The largest serialized ``content_json`` a single document may hold. A 20,000-word chapter is
#: roughly 300 KB of ProseMirror JSON, so two megabytes is generous for a chapter and still
#: refuses a payload that would take the process down.
MAX_CONTENT_BYTES = 2 * 1024 * 1024

#: Matches the project-title limit in :mod:`archetype.projects.store`.
MAX_TITLE_LENGTH = 200

#: Phase 1 has one kind of document. Later phases add others; they never repurpose this one.
DEFAULT_KIND = "chapter"

#: The soft-delete predicate (D22). Written once and spliced into every read, so that adding a
#: query and forgetting the filter is a visible omission rather than an invisible one.
LIVE_ONLY = "deleted_at IS NULL"

_FIRST_VERSION = 1

_META_COLUMNS = (
    "id, project_id, order_index, title, kind, headings_json, word_count, "
    "version, created_at, updated_at, deleted_at"
)

_ORDERED = "ORDER BY order_index, created_at, id"


class DocumentError(RuntimeError):
    """A document operation could not be completed."""


class DocumentNotFoundError(DocumentError):
    """No document with that id exists in this project."""


class ContentTooLargeError(DocumentError):
    """The presented content exceeds :data:`MAX_CONTENT_BYTES`. Nothing was written."""

    def __init__(self, size: int, limit: int = MAX_CONTENT_BYTES) -> None:
        super().__init__(f"document content is {size} bytes, over the {limit}-byte limit")
        self.size = size
        self.limit = limit


class ReorderMismatchError(DocumentError):
    """The presented order is not exactly this project's live chapters (P2-2).

    Nothing was written. The completeness check *is* the concurrency guard: a client working
    from a stale chapter list cannot present the complete set, so it is refused before it can
    silently drop a chapter someone else created out of the order.
    """

    def __init__(
        self,
        *,
        missing: Sequence[str] = (),
        unexpected: Sequence[str] = (),
        duplicated: Sequence[str] = (),
    ) -> None:
        parts = []
        if missing:
            parts.append(f"missing {list(missing)}")
        if unexpected:
            parts.append(f"not live chapters of this project: {list(unexpected)}")
        if duplicated:
            parts.append(f"listed more than once: {list(duplicated)}")
        super().__init__(
            "a reorder must present exactly this project's live chapters - " + "; ".join(parts)
        )
        self.missing = tuple(missing)
        self.unexpected = tuple(unexpected)
        self.duplicated = tuple(duplicated)


class StaleVersionError(DocumentError):
    """The save presented a version that is not the stored one (D19).

    Nothing was written. Carries what the client needs to decide what to do next: the version
    the document is actually at, and when it last changed.
    """

    def __init__(
        self, document_id: str, presented: int, current_version: int, updated_at: str
    ) -> None:
        super().__init__(
            f"document {document_id} is at version {current_version}, not {presented}; "
            "reload before saving"
        )
        self.document_id = document_id
        self.presented = presented
        self.current_version = current_version
        self.updated_at = updated_at


@dataclass(frozen=True, slots=True)
class DocumentMeta:
    """Everything about a document except its content.

    The document-list route returns these deliberately: the outline panel must never pull the
    whole manuscript to draw a chapter list (P1-5).
    """

    id: str
    project_id: str
    order_index: int
    title: str
    kind: str
    headings: tuple[Heading, ...]
    word_count: int
    version: int
    created_at: str
    updated_at: str
    #: ``None`` while the chapter is live; a UTC timestamp once it is soft-deleted (D22).
    deleted_at: str | None = None

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


@dataclass(frozen=True, slots=True)
class Document:
    """A document's metadata plus the content and projection that were left out of it."""

    meta: DocumentMeta
    content: dict[str, Any]
    text_plain: str


@dataclass(frozen=True, slots=True)
class SaveResult:
    """What a successful save hands back: the new version and the server's projection (D18)."""

    document_id: str
    version: int
    word_count: int
    headings: tuple[Heading, ...]
    updated_at: str
    #: Every anchor whose status or position moved in this write (P2-7, D21). Empty is the
    #: ordinary answer - it means the writer typed above their anchors rather than through
    #: them. The client replaces its own mapped positions with these, because the server's
    #: answer is the authoritative one.
    anchors: tuple[Anchor, ...] = ()


@dataclass(frozen=True, slots=True)
class OutlineChapter:
    """One chapter's contribution to the stitched table of contents (P1-7, P1-11)."""

    document_id: str
    title: str
    order_index: int
    word_count: int
    headings: tuple[Heading, ...]


def serialize_content(content: Any) -> str:
    """Serialize document content for storage, rejecting anything oversized.

    Runs before the transaction opens, so an oversized payload is refused with nothing written.

    Raises:
        InvalidDocumentError: If the value cannot be represented as JSON.
        ContentTooLargeError: If the serialized form exceeds :data:`MAX_CONTENT_BYTES`.
    """
    try:
        text = json.dumps(content, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise InvalidDocumentError(f"document content is not JSON-serializable: {exc}") from exc
    size = len(text.encode("utf-8"))
    if size > MAX_CONTENT_BYTES:
        raise ContentTooLargeError(size)
    return text


def clean_title(title: str, *, what: str = "document title") -> str:
    """Trim and check a title.

    Raises:
        ValueError: If the title is blank or longer than :data:`MAX_TITLE_LENGTH`.
    """
    title = title.strip()
    if not title:
        raise ValueError(f"{what} must not be blank")
    if len(title) > MAX_TITLE_LENGTH:
        raise ValueError(f"{what} must be at most {MAX_TITLE_LENGTH} characters")
    return title


class DocumentStore:
    """Read and write the documents of one project."""

    def __init__(self, handle: ProjectHandle) -> None:
        self.handle = handle

    # -- reading ----------------------------------------------------------------------------
    #
    # Reads use an ordinary connection, not the read-only mode the directory scan uses. The
    # scan's discipline is that *looking at a project must not change it* - it runs before the
    # file has been opened and must not migrate one. By the time a DocumentStore exists the
    # project has been explicitly opened and migrated, and a read-only handle cannot recover a
    # write-ahead log left behind by an unclean shutdown, which would turn every read into an
    # error.

    def list_meta(self, *, include_deleted: bool = False) -> list[DocumentMeta]:
        """Every live document in this project, in order, without content.

        Args:
            include_deleted: Include soft-deleted chapters too. Off by default, because a
                deleted chapter must be absent from every ordinary list (D22); the trash
                surface asks for them explicitly through :meth:`list_deleted`.
        """
        predicate = "" if include_deleted else f" AND {LIVE_ONLY}"
        with self.handle.connect() as conn:
            rows = conn.execute(
                f"SELECT {_META_COLUMNS} FROM document WHERE project_id = ?{predicate} {_ORDERED}",
                (self.handle.id,),
            ).fetchall()
        return [_meta_from_row(row) for row in rows]

    def list_deleted(self) -> list[DocumentMeta]:
        """The soft-deleted chapters, most recently deleted first (D22).

        What the restore surface reads. Deleting is one click and so is undoing it, which is
        what lets the confirmation stay brief - the undo path carries the safety, not the
        dialogue.
        """
        with self.handle.connect() as conn:
            rows = conn.execute(
                f"SELECT {_META_COLUMNS} FROM document "
                "WHERE project_id = ? AND deleted_at IS NOT NULL "
                "ORDER BY deleted_at DESC, id",
                (self.handle.id,),
            ).fetchall()
        return [_meta_from_row(row) for row in rows]

    def get(self, document_id: str, *, include_deleted: bool = False) -> Document:
        """One document including its content.

        Args:
            include_deleted: Read it even if it is soft-deleted. Off by default: a deleted
                chapter is gone from every ordinary read (D22), and a caller that wants to
                preview one before restoring it says so.

        Raises:
            DocumentNotFoundError: If this project holds no such document, or it is deleted
                and ``include_deleted`` is false.
        """
        predicate = "" if include_deleted else f" AND {LIVE_ONLY}"
        with self.handle.connect() as conn:
            row = conn.execute(
                f"SELECT {_META_COLUMNS}, content_json, text_plain FROM document "
                f"WHERE id = ? AND project_id = ?{predicate}",
                (document_id, self.handle.id),
            ).fetchone()
        if row is None:
            raise DocumentNotFoundError(f"no document {document_id!r} in project {self.handle.id}")
        return Document(
            meta=_meta_from_row(row),
            content=json.loads(row["content_json"]),
            text_plain=row["text_plain"],
        )

    def outline(self) -> list[OutlineChapter]:
        """The stitched table of contents across every chapter (P1-11).

        Reads only the derived columns, so drawing the whole manuscript's TOC never loads a
        single chapter's content (D2, D18).
        """
        with self.handle.connect() as conn:
            rows = conn.execute(
                "SELECT id, title, order_index, headings_json, word_count FROM document "
                f"WHERE project_id = ? AND kind = ? AND {LIVE_ONLY} {_ORDERED}",
                (self.handle.id, DEFAULT_KIND),
            ).fetchall()
        return [
            OutlineChapter(
                document_id=row["id"],
                title=row["title"],
                order_index=row["order_index"],
                word_count=row["word_count"],
                headings=_headings_from_json(row["headings_json"]),
            )
            for row in rows
        ]

    # -- writing ----------------------------------------------------------------------------

    def create(
        self,
        title: str | None = None,
        *,
        kind: str = DEFAULT_KIND,
        content: Any | None = None,
    ) -> Document:
        """Append a document to the end of this project.

        Args:
            title: Defaults to ``Chapter N``, N being one past the chapters already here.
            kind: Phase 1 has only :data:`DEFAULT_KIND`.
            content: Defaults to the document TipTap produces for an empty editor.

        Raises:
            ValueError: If an explicit title is blank or too long.
            InvalidDocumentError: If explicit content is not a well-formed document.
            ContentTooLargeError: If explicit content is oversized.
        """
        document = empty_document() if content is None else content
        content_json = serialize_content(document)
        projection = project(document)

        now = utc_now()
        document_id = new_id(IdPrefix.DOCUMENT)

        with self.handle.connect() as conn, transaction(conn):
            # The next index is taken over *every* row, deleted ones included, so restoring a
            # chapter can never land on an index a live one already holds. The default title
            # counts only live chapters, because "Chapter 4" should follow the three the writer
            # can see, not the three plus one they threw away.
            row = conn.execute(
                "SELECT COALESCE(MAX(order_index) + 1, 0) AS next_index, "
                "SUM(CASE WHEN deleted_at IS NULL THEN 1 ELSE 0 END) AS existing "
                "FROM document WHERE project_id = ?",
                (self.handle.id,),
            ).fetchone()
            order_index = int(row["next_index"])
            live_count = int(row["existing"] or 0)
            resolved_title = (
                clean_title(title) if title is not None else f"Chapter {live_count + 1}"
            )
            conn.execute(
                "INSERT INTO document (id, project_id, order_index, title, kind, content_json, "
                "text_plain, headings_json, word_count, version, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    document_id,
                    self.handle.id,
                    order_index,
                    resolved_title,
                    kind,
                    content_json,
                    projection.text_plain,
                    _headings_to_json(projection),
                    projection.word_count,
                    _FIRST_VERSION,
                    now,
                    now,
                ),
            )
            _touch_project(conn, self.handle.id, now)

        return Document(
            meta=DocumentMeta(
                id=document_id,
                project_id=self.handle.id,
                order_index=order_index,
                title=resolved_title,
                kind=kind,
                headings=projection.headings,
                word_count=projection.word_count,
                version=_FIRST_VERSION,
                created_at=now,
                updated_at=now,
            ),
            content=json.loads(content_json),
            text_plain=projection.text_plain,
        )

    def save_content(
        self,
        document_id: str,
        content: Any,
        version: int,
        *,
        before_write: Callable[[sqlite3.Connection, int], None] | None = None,
    ) -> SaveResult:
        """Save new content for a document (P1-6, D18, D19).

        Validation, the size check, and the projection all run **before** the transaction opens,
        so a rejected save cannot have written anything. Inside the transaction the stored
        version is re-read and compared under the write lock, which is what makes the guard a
        guard rather than a race.

        Args:
            before_write: Run inside this save's transaction, after the version guard has
                passed and before the row is overwritten, with the open connection and the
                version being replaced. The seam exists so that snapshotting the outgoing text
                and replacing it are one atomic act (P2-3): a save refused as stale leaves no
                ``pre-restore`` snapshot behind. It is a hook for work that must share this
                transaction, **not** a second way to write manuscript text - this method stays
                the only one of those (data-model section 6).

        Raises:
            InvalidDocumentError: The content is not a well-formed document.
            ContentTooLargeError: The content is over :data:`MAX_CONTENT_BYTES`.
            DocumentNotFoundError: This project holds no such live document.
            StaleVersionError: ``version`` is not the stored one. Nothing was written.
        """
        content_json = serialize_content(content)
        projection = project(content)
        now = utc_now()

        with self.handle.connect() as conn, transaction(conn):
            row = conn.execute(
                "SELECT version, updated_at FROM document "
                f"WHERE id = ? AND project_id = ? AND {LIVE_ONLY}",
                (document_id, self.handle.id),
            ).fetchone()
            if row is None:
                raise DocumentNotFoundError(
                    f"no document {document_id!r} in project {self.handle.id}"
                )
            stored_version = int(row["version"])
            if stored_version != version:
                raise StaleVersionError(
                    document_id=document_id,
                    presented=version,
                    current_version=stored_version,
                    updated_at=row["updated_at"],
                )

            if before_write is not None:
                before_write(conn, stored_version)

            new_version = stored_version + 1
            conn.execute(
                "UPDATE document SET content_json = ?, text_plain = ?, headings_json = ?, "
                "word_count = ?, version = ?, updated_at = ? WHERE id = ? AND project_id = ?",
                (
                    content_json,
                    projection.text_plain,
                    _headings_to_json(projection),
                    projection.word_count,
                    new_version,
                    now,
                    document_id,
                    self.handle.id,
                ),
            )
            # D21: the server re-resolves this document's anchors from the text that has just
            # replaced the old, in the same transaction that wrote it. Whoever the writer was -
            # the editor, an import, a snapshot restore, a Phase 6 accepted proposal - the
            # anchor rows are correct when the transaction commits, or nothing happened at all.
            moved = resolve_within(
                conn,
                project_id=self.handle.id,
                document_id=document_id,
                projection=projection,
                version=new_version,
                now=now,
            )
            _touch_project(conn, self.handle.id, now)

        return SaveResult(
            document_id=document_id,
            version=new_version,
            word_count=projection.word_count,
            headings=projection.headings,
            updated_at=now,
            anchors=tuple(moved),
        )

    def rename(self, document_id: str, title: str) -> DocumentMeta:
        """Change a document's title.

        The content ``version`` is deliberately **not** bumped: a rename is not a text edit, and
        invalidating an in-flight autosave over one would lose a keystroke to a cosmetic change.

        Raises:
            ValueError: If the title is blank or too long.
            DocumentNotFoundError: If this project holds no such document.
        """
        resolved = clean_title(title)
        now = utc_now()

        with self.handle.connect() as conn, transaction(conn):
            cursor = conn.execute(
                "UPDATE document SET title = ?, updated_at = ? "
                f"WHERE id = ? AND project_id = ? AND {LIVE_ONLY}",
                (resolved, now, document_id, self.handle.id),
            )
            if cursor.rowcount == 0:
                raise DocumentNotFoundError(
                    f"no document {document_id!r} in project {self.handle.id}"
                )
            _touch_project(conn, self.handle.id, now)
            row = conn.execute(
                f"SELECT {_META_COLUMNS} FROM document WHERE id = ?", (document_id,)
            ).fetchone()

        return _meta_from_row(row)

    def reorder(self, document_ids: Sequence[str]) -> list[DocumentMeta]:
        """Rewrite the order of this project's live chapters (P2-2).

        Takes the **complete** ordered list and writes ``order_index`` ``0..n-1`` in one
        transaction. A list that is not exactly the current live set - one missing, one extra,
        one duplicated, one belonging to another project - is refused and nothing is written.

        That completeness check is the concurrency guard, which is why no project-level version
        column is needed: a client working from a stale chapter list cannot produce a complete
        set, so it cannot silently reorder a chapter out of existence.

        No document's ``version`` is bumped, and no document's ``updated_at`` is stamped: the
        order is a property of the project rather than of any one chapter, and marking forty
        chapters as edited because one moved would make "last edited" mean nothing.

        Returns:
            The live chapters in their new order.

        Raises:
            ReorderMismatchError: The presented list is not exactly the live set.
        """
        presented = list(document_ids)
        duplicated = sorted({did for did in presented if presented.count(did) > 1})
        now = utc_now()

        with self.handle.connect() as conn, transaction(conn):
            live = [
                row["id"]
                for row in conn.execute(
                    f"SELECT id FROM document WHERE project_id = ? AND {LIVE_ONLY} {_ORDERED}",
                    (self.handle.id,),
                )
            ]
            missing = sorted(set(live) - set(presented))
            unexpected = sorted(set(presented) - set(live))
            if missing or unexpected or duplicated:
                raise ReorderMismatchError(
                    missing=missing, unexpected=unexpected, duplicated=duplicated
                )

            for index, ordered_id in enumerate(presented):
                conn.execute(
                    "UPDATE document SET order_index = ? WHERE id = ? AND project_id = ?",
                    (index, ordered_id, self.handle.id),
                )
            _touch_project(conn, self.handle.id, now)
            rows = conn.execute(
                f"SELECT {_META_COLUMNS} FROM document "
                f"WHERE project_id = ? AND {LIVE_ONLY} {_ORDERED}",
                (self.handle.id,),
            ).fetchall()

        return [_meta_from_row(row) for row in rows]

    def delete(self, document_id: str) -> DocumentMeta:
        """Soft-delete a chapter (P2-2, D22).

        Takes a ``pre-delete`` snapshot and sets ``deleted_at`` in **one** transaction, so a
        chapter is never removed from the lists without the copy that undoes it, and a failure
        anywhere leaves neither. The row, its content, its snapshots, and its anchors all stay;
        the anchors read as ``orphaned`` until it is restored, without a single row being
        rewritten (:mod:`archetype.manuscript.anchors.status`).

        Raises:
            DocumentNotFoundError: If this project holds no such live document.
        """
        # Deferred because snapshots.py imports this module: a snapshot is *of* a document, so
        # that is the static edge. Deleting one happens to record a snapshot, which is the
        # incidental direction and the one that gives way.
        from .snapshots import SnapshotReason, capture_within

        now = utc_now()
        with self.handle.connect() as conn, transaction(conn):
            row = conn.execute(
                "SELECT content_json, word_count, version FROM document "
                f"WHERE id = ? AND project_id = ? AND {LIVE_ONLY}",
                (document_id, self.handle.id),
            ).fetchone()
            if row is None:
                raise DocumentNotFoundError(
                    f"no document {document_id!r} in project {self.handle.id}"
                )
            capture_within(
                conn,
                project_id=self.handle.id,
                document_id=document_id,
                content_json=row["content_json"],
                word_count=int(row["word_count"]),
                version=int(row["version"]),
                reason=SnapshotReason.PRE_DELETE,
                now=now,
            )
            conn.execute(
                "UPDATE document SET deleted_at = ?, updated_at = ? "
                "WHERE id = ? AND project_id = ?",
                (now, now, document_id, self.handle.id),
            )
            _touch_project(conn, self.handle.id, now)
            meta_row = conn.execute(
                f"SELECT {_META_COLUMNS} FROM document WHERE id = ?", (document_id,)
            ).fetchone()

        return _meta_from_row(meta_row)

    def restore(self, document_id: str) -> DocumentMeta:
        """Bring a soft-deleted chapter back (P2-2, D22).

        Clears ``deleted_at`` and appends the chapter at the end of the order rather than
        guessing where it used to be - the surrounding chapters have moved on, and dropping it
        back into a position it no longer fits is a worse answer than a visible one at the end.

        Its text returns byte for byte, and its anchors return to the statuses they held before
        the delete: a soft delete changes no text, so nothing about them ever became untrue.

        Restoring a chapter that is already live is a no-op, not an error.

        Raises:
            DocumentNotFoundError: If this project holds no such document at all.
        """
        now = utc_now()
        with self.handle.connect() as conn, transaction(conn):
            row = conn.execute(
                "SELECT deleted_at FROM document WHERE id = ? AND project_id = ?",
                (document_id, self.handle.id),
            ).fetchone()
            if row is None:
                raise DocumentNotFoundError(
                    f"no document {document_id!r} in project {self.handle.id}"
                )
            if row["deleted_at"] is not None:
                next_index = int(
                    conn.execute(
                        "SELECT COALESCE(MAX(order_index) + 1, 0) AS next_index FROM document "
                        "WHERE project_id = ?",
                        (self.handle.id,),
                    ).fetchone()["next_index"]
                )
                conn.execute(
                    "UPDATE document SET deleted_at = NULL, order_index = ?, updated_at = ? "
                    "WHERE id = ? AND project_id = ?",
                    (next_index, now, document_id, self.handle.id),
                )
                _touch_project(conn, self.handle.id, now)
            meta_row = conn.execute(
                f"SELECT {_META_COLUMNS} FROM document WHERE id = ?", (document_id,)
            ).fetchone()

        return _meta_from_row(meta_row)


def _touch_project(conn: sqlite3.Connection, project_id: str, now: str) -> None:
    """Stamp the project's ``updated_at`` in the same transaction as the document write.

    The picker sorts on this (P1-12); a project whose chapter changed a minute ago must not
    claim it was last touched when it was created.
    """
    conn.execute("UPDATE project SET updated_at = ? WHERE id = ?", (now, project_id))


def _headings_to_json(projection: Projection) -> str:
    return json.dumps(projection.headings_as_dicts(), ensure_ascii=False, separators=(",", ":"))


def _headings_from_json(raw: str) -> tuple[Heading, ...]:
    """Rebuild the stored heading list. Written by us, so its shape is known."""
    return tuple(
        Heading(level=int(item["level"]), text=str(item["text"]), ordinal=int(item["ordinal"]))
        for item in json.loads(raw)
    )


def _meta_from_row(row: sqlite3.Row) -> DocumentMeta:
    return DocumentMeta(
        id=row["id"],
        project_id=row["project_id"],
        order_index=int(row["order_index"]),
        title=row["title"],
        kind=row["kind"],
        headings=_headings_from_json(row["headings_json"]),
        word_count=int(row["word_count"]),
        version=int(row["version"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        deleted_at=row["deleted_at"],
    )
