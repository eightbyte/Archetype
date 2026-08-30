"""What a route needs, resolved from the application (P1-5).

The store and the locator are built once in :func:`archetype.app.create_app` and kept on
``app.state``; these are the accessors. No dependency-injection framework - a settings object, a
store, and a locator do not need one.
"""

from __future__ import annotations

from fastapi import Request

from ..config import Settings
from ..manuscript.documents import DocumentStore
from ..manuscript.locator import DocumentLocator
from ..projects.store import ProjectHandle, ProjectStore

__all__ = [
    "document_store_for",
    "get_locator",
    "get_project_store",
    "get_settings",
    "open_project",
]


def get_settings(request: Request) -> Settings:
    """The settings this application was built with."""
    return request.app.state.settings


def get_project_store(request: Request) -> ProjectStore:
    """The store over the configured projects directory."""
    return request.app.state.project_store


def get_locator(request: Request) -> DocumentLocator:
    """The document-id to project resolver."""
    return request.app.state.document_locator


def open_project(request: Request, project_id: str) -> ProjectHandle:
    """Resolve a project id to an open, migrated handle.

    Raises:
        ProjectNotFoundError: Translated to a ``404`` by the error handlers.
    """
    return get_project_store(request).open(project_id)


def document_store_for(handle: ProjectHandle) -> DocumentStore:
    """The document repository scoped to one project."""
    return DocumentStore(handle)
