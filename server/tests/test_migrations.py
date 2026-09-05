"""P1-3 - the schema, the connection pragmas, and the migration runner (D20).

The fixture-database test is the pattern every later migration follows: take a database captured
at version N-1, run the runner, assert it reaches N. ``tests/fixtures/db/README.md`` explains how
to capture the next one.
"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from archetype.bible.citations import CitationStore
from archetype.bible.entries import EntryStore
from archetype.bible.links import LinkStore
from archetype.manuscript.anchors.store import AnchorStore
from archetype.manuscript.documents import DocumentStore
from archetype.manuscript.snapshots import SnapshotStore
from archetype.projects import ProjectStore, connect, open_migrated, transaction, utc_now
from archetype.projects.migrations import (
    MigrationError,
    current_version,
    latest_version,
    load_migrations,
    migrate,
)

from .conftest import DB_FIXTURES_DIR

TABLES = {
    "schema_version",
    "project",
    "document",
    "anchor",
    "snapshot",
    "entry",
    "entry_revision",
    "entry_link",
    "entry_anchor",
    "conversation",
    "message",
}


def table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {row["name"] for row in rows}


def column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


# -- the migration set --------------------------------------------------------------------


def test_migrations_are_numbered_consecutively_from_one() -> None:
    migrations = load_migrations()
    assert [m.version for m in migrations] == list(range(1, len(migrations) + 1))
    assert migrations[0].slug == "init"


def test_a_malformed_migration_filename_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "init.sql").write_text("SELECT 1;", encoding="utf-8")
    with pytest.raises(MigrationError, match="not a valid migration name"):
        load_migrations(tmp_path)


def test_a_gap_in_the_sequence_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "001_init.sql").write_text("SELECT 1;", encoding="utf-8")
    (tmp_path / "003_later.sql").write_text("SELECT 1;", encoding="utf-8")
    with pytest.raises(MigrationError, match="consecutive"):
        load_migrations(tmp_path)


# -- applying -----------------------------------------------------------------------------


def test_a_fresh_file_migrates_to_the_current_version(tmp_path: Path) -> None:
    path = tmp_path / "fresh.sqlite"
    conn = open_migrated(path)
    try:
        assert current_version(conn) == latest_version()
        assert TABLES <= table_names(conn)
    finally:
        conn.close()
    assert path.exists()


def test_reopening_an_up_to_date_file_is_a_no_op(tmp_path: Path) -> None:
    path = tmp_path / "reopened.sqlite"
    conn = open_migrated(path)
    applied_first = conn.execute("SELECT version, applied_at FROM schema_version").fetchall()
    conn.close()

    conn = open_migrated(path)
    try:
        applied_again = conn.execute("SELECT version, applied_at FROM schema_version").fetchall()
        assert migrate(conn) == latest_version()
    finally:
        conn.close()

    assert [tuple(r) for r in applied_first] == [tuple(r) for r in applied_again]


def test_a_version_0_fixture_database_migrates_forward(tmp_path: Path) -> None:
    # The pattern every later migration follows: a database captured at the previous version.
    fixture = DB_FIXTURES_DIR / "v000_empty.sqlite"
    assert fixture.is_file(), "the version-0 fixture database is missing"

    path = tmp_path / "from_fixture.sqlite"
    shutil.copyfile(fixture, path)

    conn = connect(path)
    try:
        assert current_version(conn) == 0
        assert migrate(conn) == latest_version()
        assert TABLES <= table_names(conn)
    finally:
        conn.close()


# -- migration 002 (P2-1, D22, D23) ---------------------------------------------------------
#
# The item data-model section 8 says the whole migration pattern exists for: a real Phase 1
# project file, captured before this migration was written, carried forward with its manuscript
# intact. `tests/fixtures/db/capture_v001_phase1.py` is how it was made.


def test_a_version_1_fixture_database_migrates_forward(tmp_path: Path) -> None:
    fixture = DB_FIXTURES_DIR / "v001_phase1.sqlite"
    assert fixture.is_file(), "the version-1 fixture database is missing"

    path = tmp_path / "from_v001.sqlite"
    shutil.copyfile(fixture, path)

    conn = connect(path)
    try:
        assert current_version(conn) == 1
        before = [
            tuple(row)
            for row in conn.execute(
                "SELECT id, title, content_json, text_plain, word_count, version FROM document "
                "ORDER BY order_index"
            )
        ]
        assert len(before) == 2, "the fixture is meant to hold two written chapters"

        # Since P3-2 this is two steps in one open - 001 -> 002 -> 003 - which is the property
        # forward-only migrations are supposed to have and had never been exercised before.
        assert migrate(conn) == latest_version()
        assert current_version(conn) == latest_version()
        assert TABLES <= table_names(conn)

        after = [
            tuple(row)
            for row in conn.execute(
                "SELECT id, title, content_json, text_plain, word_count, version FROM document "
                "ORDER BY order_index"
            )
        ]
        assert after == before, "no migration may touch a single word of the manuscript"
        assert [row["deleted_at"] for row in conn.execute("SELECT deleted_at FROM document")] == [
            None,
            None,
        ], "every chapter that predates the soft delete is live"
    finally:
        conn.close()


def test_the_migrated_v1_fixture_is_readable_through_the_document_store(tmp_path: Path) -> None:
    """The migration is not done when the schema changes - it is done when the store can read."""
    path = tmp_path / "readable.sqlite"
    shutil.copyfile(DB_FIXTURES_DIR / "v001_phase1.sqlite", path)

    handle = ProjectStore(path.parent).open_path(path)
    documents = DocumentStore(handle)

    metas = documents.list_meta()
    assert [meta.title for meta in metas] == ["The Harbour", "What Elias Knew"]
    assert all(meta.deleted_at is None for meta in metas)

    first = documents.get(metas[0].id)
    assert "The harbour was grey that morning" in first.text_plain
    assert first.meta.version == 3, "a migration does not touch a document's version"
    assert [chapter.title for chapter in documents.outline()] == [
        "The Harbour",
        "What Elias Knew",
    ]


def test_the_anchor_table_has_the_planned_columns(migrated_db: sqlite3.Connection) -> None:
    assert column_names(migrated_db, "anchor") == {
        "id",
        "project_id",
        "document_id",
        "from_pos",
        "to_pos",
        "quote",
        "prefix",
        "suffix",
        "status",
        "label",
        "document_version",
        "created_at",
        "updated_at",
        "checked_at",
    }


def test_the_snapshot_table_has_the_planned_columns(migrated_db: sqlite3.Connection) -> None:
    assert column_names(migrated_db, "snapshot") == {
        "id",
        "project_id",
        "document_id",
        "taken_at",
        "reason",
        "label",
        "content_json",
        "content_hash",
        "word_count",
        "version",
    }


def test_the_phase_2_indexes_exist(migrated_db: sqlite3.Connection) -> None:
    names = {
        row["name"]
        for row in migrated_db.execute("SELECT name FROM sqlite_master WHERE type = 'index'")
    }
    assert {
        "idx_anchor_document",
        "idx_anchor_project_status",
        "idx_snapshot_document",
    } <= names


# -- migration 003 (P3-2, D25, D26, D27, D28) -----------------------------------------------
#
# `tests/fixtures/db/capture_v002_phase2.py` made the fixture, before this migration existed:
# two live chapters with anchors in both, one soft-deleted chapter that also carries an anchor,
# and two snapshots. The soft-deleted chapter is the point - it means 003 is proved against a
# file with the D22 predicate already in play.


def test_a_version_2_fixture_database_migrates_forward(tmp_path: Path) -> None:
    fixture = DB_FIXTURES_DIR / "v002_phase2.sqlite"
    assert fixture.is_file(), "the version-2 fixture database is missing"

    path = tmp_path / "from_v002.sqlite"
    shutil.copyfile(fixture, path)

    conn = connect(path)
    try:
        assert current_version(conn) == 2

        def phase_2_rows() -> dict[str, list[tuple]]:
            return {
                "document": [
                    tuple(row)
                    for row in conn.execute(
                        "SELECT id, title, content_json, text_plain, word_count, version, "
                        "deleted_at FROM document ORDER BY id"
                    )
                ],
                "anchor": [tuple(row) for row in conn.execute("SELECT * FROM anchor ORDER BY id")],
                "snapshot": [
                    tuple(row) for row in conn.execute("SELECT * FROM snapshot ORDER BY id")
                ],
            }

        before = phase_2_rows()
        assert len(before["document"]) == 3, "three chapters, one of them soft-deleted"
        assert len(before["anchor"]) == 4, "anchors in all three chapters"
        assert len(before["snapshot"]) == 2, "a manual mark and the delete's pre-delete snapshot"

        # Since P4-4 this is two steps in one open - 002 -> 003 -> 004 - exactly as the
        # version-1 fixture became a multi-step migration at P3-2. What the test is *about* is
        # unchanged: a real Phase 2 file arrives with its manuscript untouched.
        assert migrate(conn) == latest_version()
        assert current_version(conn) == latest_version()
        assert TABLES <= table_names(conn)

        assert phase_2_rows() == before, (
            "no migration after 002 may touch document, anchor, or snapshot"
        )
        for table in ("entry", "entry_revision", "entry_link", "entry_anchor"):
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, (
                f"{table} arrives empty; a migration does not invent bible records"
            )
    finally:
        conn.close()


def test_the_migrated_v2_fixture_is_readable_through_its_stores(tmp_path: Path) -> None:
    """A migration is not done when the schema changes - it is done when the stores can read."""
    path = tmp_path / "readable_v002.sqlite"
    shutil.copyfile(DB_FIXTURES_DIR / "v002_phase2.sqlite", path)

    handle = ProjectStore(path.parent).open_path(path)
    documents = DocumentStore(handle)
    anchors = AnchorStore(handle)
    snapshots = SnapshotStore(handle)

    metas = documents.list_meta()
    assert [meta.title for meta in metas] == ["The Harbour", "What Elias Knew"]
    assert [meta.title for meta in documents.list_deleted()] == ["A Chapter Removed"]

    first = documents.get(metas[0].id)
    assert "The harbour was grey that morning" in first.text_plain

    # Anchors survive with their quotes, and the one on the deleted chapter still reads as
    # orphaned - derived from `deleted_at`, which migration 003 did not touch either (D22).
    project_anchors = anchors.list_for_project()
    assert len(project_anchors) == 4
    assert {anchor.quote for anchor in project_anchors} == {
        "the boats had not gone out",
        "Mira counted them twice",
        "folded in his coat for eleven days",
        "The lighthouse keeper had a name once",
    }
    statuses = sorted(anchor.status for anchor in project_anchors)
    assert statuses == ["ok", "ok", "ok", "orphaned"]

    assert [meta.reason for meta in snapshots.list(metas[0].id)] == ["manual"]


def test_the_entry_table_has_the_planned_columns(migrated_db: sqlite3.Connection) -> None:
    assert column_names(migrated_db, "entry") == {
        "id",
        "project_id",
        "kind",
        "name",
        "summary",
        "body_md",
        "attributes_json",
        "status",
        "origin",
        "revision",
        "needs_review",
        "review_reason",
        "created_at",
        "updated_at",
        "deleted_at",
    }


def test_the_entry_revision_table_has_the_planned_columns(migrated_db: sqlite3.Connection) -> None:
    assert column_names(migrated_db, "entry_revision") == {
        "entry_id",
        "revision",
        "revised_at",
        "reason",
        "retcon",
        "origin",
        "snapshot_json",
    }


def test_the_entry_link_table_has_the_planned_columns(migrated_db: sqlite3.Connection) -> None:
    assert column_names(migrated_db, "entry_link") == {
        "id",
        "project_id",
        "from_entry",
        "to_entry",
        "relation",
        "attributes_json",
        "since",
        "until",
        "created_at",
        "updated_at",
        "deleted_at",
    }


def test_the_entry_anchor_table_has_the_planned_columns(migrated_db: sqlite3.Connection) -> None:
    assert column_names(migrated_db, "entry_anchor") == {
        "entry_id",
        "anchor_id",
        "role",
        "created_at",
    }


def test_the_phase_3_indexes_exist(migrated_db: sqlite3.Connection) -> None:
    names = {
        row["name"]
        for row in migrated_db.execute("SELECT name FROM sqlite_master WHERE type = 'index'")
    }
    assert {
        "idx_entry_project_kind",
        "idx_entry_review",
        "idx_link_from",
        "idx_link_to",
        "idx_entry_anchor_anchor",
    } <= names


def test_migration_003_changed_no_manuscript_column(migrated_db: sqlite3.Connection) -> None:
    """Extension-only, and specifically: Phase 3 adds no manuscript behaviour (plan section 1)."""
    assert column_names(migrated_db, "snapshot") == {
        "id",
        "project_id",
        "document_id",
        "taken_at",
        "reason",
        "label",
        "content_json",
        "content_hash",
        "word_count",
        "version",
    }
    assert "deleted_at" in column_names(migrated_db, "document")


# -- migration 004 (P4-4, D30) --------------------------------------------------------------
#
# `tests/fixtures/db/capture_v003_phase3.py` made the fixture, before this migration existed: the
# whole of the v002 manuscript plus a bible with all four of its tables populated - an entry made
# *from a range*, links in a symmetric and a directed relation, a retcon that left a dependent
# flagged, and a soft-deleted entry. Both soft deletes are the point: 004 is proved against a file
# with D22's and D25's predicates already in play.


def test_a_version_3_fixture_database_migrates_forward(tmp_path: Path) -> None:
    fixture = DB_FIXTURES_DIR / "v003_phase3.sqlite"
    assert fixture.is_file(), "the version-3 fixture database is missing"

    path = tmp_path / "from_v003.sqlite"
    shutil.copyfile(fixture, path)

    conn = connect(path)
    try:
        assert current_version(conn) == 3

        def phase_3_rows() -> dict[str, list[tuple]]:
            return {
                table: [tuple(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY 1, 2")]
                for table in (
                    "document",
                    "anchor",
                    "snapshot",
                    "entry",
                    "entry_revision",
                    "entry_link",
                    "entry_anchor",
                )
            }

        before = phase_3_rows()
        assert len(before["document"]) == 3, "three chapters, one of them soft-deleted"
        assert len(before["anchor"]) == 5, "four made by hand and one minted by *Add to bible*"
        assert len(before["entry"]) == 4, "three live entries and one soft-deleted"
        assert len(before["entry_link"]) == 2
        assert len(before["entry_anchor"]) == 1, "the citation create_from_range wrote"

        assert migrate(conn) == 4
        assert current_version(conn) == 4
        assert TABLES <= table_names(conn)

        assert phase_3_rows() == before, (
            "migration 004 adds two tables and must not touch one row of the manuscript or the "
            "bible"
        )
        for table in ("conversation", "message"):
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, (
                f"{table} arrives empty; a migration does not invent a conversation"
            )
    finally:
        conn.close()


def test_the_migrated_v3_fixture_is_readable_through_its_stores(tmp_path: Path) -> None:
    """A migration is not done when the schema changes - it is done when the stores can read.

    Every Phase 3 surface at once, because the failure this catches is a migration that leaves
    the file *openable* and one join wrong.
    """
    path = tmp_path / "readable_v003.sqlite"
    shutil.copyfile(DB_FIXTURES_DIR / "v003_phase3.sqlite", path)

    handle = ProjectStore(path.parent).open_path(path)
    documents = DocumentStore(handle)
    anchors = AnchorStore(handle)
    entries = EntryStore(handle)
    links = LinkStore(handle)
    citations = CitationStore(handle)

    metas = documents.list_meta()
    assert [meta.title for meta in metas] == ["The Harbour", "What Elias Knew"]
    assert [meta.title for meta in documents.list_deleted()] == ["A Chapter Removed"]
    assert len(anchors.list_for_project()) == 5

    live = entries.list()
    assert sorted(entry.name for entry in live) == ["Elias", "Mira", "The Harbour"]
    assert [entry.name for entry in entries.list(needs_review=True)] == ["Mira"], (
        "the retcon captured in the fixture left its dependent flagged, and a migration does not "
        "clear a review queue"
    )
    assert [entry.name for entry in entries.list(include_deleted=True) if entry.deleted_at] == [
        "The Letter"
    ]

    mira = next(entry for entry in live if entry.name == "Mira")
    elias = next(entry for entry in live if entry.name == "Elias")
    assert {view.link.relation for view in links.for_entry(mira.id)} == {"knows", "located_in"}
    assert len(entries.revisions(elias.id)) == 2, "creation, and the retcon that followed it"

    cited = citations.citations(elias.id)
    assert [citation.anchor.quote for citation in cited] == ["Elias kept the letter"]
    assert cited[0].anchor.status == "ok", "the passage is still where the anchor left it"


def test_the_conversation_table_has_the_planned_columns(migrated_db: sqlite3.Connection) -> None:
    assert column_names(migrated_db, "conversation") == {
        "id",
        "project_id",
        "title",
        "created_at",
        "updated_at",
        "deleted_at",
    }


def test_the_message_table_has_the_planned_columns(migrated_db: sqlite3.Connection) -> None:
    """The plan's DDL plus `stop_reason`, which is deviation `A1` (phase-4-plan section 7)."""
    assert column_names(migrated_db, "message") == {
        "id",
        "conversation_id",
        "ord",
        "role",
        "content",
        "context_json",
        "provider",
        "model",
        "usage_json",
        "stop_reason",
        "error_code",
        "created_at",
    }


