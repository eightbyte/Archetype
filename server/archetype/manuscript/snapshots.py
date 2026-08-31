"""Snapshots: versioned copies of one chapter (P2-3, D23).

A snapshot is what makes an irreversible act reversible. Deleting a chapter, restoring an older
draft, importing over a manuscript, and - from Phase 4 - accepting an AI rewrite all replace or
remove text without a keystroke, and each takes a snapshot first.

When one is taken (D23)
-----------------------

``handover``
    The editor hands a document over - a chapter switch, a project close, best-effort on unload.
``manual``
    The writer marks a version, with a label.
``pre-restore``, ``pre-delete``, ``pre-import``
    Before an operation that replaces or removes text. Taken inside the same transaction as the
    operation itself, so a refused operation leaves no snapshot behind.

Automatic and deliberate snapshots
---------------------------------

One distinction decides both of the storage rules. ``handover`` is the only snapshot nobody
asked for - it fires because the editor moved on. Every other reason is caused by a deliberate
act: the writer marking a version, or something about to destroy text.

**Automatic snapshots are deduplicated and pruned.** If the newest snapshot for the document
already holds this exact content, a ``handover`` writes nothing, so a chapter nobody touched
never accumulates history; and only ``handover`` snapshots are pruned, to the newest
:data:`HANDOVER_RETENTION` per document, in the same transaction that inserts.

**Deliberate snapshots are always written and never pruned.** Two reasons, and the second is
the one that matters. A ``manual`` mark carries a label, and suppressing it because the text
had not changed would throw away the only thing the writer was recording. And a ``pre-*``
snapshot is a *recovery guarantee*, not a history entry: deduplicating one against a
``handover`` would leave the recovery copy for a destructive act sitting in the prunable pool,
where a later run of edits could quietly delete the only copy of what was destroyed. A
data-loss path is a release blocker (outline section 9), and one extra row per destructive act
is not a price worth arguing over. It also keeps the history honest about what happened: a
``pre-delete`` entry says the chapter was deleted at that moment, whether or not the words had
moved since the last visit.

A 20,000-word chapter is roughly 300 KB of ProseMirror JSON, so the ``handover`` ceiling is
about 7.5 MB per chapter before dedup - known arithmetic rather than a discovered surprise. If a
real manuscript proves it too generous, compressing ``content_json`` into a BLOB is the lever,
and it is a Phase 9 measurement.

Restoring is an ordinary save
-----------------------------

:meth:`SnapshotStore.restore` writes the snapshot's content back through
:meth:`~archetype.manuscript.documents.DocumentStore.save_content`. It is a save like any other:
it increments ``version``, re-derives the projection (D18), is refused with the D19 guard if the
client is stale, and - from P2-7 - re-resolves the document's anchors. There is one write path
for manuscript text and this is not an exception to it (data-model section 6).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Final

from ..ids import IdPrefix, new_id
from ..projects.db import transaction, utc_now
from ..projects.store import ProjectHandle
from .documents import DocumentNotFoundError, DocumentStore, SaveResult

__all__ = [
    "HANDOVER_RETENTION",
    "MAX_LABEL_LENGTH",
    "Snapshot",
    "SnapshotError",
    "SnapshotMeta",
    "SnapshotNotFoundError",
    "SnapshotReason",
    "SnapshotStore",
    "capture_within",
    "clean_label",
    "hash_content",
]

#: How many ``handover`` snapshots are kept per document. Older ones are pruned in the same
#: transaction that inserts a new one. A module constant, not a setting: a setting is a promise
#: to support every value of it, and no second value is wanted yet (phase-2-plan section 2,
#: ruling 8).
HANDOVER_RETENTION: Final[int] = 25

#: The longest label a writer may put on a marked version. Matches the document-title limit.
MAX_LABEL_LENGTH: Final[int] = 200


class SnapshotReason:
    """Why a snapshot was taken (D23). Stored verbatim; the UI reads it back."""

    HANDOVER: Final[str] = "handover"
    MANUAL: Final[str] = "manual"
    PRE_RESTORE: Final[str] = "pre-restore"
    PRE_DELETE: Final[str] = "pre-delete"
    PRE_IMPORT: Final[str] = "pre-import"

    #: Every reason a snapshot may carry.
    ALL: Final[frozenset[str]] = frozenset(
        {"handover", "manual", "pre-restore", "pre-delete", "pre-import"}
    )

    #: The snapshots nobody asked for. These - and only these - are deduplicated against the
    #: newest snapshot and pruned to :data:`HANDOVER_RETENTION`. Every other reason is a
    #: deliberate act, is always written, and is kept for the life of the project.
    AUTOMATIC: Final[frozenset[str]] = frozenset({"handover"})


class SnapshotError(RuntimeError):
    """A snapshot operation could not be completed."""


class SnapshotNotFoundError(SnapshotError):
    """No snapshot with that id exists in this project."""


@dataclass(frozen=True, slots=True)
class SnapshotMeta:
    """Everything about a snapshot except its content.

    The history list returns these deliberately, for the reason ``DocumentMeta`` exists: drawing
    a chapter's history must not pull every version of that chapter across the wire.
    """

    id: str
    project_id: str
    document_id: str
    taken_at: str
    reason: str
    label: str
    word_count: int
    version: int
    size_bytes: int


@dataclass(frozen=True, slots=True)
class Snapshot:
    """A snapshot's metadata plus the content that was left out of it."""

    meta: SnapshotMeta
    content: dict[str, Any]


