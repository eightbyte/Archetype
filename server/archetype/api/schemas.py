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

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..manuscript.anchors.records import Anchor
from ..manuscript.anchors.resolve import Suggestion
from ..manuscript.anchors.store import MAX_LABEL_LENGTH, clean_label
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
    "AnchorCreateIn",
    "AnchorStatusFilter",
    "AnchorListOut",
    "AnchorOut",
    "AnchorPatchIn",
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
    "SuggestionOut",
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


class SuggestionOut(_Wire):
    """Where a ``stale`` anchor's passage may have gone (``specs/anchors.md`` section 6).

    Data on a finding, never an action. Nothing on the server applies one; the writer accepts it
    through ``PATCH /api/anchors/{aid}``, which re-derives the quote and context from the range
    like any other re-link.
    """

    from_pos: int
    to_pos: int
    text: str

    @classmethod
    def of(cls, suggestion: Suggestion) -> SuggestionOut:
        return cls(from_pos=suggestion.from_pos, to_pos=suggestion.to_pos, text=suggestion.text)


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
    """What a successful save returns: the new version and the server's projection (D18).

    ``anchors`` carries every anchor this write **moved** - a changed status, a changed position,
    or both (P2-7, D21). An empty list is the ordinary answer, and it is the answer that says
    the writer typed above their anchors rather than through them. The client replaces its own
    mapped positions with these: its mapping is for liveness, the server's answer is the truth.
    """

    document_id: str
    version: int
    word_count: int
    headings: list[HeadingOut]
    updated_at: str
    anchors: list[AnchorOut]

    @classmethod
    def of(cls, result: SaveResult) -> SaveResultOut:
        return cls(
            document_id=result.document_id,
            version=result.version,
            word_count=result.word_count,
            headings=[HeadingOut.of(heading) for heading in result.headings],
            updated_at=result.updated_at,
            anchors=[AnchorOut.of(anchor) for anchor in result.anchors],
        )


# -- anchors --------------------------------------------------------------------------------


class AnchorOut(_Wire):
    """One anchor as a reader sees it (P2-7).

    ``status`` is the **effective** status: ``ok`` and ``stale`` are the resolver's answer about
    the text, and ``orphaned`` is derived from the owning chapter being soft-deleted (D22). It
    is never stored as ``orphaned``, so restoring the chapter returns the anchor to exactly the
    answer the resolver gave.

    ``from_pos``/``to_pos`` are a cache of the last resolution's conclusion, not a promise about
    the document the client is holding. ``quote`` is what the anchor *means*.
    """

    id: str
    project_id: str
    document_id: str
    from_pos: int
    to_pos: int
    quote: str
    prefix: str
    suffix: str
    status: str
    label: str
    document_version: int
    created_at: str
    updated_at: str
    checked_at: str
    suggestion: SuggestionOut | None = None

    @classmethod
    def of(cls, anchor: Anchor) -> AnchorOut:
        return cls(
            id=anchor.id,
            project_id=anchor.project_id,
            document_id=anchor.document_id,
            from_pos=anchor.from_pos,
            to_pos=anchor.to_pos,
            quote=anchor.quote,
            prefix=anchor.prefix,
            suffix=anchor.suffix,
            status=anchor.status,
            label=anchor.label,
            document_version=anchor.document_version,
            created_at=anchor.created_at,
            updated_at=anchor.updated_at,
            checked_at=anchor.checked_at,
            suggestion=None if anchor.suggestion is None else SuggestionOut.of(anchor.suggestion),
        )


class AnchorListOut(_Wire):
    """``GET /api/documents/{did}/anchors`` and ``GET /api/projects/{pid}/anchors``."""

    anchors: list[AnchorOut]


#: What ``?status=`` may be on the project anchor list. Spelled here as well as in
#: :mod:`archetype.manuscript.anchors.status` so that FastAPI refuses an unknown one with the
#: envelope and OpenAPI documents the three; ``test_anchor_routes.py`` holds the two spellings
#: together, and the store keeps its own check for callers that never touch HTTP.
AnchorStatusFilter = Literal["ok", "stale", "orphaned"]


class AnchorCreateIn(_Wire):
    """``POST /api/documents/{did}/anchors``.

    A range and a version, and nothing else. The server derives ``quote``, ``prefix``, and
    ``suffix`` from the stored content, so a client cannot create an anchor whose quote
    disagrees with the manuscript - it is never asked what the manuscript says
    (``specs/anchors.md`` section 1).
    """

    from_pos: int = Field(ge=0)
    to_pos: int = Field(ge=0)
    version: int = Field(ge=1)
    label: str = Field(default="", max_length=MAX_LABEL_LENGTH)

    @field_validator("label")
    @classmethod
    def _clean(cls, value: str) -> str:
        return clean_label(value)


class AnchorPatchIn(_Wire):
    """``PATCH /api/anchors/{aid}``: re-link to a new range, or change the label, or both.

    A re-link carries all three of ``from_pos``, ``to_pos``, and ``version`` or none of them.
    Two of the three is a client that has lost track of which document version it is looking at,
    and guessing the third is exactly how an anchor ends up over text nobody looked at (D19).
    """

    from_pos: int | None = Field(default=None, ge=0)
    to_pos: int | None = Field(default=None, ge=0)
    version: int | None = Field(default=None, ge=1)
    label: str | None = Field(default=None, max_length=MAX_LABEL_LENGTH)

    @field_validator("label")
    @classmethod
    def _clean(cls, value: str | None) -> str | None:
        return None if value is None else clean_label(value)

    @model_validator(mode="after")
    def _coherent(self) -> AnchorPatchIn:
        parts = (self.from_pos, self.to_pos, self.version)
        if any(part is not None for part in parts) and any(part is None for part in parts):
            raise ValueError("a re-link needs from_pos, to_pos, and version together")
        if self.from_pos is None and self.label is None:
            raise ValueError("nothing to change: send a range to re-link, or a label, or both")
        return self

    @property
    def relinks(self) -> bool:
        return self.from_pos is not None


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
