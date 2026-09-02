"""Capture tests/fixtures/db/v002_phase2.sqlite - a real Phase 2 project file (P3-2).

Run from server/ with the venv python, **while the code is still at schema version 2** - that is
to say before ``003_bible.sql`` exists. A fixture captured afterwards proves nothing, because it
would have been made by the very code the migration is supposed to be tested against. The script
refuses to run if the version is wrong, so that discipline is enforced rather than remembered.

What it holds, and why each piece is here (phase-3-plan P3-2):

* **two live chapters, with anchors in both** - migration 003 must carry a real manuscript and
  real anchors forward untouched;
* **one soft-deleted chapter, itself carrying an anchor** - so the file arrives at migration 003
  with the D22 predicate already in play, and with an anchor whose *effective* status is
  ``orphaned`` while its stored status is not;
* **snapshots** - one ``manual`` mark taken deliberately, and the ``pre-delete`` snapshot that
  :meth:`DocumentStore.delete` writes inside the transaction of the delete it protects.

The manuscript is built through the real stores rather than by hand-written INSERTs, so the
anchor quotes, prefixes, and suffixes are the ones the Phase 2 resolver actually derives. Ids and
timestamps are then normalised to fixed values, so re-running produces the same file.
"""

from __future__ import annotations

import json
from pathlib import Path

from archetype.manuscript.anchors.store import AnchorStore
from archetype.manuscript.documents import DocumentStore
from archetype.manuscript.snapshots import SnapshotReason, SnapshotStore
from archetype.projects import open_migrated, transaction
from archetype.projects.migrations import current_version
from archetype.projects.store import ProjectHandle

TARGET = Path("tests/fixtures/db/v002_phase2.sqlite")
CAPTURED_AT_VERSION = 2

CREATED = "2026-08-31T09:15:00Z"
UPDATED = "2026-08-31T14:20:00Z"
DELETED = "2026-08-31T14:25:00Z"

PROJECT_ID = "prj_v002phase2ff"

# Fixed ids, assigned in creation order by the normalising pass below. Every body is drawn from
# the ids.ALPHABET (no i, l, o, u), so a fixture id is a well-formed id and not merely a string.
DOCUMENT_IDS = ("doc_v002chapter1", "doc_v002chapter2", "doc_v002chapter3")
ANCHOR_IDS = ("anc_v002anchr001", "anc_v002anchr002", "anc_v002anchr003", "anc_v002anchr004")
SNAPSHOT_IDS = ("snp_v002snap0001", "snp_v002snap0002")

CHAPTERS: list[tuple[str, list[tuple[int, str]], list[str]]] = [
    (
        "The Harbour",
        [(1, "The Harbour")],
        [
            "The harbour was grey that morning, and the boats had not gone out.",
            "Mira counted them twice before she believed the number.",
        ],
    ),
    (
        "What Elias Knew",
        [(1, "What Elias Knew"), (2, "The letter")],
        [
            "Elias kept the letter folded in his coat for eleven days.",
            "By the twelfth he had stopped pretending he would burn it.",
        ],
    ),
    (
        "A Chapter Removed",
        [(1, "A Chapter Removed")],
        [
            "The lighthouse keeper had a name once, and nobody in the town could produce it.",
        ],
    ),
]

#: ``(chapter index, quoted substring, label)``. The range is found in the built document rather
#: than written as a position, so a change to the projection cannot silently move an anchor into
#: the wrong words while still producing a file that looks captured.
ANCHORS: list[tuple[int, str, str]] = [
    (0, "the boats had not gone out", "the boats"),
    (0, "Mira counted them twice", "Mira, counting"),
    (1, "folded in his coat for eleven days", "the letter"),
    (2, "The lighthouse keeper had a name once", "the keeper"),
]


def build(headings: list[tuple[int, str]], paragraphs: list[str]) -> dict:
    nodes: list[dict] = []
    for level, text in headings:
        nodes.append(
            {
                "type": "heading",
                "attrs": {"level": level},
                "content": [{"type": "text", "text": text}],
            }
        )
    for text in paragraphs:
        nodes.append({"type": "paragraph", "content": [{"type": "text", "text": text}]})
    return {"type": "doc", "content": nodes}


def prosemirror_range(content: dict, needle: str) -> tuple[int, int]:
    """The ProseMirror positions of ``needle`` in a flat heading/paragraph document.

    Every top-level block opens at the position after the one before it and costs two positions
    of its own (the open and close tokens), so a text offset inside block *n* is the sum of the
    preceding blocks' sizes plus one. The documents here are flat by construction, which is what
    makes this arithmetic honest; nothing else in the project may assume it.
    """
    position = 0
    for node in content["content"]:
        text = "".join(child["text"] for child in node.get("content", []))
        found = text.find(needle)
        if found >= 0:
            start = position + 1 + found
            return start, start + len(needle)
        position += len(text) + 2
    raise SystemExit(f"{needle!r} is not in the document; the fixture text has drifted")


