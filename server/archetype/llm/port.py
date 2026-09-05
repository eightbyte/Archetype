"""The provider port - the one interface through which Archetype talks to a language model.

Written from ``specs/providers.md`` (P4-1), which was written before this module (P4-2). Where the
two disagree, that document's section 13 records the correction and the phase plan's section 7
records why.

**Pure.** pydantic and the standard library, nothing else: no I/O, no HTTP client, no provider SDK,
importable by a test with nothing running. Phase 6's agent and Phase 7's proposals are written
against this module and never against a provider.

The promise (providers.md):

    Nothing above the port knows which provider is in play, and no answer changes shape because of
    who produced it.

And the limit, in the same breath:

    The port normalises the shape of an answer, never its quality, its latency, or its cost.

Three rules this module enforces structurally rather than by convention:

* **Every vocabulary is a ``Literal`` and its members are derived from it** with ``get_args``, so
  the closed set and the tuple a test greps for cannot drift apart.
* **Every shape is frozen and forbids extra fields.** A stream event a consumer can mutate is a
  bug that shows up three components later, and an unexpected field on the server means an adapter
  and the port have parted company.
* **An unknown stream event type fails to validate here** (D32). The *client* ignores one; the
  server refuses it. That asymmetry is deliberate, is written down in providers.md section 4, and
  is tested in both suites.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated, Any, Final, Literal, Protocol, get_args, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

__all__ = [
    "PROVIDER_ERROR_CODES",
    "ROLES",
    "STOP_REASONS",
    "STREAM_EVENT_ADAPTER",
    "STREAM_EVENT_TYPES",
    "TOOL_CHOICES",
    "Capabilities",
    "CompletionRequest",
    "CompletionResult",
    "LLMProvider",
    "Message",
    "ProviderError",
    "ProviderErrorCode",
    "Role",
    "StopReason",
    "StreamDelta",
    "StreamDone",
    "StreamError",
    "StreamEvent",
    "StreamEventType",
    "StreamStart",
    "StreamUsage",
    "ToolCall",
    "ToolChoice",
    "ToolDeclaration",
    "Usage",
    "parse_stream_event",
]


# -- the closed vocabularies ------------------------------------------------------------------
#
# providers.md section 9 lists these by name. Each tuple is derived from its Literal, so there is
# exactly one place a member is written down.

#: Who a message is from. One vocabulary; adapters translate to and from a provider's own names.
Role = Literal["system", "user", "assistant", "tool"]
ROLES: Final[tuple[str, ...]] = get_args(Role)

#: Why generation stopped (providers.md section 3). Closed, and each member has exactly one
#: writer: an adapter maps a provider's string onto the first six, and ``cancelled`` is written by
#: the caller that closed the stream - no adapter ever produces it.
StopReason = Literal[
    "end_turn",
    "max_tokens",
    "stop_sequence",
    "tool_use",
    "refusal",
    "other",
    "cancelled",
]
STOP_REASONS: Final[tuple[str, ...]] = get_args(StopReason)

#: What a request asks the model to do about tools. Only meaningful when ``tools`` is non-empty,
#: which in Phase 4 it never is (D31).
ToolChoice = Literal["auto", "none", "required"]
TOOL_CHOICES: Final[tuple[str, ...]] = get_args(ToolChoice)

#: D32's stream vocabulary, as of Phase 4. Phase 6 adds ``plan``, ``tool_call``, ``tool_result``,
#: and ``step`` to the same union and changes nothing here.
StreamEventType = Literal["start", "delta", "usage", "done", "error"]
STREAM_EVENT_TYPES: Final[tuple[str, ...]] = get_args(StreamEventType)

#: The error taxonomy (providers.md section 6, phase-4-plan section 2 ruling 4). A provider failure
#: is one of these six, an envelope, and never a crash or a silent empty answer.
ProviderErrorCode = Literal[
    "provider_unconfigured",
    "provider_auth_failed",
    "provider_rate_limited",
    "provider_unavailable",
    "provider_refused",
    "context_too_large",
]
PROVIDER_ERROR_CODES: Final[tuple[str, ...]] = get_args(ProviderErrorCode)


class _Shape(BaseModel):
    """The base every port type shares: frozen, and no field this build does not know about.

    Frozen because these travel between an adapter, a route, a socket, and a store, and a value
    any of them can edit in place is a value none of them can reason about. ``extra="forbid"``
    because on *this* side of the port an unexpected field means the adapter and the port have
    parted company - the client's tolerance for what it does not recognise is the client's, and
    is a different rule (D32).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")


