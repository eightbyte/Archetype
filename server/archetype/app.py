"""The FastAPI application (P1-1, P1-5).

The factory builds the settings-dependent pieces once - the project store and the document
locator - and hangs them on ``app.state``, where :mod:`archetype.api.deps` reads them. Tests
construct their own :class:`~archetype.config.Settings` and pass them in, so nothing in the suite
depends on the developer's data directory.

The ``/api`` router and the uniform error envelope arrive with P1-5, request logging with P1-13,
and the static mount that serves a built ``web/dist`` from this same process with P1-14. Phase 3
adds a second module of routes under the same prefix (P3-9); both are included before the mount.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI

from . import __version__
from .api.bible_routes import router as bible_router
from .api.errors import install_error_handlers
from .api.logging import RequestLogMiddleware
from .api.routes import router as api_router
from .api.static import install_web_app
from .config import Settings, get_settings
from .manuscript.locator import DocumentLocator
from .projects.store import ProjectStore

__all__ = ["create_app"]

logger = logging.getLogger("archetype")


def _configure_logging(settings: Settings) -> None:
    # uvicorn's "trace" has no logging equivalent; it is the most verbose level either way.
    level_name = "debug" if settings.log_level == "trace" else settings.log_level
    logging.basicConfig(
        level=getattr(logging, level_name.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application. Tests construct their own settings and pass them in."""
    settings = settings or get_settings()
    _configure_logging(settings)

    app = FastAPI(
        title="Archetype",
        version=__version__,
        summary="A workspace for writing and maintaining a long narrative.",
    )
    app.state.settings = settings
    projects_dir = settings.ensure_dirs()
    app.state.project_store = ProjectStore(projects_dir)
    app.state.document_locator = DocumentLocator(app.state.project_store)

    # Outside the exception handlers and inside Starlette's ServerErrorMiddleware, so every
    # request is logged once with its real outcome - including one that raised (P1-13).
    app.add_middleware(RequestLogMiddleware)
    install_error_handlers(app)
    app.include_router(api_router)
    # The bible's half of the same `/api` prefix (P3-9 to P3-11). Two modules, one router
    # surface: the prefix, the envelope, and the ordering guarantee below belong to the API.
    app.include_router(bible_router)

    # Last, and deliberately so: Starlette matches routes in order, so a mount at / can only be
    # reached by a path no API route claimed (P1-14).
    app.state.web_mounted = install_web_app(app, settings.web_dist)

    logger.info("archetype %s serving projects from %s", __version__, projects_dir)
    return app