def test_a_message_has_no_version_column_and_no_soft_delete(
    migrated_db: sqlite3.Connection,
) -> None:
    """D30: an assistant turn is never edited, so there is nothing for D19 to guard.

    A conversation is soft-deleted whole; a message inside one is not independently removable,
    because a transcript with a hole in it is a record of a conversation that did not happen.
    """
    columns = column_names(migrated_db, "message")
    assert "version" not in columns
    assert "revision" not in columns
    assert "deleted_at" not in columns
    assert "deleted_at" in column_names(migrated_db, "conversation")


def test_the_phase_4_indexes_exist(migrated_db: sqlite3.Connection) -> None:
    names = {
        row["name"]
        for row in migrated_db.execute("SELECT name FROM sqlite_master WHERE type = 'index'")
    }
    assert {"idx_conversation_project", "idx_message_conversation"} <= names


def test_two_messages_cannot_share_a_position_in_one_conversation(
    migrated_db: sqlite3.Connection,
) -> None:
    """`ord` is the transcript's order, so a duplicate is a transcript that cannot be read back."""
    with transaction(migrated_db):
        migrated_db.execute(
            "INSERT INTO project (id, title, created_at, updated_at, settings_json) "
            "VALUES ('prj_migration04', 'x', ?, ?, '{}')",
            (utc_now(), utc_now()),
        )
        migrated_db.execute(
            "INSERT INTO conversation (id, project_id, title, created_at, updated_at) "
            "VALUES ('cnv_migration004', 'prj_migration04', 'x', ?, ?)",
            (utc_now(), utc_now()),
        )
        migrated_db.execute(
            "INSERT INTO message (id, conversation_id, ord, role, content, created_at) "
            "VALUES ('msg_migration0001', 'cnv_migration004', 1, 'user', 'hello', ?)",
            (utc_now(),),
        )
    with pytest.raises(sqlite3.IntegrityError), transaction(migrated_db):
        migrated_db.execute(
            "INSERT INTO message (id, conversation_id, ord, role, content, created_at) "
            "VALUES ('msg_migration0002', 'cnv_migration004', 1, 'assistant', 'hi', ?)",
            (utc_now(),),
        )