def hash_content(content_json: str) -> str:
    """The dedupe key: SHA-256 of the serialized content, as hex.

    Taken over the *serialized* form rather than the parsed one because that is what is stored
    and what is compared, and ``serialize_content`` already produces one canonical spelling for
    a given document (sorted nothing, no spaces, ``ensure_ascii=False``).
    """
    return hashlib.sha256(content_json.encode("utf-8")).hexdigest()


def clean_label(label: str) -> str:
    """Trim a snapshot label. Blank is allowed - most snapshots carry none.

    Raises:
        ValueError: If the label is longer than :data:`MAX_LABEL_LENGTH`.
    """
    label = label.strip()
    if len(label) > MAX_LABEL_LENGTH:
        raise ValueError(f"snapshot label must be at most {MAX_LABEL_LENGTH} characters")
    return label


def capture_within(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    document_id: str,
    content_json: str,
    word_count: int,
    version: int,
    reason: str,
    label: str = "",
    now: str | None = None,
) -> SnapshotMeta | None:
    """Write one snapshot inside a transaction the **caller** owns.

    This is the primitive every ``pre-*`` snapshot goes through, so that taking one and doing
    the thing it protects against are a single atomic act: a refused delete or a refused restore
    leaves no snapshot behind.

    Args:
        conn: A connection with a transaction already open.
        content_json: The serialized content to store, exactly as the document row holds it.
        reason: One of :data:`SnapshotReason.ALL`.
        now: The timestamp to stamp, so a caller can share one with the write it protects.

    Returns:
        The snapshot's metadata, or ``None`` if this is an automatic snapshot whose content the
        newest snapshot already holds, in which case nothing was written. A deliberate snapshot
        always returns its metadata.

    Raises:
        ValueError: If ``reason`` is not a known one, or the label is too long.
    """
    if reason not in SnapshotReason.ALL:
        raise ValueError(
            f"unknown snapshot reason {reason!r}; expected one of {sorted(SnapshotReason.ALL)}"
        )
    label = clean_label(label)
    now = now or utc_now()

    content_hash = hash_content(content_json)
    if reason in SnapshotReason.AUTOMATIC:
        newest = conn.execute(
            "SELECT content_hash FROM snapshot WHERE document_id = ? "
            "ORDER BY taken_at DESC, rowid DESC LIMIT 1",
            (document_id,),
        ).fetchone()
        if newest is not None and newest["content_hash"] == content_hash:
            # An unchanged chapter never accumulates snapshots (D23).
            return None

    snapshot_id = new_id(IdPrefix.SNAPSHOT)
    conn.execute(
        "INSERT INTO snapshot (id, project_id, document_id, taken_at, reason, label, "
        "content_json, content_hash, word_count, version) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            snapshot_id,
            project_id,
            document_id,
            now,
            reason,
            label,
            content_json,
            content_hash,
            word_count,
            version,
        ),
    )
    if reason in SnapshotReason.AUTOMATIC:
        _prune(conn, document_id, reason)

    return SnapshotMeta(
        id=snapshot_id,
        project_id=project_id,
        document_id=document_id,
        taken_at=now,
        reason=reason,
        label=label,
        word_count=word_count,
        version=version,
        size_bytes=len(content_json.encode("utf-8")),
    )


def _prune(conn: sqlite3.Connection, document_id: str, reason: str) -> int:
    """Drop all but the newest :data:`HANDOVER_RETENTION` snapshots of one automatic reason.

    Runs in the caller's transaction, immediately after the insert, so the ceiling is enforced
    at the moment it would otherwise be exceeded rather than by a sweep that has to be scheduled.
    """
    cursor = conn.execute(
        "DELETE FROM snapshot WHERE document_id = ? AND reason = ? AND id NOT IN ("
        "  SELECT id FROM snapshot WHERE document_id = ? AND reason = ? "
        "  ORDER BY taken_at DESC, rowid DESC LIMIT ?"
        ")",
        (document_id, reason, document_id, reason, HANDOVER_RETENTION),
    )
    return cursor.rowcount


