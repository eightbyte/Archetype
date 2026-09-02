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

import re
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import Response

from .. import __version__
from ..manuscript.anchors.store import AnchorStore
from ..manuscript.documents import DocumentStore
from ..manuscript.markdown import chapters_to_markdown, document_to_markdown
from ..manuscript.markdown.importer import import_markdown
from ..manuscript.snapshots import SnapshotStore
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
    DocumentReorderIn,
    DocumentSaveIn,
    ImportNoticeOut,
    MarkdownImportIn,
    MarkdownImportOut,
    OutlineChapterOut,
    OutlineOut,
    ProjectCreateIn,
    ProjectDetailOut,
    ProjectListOut,
    ProjectSummaryOut,
    SaveResultOut,
    SkippedFileOut,
    SnapshotCaptureIn,
    SnapshotCaptureOut,
    SnapshotListOut,
    SnapshotMetaOut,
    SnapshotOut,
    SnapshotRestoreIn,
)

__all__ = ["router"]

router = APIRouter(prefix="/api")

#: How a Markdown export is served. The one non-JSON response in the API (P2-13, ruling 9).
MARKDOWN_MEDIA_TYPE = "text/markdown"


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
    "/projects/{project_id}/documents/deleted",
    tags=["documents"],
    summary="Soft-deleted chapters, most recently deleted first",
    response_model=DocumentListOut,
    responses=error_responses(404),
)
def list_deleted_documents(request: Request, project_id: str) -> DocumentListOut:
    """The restore surface (P2-11, D22).

    A soft delete is only recoverable if there is somewhere to recover it from. Every other
    read path filters these out; this is the one that asks for them, and it is the reason the
    delete confirmation can be brief.
    """
    handle = open_project(request, project_id)
    return DocumentListOut(
        documents=[DocumentMetaOut.of(meta) for meta in DocumentStore(handle).list_deleted()]
    )


@router.put(
    "/projects/{project_id}/documents/order",
    tags=["documents"],
    summary="Rewrite the chapter order",
    response_model=DocumentListOut,
    responses=error_responses(404, 409, 422),
)
def reorder_documents(
    request: Request, project_id: str, body: DocumentReorderIn
) -> DocumentListOut:
    """Reorder the project's chapters (P2-2, P2-11).

    The body is the **complete** ordered list of live chapters. A list that is not exactly the
    current set is refused with a ``409`` and nothing is written - that completeness check is
    the concurrency guard, which is why no project version is presented alongside it.

    No document's ``version`` moves: an order is a property of the project, not a text edit,
    and invalidating an in-flight autosave over a move would cost the writer a keystroke.
    """
    handle = open_project(request, project_id)
    documents = DocumentStore(handle).reorder(body.document_ids)
    return DocumentListOut(documents=[DocumentMetaOut.of(meta) for meta in documents])


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


@router.delete(
    "/documents/{document_id}",
    tags=["documents"],
    summary="Soft-delete a chapter",
    response_model=DocumentMetaOut,
    responses=error_responses(404),
)
def delete_document(request: Request, document_id: str) -> DocumentMetaOut:
    """Delete a chapter, recoverably (P2-2, D22).

    A soft delete: a ``pre-delete`` snapshot and ``deleted_at`` are written in one transaction,
    and the row, its text, its snapshots, and its anchors all stay. The chapter leaves every
    list and count; its anchors read as ``orphaned`` until it comes back.

    ``200`` rather than ``204``, and the chapter's metadata comes back with it: the client has
    just been told a chapter is gone and needs to say what went and when, which is exactly
    ``deleted_at``.
    """
    handle = get_locator(request).resolve(document_id)
    return DocumentMetaOut.of(DocumentStore(handle).delete(document_id))


@router.post(
    "/documents/{document_id}/restore",
    tags=["documents"],
    summary="Bring a soft-deleted chapter back",
    response_model=DocumentMetaOut,
    responses=error_responses(404),
)
def restore_document(request: Request, document_id: str) -> DocumentMetaOut:
    """Undo a delete (P2-2, D22).

    The chapter returns with its text byte for byte and its anchors at the statuses they held,
    appended at the end of the order rather than dropped back into a position the chapters
    around it have moved on from. Restoring a live chapter is a no-op, not an error.
    """
    handle = get_locator(request).resolve(document_id)
    return DocumentMetaOut.of(DocumentStore(handle).restore(document_id))


# -- snapshots ------------------------------------------------------------------------------


