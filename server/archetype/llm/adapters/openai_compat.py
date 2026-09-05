"""The OpenAI-compatible adapter (P4-6) - the chat-completions shape, translated both ways.

Not "the OpenAI adapter". The protocol is what is implemented, not the vendor: a base URL, a key,
a model id, and four capability flags are the whole of its configuration, which is what makes the
hosted services and the local servers that mimic this shape work without a new adapter. **The
point of this file is the ones that are only *nearly* compatible**, and the choices below are
mostly about them:

* **``max_tokens``, not ``max_completion_tokens``.** The newer field is the vendor's; the older one
  is what every server speaking this protocol accepts.
* **``stream_options`` is optional and on by default.** It is how this protocol reports usage on a
  streamed answer, and a server that has never heard of it rejects the request outright - so it is
  a constructor flag, and a writer pointed at such a server turns it off and loses the token counts
  rather than losing the answer (``Usage`` of zero already means *not reported*, never free).
* **Arguments arrive as a JSON string and leave as an object.** That is this protocol's own shape,
  and ``specs/providers.md`` section 8 is explicit: a string that will not parse is
  ``provider_refused`` with the raw text preserved, never a silently empty call.

One honest limit, which is the protocol's rather than this file's: **``stop_sequence`` is
unreachable here.** A chat-completions server reports ``finish_reason: "stop"`` whether the model
finished on its own or produced a stop sequence, so this adapter maps that to ``end_turn`` and
``raw_stop_reason`` records what was actually said. The port's member is not wrong; this provider
just cannot tell us (phase-4-plan section 7, ``B3``).
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
    "DEFAULT_BASE_URL",
    "DEFAULT_CAPABILITIES",
    "OpenAICompatibleAdapter",
]

#: Where an unconfigured base URL points. Any server speaking this protocol replaces it, and that
#: substitution is the whole of what "swap providers in settings with no code change" means here.
DEFAULT_BASE_URL: Final[str] = "https://api.openai.com/v1"

COMPLETIONS_PATH: Final[str] = "/chat/completions"

#: What this adapter declares when settings say nothing.
#:
#: ``max_context`` is **0 - not declared** rather than a guess, because the server on the other end
#: is deliberately unknown: it may be a frontier model with a million tokens or a quantised 7B with
#: eight thousand. Zero means the effective budget is the writer's own ``llm_context_budget`` and
#: nothing else (``specs/providers.md`` section 7), which is the honest answer to "we do not know".
DEFAULT_CAPABILITIES: Final[Capabilities] = Capabilities(
    native_tools=True,
    streaming=True,
    max_context=0,
    supports_system=True,
)

#: This protocol's ``finish_reason``, onto the port's closed set. ``stop`` is ``end_turn``: see the
#: module docstring for why ``stop_sequence`` has no writer on this adapter.
_STOP_REASONS: Final[dict[str, StopReason]] = {
    "stop": "end_turn",
    "length": "max_tokens",
    "tool_calls": "tool_use",
    "function_call": "tool_use",
    "content_filter": "refusal",
}

#: The ``type`` field on this protocol's error body, onto the taxonomy. Servers vary in how much
#: of it they fill in, which is why the HTTP status is read first and this only refines it.
_ERROR_TYPES: Final[dict[str, ProviderErrorCode]] = {
    "invalid_request_error": "provider_refused",
    "authentication_error": "provider_auth_failed",
    "permission_error": "provider_auth_failed",
    "insufficient_quota": "provider_rate_limited",
    "rate_limit_error": "provider_rate_limited",
    "server_error": "provider_unavailable",
    "overloaded_error": "provider_unavailable",
}


class OpenAICompatibleAdapter:
    """An :class:`~archetype.llm.port.LLMProvider` over any chat-completions server.

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
        name: str = "openai",
        stream_usage: bool = True,
    ) -> None:
        self.name = name
        self.capabilities = capabilities or DEFAULT_CAPABILITIES
        self.stream_usage = stream_usage
        headers = {"content-type": "application/json"}
        if api_key:
            # A local server usually wants no key at all, and sending `Bearer ` with nothing after
            # it is how a permissive server starts answering `401`.
            headers["authorization"] = f"Bearer {api_key}"
        self._transport = ProviderTransport(
            provider=name,
            base_url=base_url or DEFAULT_BASE_URL,
            headers=headers,
            client=client,
        )

    async def aclose(self) -> None:
        await self._transport.aclose()

    # -- out ------------------------------------------------------------------------------

    def build_body(self, req: CompletionRequest, *, stream: bool) -> dict[str, Any]:
        """The normalised request as a chat-completions body. Public: the fixtures assert it."""
        body: dict[str, Any] = {
            "model": req.model,
            "max_tokens": req.max_tokens,
            "messages": [_wire_message(message) for message in self._messages(req)],
        }
        if req.temperature is not None:
            body["temperature"] = req.temperature
        if req.stop:
            body["stop"] = list(req.stop)
        if req.tools and self.capabilities.native_tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters or {"type": "object", "properties": {}},
                    },
                }
                for tool in req.tools
            ]
            body["tool_choice"] = req.tool_choice
        if stream:
            body["stream"] = True
            if self.stream_usage:
                body["stream_options"] = {"include_usage": True}
        return body

    def _messages(self, req: CompletionRequest) -> list[Message]:
        """The conversation, with the prompted-tool section and ``supports_system`` applied.

        A system message stays a message here - that is this protocol's shape, and it is the exact
        half of the port that Anthropic's separate ``system`` parameter is the other of.
        """
        messages = list(req.messages)
        if req.tools and not self.capabilities.native_tools:
            messages = [*messages, Message(role="system", content=system_instructions(req.tools))]
        if not self.capabilities.supports_system:
            messages = _fold_system_into_first_user(messages)
        return _system_first(messages)

    # -- in -------------------------------------------------------------------------------

    def read_result(self, payload: dict[str, Any], req: CompletionRequest) -> CompletionResult:
        """A chat-completions response as the port's. Public because the fixtures assert it."""
        choice = _first_choice(payload)
        message = choice.get("message")
        message = message if isinstance(message, dict) else {}
        text = message.get("content")
        text = "" if text is None else str(text)
        tool_calls = list(self._read_tool_calls(message.get("tool_calls")))
        raw_stop = str(choice.get("finish_reason") or "")
        stop_reason = _STOP_REASONS.get(raw_stop, "other")
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

    def _read_tool_calls(self, raw: Any) -> list[ToolCall]:
        """Normalise the calls, parsing the arguments string this protocol sends.

        ``specs/providers.md`` section 8, rule 1: ``arguments`` is a parsed object at the port. A
        string that will not parse is ``provider_refused`` **with the raw text preserved** - the
        one thing it must never be is a call with empty arguments, which would run a tool with
        defaults the model never asked for.
        """
        if not isinstance(raw, list):
            return []
        calls: list[ToolCall] = []
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            function = entry.get("function")
            function = function if isinstance(function, dict) else {}
            arguments = function.get("arguments")
            if isinstance(arguments, dict):
                parsed = arguments
            else:
                parsed = self._parse_arguments(str(arguments or ""), str(function.get("name", "")))
            calls.append(
                ToolCall(
                    id=str(entry.get("id", "")),
                    name=str(function.get("name", "")),
                    arguments=parsed,
                )
            )
        return calls

    def _parse_arguments(self, raw: str, tool_name: str) -> dict[str, Any]:
        if not raw.strip():
            return {}
        try:
            decoded = json.loads(raw)
        except ValueError as exc:
            raise ProviderError(
                "provider_refused",
                f"{self.name} sent tool arguments for {tool_name!r} that are not JSON",
                provider=self.name,
                detail={"raw_arguments": raw},
            ) from exc
        if not isinstance(decoded, dict):
            raise ProviderError(
                "provider_refused",
                f"{self.name} sent tool arguments for {tool_name!r} that are not an object",
                provider=self.name,
                detail={"raw_arguments": raw},
            )
        return decoded

    # -- the port -------------------------------------------------------------------------

    async def complete(self, req: CompletionRequest) -> CompletionResult:
        payload = await self._transport.post_json(
            COMPLETIONS_PATH, self.build_body(req, stream=False)
        )
        return self.read_result(payload, req)

    def stream(self, req: CompletionRequest) -> AsyncIterator[StreamEvent]:
        """The answer as D32's events. Not ``async def`` - see the Anthropic adapter's note."""
        if not self.capabilities.streaming:
            raise ProviderError(
                "provider_unavailable",
                f"{self.name} is configured without streaming",
                provider=self.name,
            )
        return self._events(req, self.build_body(req, stream=True))

    async def _events(
        self, req: CompletionRequest, body: dict[str, Any]
    ) -> AsyncIterator[StreamEvent]:
        state = _StreamState(model=req.model)
        async with self._transport.stream_sse(COMPLETIONS_PATH, body) as events:
            async for event in events:
                for produced in state.feed(event.data):
                    yield produced
            for produced in state.finish():
                yield produced


