"""Resolving a bare document id to the project that holds it (P1-5).

``GET /api/documents/{did}`` and its siblings address a document without naming its project, but
storage is one SQLite file per project (D3) - so something has to answer "which file". That is
this module.

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
        path = self._cached_path(document_id)
        if path is not None and _holds_document(path, document_id):
            return self.store.open_path(path)

        for candidate in self._candidate_paths():
            if _holds_document(candidate, document_id):
                self._remember(document_id, candidate)
                return self.store.open_path(candidate)

        self._forget(document_id)
        raise DocumentNotFoundError(f"no document {document_id!r} in {self.store.projects_dir}")

    def forget(self, document_id: str) -> None:
        """Drop a cached location. Called when a document is known to have gone."""
        self._forget(document_id)

    # -- internals --------------------------------------------------------------------------

    def _candidate_paths(self) -> list[Path]:
        return [summary.path for summary in self.store.list_projects()]

    def _cached_path(self, document_id: str) -> Path | None:
        with self._lock:
            return self._cache.get(document_id)

    def _remember(self, document_id: str, path: Path) -> None:
        with self._lock:
            self._cache[document_id] = path

    def _forget(self, document_id: str) -> None:
        with self._lock:
            self._cache.pop(document_id, None)


def _holds_document(path: Path, document_id: str) -> bool:
    """True if that project file holds that document. Never raises - a bad file is a 'no'."""
    if not path.is_file():
        return False
    try:
        conn = connect(path, read_only=True)
    except sqlite3.Error:
        return False
    try:
        row = conn.execute("SELECT 1 FROM document WHERE id = ?", (document_id,)).fetchone()
        return row is not None
    except sqlite3.DatabaseError:
        # Not an Archetype project, or a corrupt one. The scan reports it; here it is a miss.
        return False
    finally:
        conn.close()
