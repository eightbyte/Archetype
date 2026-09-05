"""The Anthropic adapter (P4-5) - the Messages API, translated to and from the port.

One of exactly two places in this codebase that knows what Anthropic's wire format looks like; the
other is ``tests/fixtures/providers/anthropic/``, which holds the payloads this is asserted
against. Nothing above :mod:`archetype.llm.port` knows this file exists.

The translations that are actually interesting, rather than mechanical:

* **The system prompt has a place of its own.** Anthropic takes ``system`` as a top-level
  parameter, not as a message. The port has one representation of a system message and this is
  where it goes to its own field - which is the exact asymmetry with the OpenAI shape that
  phase-4-plan section 6's first risk is about, and why ``specs/providers.md`` was written from
  both providers' documentation before either adapter existed.
* **``temperature`` is sent only when the caller chose one.** The port defaults it to ``None``
  meaning "the provider's own", and that is not a stylistic nicety here: the current Claude models
  reject ``temperature`` outright with a ``400``, so a port that defaulted it to ``0.0`` would
  make every request to them fail.
* **A stop reason this build does not recognise becomes ``other``, and the provider's own string
  is kept beside it.** ``pause_turn`` is the live example: it is a real Anthropic stop reason, it
  is a server-tool condition Phase 4 cannot produce, and mapping it onto ``end_turn`` would report
  a finished answer that is not finished.

One limit, stated because it is a real hole rather than an oversight: **a tool call that arrives
mid-stream has no Phase 4 event to arrive in.** D32's vocabulary is ``start``, ``delta``,
``usage``, ``done``, ``error``, and Phase 6 adds ``tool_call`` to it. Until then a streamed
``input_json_delta`` is ignored and the stream's ``done`` still carries ``stop_reason="tool_use"``,
which is true. ``complete()`` returns streamed-or-not tool calls in full, and that is the path the
fixtures assert (phase-4-plan section 7, ``B4``).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, Final

import httpx

from ..port import (
    Capabilities,
    CompletionRequest,
    CompletionResult,
    Message,
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
from .prompted_tools import apply_fallback, system_instructions
from .transport import ProviderTransport, looks_like_context_overflow

__all__ = [
    "ANTHROPIC_VERSION",
    "DEFAULT_BASE_URL",
    "DEFAULT_CAPABILITIES",
    "AnthropicAdapter",
]

#: The published default. Overridable from settings, which is what points this adapter at a proxy.
DEFAULT_BASE_URL: Final[str] = "https://api.anthropic.com"

#: The API version header. A date, pinned: it is the one header whose absence is a ``400``.
ANTHROPIC_VERSION: Final[str] = "2023-06-01"

MESSAGES_PATH: Final[str] = "/v1/messages"

#: What this adapter declares about the provider.
#:
#: ``max_context`` is the **smallest** window in the current model family rather than the largest,
#: and that is deliberate: it is read by the budget check, whose answer is a hard refusal
#: (``specs/providers.md`` section 7). Under-declaring refuses a request that might have fit,
#: which costs nothing and is fixed by narrowing a selection. Over-declaring sends a request that
#: is billed and then refused. The writer raises it in settings if their model is bigger.
DEFAULT_CAPABILITIES: Final[Capabilities] = Capabilities(
    native_tools=True,
    streaming=True,
    max_context=200_000,
    supports_system=True,
)

#: Anthropic's stop reasons that this build recognises. Everything else - ``pause_turn`` today,
#: whatever arrives next - normalises to ``other`` with the original on ``raw_stop_reason``.
_STOP_REASONS: Final[dict[str, StopReason]] = {
    "end_turn": "end_turn",
    "max_tokens": "max_tokens",
    "stop_sequence": "stop_sequence",
    "tool_use": "tool_use",
    "refusal": "refusal",
}

#: Anthropic's own error taxonomy, onto ours (``specs/providers.md`` section 6).
_ERROR_TYPES: Final[dict[str, ProviderErrorCode]] = {
    "authentication_error": "provider_auth_failed",
    "permission_error": "provider_auth_failed",
    "rate_limit_error": "provider_rate_limited",
    "overloaded_error": "provider_unavailable",
    "api_error": "provider_unavailable",
    "timeout_error": "provider_unavailable",
    "invalid_request_error": "provider_refused",
    "not_found_error": "provider_refused",
    "request_too_large": "context_too_large",
    "billing_error": "provider_auth_failed",
}

#: ``tool_choice`` in the port's words, in Anthropic's. ``required`` is ``any`` here - the same
#: instruction under a different name, which is precisely what a port is for.
_TOOL_CHOICES: Final[dict[str, str]] = {"auto": "auto", "none": "none", "required": "any"}


class AnthropicAdapter:
    """An :class:`~archetype.llm.port.LLMProvider` over the Anthropic Messages API.

    Constructed only by the registry (``llm/registry.py``, P4-8). ``client`` is injectable so the
    suite replays recorded payloads through an ``httpx.MockTransport`` and opens no socket.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        capabilities: Capabilities | None = None,
        client: httpx.AsyncClient | None = None,
        name: str = "anthropic",
    ) -> None:
        self.name = name
        self.capabilities = capabilities or DEFAULT_CAPABILITIES
        self._transport = ProviderTransport(
            provider=name,
            base_url=base_url or DEFAULT_BASE_URL,
            headers={
                "content-type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": ANTHROPIC_VERSION,
            },
            client=client,
        )

    async def aclose(self) -> None:
        await self._transport.aclose()

    # -- out ------------------------------------------------------------------------------

    def build_body(self, req: CompletionRequest, *, stream: bool) -> dict[str, Any]:
        """The normalised request as Anthropic's body. Public because the fixtures assert it."""
        system, messages = self._split_system(req)
        body: dict[str, Any] = {
            "model": req.model,
            "max_tokens": req.max_tokens,
            "messages": [_wire_message(message) for message in messages],
        }
        if system:
            body["system"] = system
        if req.temperature is not None:
            body["temperature"] = req.temperature
        if req.stop:
            body["stop_sequences"] = list(req.stop)
        if req.tools and self.capabilities.native_tools:
            body["tools"] = [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.parameters or {"type": "object", "properties": {}},
                }
                for tool in req.tools
            ]
            body["tool_choice"] = {"type": _TOOL_CHOICES[req.tool_choice]}
        if stream:
            body["stream"] = True
        return body

    def _split_system(self, req: CompletionRequest) -> tuple[str, list[Message]]:
        """The system text and the conversation, with the prompted-tool section folded in.

        Every ``system`` message is joined, in order, rather than only the first: the port allows
        more than one and a provider that dropped the rest would lose an instruction the composer
        deliberately added.
        """
        system_parts = [m.content for m in req.messages if m.role == "system" and m.content]
        rest = [m for m in req.messages if m.role != "system"]
        if req.tools and not self.capabilities.native_tools:
            system_parts.append(system_instructions(req.tools))
        system = "\n\n".join(part for part in system_parts if part)
        if system and not self.capabilities.supports_system:
            rest = _fold_system_into_first_user(system, rest)
            system = ""
        return system, rest

    # -- in -------------------------------------------------------------------------------

    def read_result(self, payload: dict[str, Any], req: CompletionRequest) -> CompletionResult:
        """Anthropic's response as the port's. Public because the fixtures assert it."""
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in payload.get("content") or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                text_parts.append(str(block.get("text", "")))
            elif block.get("type") == "tool_use":
                arguments = block.get("input")
                tool_calls.append(
                    ToolCall(
                        id=str(block.get("id", "")),
                        name=str(block.get("name", "")),
                        arguments=arguments if isinstance(arguments, dict) else {},
                    )
                )
        raw_stop = str(payload.get("stop_reason") or "")
        stop_reason = _STOP_REASONS.get(raw_stop, "other")
        text = "".join(text_parts)
        if req.tools and not self.capabilities.native_tools:
            text, fallback_calls, stop_reason = apply_fallback(
                text, stop_reason, provider=self.name
            )
            tool_calls.extend(fallback_calls)
        return CompletionResult(
            text=text,
            tool_calls=tuple(tool_calls),
            stop_reason=stop_reason,
            raw_stop_reason=raw_stop,
            usage=_read_usage(payload.get("usage")),
        )

    # -- the port -------------------------------------------------------------------------

    async def complete(self, req: CompletionRequest) -> CompletionResult:
        payload = await self._transport.post_json(MESSAGES_PATH, self.build_body(req, stream=False))
        return self.read_result(payload, req)

    def stream(self, req: CompletionRequest) -> AsyncIterator[StreamEvent]:
        """The answer as D32's events.

        Deliberately **not** ``async def``: the refusal below and the translation of the request
        both happen when the caller asks, not when it first reads, so one deliberate ask fails or
        counts at the moment it is made (the rule ``FakeProvider.stream`` follows for the same
        reason - phase-4-plan section 6, the "money" risk).

        A provider declaring ``streaming=False`` refuses here rather than buffering ``complete()``
        into a fake cadence (``specs/providers.md`` section 5). A caller may make that decision in
        the open - one ``delta`` carrying the whole text - and the socket is where it is made.
        """
        if not self.capabilities.streaming:
            raise ProviderError(
                "provider_unavailable",
                f"{self.name} is configured without streaming",
                provider=self.name,
            )
        return self._events(self.build_body(req, stream=True))

    async def _events(self, body: dict[str, Any]) -> AsyncIterator[StreamEvent]:
        state = _StreamState()
        async with self._transport.stream_sse(MESSAGES_PATH, body) as events:
            async for event in events:
                for produced in state.feed(event.name, event.data):
                    yield produced


