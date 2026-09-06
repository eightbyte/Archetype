"""What a route needs, resolved from the application (P1-5).

The store, the locator, and - from Phase 4 - the provider factory are built once in
:func:`archetype.app.create_app` and kept on ``app.state``; these are the accessors. No
dependency-injection framework - a settings object, a store, and a locator do not need one.

Every accessor takes a :class:`~starlette.requests.HTTPConnection` rather than a ``Request``,
because Phase 4 adds a surface that is not a request: a WebSocket is an ``HTTPConnection`` too, and
the socket needs exactly the same three things a route does (P4-10).
"""

from __future__ import annotations

from collections.abc import Callable

from starlette.requests import HTTPConnection

from ..config import Settings
from ..llm.port import LLMProvider
from ..manuscript.documents import DocumentStore
from ..manuscript.locator import DocumentLocator
from ..projects.store import ProjectHandle, ProjectStore

__all__ = [
    "ProviderFactory",
    "document_store_for",
    "get_locator",
    "get_project_store",
    "get_provider_factory",
    "get_settings",
    "open_project",
]

#: How a provider is obtained: settings in, an :class:`~archetype.llm.port.LLMProvider` out, or a
#: ``ProviderError`` saying why there is not one. The application installs
#: :func:`archetype.llm.registry.build_provider`; the suite installs one that hands back
#: ``FakeProvider``, which is how no test in this project touches the network (outline section 8).
#:
#: A factory rather than a built provider, because settings can change under a running process
#: (``PATCH /api/settings``, P4-11) and "swapping providers takes effect on the next request" is
#: an exit criterion. A provider constructed once at startup would answer from the old settings
#: until a restart.
ProviderFactory = Callable[[Settings], LLMProvider]


def get_settings(connection: HTTPConnection) -> Settings:
    """The settings this application is currently running with."""
    return connection.app.state.settings


def get_project_store(connection: HTTPConnection) -> ProjectStore:
    """The store over the configured projects directory."""
    return connection.app.state.project_store


def get_locator(connection: HTTPConnection) -> DocumentLocator:
    """The document-id to project resolver."""
    return connection.app.state.document_locator


def get_provider_factory(connection: HTTPConnection) -> ProviderFactory:
    """The one way a route or a socket obtains a provider (P4-8, D34)."""
    return connection.app.state.provider_factory


def open_project(connection: HTTPConnection, project_id: str) -> ProjectHandle:
    """Resolve a project id to an open, migrated handle.

    Raises:
        ProjectNotFoundError: Translated to a ``404`` by the error handlers.
    """
    return get_project_store(connection).open(project_id)


def document_store_for(handle: ProjectHandle) -> DocumentStore:
    """The document repository scoped to one project."""
    return DocumentStore(handle)