@router.get(
    "/documents/{document_id}/snapshots",
    tags=["snapshots"],
    summary="One chapter's history, newest first",
    response_model=SnapshotListOut,
    responses=error_responses(404),
)
def list_snapshots(request: Request, document_id: str) -> SnapshotListOut:
    """Metadata only - never content (P2-3, P2-12).

    Deliberately not filtered by ``deleted_at``: the history of a deleted chapter is exactly
    what somebody deciding whether to restore it wants to see.
    """
    handle = get_locator(request).resolve(document_id)
    snapshots = SnapshotStore(handle).list(document_id)
    return SnapshotListOut(snapshots=[SnapshotMetaOut.of(meta) for meta in snapshots])


@router.post(
    "/documents/{document_id}/snapshots",
    tags=["snapshots"],
    summary="Mark this version, or hand the chapter over",
    response_model=SnapshotCaptureOut,
    responses=error_responses(404, 422),
)
def capture_snapshot(
    request: Request, document_id: str, body: SnapshotCaptureIn | None = None
) -> SnapshotCaptureOut:
    """Take a snapshot on demand or at handover (D23).

    Only the two reasons a client owns are accepted. The ``pre-*`` reasons are the server's,
    each written inside the transaction of the operation it protects against, so a client that
    could ask for one could put a ``pre-delete`` in the history with nothing deleted.

    A ``handover`` whose content the newest snapshot already holds writes nothing and says so.
    That is the ordinary answer for a chapter nobody touched, not a failure.
    """
    handle = get_locator(request).resolve(document_id)
    asked = body if body is not None else SnapshotCaptureIn()
    meta = SnapshotStore(handle).capture(document_id, reason=asked.reason, label=asked.label)
    return SnapshotCaptureOut(
        captured=meta is not None,
        snapshot=None if meta is None else SnapshotMetaOut.of(meta),
    )


@router.get(
    "/snapshots/{snapshot_id}",
    tags=["snapshots"],
    summary="One snapshot including its content",
    response_model=SnapshotOut,
    responses=error_responses(404),
)
def get_snapshot(request: Request, snapshot_id: str) -> SnapshotOut:
    """What a preview reads. The content is the whole point, so this route carries it."""
    handle = get_locator(request).resolve_snapshot(snapshot_id)
    return SnapshotOut.of(SnapshotStore(handle).get(snapshot_id))


@router.post(
    "/snapshots/{snapshot_id}/restore",
    tags=["snapshots"],
    summary="Write a snapshot's content back to its chapter",
    response_model=SaveResultOut,
    responses=error_responses(404, 409, 422),
)
def restore_snapshot(request: Request, snapshot_id: str, body: SnapshotRestoreIn) -> SaveResultOut:
    """A restore is an ordinary save (P2-3, D23).

    The outgoing text is captured as ``pre-restore`` inside the save's own transaction, after
    the D19 guard passes - so a restore refused as stale leaves nothing behind, not even the
    snapshot that was about to protect it. The response is a save result because that is what
    it is: a new version, a re-derived projection, and the anchors the write moved.
    """
    handle = get_locator(request).resolve_snapshot(snapshot_id)
    return SaveResultOut.of(SnapshotStore(handle).restore(snapshot_id, body.version))


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


# -- Markdown (P2-13, P2-14, D15) -------------------------------------------------------------
#
# The one non-JSON corner of this API (phase-2 plan section 2, ruling 9). An export is a file a
# person saves, not a payload a client parses, and wrapping it in JSON to honour "JSON in, JSON
# out" would make every client unwrap it. Import is ordinary JSON in both directions.


@router.get(
    "/documents/{document_id}/markdown",
    tags=["markdown"],
    summary="One chapter as a Markdown file",
    response_class=Response,
    responses={
        200: {
            "content": {MARKDOWN_MEDIA_TYPE: {"schema": {"type": "string"}}},
            "description": "The chapter as Markdown.",
        },
        **error_responses(404),
    },
)
def export_document_markdown(request: Request, document_id: str) -> Response:
    """A chapter as Markdown (P2-13, D15).

    The **title is not in the body**. This is the round-trip artifact - importing it back gives
    the same document, which is P2-14's acceptance bar - and a title written into the text would
    come back as a heading the writer never typed. It travels in the filename instead.
    """
    handle = get_locator(request).resolve(document_id)
    document = DocumentStore(handle).get(document_id)
    return _markdown_response(document_to_markdown(document.content), document.meta.title)