class _StreamState:
    """The one place Anthropic's event sequence becomes the port's.

    Anthropic reports usage in two halves - the input count arrives with ``message_start``, the
    output count with ``message_delta`` - and the port's ``usage`` event is emitted **at most
    once** (section 4). So the halves are held here and sent together, once, before ``done``.
    """

    def __init__(self) -> None:
        self.model = ""
        self.input_tokens = 0
        self.output_tokens = 0
        self.usage_sent = False
        self.raw_stop = ""

    def feed(self, name: str, data: str) -> list[StreamEvent]:
        payload = _decode(data)
        kind = str(payload.get("type") or name or "")
        if kind == "message_start":
            return self._message_start(payload)
        if kind == "content_block_delta":
            return self._content_block_delta(payload)
        if kind == "message_delta":
            return self._message_delta(payload)
        if kind == "message_stop":
            return [
                StreamDone(
                    stop_reason=_STOP_REASONS.get(self.raw_stop, "other"),
                    raw_stop_reason=self.raw_stop,
                )
            ]
        if kind == "error":
            return [self._error(payload)]
        # ping, content_block_start, content_block_stop, and anything a later API version adds.
        # Ignored rather than refused: this is a *provider's* vocabulary, not the port's, and the
        # rule that an unknown event is refused (D32) is about the port's own events.
        return []

    def _message_start(self, payload: dict[str, Any]) -> list[StreamEvent]:
        message = payload.get("message")
        message = message if isinstance(message, dict) else {}
        self.model = str(message.get("model", ""))
        usage = _read_usage(message.get("usage"))
        self.input_tokens = usage.input_tokens
        self.output_tokens = usage.output_tokens
        return [StreamStart(model=self.model)]

    def _content_block_delta(self, payload: dict[str, Any]) -> list[StreamEvent]:
        delta = payload.get("delta")
        delta = delta if isinstance(delta, dict) else {}
        if delta.get("type") == "text_delta":
            return [StreamDelta(text=str(delta.get("text", "")))]
        # `input_json_delta` - a tool call arriving in fragments. Phase 4's vocabulary has no
        # event for one and Phase 6 adds `tool_call`; `done` still says `tool_use`, which is true.
        return []

    def _message_delta(self, payload: dict[str, Any]) -> list[StreamEvent]:
        delta = payload.get("delta")
        delta = delta if isinstance(delta, dict) else {}
        if delta.get("stop_reason"):
            self.raw_stop = str(delta["stop_reason"])
        usage = _read_usage(payload.get("usage"))
        if usage.input_tokens:
            self.input_tokens = usage.input_tokens
        if usage.output_tokens:
            self.output_tokens = usage.output_tokens
        if self.usage_sent or not (self.input_tokens or self.output_tokens):
            return []
        self.usage_sent = True
        return [
            StreamUsage(
                usage=Usage(input_tokens=self.input_tokens, output_tokens=self.output_tokens)
            )
        ]

    def _error(self, payload: dict[str, Any]) -> StreamEvent:
        error = payload.get("error")
        error = error if isinstance(error, dict) else {}
        error_type = str(error.get("type", ""))
        message = str(error.get("message", "the provider reported an error"))
        code = (
            "context_too_large"
            if looks_like_context_overflow(error_type, message)
            else _ERROR_TYPES.get(error_type, "provider_unavailable")
        )
        return StreamError(code=code, message=message)


