"""Markdown, both ways (P2-13, P2-14, D15).

Two halves that hold each other honest. :mod:`.serialize` writes the closed schema out and is
ours, because the syntax for ten nodes and two marks is small, total, and a thing we get to
define. :mod:`.parse` reads CommonMark back in and leans on `markdown-it-py`, because the
grammar is not ours and the corners are where an import mangles a chapter (phase-2 plan section
2, ruling 3).

The promise between them, stated once: **``import(export(doc)) == doc`` for every case in
``tests/fixtures/markdown/cases.json``**, compared as ProseMirror JSON, per chapter, over the
closed schema. The **combined** project export makes no such promise and says so - it needs a
chapter boundary the schema has no node for, and inventing one would be a private format wearing
Markdown's clothes (ruling 4).

:mod:`.schema` is the server's mirror of the editor's closed node list, held to it by a shared
fixture the way the projection is.
"""

from __future__ import annotations

from .parse import (
    IMPORT_MODES,
    ImportedChapter,
    ImportedManuscript,
    ImportMode,
    Notice,
    parse_markdown,
    read_manuscript,
)
from .schema import ALLOWED_MARKS, ALLOWED_NODES, MAX_HEADING_LEVEL, UnknownNodeError
from .serialize import (
    HANDLED_NODES,
    UnknownMarkError,
    chapters_to_markdown,
    document_to_markdown,
)

__all__ = [
    "ALLOWED_MARKS",
    "ALLOWED_NODES",
    "HANDLED_NODES",
    "IMPORT_MODES",
    "MAX_HEADING_LEVEL",
    "ImportMode",
    "ImportedChapter",
    "ImportedManuscript",
    "Notice",
    "UnknownMarkError",
    "UnknownNodeError",
    "chapters_to_markdown",
    "document_to_markdown",
    "parse_markdown",
    "read_manuscript",
]
