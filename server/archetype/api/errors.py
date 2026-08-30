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

from ..manuscript.documents import (
    ContentTooLargeError,
    DocumentNotFoundError,
    StaleVersionError,
)
from ..manuscript.projection import InvalidDocumentError
from ..projects.store import ProjectNotFoundError
from .logging import request_id_of

__all__ = [
    "ApiError",
    "ErrorBody",
    "ErrorResponse",
    "error_response",
    "error_responses",
    "install_error_handlers",
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
