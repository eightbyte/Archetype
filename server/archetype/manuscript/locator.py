"""Resolving a bare document id to the project that holds it (P1-5).

``GET /api/documents/{did}`` and its siblings address a document without naming its project, but
storage is one SQLite file per project (D3) - so something has to answer "which file". That is
this module. ``/api/anchors/{aid}`` is addressed the same way, over the same cache (P2-7).

The answer is cached, because the alternative is opening every project file on every keystroke's
autosave. The cache is a hint, never an authority: every resolution re-confirms that the file
still holds that document, and a miss falls back to a full scan. So a project file deleted,
replaced, or copied in behind the app's back cannot make it read or write the wrong manuscript -
the worst case is one wasted scan.

The scan itself opens files read-only, keeping the D17 promise that looking at a project never
changes it. Only the resolved project is opened for real, which is where migration happens.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from ..projects.db import connect
from ..projects.store import ProjectHandle, ProjectStore
from .anchors.store import AnchorNotFoundError
from .documents import DocumentNotFoundError

__all__ = ["DocumentLocator"]


class DocumentLocator:
    """Finds the project that holds a given document id."""

    def __init__(self, store: ProjectStore) -> None:
        self.store = store
        self._lock = threading.Lock()
        self._cache: dict[str, Path] = {}

    def resolve(self, document_id: str) -> ProjectHandle:
        """The handle for the project holding ``document_id``.

        Raises:
            DocumentNotFoundError: If no project file in the directory holds that document.
        """
        handle = self._locate("document", document_id)
        if handle is None:
            raise DocumentNotFoundError(f"no document {document_id!r} in {self.store.projects_dir}")
        return handle

    def resolve_anchor(self, anchor_id: str) -> ProjectHandle:
        """The handle for the project holding ``anchor_id`` (P2-7).

        ``PATCH`` and ``DELETE /api/anchors/{aid}`` address an anchor without naming its
        document or its project, for the same reason a document route does: the *Marks* tab
        holds anchors from every chapter at once, and making it carry a project id would put
        the client in charge of a fact the server already knows.

        Raises:
            AnchorNotFoundError: If no project file in the directory holds that anchor.
        """
        handle = self._locate("anchor", anchor_id)
        if handle is None:
            raise AnchorNotFoundError(f"no anchor {anchor_id!r} in {self.store.projects_dir}")
        return handle

    def forget(self, row_id: str) -> None:
        """Drop a cached location. Called when a row is known to have gone."""
        self._forget(row_id)

    # -- internals --------------------------------------------------------------------------

    def _locate(self, table: str, row_id: str) -> ProjectHandle | None:
        """Which project file holds that row, or ``None``. The cache is a hint, never truth."""
        path = self._cached_path(row_id)
        if path is not None and _holds_row(path, table, row_id):
            return self.store.open_path(path)

        for candidate in self._candidate_paths():
            if _holds_row(candidate, table, row_id):
                self._remember(row_id, candidate)
                return self.store.open_path(candidate)

        self._forget(row_id)
        return None

    def _candidate_paths(self) -> list[Path]:
        return [summary.path for summary in self.store.list_projects()]

    def _cached_path(self, row_id: str) -> Path | None:
        with self._lock:
            return self._cache.get(row_id)

    def _remember(self, row_id: str, path: Path) -> None:
        with self._lock:
            self._cache[row_id] = path

    def _forget(self, row_id: str) -> None:
        with self._lock:
            self._cache.pop(row_id, None)


#: The tables a bare id may address. A closed list, because the table name is spliced into the
#: query rather than bound to it - ids are, and only these names ever reach it.
_ADDRESSABLE = frozenset({"anchor", "document"})


def _holds_row(path: Path, table: str, row_id: str) -> bool:
    """True if that project file holds that row. Never raises - a bad file is a 'no'."""
    if table not in _ADDRESSABLE:  # pragma: no cover - a caller bug, not a runtime condition
        raise ValueError(f"{table!r} is not addressable by a bare id")
    if not path.is_file():
        return False
    try:
        conn = connect(path, read_only=True)
    except sqlite3.Error:
        return False
    try:
        row = conn.execute(f"SELECT 1 FROM {table} WHERE id = ?", (row_id,)).fetchone()
        return row is not None
    except sqlite3.DatabaseError:
        # Not an Archetype project, a corrupt one, or one still at a schema version without
        # that table. The scan reports it; here it is a miss.
        return False
    finally:
        conn.close()
