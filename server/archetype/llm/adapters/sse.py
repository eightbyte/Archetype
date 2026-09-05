"""Server-sent events, parsed once for both adapters (P4-5, P4-6).

Anthropic and the OpenAI chat-completions shape both stream over SSE, and they frame it the same
way even though what travels inside is completely different: ``event:`` and ``data:`` lines, a
blank line dispatching the event, a leading ``:`` marking a comment. Writing that twice would be
two chances to disagree about where an event ends - which is the same argument the block index
made about walking a document twice (``manuscript/projection.py``).

**Pure.** The standard library only: it takes lines and yields events, and knows nothing about
HTTP, httpx, or either provider. What the two adapters do *with* an event is where they differ,
and that difference is their whole job.

Two details that are easy to get wrong and are handled here once:

* **A ``data:`` field may appear more than once in one event**, and the values are joined with a
  newline. Nothing in this build sends multi-line data today; a server that starts to would
  otherwise deliver a broken half of a JSON document.
* **A comment line is not an event.** Several OpenAI-compatible servers send ``: ping`` or
  ``:keep-alive`` to hold the connection open, and a parser that treated one as data would hand
  an adapter a payload that will not parse and get reported as a provider refusal.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable, Iterator

__all__ = ["SSEEvent", "iter_events", "iter_events_async"]


class SSEEvent:
    """One dispatched event: the ``event:`` name, if any, and the joined ``data:`` payload.

    Not a pydantic model. This is a wire framing artefact that never leaves the adapters package -
    the port's shapes are what cross it - and giving it validation would suggest it had a contract
    to hold.
    """

    __slots__ = ("data", "name")

    def __init__(self, name: str, data: str) -> None:
        self.name = name
        self.data = data

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"SSEEvent(name={self.name!r}, data={self.data!r})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SSEEvent):
            return NotImplemented
        return self.name == other.name and self.data == other.data


class _Accumulator:
    """The event being built, and the one place the dispatch rule is written down."""

    def __init__(self) -> None:
        self.name = ""
        self.data: list[str] = []

    def feed(self, line: str) -> SSEEvent | None:
        """Take one line; return an event when this line dispatched one."""
        line = line.rstrip("\r")
        if not line:
            return self._dispatch()
        if line.startswith(":"):
            # A comment. Keep-alives arrive this way, and they are not events.
            return None
        field, _, value = line.partition(":")
        value = value[1:] if value.startswith(" ") else value
        if field == "event":
            self.name = value
        elif field == "data":
            self.data.append(value)
        # Every other field (`id`, `retry`, anything a server invents) is ignored: neither
        # provider uses one, and inventing a meaning for it here would be a guess.
        return None

    def _dispatch(self) -> SSEEvent | None:
        if not self.data and not self.name:
            return None
        event = SSEEvent(self.name, "\n".join(self.data))
        self.name = ""
        self.data = []
        return event

    def flush(self) -> SSEEvent | None:
        """Whatever a stream that ended without a trailing blank line left behind.

        Emitted rather than dropped: a provider that ends mid-event has produced a stream with no
        terminator, and that is a condition the caller must see (``specs/providers.md`` section 4)
        rather than one this parser quietly rounds off.
        """
        return self._dispatch()


def iter_events(lines: Iterable[str]) -> Iterator[SSEEvent]:
    """Parse a whole SSE body. Used by the tests and by anything holding the text already."""
    accumulator = _Accumulator()
    for line in lines:
        event = accumulator.feed(line)
        if event is not None:
            yield event
    trailing = accumulator.flush()
    if trailing is not None:
        yield trailing


async def iter_events_async(lines: AsyncIterator[str]) -> AsyncIterator[SSEEvent]:
    """The same parser over a live response body."""
    accumulator = _Accumulator()
    async for line in lines:
        event = accumulator.feed(line)
        if event is not None:
            yield event
    trailing = accumulator.flush()
    if trailing is not None:
        yield trailing