class _StreamState:
    """One chat-completions stream, as the port's events.

    Two things this protocol does that the port does not, handled once:

    * **``[DONE]`` is a sentinel, not JSON.** It ends the stream, and the ``done`` event is built
      from whatever ``finish_reason`` arrived before it.
    * **The usage chunk has no choices.** When ``stream_options.include_usage`` is on, the last
      chunk before ``[DONE]`` carries usage and an empty ``choices`` list; without it, no usage is
      reported at all and the port's zeros correctly say *not reported*.
    """

    def __init__(self, *, model: str) -> None:
        self.model = model
        self.started = False
        self.raw_stop = ""
        self.usage_sent = False
        self.done_sent = False

    def feed(self, data: str) -> list[StreamEvent]:
        if data.strip() == "[DONE]":
            return self._done()
        payload = _decode(data)
        if not payload:
            return []
        if "error" in payload:
            return [self._error(payload["error"])]

        produced: list[StreamEvent] = []
        model = payload.get("model")
        if isinstance(model, str) and model:
            self.model = model
        if not self.started:
            self.started = True
            produced.append(StreamStart(model=self.model))

        choice = _first_choice(payload)
        delta = choice.get("delta")
        delta = delta if isinstance(delta, dict) else {}
        content = delta.get("content")
        if isinstance(content, str) and content:
            produced.append(StreamDelta(text=content))
        if choice.get("finish_reason"):
            self.raw_stop = str(choice["finish_reason"])

        usage = _read_usage(payload.get("usage"))
        if usage.reported and not self.usage_sent:
            self.usage_sent = True
            produced.append(StreamUsage(usage=usage))
        return produced

    def finish(self) -> list[StreamEvent]:
        """What a body that ended without ``[DONE]`` leaves behind: nothing.

        A stream with no terminator is a failure the caller handles (``specs/providers.md``
        section 4), and inventing a ``done`` here would hide a dropped connection behind a
        confident, complete-looking answer.
        """
        return []

    def _done(self) -> list[StreamEvent]:
        if self.done_sent:
            return []
        self.done_sent = True
        return [
            StreamDone(
                stop_reason=_STOP_REASONS.get(self.raw_stop, "other"),
                raw_stop_reason=self.raw_stop,
            )
        ]

    def _error(self, raw: Any) -> StreamEvent:
        error = raw if isinstance(raw, dict) else {}
        message = str(error.get("message") or "the provider reported an error")
        error_type = str(error.get("type", ""))
        code: ProviderErrorCode = (
            "context_too_large"
            if looks_like_context_overflow(error_type, error.get("code"), message)
            else _ERROR_TYPES.get(error_type, "provider_unavailable")
        )
        return StreamError(code=code, message=message)


