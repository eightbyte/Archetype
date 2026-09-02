"""P2-1 - the anchor status vocabulary and the one rule that derives it (D21, D22).

Small, because the rule is small. It is here on its own because both halves of it - the Python
function and the SQL expression - have to say the same thing, and the only way that stays true
is a test that asks them the same questions.

The behaviour these guard is exercised end to end in ``test_chapters.py``; this file pins the
edges, including the one mistake the split exists to prevent: writing the derived answer back
into the row.
"""

from __future__ import annotations

import sqlite3

import pytest

from archetype.manuscript.anchors import (
    ALL_STATUSES,
    EFFECTIVE_STATUS_SQL,
    STORED_STATUSES,
    AnchorStatus,
    effective_status,
)


def test_orphaned_is_not_a_stored_status() -> None:
    assert AnchorStatus.ORPHANED not in STORED_STATUSES
    assert STORED_STATUSES == {AnchorStatus.OK, AnchorStatus.STALE}
    assert ALL_STATUSES == {AnchorStatus.OK, AnchorStatus.STALE, AnchorStatus.ORPHANED}


@pytest.mark.parametrize("stored", [AnchorStatus.OK, AnchorStatus.STALE])
def test_a_live_document_reports_the_stored_answer(stored: str) -> None:
    assert effective_status(stored, None) == stored


@pytest.mark.parametrize("stored", [AnchorStatus.OK, AnchorStatus.STALE])
def test_a_deleted_document_reports_orphaned_whatever_the_text_said(stored: str) -> None:
    assert effective_status(stored, "2026-08-30T12:00:00Z") == AnchorStatus.ORPHANED


def test_a_stored_orphaned_is_refused_rather_than_returned() -> None:
    """The specific mistake the split exists to prevent, caught where it would be made."""
    with pytest.raises(ValueError, match="derived"):
        effective_status(AnchorStatus.ORPHANED, None)


def test_an_unknown_stored_status_is_refused() -> None:
    with pytest.raises(ValueError):
        effective_status("probably-fine", None)


def test_the_sql_form_agrees_with_the_python_form(migrated_db: sqlite3.Connection) -> None:
    """One rule, two spellings. A test that asks both is the only thing holding them together."""
    migrated_db.execute(
        "INSERT INTO project (id, title, created_at, updated_at) "
        "VALUES ('prj_statuscase', 'Statuses', '2026-08-30T00:00:00Z', '2026-08-30T00:00:00Z')"
    )
    cases = [
        ("doc_livestatus1", None, AnchorStatus.OK),
        ("doc_livestatus2", None, AnchorStatus.STALE),
        ("doc_deadstatus1", "2026-08-30T12:00:00Z", AnchorStatus.OK),
        ("doc_deadstatus2", "2026-08-30T12:00:00Z", AnchorStatus.STALE),
    ]
    for index, (document_id, deleted_at, stored) in enumerate(cases):
        migrated_db.execute(
            "INSERT INTO document (id, project_id, order_index, title, kind, content_json, "
            "text_plain, headings_json, word_count, version, created_at, updated_at, deleted_at) "
            "VALUES (?, 'prj_statuscase', ?, 'A Chapter', 'chapter', '{}', '', '[]', 0, 1, "
            "'2026-08-30T00:00:00Z', '2026-08-30T00:00:00Z', ?)",
            (document_id, index, deleted_at),
        )
        migrated_db.execute(
            "INSERT INTO anchor (id, project_id, document_id, from_pos, to_pos, quote, prefix, "
            "suffix, status, label, document_version, created_at, updated_at, checked_at) "
            "VALUES (?, 'prj_statuscase', ?, 1, 5, 'quote', '', '', ?, '', 1, "
            "'2026-08-30T00:00:00Z', '2026-08-30T00:00:00Z', '2026-08-30T00:00:00Z')",
            (f"anc_status{index:05d}", document_id, stored),
        )

    rows = migrated_db.execute(
        f"SELECT anchor.id AS id, {EFFECTIVE_STATUS_SQL} AS status, anchor.status AS stored, "
        "document.deleted_at AS deleted_at FROM anchor "
        "JOIN document ON document.id = anchor.document_id ORDER BY anchor.id"
    ).fetchall()

    assert len(rows) == len(cases)
    for row in rows:
        assert row["status"] == effective_status(row["stored"], row["deleted_at"])
