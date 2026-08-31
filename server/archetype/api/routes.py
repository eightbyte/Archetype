"""The ``/api`` router (P1-5, P1-6).

Two resource families. Projects are addressed by id and resolved by scanning the projects
directory (D17). Documents are addressed by their own id, without naming a project, so the
locator answers "which file" (see :mod:`archetype.manuscript.locator`).

Routes are thin on purpose: resolve the scope, call the store, shape the answer. Every rule that
matters - the projection (D18), the version guard (D19), the size limit - lives in the store, so
the agent loop in Phase 6 gets the same behaviour without going through HTTP.

Route handlers are synchronous. SQLite is a synchronous library; FastAPI runs a sync handler in
its threadpool, which is the honest way to do blocking work here.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Request, status

from .. import __version__
from ..manuscript.anchors.store import AnchorStore
from ..manuscript.documents import DocumentStore
from ..projects.store import ProjectHandle
from .deps import get_locator, get_project_store, open_project
from .errors import error_responses
from .schemas import (
    AnchorCreateIn,
    AnchorListOut,
    AnchorOut,
    AnchorPatchIn,
    AnchorStatusFilter,
    DocumentCreateIn,
    DocumentListOut,
    DocumentMetaOut,
    DocumentOut,
    DocumentRenameIn,
    DocumentSaveIn,
    OutlineChapterOut,
    OutlineOut,
    ProjectCreateIn,
    ProjectDetailOut,
    ProjectListOut,
    ProjectSummaryOut,
    SaveResultOut,
    SkippedFileOut,
)

__all__ = ["router"]

router = APIRouter(prefix="/api")


# -- meta -----------------------------------------------------------------------------------


@router.get("/health", tags=["meta"], summary="Liveness and version")
def health() -> dict[str, str]:
    """Liveness, and the version the browser is talking to."""
    return {"status": "ok", "version": __version__}


# -- projects -------------------------------------------------------------------------------


@router.get(
    "/projects",
    tags=["projects"],
    summary="Every readable project",
    response_model=ProjectListOut,
)
def list_projects(request: Request) -> ProjectListOut:
    """List projects by scanning the projects directory (D17).

    Files that are not usable projects come back under ``skipped`` rather than as an error: one
    bad file must not hide the rest (P1-12).
    """
    result = get_project_store(request).scan()
    return ProjectListOut(
        projects=[ProjectSummaryOut.of(summary) for summary in result.projects],
        skipped=[SkippedFileOut.of(skipped) for skipped in result.skipped],
    )


@router.post(
    "/projects",
    tags=["projects"],
    summary="Create a project",
    status_code=status.HTTP_201_CREATED,
    response_model=ProjectDetailOut,
    responses=error_responses(422),
)
def create_project(request: Request, body: ProjectCreateIn) -> ProjectDetailOut:
    """Create a project, seeded with one empty chapter.

    The seeding is server-side so a new project opens into a writable editor rather than an
    empty state, whichever client asked for it (P1-12).
    """
    project_store = get_project_store(request)
    handle = project_store.create(body.title)
    DocumentStore(handle).create()
    # Seeding stamped the project's updated_at; re-read the row so the response is not one
    # write behind what is on disk.
    handle = project_store.open_path(handle.path)
    return _project_detail(handle, DocumentStore(handle))


@router.get(
    "/projects/{project_id}",
    tags=["projects"],
    summary="One project with its document list",
    response_model=ProjectDetailOut,
    responses=error_responses(404),
)
def get_project(request: Request, project_id: str) -> ProjectDetailOut:
    handle = open_project(request, project_id)
    return _project_detail(handle, DocumentStore(handle))


@router.get(
    "/projects/{project_id}/documents",
    tags=["documents"],
    summary="Ordered document metadata, without content",
    response_model=DocumentListOut,
    responses=error_responses(404),
)
def list_documents(request: Request, project_id: str) -> DocumentListOut:
    """The chapter list.

    Content is deliberately omitted: the outline panel must never pull the whole manuscript to
    draw a chapter list, and that discipline starts here (P1-5).
    """
    handle = open_project(request, project_id)
    return DocumentListOut(
        documents=[DocumentMetaOut.of(meta) for meta in DocumentStore(handle).list_meta()]
    )


@router.post(
    "/projects/{project_id}/documents",
    tags=["documents"],
    summary="Create a chapter, appended at the end",
    status_code=status.HTTP_201_CREATED,
    response_model=DocumentOut,
    responses=error_responses(404, 422),
)
def create_document(
    request: Request, project_id: str, body: DocumentCreateIn | None = None
) -> DocumentOut:
    handle = open_project(request, project_id)
    title = body.title if body is not None else None
    return DocumentOut.of(DocumentStore(handle).create(title))


@router.get(
    "/projects/{project_id}/outline",
    tags=["outline"],
    summary="The table of contents across every chapter",
    response_model=OutlineOut,
    responses=error_responses(404),
)
def get_outline(request: Request, project_id: str) -> OutlineOut:
    """The stitched TOC (P1-7, P1-11).

    Reads only derived columns, so the whole manuscript's outline is drawn without loading a
    single chapter's content (D2, D18).
    """
    handle = open_project(request, project_id)
    chapters = DocumentStore(handle).outline()
    return OutlineOut(
        project_id=handle.id,
        chapters=[OutlineChapterOut.of(chapter) for chapter in chapters],
    )


# -- documents ------------------------------------------------------------------------------


@router.get(
    "/documents/{document_id}",
    tags=["documents"],
    summary="One document including its content",
    response_model=DocumentOut,
    responses=error_responses(404),
)
def get_document(request: Request, document_id: str) -> DocumentOut:
    handle = get_locator(request).resolve(document_id)
    return DocumentOut.of(DocumentStore(handle).get(document_id))


@router.put(
    "/documents/{document_id}/content",
    tags=["documents"],
    summary="Save document content",
    response_model=SaveResultOut,
    responses=error_responses(400, 404, 409, 413, 422),
)
def save_document_content(
    request: Request, document_id: str, body: DocumentSaveIn
) -> SaveResultOut:
    """The only path by which manuscript text changes (P1-6).

    Validates, derives the projection, increments the version, and writes - all in one
    transaction. A stale ``version`` writes nothing and comes back as a ``409`` carrying the
    current version, so the client can offer a reload instead of merging (D19).
    """
    handle = get_locator(request).resolve(document_id)
    result = DocumentStore(handle).save_content(document_id, body.content_json, body.version)
    return SaveResultOut.of(result)


@router.patch(
    "/documents/{document_id}",
    tags=["documents"],
    summary="Rename a document",
    response_model=DocumentMetaOut,
    responses=error_responses(404, 422),
)
def rename_document(request: Request, document_id: str, body: DocumentRenameIn) -> DocumentMetaOut:
    """Rename. The content ``version`` is untouched - a rename is not a text edit."""
    handle = get_locator(request).resolve(document_id)
    return DocumentMetaOut.of(DocumentStore(handle).rename(document_id, body.title))


# -- anchors --------------------------------------------------------------------------------


@router.post(
    "/documents/{document_id}/anchors",
    tags=["anchors"],
    summary="Anchor a range of this document's text",
    status_code=status.HTTP_201_CREATED,
    response_model=AnchorOut,
    responses=error_responses(404, 409, 422),
)
def create_anchor(request: Request, document_id: str, body: AnchorCreateIn) -> AnchorOut:
    """Create an anchor from a range and a version (P2-7).

    The client sends where, not what: the server reads the quote and its surrounding context out
    of the stored content, so an anchor can never disagree with the manuscript. A range
    presented against a stale version is refused with a ``409`` exactly as a save is - an anchor
    over text that has since changed is an anchor over text nobody looked at (D19).
    """
    handle = get_locator(request).resolve(document_id)
    anchor = AnchorStore(handle).create(
        document_id,
        from_pos=body.from_pos,
        to_pos=body.to_pos,
        version=body.version,
        label=body.label,
    )
    return AnchorOut.of(anchor)


@router.get(
    "/documents/{document_id}/anchors",
    tags=["anchors"],
    summary="This document's anchors, resolved against its current text",
    response_model=AnchorListOut,
    responses=error_responses(404),
)
def list_document_anchors(request: Request, document_id: str) -> AnchorListOut:
    """Resolved on read and **not** persisted (D21).

    So a document opened after its file changed behind the app's back reports what is true now
    rather than what was true at the last write. The stored columns are a cache of that write's
    answer; the resolver is the answer.
    """
    handle = get_locator(request).resolve(document_id)
    anchors = AnchorStore(handle).list_for_document(document_id)
    return AnchorListOut(anchors=[AnchorOut.of(anchor) for anchor in anchors])


@router.get(
    "/projects/{project_id}/anchors",
    tags=["anchors"],
    summary="Every anchor in the project, filterable by status",
    response_model=AnchorListOut,
    responses=error_responses(404, 422),
)
def list_project_anchors(
    request: Request,
    project_id: str,
    status_filter: Annotated[AnchorStatusFilter | None, Query(alias="status")] = None,
) -> AnchorListOut:
    """What the *Marks* tab reads, so "what is stale" is one click.

    These are the cached answers, not a fresh resolution: re-resolving here would mean
    projecting every chapter in the manuscript to draw one panel, which is what the document
    list route exists not to do (P1-5, D2).
    """
    handle = open_project(request, project_id)
    anchors = AnchorStore(handle).list_for_project(status=status_filter)
    return AnchorListOut(anchors=[AnchorOut.of(anchor) for anchor in anchors])


@router.patch(
    "/anchors/{anchor_id}",
    tags=["anchors"],
    summary="Re-link an anchor to a new range, or change its label",
    response_model=AnchorOut,
    responses=error_responses(404, 409, 422),
)
def patch_anchor(request: Request, anchor_id: str, body: AnchorPatchIn) -> AnchorOut:
    """The repair path (P2-10), and the same request whichever way the writer got here.

    Accepting a suggestion and picking a passage by hand both come down to a range, so the
    server cannot tell them apart and does not try. Nothing is ever repaired automatically.
    """
    handle = get_locator(request).resolve_anchor(anchor_id)
    store = AnchorStore(handle)
    anchor = store.get(anchor_id)
    if body.relinks:
        assert body.from_pos is not None and body.to_pos is not None and body.version is not None
        anchor = store.relink(
            anchor_id, from_pos=body.from_pos, to_pos=body.to_pos, version=body.version
        )
    if body.label is not None:
        anchor = store.set_label(anchor_id, body.label)
    return AnchorOut.of(anchor)


@router.delete(
    "/anchors/{anchor_id}",
    tags=["anchors"],
    summary="Remove an anchor",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=error_responses(404),
)
def delete_anchor(request: Request, anchor_id: str) -> None:
    """The only way an anchor ever goes away (``specs/anchors.md`` section 9)."""
    locator = get_locator(request)
    handle = locator.resolve_anchor(anchor_id)
    AnchorStore(handle).delete(anchor_id)
    locator.forget(anchor_id)


# -- helpers --------------------------------------------------------------------------------


def _project_detail(handle: ProjectHandle, store: DocumentStore) -> ProjectDetailOut:
    """One project with its documents, counting chapters from the list we already have."""
    documents = store.list_meta()
    return ProjectDetailOut(
        project=ProjectSummaryOut.of_handle(handle, documents),
        documents=[DocumentMetaOut.of(meta) for meta in documents],
    )
