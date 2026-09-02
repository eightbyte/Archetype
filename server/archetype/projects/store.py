"""The project store (P1-4).

One SQLite file per project (D3), discovered by scanning ``<data_dir>/projects/*.sqlite`` (D17).
There is no registry file: a registry is a second source of truth that can disagree with the
filesystem, and D3 already promises that backup is a file copy. A project file dropped into the
directory simply appears; one deleted simply goes.

Files are named from a slug of the title plus a short suffix - ``the-long-road-4k2h9w.sqlite`` -
so the directory reads like a shelf and a copied file is a portable project.

:class:`ProjectHandle` is the resolved scope every later service takes: it knows the project's
identity and how to open its file. Nothing above this layer builds a path by hand.
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from ..ids import IdPrefix, new_id, random_token
from .db import connect, transaction, utc_now
from .migrations import current_version, migrate, open_migrated

__all__ = [
    "PROJECT_FILE_SUFFIX",
    "ProjectHandle",
    "ProjectNotFoundError",
    "ProjectStore",
    "ProjectStoreError",
    "ProjectSummary",
    "ScanResult",
    "SkippedFile",
    "slugify",
]

PROJECT_FILE_SUFFIX = ".sqlite"

_SLUG_MAX_LENGTH = 48
_SLUG_FALLBACK = "project"
_SUFFIX_LENGTH = 6
_TITLE_MAX_LENGTH = 200


class ProjectStoreError(RuntimeError):
    """The project store could not complete an operation."""


class ProjectNotFoundError(ProjectStoreError):
    """No project file in the directory holds the requested id."""


@dataclass(frozen=True, slots=True)
class ProjectHandle:
    """A resolved project: its identity plus its file.

    Every later service is scoped by one of these rather than by a raw path, so "which project"
    is answered once, at the edge.
    """

    id: str
    title: str
    path: Path
    created_at: str
    updated_at: str

    @contextmanager
    def connect(self, *, read_only: bool = False) -> Iterator[sqlite3.Connection]:
        """Open a short-lived connection to this project's file."""
        conn = connect(self.path, read_only=read_only)
        try:
            yield conn
        finally:
            conn.close()


@dataclass(frozen=True, slots=True)
class ProjectSummary:
    """What the picker and ``GET /api/projects`` need, without opening the manuscript."""

    id: str
    title: str
    path: Path
    created_at: str
    updated_at: str
    chapter_count: int
    word_count: int
    schema_version: int

    def to_handle(self) -> ProjectHandle:
        return ProjectHandle(
            id=self.id,
            title=self.title,
            path=self.path,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


@dataclass(frozen=True, slots=True)
class SkippedFile:
    """A ``.sqlite`` file in the directory that is not a usable project.

    Surfaced rather than swallowed: a corrupt or unreadable file must be reported without taking
    down the list (P1-12).
    """

    path: Path
    reason: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class ScanResult:
    """The outcome of one directory scan."""

    projects: list[ProjectSummary] = field(default_factory=list)
    skipped: list[SkippedFile] = field(default_factory=list)


def slugify(title: str) -> str:
    """A filesystem-safe, human-readable slug for a project title.

    Non-ASCII is folded rather than dropped where it decomposes; anything else becomes a hyphen.
    Apostrophes are removed instead - ``Emile's Journey`` reads better as ``emiles-journey`` than
    as ``emile-s-journey``. The result is always non-empty, so a title of pure punctuation still
    yields a usable name.
    """
    normalized = unicodedata.normalize("NFKD", title)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii").lower()
    ascii_only = ascii_only.replace("'", "")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_only).strip("-")
    slug = slug[:_SLUG_MAX_LENGTH].strip("-")
    return slug or _SLUG_FALLBACK


