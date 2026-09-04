"""Re-resolving a document's anchors inside the transaction of the write that moved them (D21).

This is the other half of D21, and the reason it is a module of its own: it is called by
:meth:`archetype.manuscript.documents.DocumentStore.save_content`, so it must not import the
document store back. Nothing here opens a connection or a transaction - it is handed the caller's
open one, and either the whole write lands or none of it does.

**The server re-resolves every anchor of a document from that document's own text on every
write, and its answer is authoritative.** It does not matter who wrote: an editor, a Markdown
import, a snapshot restore, or a Phase 6 accepted proposal all arrive through ``save_content``
and all leave the anchor rows correct. The client rebases its decorations through ProseMirror's
transaction mapping for liveness, and that rebasing is display-only - it is never sent, and
never overrides a text match.

This is **not** the ``before_write`` seam (P2-3). That runs before the row is overwritten, to
snapshot what is about to be replaced; this runs after, against the text that replaced it.
"""

from __future__ import annotations

import sqlite3

from ..projection import Projection
from .records import ANCHOR_COLUMNS, Anchor, anchor_from_row, as_record
from .resolve import context_for, resolve
from .status import AnchorStatus

__all__ = ["resolve_within"]


def resolve_within(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    document_id: str,
    projection: Projection,
    version: int,
    now: str,
) -> list[Anchor]:
    """Re-resolve one document's anchors against ``projection``, in the caller's transaction.

    Every anchor is checked and every row's ``checked_at`` is stamped, because a status is a
    statement about the text as it is *now* and a row that was not looked at cannot make one.
    ``document_version`` moves to ``version`` for an anchor that resolved, because its positions
    are true at that version; a ``stale`` anchor keeps the version its positions were last true
    at, since they are true at no version now.

    The document is assumed live: ``save_content`` filters on the soft-delete predicate, and a
    deleted chapter's anchors are ``orphaned`` by derivation rather than by resolution.

    Returns:
        The anchors whose status or position **moved**, as they now are - what the save response
        carries back, so the client does not need a second round trip on the request that
        happens most often. An empty list is the ordinary answer while someone is typing above
        their anchors rather than through them.
    """
    rows = conn.execute(
        f"SELECT {ANCHOR_COLUMNS} FROM anchor WHERE document_id = ? AND project_id = ? "
        "ORDER BY anchor.from_pos, anchor.id",
        (document_id, project_id),
    ).fetchall()
    if not rows:
        return []

    anchors = [anchor_from_row(row, document_deleted_at=None) for row in rows]
    context = context_for(projection)

    moved: list[Anchor] = []
    updates: list[tuple[str, int, int, int, str, str, str]] = []
    for anchor in anchors:
        resolution = resolve(as_record(anchor), context)
        changed = (
            resolution.status != anchor.status
            or resolution.from_pos != anchor.from_pos
            or resolution.to_pos != anchor.to_pos
        )
        resolved = anchor.with_resolution(resolution, checked_at=now)
        if changed:
            moved.append(resolved)
        updates.append(
            (
                resolved.status,
                resolved.from_pos,
                resolved.to_pos,
                version if resolution.status == AnchorStatus.OK else anchor.document_version,
                now,
                anchor.updated_at if not changed else now,
                anchor.id,
            )
        )

    conn.executemany(
        "UPDATE anchor SET status = ?, from_pos = ?, to_pos = ?, document_version = ?, "
        "checked_at = ?, updated_at = ? WHERE id = ?",
        updates,
    )
    return moved