def normalise(conn, documents: list[str], anchors: list[str], snapshots: list[str]) -> None:
    """Rewrite generated ids and timestamps to the fixed ones, in creation order.

    Foreign keys are deferred for the duration: renaming a document id means the ``anchor`` and
    ``snapshot`` rows pointing at it are momentarily wrong, and they are corrected in the same
    transaction. ``PRAGMA defer_foreign_keys`` is exactly the tool for that - it re-checks at
    COMMIT, so the file is never left inconsistent.
    """
    conn.execute("PRAGMA defer_foreign_keys = ON")
    for generated, fixed in zip(documents, DOCUMENT_IDS, strict=True):
        conn.execute("UPDATE document SET id = ? WHERE id = ?", (fixed, generated))
        conn.execute("UPDATE anchor SET document_id = ? WHERE document_id = ?", (fixed, generated))
        conn.execute(
            "UPDATE snapshot SET document_id = ? WHERE document_id = ?", (fixed, generated)
        )
    for generated, fixed in zip(anchors, ANCHOR_IDS, strict=True):
        conn.execute("UPDATE anchor SET id = ? WHERE id = ?", (fixed, generated))
    for generated, fixed in zip(snapshots, SNAPSHOT_IDS, strict=True):
        conn.execute("UPDATE snapshot SET id = ? WHERE id = ?", (fixed, generated))

    # The migration runner stamps its own `applied_at` with the wall clock, so pinning the rows
    # this script writes is not enough to make the file reproducible. This is the last thing in
    # it that a second run would change.
    conn.execute("UPDATE schema_version SET applied_at = ?", (CREATED,))
    conn.execute("UPDATE project SET created_at = ?, updated_at = ?", (CREATED, UPDATED))
    conn.execute("UPDATE document SET created_at = ?, updated_at = ?", (CREATED, UPDATED))
    conn.execute("UPDATE document SET deleted_at = ? WHERE deleted_at IS NOT NULL", (DELETED,))
    conn.execute(
        "UPDATE anchor SET created_at = ?, updated_at = ?, checked_at = ?",
        (CREATED, UPDATED, UPDATED),
    )
    conn.execute("UPDATE snapshot SET taken_at = ?", (UPDATED,))


def main() -> None:
    TARGET.unlink(missing_ok=True)
    for extra in (".wal", ".shm"):
        Path(str(TARGET) + extra).unlink(missing_ok=True)

    conn = open_migrated(TARGET)
    version = current_version(conn)
    if version != CAPTURED_AT_VERSION:
        raise SystemExit(
            f"refusing to capture: the code is at schema version {version}, not "
            f"{CAPTURED_AT_VERSION}. Capture this fixture before writing the next migration."
        )
    try:
        with transaction(conn):
            conn.execute(
                "INSERT INTO project (id, title, created_at, updated_at, settings_json) "
                "VALUES (?, ?, ?, ?, '{}')",
                (PROJECT_ID, "A Phase 2 Manuscript", CREATED, UPDATED),
            )
    finally:
        conn.close()

    handle = ProjectHandle(
        id=PROJECT_ID,
        title="A Phase 2 Manuscript",
        path=TARGET,
        created_at=CREATED,
        updated_at=UPDATED,
    )
    documents = DocumentStore(handle)
    anchors = AnchorStore(handle)
    snapshots = SnapshotStore(handle)

    contents: list[dict] = []
    document_ids: list[str] = []
    for title, headings, paragraphs in CHAPTERS:
        content = build(headings, paragraphs)
        contents.append(content)
        document_ids.append(documents.create(title, content=content).meta.id)

    anchor_ids: list[str] = []
    for chapter_index, needle, label in ANCHORS:
        document_id = document_ids[chapter_index]
        from_pos, to_pos = prosemirror_range(contents[chapter_index], needle)
        version_now = documents.get(document_id).meta.version
        created = anchors.create(
            document_id, from_pos=from_pos, to_pos=to_pos, version=version_now, label=label
        )
        if created.quote != needle:
            raise SystemExit(f"anchor quote is {created.quote!r}, expected {needle!r}")
        anchor_ids.append(created.id)

    snapshot_ids: list[str] = []
    marked = snapshots.capture(
        document_ids[0], reason=SnapshotReason.MANUAL, label="before the rewrite"
    )
    if marked is None:
        raise SystemExit("the manual snapshot was not written")
    snapshot_ids.append(marked.id)

    # The soft delete writes its own pre-delete snapshot, in the transaction of the delete.
    documents.delete(document_ids[2])
    pre_delete = [
        meta for meta in snapshots.list(document_ids[2]) if meta.reason == SnapshotReason.PRE_DELETE
    ]
    if len(pre_delete) != 1:
        raise SystemExit(f"expected one pre-delete snapshot, found {len(pre_delete)}")
    snapshot_ids.append(pre_delete[0].id)

    conn = open_migrated(TARGET)
    try:
        with transaction(conn):
            normalise(conn, document_ids, anchor_ids, snapshot_ids)
        # Fold the write-ahead log back in and leave a single self-contained file behind.
        conn.execute("PRAGMA journal_mode = DELETE")
        conn.execute("VACUUM")

        summary = {
            "documents": conn.execute("SELECT COUNT(*) FROM document").fetchone()[0],
            "live": conn.execute(
                "SELECT COUNT(*) FROM document WHERE deleted_at IS NULL"
            ).fetchone()[0],
            "anchors": conn.execute("SELECT COUNT(*) FROM anchor").fetchone()[0],
            "snapshots": conn.execute("SELECT COUNT(*) FROM snapshot").fetchone()[0],
        }
    finally:
        conn.close()

    print(f"captured {TARGET} ({TARGET.stat().st_size} bytes)")
    print(json.dumps(summary, indent=2))


main()
