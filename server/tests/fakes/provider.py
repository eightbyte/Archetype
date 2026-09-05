"""``FakeProvider`` - the scripted provider the whole backend suite runs against (P4-3).

The first resident of a directory reserved since Phase 1, and the reason no test in this project
has ever touched the network or a real key (outline section 8).

**It is scripted and it computes nothing.** A test stages the answer, the deltas, the usage, the
stop reason, or the failure, and this returns them. That is the same standing rule the fake API
client on the client side has carried since Phase 1, and it is written here for the same reason:

* it does **not** count tokens - that is the budget module's job (P4-8), tested separately;
* it does **not** decide whether a context is too large - ruling 7's refusal is the composer's,
  and P4-10's test asserts this fake recorded **zero** calls when it fires;
* it does **not** translate anything - translation is an adapter's whole job, and a fake that
  translated would be a third implementation with neither a specification nor a fixture behind it;
* it does **not** invent an answer when nothing was staged. An unstaged call fails loudly, because
  a fake that made something up would let a test pass while asserting nothing.

What it *may* do, and no real provider will do on demand, is **cadence and failure**: a slow first
token, a mid-stream error, a stream that ends without ``done``. Those are precisely the conditions
the panel's handling exists for (P4-12), and staging them is the only way to reach that code.

The one rule it does implement is the port's own, about itself: a fake declaring
``streaming=False`` refuses ``stream()`` with ``provider_unavailable``, because that is what
specs/providers.md section 5 says a provider does. Implementing the contract it claims to satisfy
is not the same as holding a rule of its own.
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncIterator, Sequence

from archetype.llm.port import (
    Capabilities,
    CompletionRequest,
    CompletionResult,
    ProviderError,
    ProviderErrorCode,
    StopReason,
    StreamDelta,
    StreamDone,
    StreamError,
    StreamEvent,
    StreamStart,
    StreamUsage,
    ToolCall,
    Usage,
)

__all__ = ["FakeProvider", "NothingStagedError"]

#: What an unstaged fake declares it can do. Generous on context, because a test that wants the
#: budget to bite sets a small one deliberately rather than discovering this number.
DEFAULT_CAPABILITIES = Capabilities(
    native_tools=True,
    streaming=True,
    max_context=200_000,
    supports_system=True,
)


class NothingStagedError(AssertionError):
    """A call was made that no test staged an answer for.

    An ``AssertionError`` on purpose: it is a defect in the test, not in the code under test, and
    it should read as one in the failure output.
    """


class FakeProvider:
    """A scripted :class:`~archetype.llm.port.LLMProvider`.

    Staging is a queue per method: each staged completion or stream is consumed by one call, in
    order, so a test that expects two answers stages two and a test that expects one call and gets
    two fails on the second.
    """

    def __init__(self, *, name: str = "fake", capabilities: Capabilities | None = None) -> None:
        self.name = name
        self.capabilities = capabilities or DEFAULT_CAPABILITIES

        #: Every request this fake was handed, in order - the record P4-10 and the "money" risk
        #: assert against. A remount that quietly asks twice shows up here as two entries.
        self.calls: list[CompletionRequest] = []
        self.complete_calls = 0
        self.stream_calls = 0

        self._completions: deque[CompletionResult | ProviderError] = deque()
        self._streams: deque[Sequence[StreamEvent] | ProviderError] = deque()

        #: Cadence, in seconds. Zero by default: a suite that sleeps is a suite nobody runs.
        self.first_event_delay = 0.0
        self.between_event_delay = 0.0

    # -- inspection ---------------------------------------------------------------------------

    @property
    def call_count(self) -> int:
        """Every call, of either kind. One deliberate ask must produce exactly one (ruling 6)."""
        return self.complete_calls + self.stream_calls

    @property
    def last_request(self) -> CompletionRequest:
        """The most recent request, for a test that asserts on what was composed."""
        if not self.calls:
            raise NothingStagedError("no request has been made")
        return self.calls[-1]

    # -- staging: whole answers ---------------------------------------------------------------

    def stage_completion(
        self,
        text: str = "",
        *,
        tool_calls: Sequence[ToolCall] = (),
        stop_reason: StopReason = "end_turn",
        raw_stop_reason: str = "",
        usage: Usage | None = None,
    ) -> CompletionResult:
        """Stage one answer for the next :meth:`complete`, and return it for assertions."""
        result = CompletionResult(
            text=text,
            tool_calls=tuple(tool_calls),
            stop_reason=stop_reason,
            raw_stop_reason=raw_stop_reason or stop_reason,
            usage=usage or Usage(),
        )
        self._completions.append(result)
        return result

    def stage_result(self, result: CompletionResult) -> CompletionResult:
        """Stage a result built by the test itself, for a shape :meth:`stage_completion` cannot."""
        self._completions.append(result)
        return result

    # -- staging: streams ---------------------------------------------------------------------

    def stage_stream(self, events: Sequence[StreamEvent]) -> tuple[StreamEvent, ...]:
        """Stage an exact event sequence, including a pathological one.

        Nothing is added, checked, or reordered: an out-of-order stream, a duplicate ``start``, or
        a sequence with no terminator is a legitimate thing to stage, because it is a legitimate
        thing for a socket to receive.
        """
        staged = tuple(events)
        self._streams.append(staged)
        return staged

    def stage_stream_text(
        self,
        fragments: Sequence[str],
        *,
        model: str = "fake-model",
        stop_reason: StopReason = "end_turn",
        usage: Usage | None = None,
    ) -> tuple[StreamEvent, ...]:
        """The ordinary case: ``start``, the deltas, ``usage`` if given, then ``done``."""
        events: list[StreamEvent] = [StreamStart(model=model)]
        events.extend(StreamDelta(text=fragment) for fragment in fragments)
        if usage is not None:
            events.append(StreamUsage(usage=usage))
        events.append(StreamDone(stop_reason=stop_reason, raw_stop_reason=stop_reason))
        return self.stage_stream(events)

    def stage_stream_failure(
        self,
        fragments: Sequence[str],
        *,
        code: ProviderErrorCode = "provider_unavailable",
        message: str = "the provider stopped answering",
        model: str = "fake-model",
    ) -> tuple[StreamEvent, ...]:
        """A stream that starts, produces some text, and then fails mid-answer.

        The partial text is real and must survive: P4-10 persists it with the error code, so the
        failed turn is visible in the history rather than being a gap the writer has to remember.
        """
        events: list[StreamEvent] = [StreamStart(model=model)]
        events.extend(StreamDelta(text=fragment) for fragment in fragments)
        events.append(StreamError(code=code, message=message))
        return self.stage_stream(events)

    def stage_stream_truncated(
        self,
        fragments: Sequence[str],
        *,
        model: str = "fake-model",
    ) -> tuple[StreamEvent, ...]:
        """A stream that simply stops - no ``done``, no ``error``.

        What a dropped socket looks like from the inside, and the one shape no real provider will
        produce on request. Exactly one of ``done`` or ``error`` ends a well-formed stream
        (providers.md section 4), so a caller that assumes a terminator hangs or loses the answer,
        and this is how that assumption is caught.
        """
        events: list[StreamEvent] = [StreamStart(model=model)]
        events.extend(StreamDelta(text=fragment) for fragment in fragments)
        return self.stage_stream(events)

    # -- staging: failure before anything arrives ---------------------------------------------

    def stage_error(
        self,
        code: ProviderErrorCode,
        message: str = "staged failure",
        *,
        detail: object = None,
    ) -> ProviderError:
        """Stage a raised failure for the next call of **either** method.

        This is the "the request never got off the ground" case - auth, rate limit, an
        unreachable host. A failure *during* a stream is :meth:`stage_stream_failure`, and the two
        reach the panel differently: one refuses the ask, the other keeps the partial answer.
        """
        error = ProviderError(code, message, provider=self.name, detail=detail)
        self._completions.append(error)
        self._streams.append(error)
        return error

    def set_cadence(self, *, first_event: float = 0.0, between_events: float = 0.0) -> None:
        """Slow the stream down, in seconds, to reach code that only runs while one is open."""
        self.first_event_delay = first_event
        self.between_event_delay = between_events

    # -- the port -----------------------------------------------------------------------------

    async def complete(self, req: CompletionRequest) -> CompletionResult:
        self.calls.append(req)
        self.complete_calls += 1
        if not self._completions:
            raise NothingStagedError(
                "complete() was called with nothing staged; stage_completion() first"
            )
        staged = self._completions.popleft()
        if isinstance(staged, ProviderError):
            self._discard_matching_stream(staged)
            raise staged
        return staged

    def stream(self, req: CompletionRequest) -> AsyncIterator[StreamEvent]:
        """The call is recorded **here**, not on first iteration.

        A caller that opened a stream and never read it still spent the request, and the whole
        point of :attr:`calls` is that it counts what was actually asked for.
        """
        self.calls.append(req)
        self.stream_calls += 1
        if not self.capabilities.streaming:
            raise ProviderError(
                "provider_unavailable",
                f"{self.name} does not support streaming",
                provider=self.name,
            )
        if not self._streams:
            raise NothingStagedError(
                "stream() was called with nothing staged; stage_stream_text() first"
            )
        staged = self._streams.popleft()
        if isinstance(staged, ProviderError):
            self._discard_matching_completion(staged)
            return self._raising(staged)
        return self._emit(staged)

    # -- internals ----------------------------------------------------------------------------

    async def _emit(self, events: Sequence[StreamEvent]) -> AsyncIterator[StreamEvent]:
        for index, event in enumerate(events):
            delay = self.first_event_delay if index == 0 else self.between_event_delay
            if delay:
                await asyncio.sleep(delay)
            yield event

    async def _raising(self, error: ProviderError) -> AsyncIterator[StreamEvent]:
        raise error
        yield  # pragma: no cover - unreachable, and required to make this a generator

    def _discard_matching_stream(self, error: ProviderError) -> None:
        """One :meth:`stage_error` is one failure, whichever method the caller reached for."""
        if self._streams and self._streams[0] is error:
            self._streams.popleft()

    def _discard_matching_completion(self, error: ProviderError) -> None:
        if self._completions and self._completions[0] is error:
            self._completions.popleft()
