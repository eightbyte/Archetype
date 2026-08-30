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

from archetype.projects import connect, open_migrated, transaction, utc_now
from archetype.projects.migrations import (
    MigrationError,
    current_version,
    latest_version,
    load_migrations,
    migrate,
)

from .conftest import DB_FIXTURES_DIR

TABLES = {"schema_version", "project", "document"}


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