@router.get(
    "/projects/{project_id}/markdown",
    tags=["markdown"],
    summary="Every live chapter as one Markdown file",
    response_class=Response,
    responses={
        200: {
            "content": {MARKDOWN_MEDIA_TYPE: {"schema": {"type": "string"}}},
            "description": "The manuscript as Markdown, each chapter under its title.",
        },
        **error_responses(404),
    },
)
def export_project_markdown(request: Request, project_id: str) -> Response:
    """The whole manuscript in order, each chapter preceded by its title as an H1 (P2-13, D15).

    A reading and hand-off artifact, and **no round trip is promised** (ruling 4): the chapter
    boundaries are H1s, and the schema has no node that means "chapter". Deleted chapters are
    absent, from the one predicate every read in the document store applies (D22).
    """
    handle = open_project(request, project_id)
    body = chapters_to_markdown(DocumentStore(handle).list_content())
    return _markdown_response(body, handle.title)


@router.post(
    "/projects/{project_id}/import",
    tags=["markdown"],
    summary="Create chapters from a Markdown file",
    status_code=status.HTTP_201_CREATED,
    response_model=MarkdownImportOut,
    responses=error_responses(404, 413, 422),
)
def import_project_markdown(
    request: Request, project_id: str, body: MarkdownImportIn
) -> MarkdownImportOut:
    """Append the chapters a Markdown file describes (P2-14, D15).

    **Creates; never replaces.** Every chapter is appended through the store's ``create``, so
    ``save_content`` stays the only path by which existing manuscript text changes (ruling 5).
    Replacing a chapter is import-then-delete, and both are already recoverable.

    Nothing is created until every chapter has been measured, so a file holding one oversized
    chapter is a ``413`` with an empty project rather than half an import. What the closed schema
    could not hold comes back in ``dropped`` - never as an error, and never silently.
    """
    handle = open_project(request, project_id)
    outcome = import_markdown(
        DocumentStore(handle), body.markdown, mode=body.mode, title=body.title
    )
    return MarkdownImportOut(
        documents=[DocumentMetaOut.of(document.meta) for document in outcome.documents],
        dropped=[ImportNoticeOut.of(notice) for notice in outcome.notices],
    )


# -- helpers --------------------------------------------------------------------------------


def _markdown_response(body: str, name: str) -> Response:
    """A Markdown file, named after what it holds.

    A trailing newline is added because a text file ends with one; the importer does not care
    either way, and every other reader does. The filename is given twice - an ASCII fallback and
    the RFC 5987 form - so a chapter called "Départ" downloads under its own name in a browser
    that understands it and under a readable one in a browser that does not.
    """
    text = f"{body}\n" if body else ""
    stem = _filename_stem(name)
    ascii_stem = stem.encode("ascii", "replace").decode("ascii").replace("?", "_")
    disposition = (
        f"attachment; filename=\"{ascii_stem}.md\"; filename*=UTF-8''{quote(stem, safe='')}.md"
    )
    return Response(
        content=text,
        media_type=f"{MARKDOWN_MEDIA_TYPE}; charset=utf-8",
        headers={"Content-Disposition": disposition},
    )


def _filename_stem(name: str) -> str:
    """A title, made safe to put in a filename and in a header.

    Everything a filesystem or a header would object to becomes a hyphen. A title that reduces
    to nothing at all becomes ``chapter``, because a download named ``.md`` is not a download
    anybody can find again.
    """
    stem = _UNSAFE_IN_FILENAME.sub("-", name)
    return _RUN_OF_HYPHENS.sub("-", stem).strip(" .-")[:_MAX_FILENAME_STEM] or "chapter"


#: Path separators, the characters Windows refuses in a name, control characters, and the quote
#: and semicolon that would end a `Content-Disposition` value early. Surrounding whitespace goes
#: with them, and the hyphens that leaves are collapsed, so `A/B: "quoted"` is `A-B-quoted`.
_UNSAFE_IN_FILENAME = re.compile(r'\s*[\\/:*?"<>|;,\x00-\x1f]+\s*')
_RUN_OF_HYPHENS = re.compile(r"-{2,}")
_MAX_FILENAME_STEM = 80


def _project_detail(handle: ProjectHandle, store: DocumentStore) -> ProjectDetailOut:
    """One project with its documents, counting chapters from the list we already have."""
    documents = store.list_meta()
    return ProjectDetailOut(
        project=ProjectSummaryOut.of_handle(handle, documents),
        documents=[DocumentMetaOut.of(meta) for meta in documents],
    )
