"""Capture tests/fixtures/db/v003_phase3.sqlite - a real Phase 3 project file (P4-4).

Run from server/ with the venv python, **while the code is still at schema version 3** - that is
to say before ``004_chat.sql`` exists. A fixture captured afterwards proves nothing, because it
would have been made by the very code the migration is supposed to be tested against. The script
refuses to run if the version is wrong, so that discipline is enforced rather than remembered.

What it holds, and why each piece is here (phase-4-plan P4-4):

* **the whole of the v002 manuscript** - two live chapters with anchors in both, one soft-deleted
  chapter that also carries an anchor, a ``manual`` snapshot and a ``pre-delete`` one - so that
  migration 004 is proved against a file where D22's predicate is already in play;
* **a bible with all four Phase 3 tables populated**: entries of three kinds, an entry created
  *from a range* (which mints an anchor, an entry, and a citation in one transaction), links in
  both a symmetric and a directed relation, a **retcon** that left a dependent flagged, and a
  **soft-deleted entry**, so D25's predicate is in play too;
* **more than one revision on one entry**, so ``entry_revision`` carries a history rather than
  only creations.

Everything is built through the real stores rather than by hand-written INSERTs, so the derived
columns - projections, anchor quotes and contexts, revision snapshots, review reasons - are the
ones the code actually produces. Ids and timestamps are then normalised to fixed values, so
re-running produces the same bytes (README.md's hash check).
"""

from __future__ import annotations

import json
from pathlib import Path

from archetype.bible.citations import CitationStore
from archetype.bible.entries import EntryStore
from archetype.bible.links import LinkStore
from archetype.bible.schema import EntryKind
from archetype.manuscript.anchors.store import AnchorStore
from archetype.manuscript.documents import DocumentStore
from archetype.manuscript.snapshots import SnapshotReason, SnapshotStore
from archetype.projects import open_migrated, transaction
from archetype.projects.migrations import current_version
from archetype.projects.store import ProjectHandle

TARGET = Path("tests/fixtures/db/v003_phase3.sqlite")
CAPTURED_AT_VERSION = 3

CREATED = "2026-09-03T09:15:00Z"
UPDATED = "2026-09-03T14:20:00Z"
DELETED = "2026-09-03T14:25:00Z"

PROJECT_ID = "prj_v003phase3ff"

# Fixed ids, assigned in creation order by the normalising pass below. Every body is drawn from
# the ids.ALPHABET (no i, l, o, u), so a fixture id is a well-formed id and not merely a string.
DOCUMENT_IDS = ("doc_v003chapter1", "doc_v003chapter2", "doc_v003chapter3")
ANCHOR_IDS = (
    "anc_v003anchr001",
    "anc_v003anchr002",
    "anc_v003anchr003",
    "anc_v003anchr004",
    "anc_v003anchr005",
)
SNAPSHOT_IDS = ("snp_v003snap0001", "snp_v003snap0002")
ENTRY_IDS = ("ent_v003entry001", "ent_v003entry002", "ent_v003entry003", "ent_v003entry004")
LINK_IDS = ("lnk_v003link0001", "lnk_v003link0002")

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

#: ``(chapter index, quoted substring, label)``, found in the built document rather than written
#: as a position - so a change to the projection cannot silently move an anchor into the wrong
#: words while still producing a file that looks captured.
ANCHORS: list[tuple[int, str, str]] = [
    (0, "the boats had not gone out", "the boats"),
    (0, "Mira counted them twice", "Mira, counting"),
    (1, "folded in his coat for eleven days", "the letter"),
    (2, "The lighthouse keeper had a name once", "the keeper"),
]

#: The fifth anchor is minted by *Add to bible* rather than by hand, which is the point of it:
#: ``create_from_range`` writes an anchor, an entry, and a citation in **one** transaction.
FROM_RANGE = (1, "Elias kept the letter", "Elias")


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
    of its own, so a text offset inside block *n* is the sum of the preceding blocks' sizes plus
    one. The documents here are flat by construction, which is what makes this arithmetic honest;
    nothing else in the project may assume it.
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


