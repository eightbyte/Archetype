"""Turning a Markdown file into chapters (P2-14, D15).

:mod:`.parse` is pure - text in, nodes out, no database. This is the part that writes, and it is
one function because the *order* is the whole design.

**Import creates chapters; it never replaces the text of one** (phase-2 plan section 2, ruling
5). Every chapter is appended through :meth:`~archetype.manuscript.documents.DocumentStore.create`
so that :meth:`~archetype.manuscript.documents.DocumentStore.save_content` stays the only path by
which *existing* manuscript text changes (data-model section 6). Replacing a chapter is
import-then-delete, and both halves of that are already recoverable.

That ruling is also why no ``pre-import`` snapshot is taken here. The reason is registered and
the store can write one, but nothing an import does can destroy text: there is no chapter whose
words are about to be replaced, so a snapshot before it would be a history entry recording that
nothing happened. The first writer of a ``pre-import`` snapshot is whatever later phase lets an
import overwrite a chapter, and the reason exists so that it does not have to add one.

**Nothing is created until everything is measured.** P2-14 says a document too large for
``MAX_CONTENT_BYTES`` is refused before anything is created, so the file is parsed, every
chapter is serialized, and every size is checked - and only then does the first row get written.
The alternative, creating as we go and failing halfway, would leave a writer with three chapters
of a five-chapter file and no way to tell which two were missing.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..documents import ContentTooLargeError, Document, DocumentStore, serialize_content
from .parse import ImportedManuscript, ImportMode, Notice, read_manuscript

__all__ = ["MAX_IMPORT_BYTES", "ImportOutcome", "import_markdown"]

#: The largest Markdown file an import will read. Four times the per-chapter content limit,
#: because one file legitimately becomes many chapters and Markdown is smaller than the JSON it
#: becomes - and still small enough that a mis-aimed upload is refused rather than parsed. A
#: module constant, not a setting: none of these has a second value anyone wants (ruling 8).
MAX_IMPORT_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ImportOutcome:
    """The chapters an import created, and what it could not keep."""

    documents: tuple[Document, ...]
    notices: tuple[Notice, ...]


def import_markdown(
    store: DocumentStore,
    markdown: str,
    *,
    mode: str = ImportMode.ONE_CHAPTER,
    title: str | None = None,
) -> ImportOutcome:
    """Read a Markdown file and append the chapters it describes to a project.

    Args:
        store: The document store of the project the chapters are appended to.
        markdown: The file's text.
        mode: :data:`~archetype.manuscript.markdown.parse.ImportMode.ONE_CHAPTER` or
            ``SPLIT_ON_H1``.
        title: The title for the single chapter of ``one-chapter`` mode. ``split-on-h1`` takes
            each chapter's title from its own heading and ignores this.

    Raises:
        ValueError: If ``mode`` is unknown, or ``title`` is blank or too long.
        ContentTooLargeError: If the file is over :data:`MAX_IMPORT_BYTES`, or any one chapter
            it describes is over ``MAX_CONTENT_BYTES``. Nothing has been created.
    """
    size = len(markdown.encode("utf-8"))
    if size > MAX_IMPORT_BYTES:
        raise ContentTooLargeError(size, MAX_IMPORT_BYTES)

    read: ImportedManuscript = read_manuscript(markdown, mode=mode, title=title)

    # Measure first, write second. `serialize_content` raises if a chapter is oversized, and
    # doing it for all of them here is what makes the refusal total rather than partial.
    for chapter in read.chapters:
        serialize_content(chapter.content)

    created = [store.create(chapter.title, content=chapter.content) for chapter in read.chapters]
    return ImportOutcome(documents=tuple(created), notices=read.notices)
