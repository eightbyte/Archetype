"""Serving the built frontend from this process (P1-14).

Archetype has two run modes and they differ only here.

**Dev** is two processes: uvicorn on 8787 and Vite on 5173, with Vite proxying ``/api`` to
uvicorn. Nothing in this module is involved.

**Single process** is the real target shape (D7): ``npm run build`` leaves a static bundle in
``web/dist``, this module mounts it at ``/``, and the whole app is one uvicorn on 8787 with no
Node in the picture. Phase 9 packages that; Phase 1 verifies it works, early, rather than
discovering in Phase 9 that it does not.

The mount goes on **after** the ``/api`` router. Starlette matches routes in order, so a mount at
``/`` can only be reached by a path no API route claimed - the API can never be shadowed by a file
that happens to be named after it.

The mount is optional in the honest sense: a clone that has never run ``npm run build`` has no
``web/dist``, and the server must still start and serve its API. When there is nothing to mount,
``GET /`` answers in the standard error envelope with a code that says *why* - a bare "Not Found"
at the address the README tells you to open is a bad way to learn you skipped a build step.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from .errors import error_response

__all__ = ["INDEX_FILE", "install_web_app", "is_built"]

logger = logging.getLogger("archetype.web")

#: The file a built frontend must have for the directory to be worth mounting.
INDEX_FILE = "index.html"


def is_built(dist: Path | None) -> bool:
    """True if ``dist`` looks like a built frontend rather than an empty or absent directory."""
    return dist is not None and (dist / INDEX_FILE).is_file()


class _WebFiles(StaticFiles):
    """``StaticFiles`` that keeps ``index.html`` out of the browser's cache.

    Vite fingerprints everything under ``assets/`` so those files are safe to cache forever, but
    ``index.html`` is the one file whose name never changes and whose contents do on every build.
    Cached, it would go on loading the previous build's scripts after an upgrade. ``no-cache``
    means *revalidate*, not *do not store*: the ETag Starlette already sends turns the check into
    a 304 in the ordinary case.
    """

    def file_response(
        self,
        full_path: str | os.PathLike[str],
        stat_result: os.stat_result,
        scope: Scope,
        status_code: int = 200,
    ) -> Response:
        response = super().file_response(full_path, stat_result, scope, status_code)
        if str(full_path).endswith(".html"):
            response.headers["cache-control"] = "no-cache"
        return response


def install_web_app(app: FastAPI, dist: Path | None) -> bool:
    """Mount the built frontend at ``/`` if there is one, and report whether it was mounted.

    Call this **last**, after every route the API owns is registered.

    Args:
        app: The application to mount onto.
        dist: The directory ``npm run build`` wrote, or ``None`` to never mount one.

    Returns:
        ``True`` if a bundle was mounted, ``False`` if the app is serving its API alone.
    """
    if not is_built(dist):
        _install_not_built_notice(app, dist)
        return False

    # html=True serves index.html for "/" and, for anything else it cannot find, raises the 404
    # that the error handlers turn into the envelope. It is deliberately not a catch-all
    # rewrite: the app has no router (see web/src/App.tsx), so every real URL is "/", and a
    # missing asset should say it is missing rather than come back as a page.
    app.mount("/", _WebFiles(directory=dist, html=True), name="web")
    logger.info("serving the built frontend from %s", dist)
    return True


def _install_not_built_notice(app: FastAPI, dist: Path | None) -> None:
    """Answer ``GET /`` with what to do about it, in the standard envelope."""
    if dist is None:
        reason = "the static mount is switched off (ARCHETYPE_WEB_DIST is empty)"
    else:
        reason = f"no {INDEX_FILE} in {dist}"
    logger.info("no frontend mounted: %s; serving the API alone", reason)

    @app.get("/", include_in_schema=False)
    def web_not_built() -> JSONResponse:
        return error_response(
            404,
            "web_not_built",
            "the web app is not being served from this process",
            {
                "reason": reason,
                "remedy": (
                    "run 'npm run build' in web/ and restart, or use the two-process dev mode "
                    "and open http://127.0.0.1:5173"
                ),
            },
        )
