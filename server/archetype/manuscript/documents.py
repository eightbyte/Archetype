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
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from ..ids import IdPrefix, new_id
from ..projects.db import transaction, utc_now
from ..projects.store import ProjectHandle
from .projection import Heading, InvalidDocumentError, Projection, empty_document, project

__all__ = [
    "DEFAULT_KIND",
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

_FIRST_VERSION = 1

_META_COLUMNS = (
    "id, project_id, order_index, title, kind, headings_json, word_count, "
    "version, created_at, updated_at"
)


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

    def list_meta(self) -> list[DocumentMeta]:
        """Every document in this project, in order, without content."""
        with self.handle.connect() as conn:
            rows = conn.execute(
                f"SELECT {_META_COLUMNS} FROM document WHERE project_id = ? "
                "ORDER BY order_index, created_at, id",
                (self.handle.id,),
            ).fetchall()
        return [_meta_from_row(row) for row in rows]

    def get(self, document_id: str) -> Document:
        """One document including its content.

        Raises:
            DocumentNotFoundError: If this project holds no such document.
        """
        with self.handle.connect() as conn:
            row = conn.execute(
                f"SELECT {_META_COLUMNS}, content_json, text_plain FROM document "
                "WHERE id = ? AND project_id = ?",
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
                "WHERE project_id = ? AND kind = ? ORDER BY order_index, created_at, id",
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
            row = conn.execute(
                "SELECT COALESCE(MAX(order_index) + 1, 0) AS next_index, "
                "COUNT(*) AS existing FROM document WHERE project_id = ?",
                (self.handle.id,),
            ).fetchone()
            order_index = int(row["next_index"])
            resolved_title = (
                clean_title(title) if title is not None else f"Chapter {int(row['existing']) + 1}"
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

    def save_content(self, document_id: str, content: Any, version: int) -> SaveResult:
        """Save new content for a document (P1-6, D18, D19).

        Validation, the size check, and the projection all run **before** the transaction opens,
        so a rejected save cannot have written anything. Inside the transaction the stored
        version is re-read and compared under the write lock, which is what makes the guard a
        guard rather than a race.

        Raises:
            InvalidDocumentError: The content is not a well-formed document.
            ContentTooLargeError: The content is over :data:`MAX_CONTENT_BYTES`.
            DocumentNotFoundError: This project holds no such document.
            StaleVersionError: ``version`` is not the stored one. Nothing was written.
        """
        content_json = serialize_content(content)
        projection = project(content)
        now = utc_now()

        with self.handle.connect() as conn, transaction(conn):
            row = conn.execute(
                "SELECT version, updated_at FROM document WHERE id = ? AND project_id = ?",
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
            _touch_project(conn, self.handle.id, now)

        return SaveResult(
            document_id=document_id,
            version=new_version,
            word_count=projection.word_count,
            headings=projection.headings,
            updated_at=now,
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
                "UPDATE document SET title = ?, updated_at = ? WHERE id = ? AND project_id = ?",
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
    )