def _wire_message(message: Message) -> dict[str, Any]:
    """One port message as one chat-completions message."""
    if message.role == "tool":
        return {
            "role": "tool",
            "tool_call_id": message.tool_call_id or "",
            "content": message.content,
        }
    if message.role == "assistant" and message.tool_calls:
        return {
            "role": "assistant",
            "content": message.content or None,
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments, sort_keys=True),
                    },
                }
                for call in message.tool_calls
            ],
        }
    return {"role": message.role, "content": message.content}


def _system_first(messages: list[Message]) -> list[Message]:
    """Every system message ahead of the conversation, in the order they were given.

    This protocol does not require it, and most servers do not care - but the ones that are only
    nearly compatible are exactly the ones that quietly ignore a system message found halfway
    down. Order within each group is preserved, so nothing a composer decided is reordered.
    """
    system = [m for m in messages if m.role == "system"]
    rest = [m for m in messages if m.role != "system"]
    return [*system, *rest]


def _fold_system_into_first_user(messages: list[Message]) -> list[Message]:
    """What ``supports_system=False`` means, and the only thing it means (section 5)."""
    system = "\n\n".join(m.content for m in messages if m.role == "system" and m.content)
    rest = [m for m in messages if m.role != "system"]
    if not system:
        return rest
    for index, message in enumerate(rest):
        if message.role == "user":
            folded = message.model_copy(update={"content": f"{system}\n\n{message.content}"})
            return [*rest[:index], folded, *rest[index + 1 :]]
    return [Message(role="user", content=system), *rest]


def _first_choice(payload: dict[str, Any]) -> dict[str, Any]:
    choices = payload.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        return choices[0]
    return {}


def _read_usage(raw: Any) -> Usage:
    """Usage, or the zeros that mean **not reported** rather than free."""
    if not isinstance(raw, dict):
        return Usage()
    return Usage(
        input_tokens=max(0, int(raw.get("prompt_tokens") or 0)),
        output_tokens=max(0, int(raw.get("completion_tokens") or 0)),
    )


def _decode(data: str) -> dict[str, Any]:
    try:
        decoded = json.loads(data)
    except ValueError:
        return {}
    return decoded if isinstance(decoded, dict) else {}