def _wire_message(message: Message) -> dict[str, Any]:
    """One port message as one Anthropic message.

    A ``tool`` message becomes a **user** message carrying a ``tool_result`` block, because that
    is where Anthropic puts a tool's answer. The port keeps them as their own role so that neither
    provider's placement leaks upward (D31).
    """
    if message.role == "tool":
        return {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": message.tool_call_id or "",
                    "content": message.content,
                }
            ],
        }
    if message.role == "assistant" and message.tool_calls:
        blocks: list[dict[str, Any]] = []
        if message.content:
            blocks.append({"type": "text", "text": message.content})
        blocks.extend(
            {"type": "tool_use", "id": call.id, "name": call.name, "input": dict(call.arguments)}
            for call in message.tool_calls
        )
        return {"role": "assistant", "content": blocks}
    return {"role": message.role, "content": message.content}


def _fold_system_into_first_user(system: str, messages: list[Message]) -> list[Message]:
    """What ``supports_system=False`` means, and the only thing it means (section 5)."""
    for index, message in enumerate(messages):
        if message.role == "user":
            folded = message.model_copy(update={"content": f"{system}\n\n{message.content}"})
            return [*messages[:index], folded, *messages[index + 1 :]]
    return [Message(role="user", content=system), *messages]


def _read_usage(raw: Any) -> Usage:
    """Usage, or the zeros that mean **not reported** rather than free."""
    if not isinstance(raw, dict):
        return Usage()
    return Usage(
        input_tokens=max(0, int(raw.get("input_tokens") or 0)),
        output_tokens=max(0, int(raw.get("output_tokens") or 0)),
    )


def _decode(data: str) -> dict[str, Any]:
    try:
        decoded = json.loads(data)
    except ValueError:
        return {}
    return decoded if isinstance(decoded, dict) else {}