# -- messages and tools -----------------------------------------------------------------------


class ToolCall(_Shape):
    """One call the model asked for.

    ``arguments`` is **already parsed** - never a JSON string. A provider that sends a string has
    it parsed by its adapter, and a string that will not parse is ``provider_refused`` with the
    raw text preserved, never a silently empty call (providers.md section 8).

    ``id`` is the provider's own identifier where it has one and is minted by the prompted-JSON
    fallback where it does not (P4-7). Nothing above the port may assume its shape or parse it.
    """

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class Message(_Shape):
    """One turn in a conversation, in the port's vocabulary.

    A ``system`` message is a message like any other **here**. Where it goes on the wire is the
    adapter's problem: Anthropic takes a separate parameter, OpenAI takes a message in the list,
    and a provider declaring ``supports_system=False`` has it folded into the first user message.
    The port having one representation of it is what stops the port from having a favourite
    (phase-4-plan section 6, the first risk).
    """

    role: Role
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None


class ToolDeclaration(_Shape):
    """A tool the model may call: its name, what it does, and its argument schema.

    Declared in Phase 4 and used in Phase 6 (D31). **Phase 4 declares none.** This is the one
    place the phase deliberately builds ahead, on D28's precedent, and the recorded provider
    fixtures are its only consumer until the agent arrives.
    """

    name: str
    description: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)


# -- the request ------------------------------------------------------------------------------


class CompletionRequest(_Shape):
    """One complete request. The port is stateless: this carries the whole conversation.

    ``temperature`` is ``None`` by default, which means "the provider's default" and is **not**
    the same as ``0.0``. Sending a number the writer did not choose is a quiet change to every
    answer the product gives.
    """

    messages: tuple[Message, ...] = Field(min_length=1)
    model: str = Field(min_length=1)
    max_tokens: int = Field(ge=1)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    stop: tuple[str, ...] = ()
    tools: tuple[ToolDeclaration, ...] = ()
    tool_choice: ToolChoice = "auto"


# -- the result -------------------------------------------------------------------------------


class Usage(_Shape):
    """What an answer cost, as the provider reported it.

    Both fields default to ``0``, which means **"not reported"** and not "free". A provider that
    reports no usage is a provider whose bill this app cannot show, and the panel says so rather
    than drawing a confident zero.
    """

    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)

    @property
    def reported(self) -> bool:
        """True when the provider reported anything at all."""
        return self.input_tokens > 0 or self.output_tokens > 0


class CompletionResult(_Shape):
    """A whole answer. There is no partially-filled result: a failure raises (section 6).

    ``raw_stop_reason`` keeps the provider's own string beside the normalised one, always - even
    when the mapping was the identity. That is what makes ``other`` diagnosable rather than merely
    honest.
    """

    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    stop_reason: StopReason
    raw_stop_reason: str = ""
    usage: Usage = Usage()


# -- the stream (D32) -------------------------------------------------------------------------


class StreamStart(_Shape):
    """First event of every stream, before any text."""

    type: Literal["start"] = "start"
    model: str = ""


class StreamDelta(_Shape):
    """A fragment of the answer. Never the accumulated text - fragments concatenate in order."""

    type: Literal["delta"] = "delta"
    text: str


class StreamUsage(_Shape):
    """What the answer cost, when the provider says so. At most once, before or after the text."""

    type: Literal["usage"] = "usage"
    usage: Usage


class StreamDone(_Shape):
    """The last event of a stream that completed."""

    type: Literal["done"] = "done"
    stop_reason: StopReason
    raw_stop_reason: str = ""


