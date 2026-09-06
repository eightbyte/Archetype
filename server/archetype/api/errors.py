"""The uniform error envelope (P1-5).

Every failing response - a missing project, a stale save, a malformed payload, an unhandled bug -
comes back in one shape::

    {"error": {"code": "...", "message": "...", "detail": ...}}

``code`` is the stable, machine-readable name the client branches on. ``message`` is a sentence a
person can read. ``detail`` carries whatever that particular failure needs and is ``null`` when
there is nothing to add - the ``409`` from the save protocol puts the current version there, so
the editor can offer a reload without a second round trip (D19).

Domain exceptions are translated by handlers registered here rather than caught in each route.
A route that raises :class:`~archetype.manuscript.documents.StaleVersionError` gets the right
status and body without knowing what HTTP is, which keeps the store usable from the agent loop
in Phase 6 as well as from a request.

Stack traces never reach the client. A ``500`` carries the request id and nothing else, so the
envelope can be matched to the log line that has the traceback (P1-13).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..bible.entries import (
    EntryNotFoundError,
    RevisionNotFoundError,
    StaleEntryVersionError,
)
from ..bible.links import DuplicateLinkError, LinkNotFoundError
from ..bible.schema import InvalidAttributesError
from ..chat.conversations import ConversationNotFoundError
from ..llm.port import ProviderError
from ..manuscript.anchors.resolve import AnchorRangeError
from ..manuscript.anchors.store import AnchorNotFoundError
from ..manuscript.documents import (
    ContentTooLargeError,
    DocumentNotFoundError,
    ReorderMismatchError,
    StaleVersionError,
)
from ..manuscript.projection import InvalidDocumentError
from ..manuscript.snapshots import SnapshotNotFoundError
from ..projects.store import ProjectNotFoundError
from .logging import request_id_of

__all__ = [
    "PROVIDER_ERROR_STATUS",
    "ApiError",
    "ErrorBody",
    "ErrorResponse",
    "error_response",
    "error_responses",
    "install_error_handlers",
    "provider_error_status",
]

logger = logging.getLogger("archetype.api")


class ErrorBody(BaseModel):
    """The body of the envelope."""

    code: str = Field(description="Stable machine-readable name for this failure.")
    message: str = Field(description="A sentence a person can read.")
    detail: Any | None = Field(
        default=None, description="Whatever this particular failure needs; null when nothing."
    )


class ErrorResponse(BaseModel):
    """The envelope every failing response uses."""

    error: ErrorBody


class ApiError(Exception):
    """An error that already knows its status and its code."""

    def __init__(self, status_code: int, code: str, message: str, detail: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.detail = detail


def error_response(status_code: int, code: str, message: str, detail: Any = None) -> JSONResponse:
    """Build the envelope. The only place a failing body is constructed."""
    body = ErrorBody(code=code, message=message, detail=detail)
    return JSONResponse(
        status_code=status_code, content={"error": jsonable_encoder(body, exclude_none=False)}
    )


def error_responses(*status_codes: int) -> dict[int | str, dict[str, Any]]:
    """OpenAPI ``responses`` entries, so the generated schema documents the envelope."""
    return {code: {"model": ErrorResponse} for code in status_codes}


#: What each provider failure is over HTTP (P4-9, ruling 4). The codes are the taxonomy's, closed
#: at six; the statuses are this layer's reading of them, and each is chosen so a client that only
#: looks at the number still does something sensible:
#:
#: * ``provider_unconfigured`` is a ``503`` - the assistant is not available *yet*, and nothing
#:   about the request was wrong;
#: * ``provider_rate_limited`` is a ``429``, the status that means exactly that;
#: * ``context_too_large`` is a ``413``, which is what an oversized chapter already answers, and
#:   the writer's fix is the same shape: send less;
#: * the remaining three are ``502`` - the failure is upstream and it is not the writer's request
#:   that is malformed.
#:
#: The **code** is what a client branches on; this table exists so that the status never
#: contradicts it.
PROVIDER_ERROR_STATUS: dict[str, int] = {
    "provider_unconfigured": 503,
    "provider_auth_failed": 502,
    "provider_rate_limited": 429,
    "provider_unavailable": 502,
    "provider_refused": 502,
    "context_too_large": 413,
}


def provider_error_status(code: str) -> int:
    """The HTTP status for one provider failure. Unknown codes are a ``502``, never a ``500``.

    A code this table has never heard of would mean the taxonomy grew without this map being
    told - and the honest answer to that is still "the provider layer failed", not "the server
    has a bug".
    """
    return PROVIDER_ERROR_STATUS.get(code, 502)


# Status codes carry a default code name, used when an HTTPException is raised without one.
_STATUS_CODES = {
    400: "invalid_request",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    422: "validation_error",
    500: "internal_error",
}


def install_error_handlers(app: FastAPI) -> None:
    """Register every handler that produces the envelope."""

    @app.exception_handler(ApiError)
    def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return error_response(exc.status_code, exc.code, exc.message, exc.detail)

    @app.exception_handler(ProjectNotFoundError)
    def _project_not_found(request: Request, exc: ProjectNotFoundError) -> JSONResponse:
        return _not_found(request, exc, "project_not_found", "project", "project_id")

    @app.exception_handler(DocumentNotFoundError)
    def _document_not_found(request: Request, exc: DocumentNotFoundError) -> JSONResponse:
        return _not_found(request, exc, "document_not_found", "document", "document_id")

    @app.exception_handler(AnchorNotFoundError)
    def _anchor_not_found(request: Request, exc: AnchorNotFoundError) -> JSONResponse:
        return _not_found(request, exc, "anchor_not_found", "anchor", "anchor_id")

    @app.exception_handler(SnapshotNotFoundError)
    def _snapshot_not_found(request: Request, exc: SnapshotNotFoundError) -> JSONResponse:
        return _not_found(request, exc, "snapshot_not_found", "snapshot", "snapshot_id")

    @app.exception_handler(EntryNotFoundError)
    def _entry_not_found(request: Request, exc: EntryNotFoundError) -> JSONResponse:
        return _not_found(request, exc, "entry_not_found", "entry", "entry_id")

    @app.exception_handler(LinkNotFoundError)
    def _link_not_found(request: Request, exc: LinkNotFoundError) -> JSONResponse:
        return _not_found(request, exc, "link_not_found", "link", "link_id")

    @app.exception_handler(ConversationNotFoundError)
    def _conversation_not_found(request: Request, exc: ConversationNotFoundError) -> JSONResponse:
        return _not_found(request, exc, "conversation_not_found", "conversation", "conversation_id")

    @app.exception_handler(ProviderError)
    def _provider_failed(_: Request, exc: ProviderError) -> JSONResponse:
        # Ruling 4: a provider failure is an envelope, never a crash and never a silent empty
        # answer. A rate limit reaching the writer as a blank reply teaches them the assistant is
        # unreliable rather than that their key is out of quota.
        #
        # On the socket the same six codes arrive as an `error` event instead (P4-10). One
        # taxonomy, two carriers - which is why the code, and not the status, is what a client
        # branches on.
        return error_response(
            provider_error_status(exc.code),
            exc.code,
            exc.message,
            {"provider": exc.provider} if exc.provider else None,
        )

    @app.exception_handler(RevisionNotFoundError)
    def _revision_not_found(_: Request, exc: RevisionNotFoundError) -> JSONResponse:
        # A 404 that says which revision, because the client asked for a number and the number is
        # the useful half of the answer - the entry it asked about does exist.
        return error_response(404, "revision_not_found", str(exc))

    @app.exception_handler(StaleEntryVersionError)
    def _stale_entry(_: Request, exc: StaleEntryVersionError) -> JSONResponse:
        # D19, applied to entries (plan section 2, ruling 3). A different `code` from a
        # document's on purpose: the client's two surfaces recover differently - the editor
        # offers to reload a chapter, the entry form offers to reload a record - and one code
        # for both would make that a branch on which request was in flight.
        return error_response(
            409,
            "entry_version_conflict",
            str(exc),
            {
                "entry_id": exc.entry_id,
                "presented_revision": exc.presented,
                "current_revision": exc.current_revision,
                "updated_at": exc.updated_at,
            },
        )

    @app.exception_handler(DuplicateLinkError)
    def _duplicate_link(_: Request, exc: DuplicateLinkError) -> JSONResponse:
        # A 409 rather than a 422: the request is well-formed and says something true, and what
        # is wrong is the state it arrived into. It carries the id of the link that already says
        # it, so the client can show that one instead of asking the writer to go and find it.
        return error_response(409, "duplicate_link", str(exc), {"link_id": exc.link_id})

    @app.exception_handler(InvalidAttributesError)
    def _invalid_attributes(_: Request, exc: InvalidAttributesError) -> JSONResponse:
        # Every refusal the kind and relation definition makes (D26): an unknown kind, an
        # undeclared attribute, a wrong type, a value outside an `enum`, an `entry_ref` to the
        # wrong kind, an unknown relation or citation role. `field` is what lets the form say
        # which input is wrong rather than rejecting itself as a whole.
        return error_response(422, "invalid_attributes", str(exc), {"field": exc.field})

    @app.exception_handler(ReorderMismatchError)
    def _reorder_mismatch(_: Request, exc: ReorderMismatchError) -> JSONResponse:
        # A 409, not a 422: the body is well-formed and every id in it is a string. What is
        # wrong is that it does not describe this project as it is *now* - which is the same
        # kind of failure a stale save is, and the client answers it the same way, by re-reading
        # the chapter list rather than by correcting a field (P2-2).
        return error_response(
            409,
            "reorder_mismatch",
            str(exc),
            {
                "missing": list(exc.missing),
                "unexpected": list(exc.unexpected),
                "duplicated": list(exc.duplicated),
            },
        )

    @app.exception_handler(AnchorRangeError)
    def _anchor_range(_: Request, exc: AnchorRangeError) -> JSONResponse:
        # Every refusal in specs/anchors.md section 8. The message is written to be shown: the
        # writer selected something, and "invalid range" would not tell them what to do next.
        return error_response(422, "invalid_anchor_range", str(exc))

    @app.exception_handler(StaleVersionError)
    def _stale_version(_: Request, exc: StaleVersionError) -> JSONResponse:
        # D19: the client warns and offers reload. It never merges - so it is handed exactly
        # what it needs to say so, and nothing was written.
        return error_response(
            409,
            "version_conflict",
            str(exc),
            {
                "document_id": exc.document_id,
                "presented_version": exc.presented,
                "current_version": exc.current_version,
                "updated_at": exc.updated_at,
            },
        )

    @app.exception_handler(ContentTooLargeError)
    def _too_large(_: Request, exc: ContentTooLargeError) -> JSONResponse:
        return error_response(
            413, "payload_too_large", str(exc), {"size": exc.size, "limit": exc.limit}
        )

    @app.exception_handler(InvalidDocumentError)
    def _invalid_document(_: Request, exc: InvalidDocumentError) -> JSONResponse:
        return error_response(400, "invalid_document", str(exc))

    @app.exception_handler(RequestValidationError)
    def _request_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return error_response(
            422,
            "validation_error",
            "the request body or path did not validate",
            jsonable_encoder(exc.errors()),
        )

    @app.exception_handler(StarletteHTTPException)
    def _http_exception(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _STATUS_CODES.get(exc.status_code, "error")
        return error_response(exc.status_code, code, str(exc.detail))

    @app.exception_handler(Exception)
    def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # The traceback goes to the log, never to the browser. The request id does cross, and is
        # the only thing that does: it is what turns "it broke" into a line in the log (P1-13).
        request_id = request_id_of(request.scope)
        logger.exception(
            "unhandled error serving %s %s (request_id=%s)",
            request.method,
            request.url.path,
            request_id,
        )
        return error_response(
            500,
            "internal_error",
            "the server failed to handle the request",
            {"request_id": request_id} if request_id else None,
        )


def _not_found(request: Request, exc: Exception, code: str, noun: str, param: str) -> JSONResponse:
    """A 404 that names what was asked for and nothing else.

    The store's own message carries the projects directory, which is useful in a log and is no
    business of the browser's - so it goes to the log and the client gets the id it asked for.
    """
    logger.info("%s not found: %s", noun, exc)
    identifier = request.path_params.get(param)
    named = f" {identifier!r}" if isinstance(identifier, str) else ""
    return error_response(404, code, f"no {noun}{named} in this workspace")