def test_migration_004_changed_no_manuscript_or_bible_column(
    migrated_db: sqlite3.Connection,
) -> None:
    """Extension-only, and specifically: Phase 4 writes to neither of them (plan section 1)."""
    assert column_names(migrated_db, "entry") == {
        "id",
        "project_id",
        "kind",
        "name",
        "summary",
        "body_md",
        "attributes_json",
        "status",
        "origin",
        "revision",
        "needs_review",
        "review_reason",
        "created_at",
        "updated_at",
        "deleted_at",
    }
    assert "deleted_at" in column_names(migrated_db, "document")
    assert "content_hash" in column_names(migrated_db, "snapshot")


def test_a_file_newer_than_this_build_is_refused(tmp_path: Path) -> None:
    conn = open_migrated(tmp_path / "future.sqlite")
    try:
        with transaction(conn):
            conn.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                (latest_version() + 1, utc_now()),
            )
        with pytest.raises(MigrationError, match="newer than this build"):
            migrate(conn)
    finally:
        conn.close()


def test_a_failing_migration_leaves_no_partial_schema(tmp_path: Path) -> None:
    directory = tmp_path / "migrations"
    directory.mkdir()
    (directory / "001_init.sql").write_text(
        "CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);\n"
        "CREATE TABLE good (id TEXT PRIMARY KEY);\n"
        "CREATE TABLE bad (this is not valid sql;\n",
        encoding="utf-8",
    )

    conn = connect(tmp_path / "broken.sqlite")
    try:
        with pytest.raises(MigrationError, match="rolled back"):
            migrate(conn, directory=directory)
        assert not conn.in_transaction
        assert "good" not in table_names(conn), "a failed migration must not leave half a schema"
        assert current_version(conn) == 0
    finally:
        conn.close()


