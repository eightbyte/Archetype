"""Capture tests/fixtures/db/v001_phase1.sqlite - a real Phase 1 project file (P2-1).

Run from server/ with the venv python, while the code is still at schema version 1.
Deterministic: fixed ids and timestamps, so re-running produces the same file.
"""

from __future__ import annotations

import json
from pathlib import Path

from archetype.manuscript.projection import project
from archetype.projects import open_migrated, transaction
from archetype.projects.migrations import current_version

TARGET = Path("tests/fixtures/db/v001_phase1.sqlite")
CREATED = "2026-08-30T09:15:00Z"
UPDATED = "2026-08-30T10:42:00Z"

PROJECT_ID = "prj_v001fixture"
CHAPTERS = [
    (
        "doc_v001chapter1",
        0,
        "The Harbour",
        [(1, "The Harbour")],
        [
            "The harbour was grey that morning, and the boats had not gone out.",
            "Mira counted them twice before she believed the number.",
        ],
    ),
    (
        "doc_v001chapter2",
        1,
        "What Elias Knew",
        [(1, "What Elias Knew"), (2, "The letter")],
        [
            "Elias kept the letter folded in his coat for eleven days.",
            "By the twelfth he had stopped pretending he would burn it.",
        ],
    ),
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


def main() -> None:
    TARGET.unlink(missing_ok=True)
    for extra in (".wal", ".shm"):
        Path(str(TARGET) + extra).unlink(missing_ok=True)

    conn = open_migrated(TARGET)
    version = current_version(conn)
    if version != 1:
        raise SystemExit(f"refusing to capture: the code is at schema version {version}, not 1")

    try:
        with transaction(conn):
            conn.execute(
                "INSERT INTO project (id, title, created_at, updated_at, settings_json) "
                "VALUES (?, ?, ?, ?, '{}')",
                (PROJECT_ID, "A Phase 1 Manuscript", CREATED, UPDATED),
            )
            for doc_id, order_index, title, headings, paragraphs in CHAPTERS:
                content = build(headings, paragraphs)
                projection = project(content)
                conn.execute(
                    "INSERT INTO document (id, project_id, order_index, title, kind, "
                    "content_json, text_plain, headings_json, word_count, version, "
                    "created_at, updated_at) VALUES (?, ?, ?, ?, 'chapter', ?, ?, ?, ?, ?, ?, ?)",
                    (
                        doc_id,
                        PROJECT_ID,
                        order_index,
                        title,
                        json.dumps(content, ensure_ascii=False, separators=(",", ":")),
                        projection.text_plain,
                        json.dumps(
                            projection.headings_as_dicts(),
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                        projection.word_count,
                        3,
                        CREATED,
                        UPDATED,
                    ),
                )
        # Fold the write-ahead log back in and leave a single self-contained file behind.
        conn.execute("PRAGMA journal_mode = DELETE")
        conn.execute("VACUUM")
    finally:
        conn.close()
    print(f"captured {TARGET} ({TARGET.stat().st_size} bytes)")


main()