def normalise(
    conn,
    documents: list[str],
    anchors: list[str],
    snapshots: list[str],
    entries: list[str],
    links: list[str],
) -> None:
    """Rewrite generated ids and timestamps to the fixed ones, in creation order.

    Foreign keys are deferred for the duration: renaming a document id means the ``anchor`` and
    ``snapshot`` rows pointing at it are momentarily wrong, and renaming an entry id means its
    revisions, links, and citations are. ``PRAGMA defer_foreign_keys`` re-checks at COMMIT, so the
    corrections land together and the file is never left inconsistent.
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
        conn.execute(
            "UPDATE entry_anchor SET anchor_id = ? WHERE anchor_id = ?", (fixed, generated)
        )
    for generated, fixed in zip(snapshots, SNAPSHOT_IDS, strict=True):
        conn.execute("UPDATE snapshot SET id = ? WHERE id = ?", (fixed, generated))
    for generated, fixed in zip(entries, ENTRY_IDS, strict=True):
        conn.execute("UPDATE entry SET id = ? WHERE id = ?", (fixed, generated))
        conn.execute(
            "UPDATE entry_revision SET entry_id = ? WHERE entry_id = ?", (fixed, generated)
        )
        conn.execute("UPDATE entry_anchor SET entry_id = ? WHERE entry_id = ?", (fixed, generated))
        conn.execute(
            "UPDATE entry_link SET from_entry = ? WHERE from_entry = ?", (fixed, generated)
        )
        conn.execute("UPDATE entry_link SET to_entry = ? WHERE to_entry = ?", (fixed, generated))
    for generated, fixed in zip(links, LINK_IDS, strict=True):
        conn.execute("UPDATE entry_link SET id = ? WHERE id = ?", (fixed, generated))

    # A revision's snapshot_json holds the entry's full state, id included, and the review reason
    # names the entry that caused the flag. Both carry generated ids, so both are rewritten too -
    # otherwise the fixture would contain ids that point at nothing.
    for generated, fixed in zip(entries, ENTRY_IDS, strict=True):
        conn.execute(
            "UPDATE entry_revision SET snapshot_json = REPLACE(snapshot_json, ?, ?)",
            (generated, fixed),
        )
        conn.execute(
            "UPDATE entry SET review_reason = REPLACE(review_reason, ?, ?)", (generated, fixed)
        )

    # The migration runner stamps its own `applied_at` with the wall clock, so pinning the rows
    # this script writes is not enough to make the file reproducible.
    conn.execute("UPDATE schema_version SET applied_at = ?", (CREATED,))
    conn.execute("UPDATE project SET created_at = ?, updated_at = ?", (CREATED, UPDATED))
    conn.execute("UPDATE document SET created_at = ?, updated_at = ?", (CREATED, UPDATED))
    conn.execute("UPDATE document SET deleted_at = ? WHERE deleted_at IS NOT NULL", (DELETED,))
    conn.execute(
        "UPDATE anchor SET created_at = ?, updated_at = ?, checked_at = ?",
        (CREATED, UPDATED, UPDATED),
    )
    conn.execute("UPDATE snapshot SET taken_at = ?", (UPDATED,))
    conn.execute("UPDATE entry SET created_at = ?, updated_at = ?", (CREATED, UPDATED))
    conn.execute("UPDATE entry SET deleted_at = ? WHERE deleted_at IS NOT NULL", (DELETED,))
    conn.execute("UPDATE entry_revision SET revised_at = ?", (UPDATED,))
    conn.execute("UPDATE entry_link SET created_at = ?, updated_at = ?", (CREATED, UPDATED))
    conn.execute("UPDATE entry_anchor SET created_at = ?", (CREATED,))
    # The revision snapshots carry their own copies of the timestamps they were taken with -
    # including, on the revision a soft delete writes, a `deleted_at` straight off the wall
    # clock. Pinning the columns is not enough when a column holds a document (README.md).
    conn.execute(
        "UPDATE entry_revision SET snapshot_json = "
        "json_set(snapshot_json, '$.created_at', ?, '$.updated_at', ?)",
        (CREATED, UPDATED),
    )
    conn.execute(
        "UPDATE entry_revision SET snapshot_json = json_set(snapshot_json, '$.deleted_at', ?) "
        "WHERE json_extract(snapshot_json, '$.deleted_at') IS NOT NULL",
        (DELETED,),
    )


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
                (PROJECT_ID, "A Phase 3 Manuscript", CREATED, UPDATED),
            )
    finally:
        conn.close()

    handle = ProjectHandle(
        id=PROJECT_ID,
        title="A Phase 3 Manuscript",
        path=TARGET,
        created_at=CREATED,
        updated_at=UPDATED,
    )
    documents = DocumentStore(handle)
    anchors = AnchorStore(handle)
    snapshots = SnapshotStore(handle)
    entries = EntryStore(handle)
    links = LinkStore(handle)
    citations = CitationStore(handle)

    # -- the manuscript, as v002 had it -------------------------------------------------------

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

    # -- the bible ----------------------------------------------------------------------------

    entry_ids: list[str] = []

    mira = entries.create(
        EntryKind.CHARACTER,
        "Mira",
        summary="Counts the boats, twice.",
        attributes={"role": "protagonist", "aliases": ["the counter"]},
    )
    entry_ids.append(mira.id)

    harbour = entries.create(
        EntryKind.PLACE,
        "The Harbour",
        summary="Grey, and empty of boats that were meant to be out.",
        attributes={"place_type": "settlement"},
    )
    entry_ids.append(harbour.id)

    # *Add to bible* from a selection: one transaction over anchor, entry, and citation.
    chapter_index, needle, label = FROM_RANGE
    from_pos, to_pos = prosemirror_range(contents[chapter_index], needle)
    created_from_range = citations.create_from_range(
        document_ids[chapter_index],
        from_pos=from_pos,
        to_pos=to_pos,
        version=documents.get(document_ids[chapter_index]).meta.version,
        kind=EntryKind.CHARACTER,
        name="Elias",
        summary="Kept the letter for eleven days.",
        attributes={"role": "supporting"},
        label=label,
    )
    elias = created_from_range.entry
    entry_ids.append(elias.id)
    anchor_ids.append(created_from_range.anchor.id)

    # A soft-deleted entry, so D25's predicate is in play when migration 004 runs.
    letter = entries.create(
        EntryKind.ITEM,
        "The Letter",
        summary="Folded, unburnt, and not yet read on the page.",
        attributes={"item_type": "document"},
    )
    entry_ids.append(letter.id)

    link_ids = [
        links.create(mira.id, "knows", elias.id).id,
        links.create(mira.id, "located_in", harbour.id, since="the first morning").id,
    ]

    # A retcon: changing what Elias is leaves everything linked to him flagged for review (D27).
    flagged = entries.update(
        elias.id,
        elias.revision,
        summary="Kept the letter for eleven days, and had read it on the first.",
        attributes={"role": "antagonist"},
        reason="he was never on her side",
    )
    if not flagged.flagged:
        raise SystemExit("the retcon flagged nothing; the fixture would not exercise D27")

    entries.delete(letter.id)

    # -- snapshots, and the delete that writes one --------------------------------------------

    snapshot_ids: list[str] = []
    marked = snapshots.capture(
        document_ids[0], reason=SnapshotReason.MANUAL, label="before the rewrite"
    )
    if marked is None:
        raise SystemExit("the manual snapshot was not written")
    snapshot_ids.append(marked.id)

    documents.delete(document_ids[2])
    pre_delete = [
        meta for meta in snapshots.list(document_ids[2]) if meta.reason == SnapshotReason.PRE_DELETE
    ]
    if len(pre_delete) != 1:
        raise SystemExit(f"expected one pre-delete snapshot, found {len(pre_delete)}")
    snapshot_ids.append(pre_delete[0].id)

    # -- normalise, compact, and report -------------------------------------------------------

    conn = open_migrated(TARGET)
    try:
        with transaction(conn):
            normalise(conn, document_ids, anchor_ids, snapshot_ids, entry_ids, link_ids)
        conn.execute("PRAGMA journal_mode = DELETE")
        conn.execute("VACUUM")

        def count(table: str, where: str = "") -> int:
            clause = f" WHERE {where}" if where else ""
            return int(conn.execute(f"SELECT COUNT(*) FROM {table}{clause}").fetchone()[0])

        summary = {
            "documents": count("document"),
            "live_documents": count("document", "deleted_at IS NULL"),
            "anchors": count("anchor"),
            "snapshots": count("snapshot"),
            "entries": count("entry"),
            "live_entries": count("entry", "deleted_at IS NULL"),
            "entries_needing_review": count("entry", "needs_review = 1"),
            "entry_revisions": count("entry_revision"),
            "entry_links": count("entry_link"),
            "citations": count("entry_anchor"),
        }
    finally:
        conn.close()

    print(f"captured {TARGET} ({TARGET.stat().st_size} bytes)")
    print(json.dumps(summary, indent=2))


main()