# -- the Phase 1 schema (P1-3) --------------------------------------------------------------


def test_the_document_table_has_the_planned_columns(migrated_db: sqlite3.Connection) -> None:
    assert column_names(migrated_db, "document") == {
        "id",
        "project_id",
        "order_index",
        "title",
        "kind",
        "content_json",
        "text_plain",
        "headings_json",
        "word_count",
        "version",
        "created_at",
        "updated_at",
        # Added by migration 002 (D22). NULL means live.
        "deleted_at",
    }


def test_the_project_table_has_the_planned_columns(migrated_db: sqlite3.Connection) -> None:
    assert column_names(migrated_db, "project") == {
        "id",
        "title",
        "created_at",
        "updated_at",
        "settings_json",
    }


# -- connection handling --------------------------------------------------------------------


def test_the_standard_pragmas_are_set(migrated_db: sqlite3.Connection) -> None:
    assert migrated_db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert migrated_db.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert migrated_db.execute("PRAGMA busy_timeout").fetchone()[0] > 0


def test_foreign_keys_are_enforced(migrated_db: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError), transaction(migrated_db):
        migrated_db.execute(
            "INSERT INTO document (id, project_id, order_index, title, kind, content_json, "
            "text_plain, headings_json, word_count, version, created_at, updated_at) "
            "VALUES ('doc_aaaaaaaaaaaa', 'prj_missing00', 0, 'Orphan', 'chapter', '{}', '', "
            "'[]', 0, 1, ?, ?)",
            (utc_now(), utc_now()),
        )


def test_a_transaction_rolls_back_on_error(migrated_db: sqlite3.Connection) -> None:
    now = utc_now()
    with pytest.raises(RuntimeError), transaction(migrated_db):
        migrated_db.execute(
            "INSERT INTO project (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            ("prj_rollback001", "Doomed", now, now),
        )
        raise RuntimeError("something went wrong mid-write")

    assert migrated_db.execute("SELECT COUNT(*) FROM project").fetchone()[0] == 0
    assert not migrated_db.in_transaction


def test_a_read_only_connection_cannot_write(tmp_path: Path) -> None:
    path = tmp_path / "readonly.sqlite"
    open_migrated(path).close()

    conn = connect(path, read_only=True)
    try:
        assert current_version(conn) == latest_version()
        with pytest.raises(sqlite3.OperationalError):
            conn.execute(
                "INSERT INTO project (id, title, created_at, updated_at) "
                "VALUES ('prj_readonly01', 'No', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"
            )
    finally:
        conn.close()


def test_utc_now_is_iso_8601_zulu() -> None:
    value = utc_now()
    assert value.endswith("Z")
    assert "T" in value
    assert len(value) == len("2026-08-29T12:00:00Z")
