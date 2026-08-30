"""P1-4 - creating, opening, and listing projects (D17)."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from archetype.ids import IdPrefix, is_id
from archetype.projects import (
    ProjectNotFoundError,
    ProjectStore,
    latest_version,
    open_migrated,
    slugify,
    utc_now,
)

# -- creation -------------------------------------------------------------------------------


def test_create_writes_a_migrated_file_with_a_project_row(store: ProjectStore) -> None:
    handle = store.create("The Long Road")

    assert is_id(handle.id, IdPrefix.PROJECT)
    assert handle.title == "The Long Road"
    assert handle.path.is_file()
    assert handle.path.parent == store.projects_dir

    with handle.connect() as conn:
        row = conn.execute("SELECT * FROM project").fetchone()
        assert row["id"] == handle.id
        assert row["title"] == "The Long Road"
        assert row["settings_json"] == "{}"
        assert row["created_at"] == row["updated_at"] == handle.created_at
        version = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
        assert version == latest_version()


def test_the_filename_is_a_readable_slug_plus_a_suffix(store: ProjectStore) -> None:
    handle = store.create("The Long Road")
    stem = handle.path.stem
    assert handle.path.suffix == ".sqlite"
    assert stem.startswith("the-long-road-")
    assert len(stem.rsplit("-", 1)[1]) == 6


def test_two_projects_with_the_same_title_get_different_files(store: ProjectStore) -> None:
    first = store.create("Same Name")
    second = store.create("Same Name")

    assert first.path != second.path
    assert first.id != second.id
    assert {p.id for p in store.list_projects()} == {first.id, second.id}


def test_create_makes_the_projects_directory_if_it_is_absent(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "data" / "projects")
    handle = store.create("First Ever")
    assert handle.path.is_file()


@pytest.mark.parametrize("title", ["", "   ", "\n\t"])
def test_a_blank_title_is_rejected(store: ProjectStore, title: str) -> None:
    with pytest.raises(ValueError, match="blank"):
        store.create(title)
    assert list(store.projects_dir.glob("*.sqlite")) == []


def test_an_overlong_title_is_rejected(store: ProjectStore) -> None:
    with pytest.raises(ValueError, match="at most"):
        store.create("x" * 201)


def test_the_title_is_stripped(store: ProjectStore) -> None:
    assert store.create("  Padded  ").title == "Padded"


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("The Long Road", "the-long-road"),
        ("A Tale: Part II", "a-tale-part-ii"),
        ("  spaced  out  ", "spaced-out"),
        ("Émile's Journey", "emiles-journey"),
        ("!!!", "project"),
        ("...", "project"),
        ("x" * 100, "x" * 48),
    ],
)
def test_slugify(title: str, expected: str) -> None:
    assert slugify(title) == expected


def test_a_title_of_only_non_ascii_still_produces_a_usable_filename(store: ProjectStore) -> None:
    handle = store.create("物語")
    assert handle.path.stem.startswith("project-")
    assert handle.path.is_file()


# -- listing (D17) --------------------------------------------------------------------------


def test_listing_an_empty_directory_returns_nothing(store: ProjectStore) -> None:
    assert store.list_projects() == []


def test_listing_a_missing_directory_returns_nothing(tmp_path: Path) -> None:
    assert ProjectStore(tmp_path / "nope").list_projects() == []


def test_list_reports_title_counts_and_timestamps(store: ProjectStore) -> None:
    handle = store.create("Counted")
    now = utc_now()
    with handle.connect() as conn:
        for index in range(3):
            conn.execute(
                "INSERT INTO document (id, project_id, order_index, title, kind, content_json, "
                "text_plain, headings_json, word_count, version, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, 'chapter', '{}', '', '[]', ?, 1, ?, ?)",
                (f"doc_chapter{index:05d}", handle.id, index, f"Chapter {index}", 100, now, now),
            )

    [summary] = store.list_projects()
    assert summary.id == handle.id
    assert summary.title == "Counted"
    assert summary.chapter_count == 3
    assert summary.word_count == 300
    assert summary.schema_version == latest_version()
    assert summary.to_handle().path == handle.path


def test_list_is_ordered_by_most_recently_updated(store: ProjectStore) -> None:
    older = store.create("Older")
    newer = store.create("Newer")
    with older.connect() as conn:
        conn.execute("UPDATE project SET updated_at = '2020-01-01T00:00:00Z'")
    with newer.connect() as conn:
        conn.execute("UPDATE project SET updated_at = '2030-01-01T00:00:00Z'")

    assert [p.title for p in store.list_projects()] == ["Newer", "Older"]


def test_a_project_file_copied_in_from_a_backup_is_listed(
    store: ProjectStore, tmp_path: Path
) -> None:
    # D3: backup is a file copy. A file dropped into the directory simply appears.
    elsewhere = tmp_path / "backup"
    elsewhere.mkdir()
    source = ProjectStore(elsewhere).create("Restored From Backup")
    shutil.copyfile(source.path, store.projects_dir / "restored-from-backup-aaaaaa.sqlite")

    [summary] = store.list_projects()
    assert summary.id == source.id
    assert summary.title == "Restored From Backup"

    handle = store.open(summary.id)
    assert handle.path.name == "restored-from-backup-aaaaaa.sqlite"


def test_a_non_archetype_sqlite_file_is_skipped_not_crashed(store: ProjectStore) -> None:
    stranger = store.projects_dir / "someone-elses-app.sqlite"
    conn = sqlite3.connect(stranger)
    conn.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT)")
    conn.commit()
    conn.close()

    mine = store.create("Mine")
    result = store.scan()

    assert [p.id for p in result.projects] == [mine.id]
    assert [(s.path.name, s.reason) for s in result.skipped] == [
        ("someone-elses-app.sqlite", "not-an-archetype-project")
    ]


def test_a_corrupt_file_is_reported_without_taking_down_the_list(store: ProjectStore) -> None:
    good = store.create("Good")
    (store.projects_dir / "corrupt.sqlite").write_bytes(b"this is not a database at all")

    result = store.scan()
    assert [p.id for p in result.projects] == [good.id]
    assert [s.reason for s in result.skipped] == ["unreadable"]
    assert result.skipped[0].detail


def test_an_empty_file_is_skipped(store: ProjectStore) -> None:
    (store.projects_dir / "empty.sqlite").touch()
    result = store.scan()
    assert result.projects == []
    assert [s.reason for s in result.skipped] == ["not-an-archetype-project"]


def test_a_migrated_file_with_no_project_row_is_skipped(store: ProjectStore) -> None:
    open_migrated(store.projects_dir / "no-row.sqlite").close()
    result = store.scan()
    assert result.projects == []
    assert [s.reason for s in result.skipped] == ["empty"]


def test_non_sqlite_files_are_ignored_entirely(store: ProjectStore) -> None:
    (store.projects_dir / "notes.txt").write_text("not a project", encoding="utf-8")
    (store.projects_dir / "readme.md").write_text("# not a project", encoding="utf-8")
    store.create("Real")

    result = store.scan()
    assert len(result.projects) == 1
    assert result.skipped == []


def test_scanning_does_not_modify_the_files_it_reads(store: ProjectStore) -> None:
    handle = store.create("Untouched")
    before = handle.path.stat().st_mtime_ns
    store.scan()
    assert handle.path.stat().st_mtime_ns == before


# -- opening --------------------------------------------------------------------------------


def test_open_resolves_an_id_to_a_handle(store: ProjectStore) -> None:
    created = store.create("Openable")
    opened = store.open(created.id)

    assert opened.id == created.id
    assert opened.title == created.title
    assert opened.path == created.path
    assert opened.created_at == created.created_at


def test_open_picks_the_right_project_out_of_several(store: ProjectStore) -> None:
    handles = [store.create(f"Book {n}") for n in range(4)]
    for handle in handles:
        assert store.open(handle.id).title == handle.title


def test_opening_an_unknown_id_raises(store: ProjectStore) -> None:
    store.create("Only One")
    with pytest.raises(ProjectNotFoundError, match="prj_doesnotexist"):
        store.open("prj_doesnotexist")


def test_find_returns_none_for_an_unknown_id(store: ProjectStore) -> None:
    assert store.find("prj_doesnotexist") is None


def test_open_path_resolves_a_file_directly(store: ProjectStore) -> None:
    created = store.create("By Path")
    assert store.open_path(created.path).id == created.id


def test_a_handle_connection_is_usable_and_closes(store: ProjectStore) -> None:
    handle = store.create("Connectable")
    with handle.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM project").fetchone()[0] == 1
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


def test_touch_advances_updated_at(store: ProjectStore) -> None:
    handle = store.create("Touched")
    with handle.connect() as conn:
        conn.execute("UPDATE project SET updated_at = '2020-01-01T00:00:00Z'")

    stamped = store.touch(handle.id)
    assert stamped > "2020-01-01T00:00:00Z"
    assert store.open(handle.id).updated_at == stamped
