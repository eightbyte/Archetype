"""The HTTP half of an adapter, written once (P4-5, P4-6).

``specs/project-outline.md`` section 3 fixes this: **LLM access is HTTP via httpx, one adapter per
provider.** No vendor SDK is used, which makes ``llm/adapters/`` the only place httpx is imported
just as it is the only place an SDK could be - and the import-graph test in
``tests/test_llm_port.py`` asserts both.

What lives here is everything the two adapters would otherwise write twice: one client, one place
a status code becomes a :class:`~archetype.llm.port.ProviderError`, and one place a transport
failure does. What does **not** live here is any knowledge of either wire format - the body an
adapter posts and the shapes it reads back are its own, and that difference is the whole of an
adapter's job.

Three rules this module holds structurally:

* **Nothing is retried** (phase-4-plan section 2, ruling 6). httpx's default transport retries no
  request, and this module adds none. The autosave backoff ladder is right there and is exactly
  wrong here: retrying a save costs nothing and protects the writer's words; retrying a completion
  costs money and protects nothing.
* **A provider SDK's own exception never escapes this package**, and neither does httpx's. Every
  failure leaves as a ``ProviderError`` carrying one of the six codes.
* **A key is a value this module is handed, never one it reads.** It arrives already in the
  headers an adapter built; nothing here touches settings, and nothing here logs a header (D8,
  D34).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any, Final

import httpx

from ..port import ProviderError, ProviderErrorCode
from .sse import SSEEvent, iter_events_async

__all__ = [
    "CONTEXT_OVERFLOW_SIGNALS",
    "DEFAULT_TIMEOUT",
    "ProviderTransport",
    "code_for_status",
    "looks_like_context_overflow",
]

#: Generous on reading, short on connecting. A model thinking for two minutes is ordinary; a host
#: that will not answer a TCP handshake in ten seconds is not coming.
DEFAULT_TIMEOUT: Final[httpx.Timeout] = httpx.Timeout(
    connect=10.0, read=180.0, write=30.0, pool=10.0
)

#: The substrings that turn a provider's own "no" into ``context_too_large`` rather than
#: ``provider_refused``. This is a **heuristic over somebody else's prose** and is written down
#: here so it reads as one: providers report an over-long prompt as an ordinary ``400`` with a
#: sentence in it, and there is no code either of them sets that means only this.
#:
#: The failure mode is deliberately mild in both directions. A miss lands as ``provider_refused``,
#: which is still a stated cause and still carries the provider's own message - not a blank reply.
#: A false positive names a cause that is one word off. Our own budget check (section 7, P4-8) is
#: the path that matters, and it refuses *before* the request is sent and never guesses.
CONTEXT_OVERFLOW_SIGNALS: Final[tuple[str, ...]] = (
    "context_length_exceeded",
    "context length",
    "context window",
    "maximum context",
    "prompt is too long",
    "too many tokens",
    "reduce the length",
)


def looks_like_context_overflow(*parts: Any) -> bool:
    """True when any of the provider's own strings reads like an over-long prompt."""
    haystack = " ".join(str(part) for part in parts if part).lower()
    return any(signal in haystack for signal in CONTEXT_OVERFLOW_SIGNALS)


def code_for_status(status: int, *, context_overflow: bool = False) -> ProviderErrorCode:
    """One HTTP status to one of the six codes (``specs/providers.md`` section 6).

    ``413`` is ``context_too_large`` rather than ``provider_refused``: a request rejected for its
    size is one the writer fixes by narrowing the selection, which is what that code tells them to
    do. A ``4xx`` this build has no opinion about is ``provider_refused`` - the provider rejected
    the request, and its own message travels with the error.
    """
    if context_overflow:
        return "context_too_large"
    if status in (401, 403):
        return "provider_auth_failed"
    if status == 429:
        return "provider_rate_limited"
    if status == 413:
        return "context_too_large"
    if status == 408 or status >= 500:
        return "provider_unavailable"
    return "provider_refused"


