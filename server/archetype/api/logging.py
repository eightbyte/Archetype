"""Structured request logging (P1-13).

One line per request, at a level chosen by the outcome: a `5xx` is an error, a `4xx` is a
warning, everything else is info. The line is `key=value` pairs so it can be grepped without a
parser, and the same values are attached as ``extra`` so a JSON formatter in Phase 9 can pick
them up without the message changing.

Every request gets a short ``request_id``. It goes into the log line, into the ASGI scope so
downstream code can reach it, and - for a `500` only - into the error envelope, so a writer who
reports "it broke" hands over a token that finds the traceback. Nothing else about the failure
crosses to the browser: the traceback belongs in the log (P1-5, P1-13).

Written as pure ASGI rather than ``BaseHTTPMiddleware``: this sits outside the exception
handlers but inside Starlette's ``ServerErrorMiddleware``, so an unhandled exception passes
*through* it. It is logged and re-raised, and the envelope is still produced above.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ..ids import random_token

__all__ = ["REQUEST_ID_LENGTH", "RequestLogMiddleware", "request_id_of"]

logger = logging.getLogger("archetype.request")

#: Long enough to be unambiguous in a session's worth of log, short enough to read aloud.
REQUEST_ID_LENGTH = 8


def request_id_of(scope: Scope) -> str | None:
    """The request id this middleware put on the scope, if it ran."""
    state = scope.get("state")
    if isinstance(state, dict):
        value = state.get("request_id")
        if isinstance(value, str):
            return value
    return None


class RequestLogMiddleware:
    """Log every HTTP request once, with its outcome and how long it took."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = random_token(REQUEST_ID_LENGTH)
        # ``Request.state`` is backed by this dict, so anything downstream - including the
        # exception handlers, which build their own Request over the same scope - can read it.
        state = scope.setdefault("state", {})
        if isinstance(state, dict):
            state["request_id"] = request_id

        method = scope.get("method", "?")
        path = scope.get("path", "?")
        started = time.perf_counter()
        status = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            # The traceback is logged where it is useful. ``ServerErrorMiddleware`` sits above
            # this one and turns the exception into the envelope.
            self._log(logging.ERROR, request_id, method, path, 500, started, failed=True)
            raise

        self._log(_level_for(status), request_id, method, path, status, started)

    @staticmethod
    def _log(
        level: int,
        request_id: str,
        method: str,
        path: str,
        status: int,
        started: float,
        *,
        failed: bool = False,
    ) -> None:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        fields: dict[str, Any] = {
            "request_id": request_id,
            "method": method,
            "path": path,
            "status": status,
            "duration_ms": round(elapsed_ms, 1),
        }
        message = "request_id=%s method=%s path=%s status=%d duration_ms=%.1f"
        args = (request_id, method, path, status, elapsed_ms)
        if failed:
            logger.exception(message + " unhandled=1", *args, extra=fields)
        else:
            logger.log(level, message, *args, extra=fields)


def _level_for(status: int) -> int:
    if status >= 500:
        return logging.ERROR
    if status >= 400:
        return logging.WARNING
    return logging.INFO
