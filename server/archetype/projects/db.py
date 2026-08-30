"""SQLite connection handling for a project file (P1-3).

One SQLite file per project (D3), opened with the pragmas the rest of the system assumes:

* ``foreign_keys=ON`` - referential integrity is enforced, not documented;
* ``journal_mode=WAL`` - a reader (the outline scan) never blocks the writer (autosave);
* ``busy_timeout`` - a brief lock waits rather than raising, which matters once autosave and a
  project-list refresh overlap.

Connections are cheap and short-lived: open one, do the work, close it. No pool, no ORM (D20).

Transaction control is explicit. ``isolation_level=None`` turns off the driver's implicit
transaction management so this module - and the migration runner - own every ``BEGIN`` and
``COMMIT``. That is what makes a migration atomic across an ``executescript``.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

__all__ = [
    "BUSY_TIMEOUT_MS",
    "connect",
    "transaction",
    "utc_now",
]

#: How long a statement waits on a locked database before raising (milliseconds).
BUSY_TIMEOUT_MS = 5000


def utc_now() -> str:
    """The current time as a UTC ISO-8601 string - the only timestamp format we store."""
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def connect(path: Path | str, *, read_only: bool = False) -> sqlite3.Connection:
    """Open a project file with the standard pragmas.

    Args:
        path: The ``.sqlite`` file. Its parent directory must already exist.
        read_only: Open via a ``file:`` URI in read-only mode. Used by the project scan (D17),
            which must never create or migrate a file just by looking at it.

    Returns:
        A connection with :class:`sqlite3.Row` rows and explicit transaction control.
    """
    path = Path(path)
    if read_only:
        uri = f"{path.resolve().as_uri()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=BUSY_TIMEOUT_MS / 1000)
    else:
        conn = sqlite3.connect(path, timeout=BUSY_TIMEOUT_MS / 1000)

    conn.row_factory = sqlite3.Row
    # Explicit transaction control; see the module docstring.
    conn.isolation_level = None
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA foreign_keys = ON")
    if not read_only:
        # WAL is a property of the file, not the connection, but setting it on open makes a
        # file created outside the app converge on the mode the app expects.
        conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Run a block inside one explicit transaction, rolling back on any exception."""
    conn.execute("BEGIN")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")