class ProviderTransport:
    """One HTTP client for one adapter, and the only place its failures become port errors.

    ``client`` is injectable, which is what makes ruling 3 possible: every adapter test replays a
    recorded payload through an ``httpx.MockTransport`` and **no test in this suite opens a
    socket**. When no client is given, one is built on first use and owned by this object.
    """

    def __init__(
        self,
        *,
        provider: str,
        base_url: str,
        headers: Mapping[str, str],
        client: httpx.AsyncClient | None = None,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
    ) -> None:
        self.provider = provider
        self.base_url = base_url.rstrip("/")
        self.headers = dict(headers)
        self._timeout = timeout
        self._client = client
        self._owns_client = client is None

    # -- the client -----------------------------------------------------------------------

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            # No retry configuration, deliberately: httpx retries nothing by default and ruling 6
            # says nothing here may add any.
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def aclose(self) -> None:
        """Close the client if this transport built it. An injected one belongs to its owner."""
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    def url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    # -- the two calls --------------------------------------------------------------------

    async def post_json(self, path: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        """POST a body and return the decoded response, or raise a :class:`ProviderError`."""
        client = self._ensure_client()
        try:
            response = await client.post(
                self.url(path), json=dict(payload), headers=self.headers, timeout=self._timeout
            )
        except httpx.HTTPError as exc:
            raise self.unreachable(exc) from exc
        if response.status_code >= 400:
            raise self.failure(response.status_code, response.text)
        try:
            decoded = response.json()
        except ValueError as exc:
            raise ProviderError(
                "provider_unavailable",
                f"{self.provider} answered with something that is not JSON",
                provider=self.provider,
                detail=response.text[:2000],
            ) from exc
        if not isinstance(decoded, dict):
            raise ProviderError(
                "provider_unavailable",
                f"{self.provider} answered with a {type(decoded).__name__}, not an object",
                provider=self.provider,
                detail=decoded,
            )
        return decoded

    @asynccontextmanager
    async def stream_sse(
        self, path: str, payload: Mapping[str, Any]
    ) -> AsyncIterator[AsyncIterator[SSEEvent]]:
        """Open a streaming POST and yield its events.

        A context manager because the response has to be closed on the way out **including when
        the caller stops reading**, which is exactly what cancelling an answer does (D11). A
        failure status is read whole and raised before the first event, so an auth failure on a
        streamed request reaches the writer as the same error a non-streamed one would.
        """
        client = self._ensure_client()
        try:
            async with client.stream(
                "POST", self.url(path), json=dict(payload), headers=self.headers
            ) as response:
                if response.status_code >= 400:
                    body = (await response.aread()).decode("utf-8", "replace")
                    raise self.failure(response.status_code, body)
                yield iter_events_async(response.aiter_lines())
        except httpx.HTTPError as exc:
            raise self.unreachable(exc) from exc

    # -- failure ---------------------------------------------------------------------------

    def failure(self, status: int, body: str) -> ProviderError:
        """Turn a failing HTTP response into the error the writer will be shown.

        Both providers wrap their message in ``{"error": {...}}``; anything that does not decode
        is carried through as text, because a provider having a bad day is exactly when the raw
        body is the useful half of the answer.
        """
        message, detail = _read_error_body(body)
        overflow = looks_like_context_overflow(message, detail)
        code = code_for_status(status, context_overflow=overflow)
        return ProviderError(
            code,
            f"{self.provider} refused the request ({status}): {message}"
            if code == "provider_refused"
            else f"{self.provider}: {message}",
            provider=self.provider,
            detail={"status": status, "body": detail},
        )

    def unreachable(self, exc: httpx.HTTPError) -> ProviderError:
        """A transport failure: no answer, a dropped connection, a read that timed out."""
        return ProviderError(
            "provider_unavailable",
            f"{self.provider} could not be reached: {type(exc).__name__}: {exc}",
            provider=self.provider,
            detail=str(exc),
        )


def _read_error_body(body: str) -> tuple[str, Any]:
    """The sentence to show and the payload to keep, from whatever the provider sent."""
    try:
        decoded = json.loads(body)
    except ValueError:
        text = body.strip()
        return (text[:500] or "no message", text[:2000])
    if isinstance(decoded, dict):
        error = decoded.get("error")
        if isinstance(error, dict):
            message = error.get("message") or error.get("type") or error.get("code")
            if message:
                return (str(message), decoded)
        if isinstance(error, str) and error:
            return (error, decoded)
        message = decoded.get("message")
        if message:
            return (str(message), decoded)
    return (json.dumps(decoded)[:500], decoded)