class ProjectStore:
    """Create, open, and list the projects under one data directory."""

    def __init__(self, projects_dir: Path | str) -> None:
        self.projects_dir = Path(projects_dir)

    # -- creation ---------------------------------------------------------------------------

    def create(self, title: str) -> ProjectHandle:
        """Create a project file, migrate it, and write its ``project`` row.

        Raises:
            ValueError: If the title is blank or longer than 200 characters.
        """
        title = title.strip()
        if not title:
            raise ValueError("project title must not be blank")
        if len(title) > _TITLE_MAX_LENGTH:
            raise ValueError(f"project title must be at most {_TITLE_MAX_LENGTH} characters")

        self.projects_dir.mkdir(parents=True, exist_ok=True)
        path = self._unused_path(title)
        project_id = new_id(IdPrefix.PROJECT)
        now = utc_now()

        conn = open_migrated(path)
        try:
            with transaction(conn):
                conn.execute(
                    "INSERT INTO project (id, title, created_at, updated_at, settings_json) "
                    "VALUES (?, ?, ?, ?, '{}')",
                    (project_id, title, now, now),
                )
        except BaseException:
            conn.close()
            path.unlink(missing_ok=True)
            raise
        conn.close()

        return ProjectHandle(id=project_id, title=title, path=path, created_at=now, updated_at=now)

    def _unused_path(self, title: str) -> Path:
        """A free path named from the title. Retries on the (vanishingly rare) collision."""
        slug = slugify(title)
        for _ in range(8):
            path = self.projects_dir / f"{slug}-{random_token(_SUFFIX_LENGTH)}{PROJECT_FILE_SUFFIX}"
            if not path.exists():
                return path
        raise ProjectStoreError(f"could not find a free filename for {title!r}")

    # -- discovery --------------------------------------------------------------------------

    def scan(self) -> ScanResult:
        """Read every project file in the directory (D17).

        A file that is not an Archetype project, or cannot be read, is recorded in
        :attr:`ScanResult.skipped` rather than raised - one bad file must not hide the rest.
        """
        result = ScanResult()
        if not self.projects_dir.is_dir():
            return result

        for path in sorted(self.projects_dir.glob(f"*{PROJECT_FILE_SUFFIX}")):
            summary_or_skip = self._read_summary(path)
            if isinstance(summary_or_skip, ProjectSummary):
                result.projects.append(summary_or_skip)
            else:
                result.skipped.append(summary_or_skip)

        result.projects.sort(key=lambda p: p.updated_at, reverse=True)
        return result

    def list_projects(self) -> list[ProjectSummary]:
        """Every readable project, most recently updated first."""
        return self.scan().projects

    def _read_summary(self, path: Path) -> ProjectSummary | SkippedFile:
        """Read one file without migrating it - looking at a project must not change it."""
        try:
            conn = connect(path, read_only=True)
        except sqlite3.Error as exc:
            return SkippedFile(path, "unreadable", str(exc))

        try:
            version = current_version(conn)
            if version == 0:
                return SkippedFile(path, "not-an-archetype-project", "no schema_version table")
            row = conn.execute(
                "SELECT id, title, created_at, updated_at FROM project LIMIT 1"
            ).fetchone()
            if row is None:
                return SkippedFile(path, "empty", "no project row")
            # A soft-deleted chapter is out of the picker's counts as well as out of the
            # lists (D22). The predicate is version-gated because the scan reads files it has
            # deliberately not migrated: `deleted_at` arrives in migration 002, and asking a
            # version-1 file for it would turn a perfectly readable project into a skipped one.
            live_only = " AND deleted_at IS NULL" if version >= 2 else ""
            counts = conn.execute(
                "SELECT COUNT(*) AS chapters, COALESCE(SUM(word_count), 0) AS words "
                f"FROM document WHERE project_id = ? AND kind = 'chapter'{live_only}",
                (row["id"],),
            ).fetchone()
            return ProjectSummary(
                id=row["id"],
                title=row["title"],
                path=path,
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                chapter_count=int(counts["chapters"]),
                word_count=int(counts["words"]),
                schema_version=version,
            )
        except sqlite3.DatabaseError as exc:
            # Covers both "some other application's SQLite file" and genuine corruption.
            return SkippedFile(path, "unreadable", str(exc))
        finally:
            conn.close()

    # -- opening ----------------------------------------------------------------------------

    def find(self, project_id: str) -> ProjectSummary | None:
        """The summary for ``project_id``, or ``None`` if no file in the directory holds it."""
        for summary in self.scan().projects:
            if summary.id == project_id:
                return summary
        return None

    def open(self, project_id: str) -> ProjectHandle:
        """Resolve a project id to a handle, migrating its file to the current schema (D20).

        Raises:
            ProjectNotFoundError: If no file in the directory holds that id.
        """
        summary = self.find(project_id)
        if summary is None:
            raise ProjectNotFoundError(f"no project with id {project_id!r} in {self.projects_dir}")

        conn = connect(summary.path)
        try:
            migrate(conn)
            row = conn.execute(
                "SELECT id, title, created_at, updated_at FROM project WHERE id = ?",
                (project_id,),
            ).fetchone()
        finally:
            conn.close()

        if row is None:  # pragma: no cover - the scan just read this row
            raise ProjectNotFoundError(f"project {project_id!r} vanished from {summary.path}")

        return ProjectHandle(
            id=row["id"],
            title=row["title"],
            path=summary.path,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def open_path(self, path: Path) -> ProjectHandle:
        """Resolve a project file directly, migrating it. Used when the path is already known."""
        conn = open_migrated(path)
        try:
            row = conn.execute(
                "SELECT id, title, created_at, updated_at FROM project LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            raise ProjectNotFoundError(f"{path} holds no project row")
        return ProjectHandle(
            id=row["id"],
            title=row["title"],
            path=Path(path),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def touch(self, project_id: str) -> str:
        """Stamp ``project.updated_at`` and return the new timestamp."""
        handle = self.open(project_id)
        now = utc_now()
        with handle.connect() as conn, transaction(conn):
            conn.execute("UPDATE project SET updated_at = ? WHERE id = ?", (now, project_id))
        return now