class StreamError(_Shape):
    """The last event of a stream that failed, carrying the same code the envelope would."""

    type: Literal["error"] = "error"
    code: ProviderErrorCode
    message: str


#: The discriminated union. Exactly one of ``done`` or ``error`` ends a stream; a stream that ends
#: without either is a failure the caller handles, and ``FakeProvider`` can produce it on demand.
StreamEvent = Annotated[
    StreamStart | StreamDelta | StreamUsage | StreamDone | StreamError,
    Field(discriminator="type"),
]

STREAM_EVENT_ADAPTER: Final[TypeAdapter[StreamEvent]] = TypeAdapter(StreamEvent)


def parse_stream_event(payload: Any) -> StreamEvent:
    """Validate one stream event, **refusing a ``type`` this build does not know** (D32).

    The server is strict and the client is tolerant, deliberately: here an unrecognised event
    means an adapter and the port have parted company and the only safe answer is to stop, while a
    browser holding a stale bundle against a newer server must degrade to *less detail* rather
    than to a broken panel. The client half of this rule lives in ``web/src/api/stream.ts``.

    Raises:
        pydantic.ValidationError: If ``type`` is missing, unknown, or the payload does not match
            that event's shape.
    """
    return STREAM_EVENT_ADAPTER.validate_python(payload)


# -- capabilities -----------------------------------------------------------------------------


class Capabilities(_Shape):
    """What a provider can do, as a statement about the provider (providers.md section 5).

    A capability is **not** a switch on our behaviour above the port: no route, no store, and no
    component branches on one. The only readers are the adapters, the socket's decision whether to
    stream at all, and the context budget check.
    """

    native_tools: bool = True
    streaming: bool = True
    max_context: int = Field(default=0, ge=0)
    supports_system: bool = True


# -- failure ----------------------------------------------------------------------------------


class ProviderError(RuntimeError):
    """A provider failed, with a stated cause from the closed taxonomy (section 6, ruling 4).

    One exception for all six codes rather than six classes: the codes differ in what the writer
    is told and in nothing else, and a handler that has to know six types to write one envelope is
    a handler that will miss the seventh.

    ``detail`` preserves what the provider actually said - untyped on purpose, so a condition this
    build does not distinguish is still diagnosable from a log line.

    Note the distinction this class exists on one side of: ``provider_refused`` is the *provider*
    rejecting the request and costs nothing; ``stop_reason="refusal"`` is the *model* declining to
    answer, which is a complete, billed response and is not an error at all.
    """

    def __init__(
        self,
        code: ProviderErrorCode,
        message: str,
        *,
        provider: str = "",
        detail: Any = None,
    ) -> None:
        super().__init__(message)
        self.code: ProviderErrorCode = code
        self.message = message
        self.provider = provider
        self.detail = detail

    def __str__(self) -> str:
        return f"{self.code}: {self.message}" if self.code else self.message


# -- the protocol -----------------------------------------------------------------------------


@runtime_checkable
class LLMProvider(Protocol):
    """The port. Two methods, because a streamed answer and a whole one are different call sites.

    Faking either from the other lies in both directions: buffering a stream to fake ``complete``
    hides latency, and chunking a result to fake ``stream`` invents a token cadence that was never
    real. So both are declared and every adapter implements both.

    ``stream`` is deliberately **not** ``async def``: it returns an ``AsyncIterator``, so an
    implementation may be an async generator function and a caller may hold the iterator before
    awaiting anything. Both forms satisfy this protocol and neither is preferred.

    Implementations raise :class:`ProviderError` and nothing else. A provider SDK's own exception
    never escapes ``llm/adapters/`` - that is the same rule as its imports, one layer down.
    """

    name: str
    capabilities: Capabilities

    async def complete(self, req: CompletionRequest) -> CompletionResult:
        """The whole answer, once it exists."""
        ...

    def stream(self, req: CompletionRequest) -> AsyncIterator[StreamEvent]:
        """The answer as it arrives, as D32's events."""
        ...
