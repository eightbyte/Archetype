"""Wire shapes for the Phase 1 routes (P1-5).

Pydantic models on the server, mirrored TypeScript in ``web/src/api/types.ts``; the two are held
together by the contract fixtures (P1-8), so a shape change fails the suite rather than the
browser. The contract itself is written up in ``specs/api-contract.md`` at phase close (P1-15).

Wire schemas are **extension-only** (outline section 7): add a field, never repurpose or remove
one. Field names match the storage columns wherever a column exists, so there is one vocabulary
end to end - ``content_json`` is called ``content_json`` in the database, on the wire, and in the
client.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..manuscript.documents import (
    MAX_TITLE_LENGTH,
    Document,
    DocumentMeta,
    OutlineChapter,
    SaveResult,
    clean_title,
)
from ..manuscript.projection import Heading
from ..projects.store import ProjectHandle, ProjectSummary, SkippedFile

__all__ = [
    "DocumentCreateIn",
    "DocumentListOut",
    "DocumentMetaOut",
    "DocumentOut",
    "DocumentRenameIn",
    "DocumentSaveIn",
    "HeadingOut",
    "OutlineChapterOut",
    "OutlineOut",
    "ProjectCreateIn",
    "ProjectDetailOut",
    "ProjectListOut",
    "ProjectSummaryOut",
    "SaveResultOut",
    "SkippedFileOut",
]


class _Wire(BaseModel):
    """Base for every wire model: no undeclared fields in, no surprises out."""

    model_config = ConfigDict(extra="forbid")


# -- pieces ---------------------------------------------------------------------------------


class HeadingOut(_Wire):
    """One heading in a document's derived heading list (D18).

    ``ordinal`` is the heading's index among all headings in its document, counting from zero.
    Jump-to-heading resolves against it until anchors arrive in Phase 2 (P1-11).
    """

    level: int
    text: str
    ordinal: int

    @classmethod
    def of(cls, heading: Heading) -> HeadingOut:
        return cls(level=heading.level, text=heading.text, ordinal=heading.ordinal)


class SkippedFileOut(_Wire):
    """A file in the projects directory that is not a usable project.

    Reported rather than swallowed, so the picker can say what it found without the list
    collapsing over one bad file (P1-12). Only the filename is exposed - the browser has no
    business knowing the writer's directory layout.
    """

    name: str
    reason: str
    detail: str

    @classmethod
    def of(cls, skipped: SkippedFile) -> SkippedFileOut:
        return cls(name=skipped.path.name, reason=skipped.reason, detail=skipped.detail)


# -- documents ------------------------------------------------------------------------------


class DocumentMetaOut(_Wire):
    """A document without its content.

    The list routes return these deliberately: the outline panel must never pull the whole
    manuscript to draw a chapter list (P1-5).
    """

    id: str
    project_id: str
    order_index: int
    title: str
    kind: str
    headings: list[HeadingOut]
    word_count: int
    version: int
    created_at: str
    updated_at: str

    @classmethod
    def of(cls, meta: DocumentMeta) -> DocumentMetaOut:
        return cls(
            id=meta.id,
            project_id=meta.project_id,
            order_index=meta.order_index,
            title=meta.title,
            kind=meta.kind,
            headings=[HeadingOut.of(heading) for heading in meta.headings],
            word_count=meta.word_count,
            version=meta.version,
            created_at=meta.created_at,
            updated_at=meta.updated_at,
        )


class DocumentListOut(_Wire):
    """``GET /api/projects/{pid}/documents``."""

    documents: list[DocumentMetaOut]


class DocumentOut(_Wire):
    """``GET /api/documents/{did}``: the metadata plus the content the list left out.

    ``text_plain`` is deliberately **not** here. It is derived from ``content_json`` by rules the
    client mirrors (P1-7), so shipping it would double the size of every chapter load to send
    something the client can compute. The server's projection reaches the client where it
    matters - in ``headings`` and ``word_count``, and again in the save response (D18).
    """

    id: str
    project_id: str
    order_index: int
    title: str
    kind: str
    content_json: dict[str, Any]
    headings: list[HeadingOut]
    word_count: int
    version: int
    created_at: str
    updated_at: str

    @classmethod
    def of(cls, document: Document) -> DocumentOut:
        meta = document.meta
        return cls(
            id=meta.id,
            project_id=meta.project_id,
            order_index=meta.order_index,
            title=meta.title,
            kind=meta.kind,
            content_json=document.content,
            headings=[HeadingOut.of(heading) for heading in meta.headings],
            word_count=meta.word_count,
            version=meta.version,
            created_at=meta.created_at,
            updated_at=meta.updated_at,
        )


class DocumentCreateIn(_Wire):
    """``POST /api/projects/{pid}/documents``. Omitting the title takes ``Chapter N``."""

    title: str | None = Field(default=None, max_length=MAX_TITLE_LENGTH)

    @field_validator("title")
    @classmethod
    def _clean(cls, value: str | None) -> str | None:
        return None if value is None else clean_title(value)


class DocumentRenameIn(_Wire):
    """``PATCH /api/documents/{did}``."""

    title: str = Field(min_length=1, max_length=MAX_TITLE_LENGTH)

    @field_validator("title")
    @classmethod
    def _clean(cls, value: str) -> str:
        return clean_title(value)


class DocumentSaveIn(_Wire):
    """``PUT /api/documents/{did}/content`` (P1-6, D19).

    ``version`` is the version the client believes it is editing. If it is not the stored one,
    nothing is written and the response is a ``409``.
    """

    content_json: dict[str, Any]
    version: int = Field(ge=1)


class SaveResultOut(_Wire):
    """What a successful save returns: the new version and the server's projection (D18)."""

    document_id: str
    version: int
    word_count: int
    headings: list[HeadingOut]
    updated_at: str

    @classmethod
    def of(cls, result: SaveResult) -> SaveResultOut:
        return cls(
            document_id=result.document_id,
            version=result.version,
            word_count=result.word_count,
            headings=[HeadingOut.of(heading) for heading in result.headings],
            updated_at=result.updated_at,
        )


