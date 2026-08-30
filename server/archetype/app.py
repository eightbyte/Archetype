"""The FastAPI application (P1-1).

Group A ships the smallest app that makes "a clean clone reaches a running server" checkable:
the factory, logging wired to the configured level, and a health route. The ``/api`` router,
the pydantic request/response models, and the uniform error envelope are P1-5; the static mount
for single-process serving is P1-14.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI

from . import __version__
from .config import Settings, get_settings

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
    settings.ensure_dirs()
    logger.info("archetype %s serving projects from %s", __version__, settings.projects_dir)

    @app.get("/api/health", tags=["meta"])
    def health() -> dict[str, str]:
        """Liveness, and the version the browser is talking to."""
        return {"status": "ok", "version": __version__}

    return app
