"""The migration runner (P1-3, D20).

Numbered, forward-only SQL migrations live beside this module in ``migrations/``, named
``NNN_description.sql``. They are applied in numeric order when a project file is opened, and
recorded in ``schema_version``. There are no down-migrations and no ORM.

Each migration runs inside one transaction together with its ``schema_version`` row, so a failure
leaves the file at the previous version rather than half-migrated. The ``BEGIN``/``COMMIT`` pair
is written into the script text rather than issued around it: ``sqlite3.Cursor.executescript``
commits any open transaction before it runs, so a transaction started outside the script would be
closed by the very call it was meant to protect.

Adding a migration: drop ``00N_thing.sql`` into ``migrations/`` and add a test that runs it
against a fixture database captured at version ``N-1`` (see ``tests/fixtures/db/README.md``).
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .db import connect, utc_now

__all__ = [
    "MIGRATIONS_DIR",
    "Migration",
    "MigrationError",
    "current_version",
    "latest_version",
    "load_migrations",
    "migrate",
    "open_migrated",
]

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

_FILENAME_PATTERN = re.compile(r"^(?P<version>\d{3})_(?P<slug>[a-z0-9_]+)\.sql$")


class MigrationError(RuntimeError):
    """A migration could not be applied, or the migration set itself is malformed."""


@dataclass(frozen=True, slots=True)
class Migration:
    """One numbered SQL migration."""

    version: int
    slug: str
    path: Path

    def read(self) -> str:
        return self.path.read_text(encoding="utf-8")


def load_migrations(directory: Path | None = None) -> list[Migration]:
    """Every migration in ``directory``, ordered by version.

    Raises:
        MigrationError: If a filename is malformed, a version is duplicated, or the sequence
            has a gap - all three mean someone's migration will silently not run.
    """
    directory = directory or MIGRATIONS_DIR
    migrations: list[Migration] = []
    for path in sorted(directory.glob("*.sql")):
        match = _FILENAME_PATTERN.match(path.name)
        if match is None:
            raise MigrationError(
                f"{path.name} is not a valid migration name; expected NNN_lower_snake.sql"
            )
        migrations.append(
            Migration(
                version=int(match.group("version")),
                slug=match.group("slug"),
                path=path,
            )
        )

    migrations.sort(key=lambda m: m.version)
    for expected, migration in enumerate(migrations, start=1):
        if migration.version != expected:
            raise MigrationError(
                f"migration versions must be consecutive from 001; expected {expected:03d}, "
                f"found {migration.version:03d} ({migration.path.name})"
            )
    return migrations


def _sql_quote(value: str) -> str:
    """Quote a string literal for inlining into a script that cannot take bound parameters."""
    escaped = value.replace("'", "''")
    return f"'{escaped}'"


def _transactional_script(migration: Migration) -> str:
    """The migration wrapped in its own transaction, with its ``schema_version`` row appended.

    ``executescript`` takes no bound parameters, so the two values are inlined - both are
    generated here (an integer and our own ISO timestamp), never user input, and the string is
    quoted defensively regardless.
    """
    return (
        "BEGIN;\n"
        f"{migration.read()}\n"
        "INSERT INTO schema_version (version, applied_at) VALUES "
        f"({int(migration.version)}, {_sql_quote(utc_now())});\n"
        "COMMIT;\n"
    )


def latest_version(directory: Path | None = None) -> int:
    """The version a fully migrated file reaches. ``0`` when there are no migrations."""
    migrations = load_migrations(directory)
    return migrations[-1].version if migrations else 0


def current_version(conn: sqlite3.Connection) -> int:
    """The version recorded in the file. ``0`` for an empty or non-Archetype database."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'schema_version'"
    ).fetchone()
    if row is None:
        return 0
    row = conn.execute("SELECT COALESCE(MAX(version), 0) AS version FROM schema_version").fetchone()
    return int(row["version"])


def migrate(conn: sqlite3.Connection, *, directory: Path | None = None) -> int:
    """Apply every pending migration and return the resulting version.

    Re-running against an up-to-date file is a no-op: nothing is executed and no row is written.

    Raises:
        MigrationError: If the file is newer than this build knows about, or a migration fails.
    """
    migrations = load_migrations(directory)
    version = current_version(conn)
    target = migrations[-1].version if migrations else 0

    if version > target:
        raise MigrationError(
            f"project file is at schema version {version}, newer than this build's {target}; "
            "migrations are forward-only (D20) and this file cannot be opened safely"
        )

    for migration in migrations:
        if migration.version <= version:
            continue
        try:
            conn.executescript(_transactional_script(migration))
        except BaseException as exc:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise MigrationError(
                f"migration {migration.path.name} failed and was rolled back: {exc}"
            ) from exc
        version = migration.version

    return version


def open_migrated(path: Path, *, directory: Path | None = None) -> sqlite3.Connection:
    """Open a project file and bring it to the current schema version (D20).

    The caller owns the returned connection and must close it.
    """
    conn = connect(path)
    try:
        migrate(conn, directory=directory)
    except BaseException:
        conn.close()
        raise
    return conn
