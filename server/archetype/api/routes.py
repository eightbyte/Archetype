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

from fastapi import APIRouter, Request, status

from .. import __version__
from ..manuscript.documents import DocumentStore
from ..projects.store import ProjectHandle
from .deps import get_locator, get_project_store, open_project
from .errors import error_responses
from .schemas import (
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


# -- helpers --------------------------------------------------------------------------------


def _project_detail(handle: ProjectHandle, store: DocumentStore) -> ProjectDetailOut:
    """One project with its documents, counting chapters from the list we already have."""
    documents = store.list_meta()
    return ProjectDetailOut(
        project=ProjectSummaryOut.of_handle(handle, documents),
        documents=[DocumentMetaOut.of(meta) for meta in documents],
    )