# -- projects -------------------------------------------------------------------------------


class ProjectSummaryOut(_Wire):
    """A project as the picker and the project list see it (P1-12)."""

    id: str
    title: str
    chapter_count: int
    word_count: int
    created_at: str
    updated_at: str

    @classmethod
    def of(cls, summary: ProjectSummary) -> ProjectSummaryOut:
        return cls(
            id=summary.id,
            title=summary.title,
            chapter_count=summary.chapter_count,
            word_count=summary.word_count,
            created_at=summary.created_at,
            updated_at=summary.updated_at,
        )

    @classmethod
    def of_handle(cls, handle: ProjectHandle, documents: list[DocumentMeta]) -> ProjectSummaryOut:
        """Build from an open project whose documents have already been read."""
        chapters = [doc for doc in documents if doc.kind == "chapter"]
        return cls(
            id=handle.id,
            title=handle.title,
            chapter_count=len(chapters),
            word_count=sum(doc.word_count for doc in chapters),
            created_at=handle.created_at,
            updated_at=handle.updated_at,
        )


class ProjectListOut(_Wire):
    """``GET /api/projects``: what was readable, and what was not."""

    projects: list[ProjectSummaryOut]
    skipped: list[SkippedFileOut]


class ProjectCreateIn(_Wire):
    """``POST /api/projects``."""

    title: str = Field(min_length=1, max_length=MAX_TITLE_LENGTH)

    @field_validator("title")
    @classmethod
    def _clean(cls, value: str) -> str:
        return clean_title(value, what="project title")


class ProjectDetailOut(_Wire):
    """``GET /api/projects/{pid}``: one project with its document list."""

    project: ProjectSummaryOut
    documents: list[DocumentMetaOut]


# -- outline --------------------------------------------------------------------------------


class OutlineChapterOut(_Wire):
    """One chapter in the stitched table of contents."""

    document_id: str
    title: str
    order_index: int
    word_count: int
    headings: list[HeadingOut]

    @classmethod
    def of(cls, chapter: OutlineChapter) -> OutlineChapterOut:
        return cls(
            document_id=chapter.document_id,
            title=chapter.title,
            order_index=chapter.order_index,
            word_count=chapter.word_count,
            headings=[HeadingOut.of(heading) for heading in chapter.headings],
        )


class OutlineOut(_Wire):
    """``GET /api/projects/{pid}/outline``: the TOC across the whole manuscript (D2, D18)."""

    project_id: str
    chapters: list[OutlineChapterOut]