class SnapshotStore:
    """Capture, list, read, and restore the snapshots of one project."""

    def __init__(self, handle: ProjectHandle) -> None:
        self.handle = handle
        self.documents = DocumentStore(handle)

    # -- capture ----------------------------------------------------------------------------

    def capture(
        self,
        document_id: str,
        *,
        reason: str = SnapshotReason.HANDOVER,
        label: str = "",
    ) -> SnapshotMeta | None:
        """Snapshot a document's current content.

        Returns:
            The snapshot's metadata, or ``None`` when this is an automatic snapshot whose
            content the newest snapshot already holds and nothing was written.

        Raises:
            ValueError: If ``reason`` is unknown or the label is too long.
            DocumentNotFoundError: If this project holds no such live document.
        """
        if reason not in SnapshotReason.ALL:
            raise ValueError(
                f"unknown snapshot reason {reason!r}; expected one of {sorted(SnapshotReason.ALL)}"
            )
        label = clean_label(label)

        with self.handle.connect() as conn, transaction(conn):
            row = conn.execute(
                "SELECT content_json, word_count, version FROM document "
                "WHERE id = ? AND project_id = ? AND deleted_at IS NULL",
                (document_id, self.handle.id),
            ).fetchone()
            if row is None:
                raise DocumentNotFoundError(
                    f"no document {document_id!r} in project {self.handle.id}"
                )
            return capture_within(
                conn,
                project_id=self.handle.id,
                document_id=document_id,
                content_json=row["content_json"],
                word_count=int(row["word_count"]),
                version=int(row["version"]),
                reason=reason,
                label=label,
            )

    # -- reading ----------------------------------------------------------------------------

    def list(self, document_id: str) -> list[SnapshotMeta]:
        """One document's history, newest first. Metadata only - never content.

        Deliberately not filtered by ``deleted_at``: the history of a deleted chapter is exactly
        what someone deciding whether to restore it wants to see.
        """
        with self.handle.connect() as conn:
            rows = conn.execute(
                f"SELECT {_META_COLUMNS} FROM snapshot WHERE document_id = ? AND project_id = ? "
                "ORDER BY taken_at DESC, rowid DESC",
                (document_id, self.handle.id),
            ).fetchall()
        return [_meta_from_row(row) for row in rows]

    def get(self, snapshot_id: str) -> Snapshot:
        """One snapshot including its content, for preview and diff.

        Raises:
            SnapshotNotFoundError: If this project holds no such snapshot.
        """
        with self.handle.connect() as conn:
            row = conn.execute(
                f"SELECT {_META_COLUMNS}, content_json FROM snapshot "
                "WHERE id = ? AND project_id = ?",
                (snapshot_id, self.handle.id),
            ).fetchone()
        if row is None:
            raise SnapshotNotFoundError(f"no snapshot {snapshot_id!r} in project {self.handle.id}")
        return Snapshot(meta=_meta_from_row(row), content=json.loads(row["content_json"]))

    # -- restoring --------------------------------------------------------------------------

    def restore(self, snapshot_id: str, version: int) -> SaveResult:
        """Write a snapshot's content back to its document as an ordinary save.

        The document's outgoing content is captured as ``pre-restore`` **inside the save's own
        transaction**, after the D19 version guard has passed - so a restore refused as stale
        has written nothing at all, not even the snapshot that was about to protect it.

        Args:
            snapshot_id: The version to restore.
            version: The document version the client believes it is at (D19).

        Returns:
            The save's result: the new version and the re-derived projection.

        Raises:
            SnapshotNotFoundError: If this project holds no such snapshot.
            DocumentNotFoundError: If its document is gone or soft-deleted.
            StaleVersionError: If ``version`` is not the stored one. Nothing was written.
        """
        snapshot = self.get(snapshot_id)
        document_id = snapshot.meta.document_id

        def capture_outgoing(conn: sqlite3.Connection, current_version: int) -> None:
            row = conn.execute(
                "SELECT content_json, word_count FROM document WHERE id = ? AND project_id = ?",
                (document_id, self.handle.id),
            ).fetchone()
            capture_within(
                conn,
                project_id=self.handle.id,
                document_id=document_id,
                content_json=row["content_json"],
                word_count=int(row["word_count"]),
                version=current_version,
                reason=SnapshotReason.PRE_RESTORE,
            )

        return self.documents.save_content(
            document_id,
            snapshot.content,
            version,
            before_write=capture_outgoing,
        )


_META_COLUMNS = (
    "id, project_id, document_id, taken_at, reason, label, word_count, version, "
    "LENGTH(CAST(content_json AS BLOB)) AS size_bytes"
)


def _meta_from_row(row: sqlite3.Row) -> SnapshotMeta:
    return SnapshotMeta(
        id=row["id"],
        project_id=row["project_id"],
        document_id=row["document_id"],
        taken_at=row["taken_at"],
        reason=row["reason"],
        label=row["label"],
        word_count=int(row["word_count"]),
        version=int(row["version"]),
        size_bytes=int(row["size_bytes"]),
    )
