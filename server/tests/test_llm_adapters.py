"""P4-5 and P4-6 - what is true of **both** adapters, and of the transport under them.

The tests that belong to neither adapter live here: that the two are interchangeable, that the
error taxonomy is one taxonomy rather than two that happen to agree, that nothing retries, and
that the SSE framing both providers stream over is parsed once and correctly.

The first of those is phase-4-plan section 6's opening risk made falsifiable. **The port is shaped
by whichever adapter is written first** is the classic way an abstraction over two things becomes
an abstraction over one; the parametrised test below runs one normalised request through both and
compares the normalised results, so it fails the moment the port has a favourite.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from archetype.llm.adapters.anthropic import AnthropicAdapter
from archetype.llm.adapters.openai_compat import OpenAICompatibleAdapter
from archetype.llm.adapters.sse import SSEEvent, iter_events
from archetype.llm.port import (
    CompletionRequest,
    CompletionResult,
    LLMProvider,
    Message,
    ProviderError,
    Usage,
    parse_stream_event,
)

from .conftest import RecordedCalls, replay

MODEL = "one-model"
ANSWER = "The harbour was grey."

#: One request, composed once, run through both adapters. Nothing in it is provider-specific -
#: which is the point, and is what a port is for.
SHARED_REQUEST = CompletionRequest(
    messages=(
        Message(role="system", content="Answer only from the passage."),
        Message(role="user", content="What colour is the harbour?"),
    ),
    model=MODEL,
    max_tokens=128,
)

#: The same answer, in each provider's own words.
WHOLE_ANSWERS: dict[str, dict[str, Any]] = {
    "anthropic": {
        "model": MODEL,
        "content": [{"type": "text", "text": ANSWER}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 11, "output_tokens": 5},
    },
    "openai": {
        "model": MODEL,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": ANSWER},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 11, "completion_tokens": 5},
    },
}

#: And the same answer as it arrives, in each provider's own event sequence.
STREAMS: dict[str, list[str]] = {
    "anthropic": [
        "event: message_start",
        'data: {"type":"message_start","message":{"model":"one-model",'
        '"usage":{"input_tokens":11,"output_tokens":1}}}',
        "",
        "event: content_block_delta",
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"The harbour"}}',
        "",
        "event: content_block_delta",
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":" was grey."}}',
        "",
        "event: message_delta",
        'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},'
        '"usage":{"output_tokens":5}}',
        "",
        "event: message_stop",
        'data: {"type":"message_stop"}',
        "",
    ],
    "openai": [
        'data: {"model":"one-model","choices":[{"index":0,"delta":{"content":"The harbour"},'
        '"finish_reason":null}]}',
        "",
        'data: {"model":"one-model","choices":[{"index":0,"delta":{"content":" was grey."},'
        '"finish_reason":null}]}',
        "",
        'data: {"model":"one-model","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}',
        "",
        'data: {"model":"one-model","choices":[],'
        '"usage":{"prompt_tokens":11,"completion_tokens":5}}',
        "",
        "data: [DONE]",
        "",
    ],
}

#: The same six conditions, in each provider's own error shape.
FAILURES: dict[str, list[tuple[str, int, dict[str, Any]]]] = {
    "anthropic": [
        (
            "provider_auth_failed",
            401,
            {"error": {"type": "authentication_error", "message": "invalid x-api-key"}},
        ),
        (
            "provider_rate_limited",
            429,
            {"error": {"type": "rate_limit_error", "message": "slow down"}},
        ),
        (
            "provider_unavailable",
            529,
            {"error": {"type": "overloaded_error", "message": "Overloaded"}},
        ),
        (
            "provider_refused",
            400,
            {"error": {"type": "invalid_request_error", "message": "max_tokens must be positive"}},
        ),
        (
            "context_too_large",
            400,
            {"error": {"type": "invalid_request_error", "message": "prompt is too long: 9 > 8"}},
        ),
    ],
    "openai": [
        (
            "provider_auth_failed",
            401,
            {"error": {"message": "Incorrect API key provided", "type": "invalid_request_error"}},
        ),
        (
            "provider_rate_limited",
            429,
            {"error": {"message": "Rate limit reached", "type": "rate_limit_error"}},
        ),
        (
            "provider_unavailable",
            503,
            {"error": {"message": "The server is overloaded", "type": "server_error"}},
        ),
        (
            "provider_refused",
            400,
            {
                "error": {
                    "message": "Unsupported parameter: 'stream_options'",
                    "type": "invalid_request_error",
                }
            },
        ),
        (
            "context_too_large",
            400,
            {
                "error": {
                    "message": "Please reduce the length of the messages.",
                    "type": "invalid_request_error",
                    "code": "context_length_exceeded",
                }
            },
        ),
    ],
}

AdapterFactory = Callable[[httpx.AsyncClient], Any]

BUILDERS: dict[str, AdapterFactory] = {
    "anthropic": lambda client: AnthropicAdapter(api_key="k", client=client),
    "openai": lambda client: OpenAICompatibleAdapter(api_key="k", client=client),
}

PROVIDERS = tuple(BUILDERS)


# -- interchangeable ---------------------------------------------------------------------------


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_one_request_through_either_adapter_gives_the_same_normalised_result(
    provider: str,
) -> None:
    """P4-6's *done when*, and section 6's first risk made falsifiable.

    Everything the port promises is compared exactly. ``raw_stop_reason`` is deliberately excluded
    and asserted separately: it is *supposed* to differ, because it is the provider's own word,
    and that is what makes ``other`` diagnosable rather than merely honest (section 3).
    """
    client, calls = replay(json_body=WHOLE_ANSWERS[provider])
    try:
        result = await BUILDERS[provider](client).complete(SHARED_REQUEST)
    finally:
        await client.aclose()

    assert result.model_dump(exclude={"raw_stop_reason"}) == CompletionResult(
        text=ANSWER,
        stop_reason="end_turn",
        usage=Usage(input_tokens=11, output_tokens=5),
    ).model_dump(exclude={"raw_stop_reason"})
    assert result.raw_stop_reason == {"anthropic": "end_turn", "openai": "stop"}[provider]
    assert calls.count == 1


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_one_request_streamed_through_either_adapter_gives_the_same_events(
    provider: str,
) -> None:
    client, _ = replay(sse=STREAMS[provider])
    try:
        events = [event async for event in BUILDERS[provider](client).stream(SHARED_REQUEST)]
    finally:
        await client.aclose()

    expected = [
        {"type": "start", "model": MODEL},
        {"type": "delta", "text": "The harbour"},
        {"type": "delta", "text": " was grey."},
        {"type": "usage", "usage": {"input_tokens": 11, "output_tokens": 5}},
        {
            "type": "done",
            "stop_reason": "end_turn",
            "raw_stop_reason": {"anthropic": "end_turn", "openai": "stop"}[provider],
        },
    ]
    assert events == [parse_stream_event(raw) for raw in expected]


@pytest.mark.parametrize("provider", PROVIDERS)
def test_both_adapters_satisfy_the_protocol_rather_than_being_assumed_to(provider: str) -> None:
    adapter: LLMProvider = BUILDERS[provider](None)
    assert isinstance(adapter, LLMProvider)
    assert adapter.name in {"anthropic", "openai"}


# -- one taxonomy, not two that happen to agree -------------------------------------------------


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_every_failure_condition_maps_to_the_same_code_from_either_provider(
    provider: str,
) -> None:
    for expected_code, status, body in FAILURES[provider]:
        client, _ = replay(status=status, json_body=body)
        try:
            with pytest.raises(ProviderError) as raised:
                await BUILDERS[provider](client).complete(SHARED_REQUEST)
        finally:
            await client.aclose()
        assert raised.value.code == expected_code, f"{provider}: {status} {body}"
        assert raised.value.detail["status"] == status, "what the provider said is kept"


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_a_provider_that_cannot_be_reached_is_unavailable_and_is_not_retried(
    provider: str,
) -> None:
    """Ruling 6 has no retry in it, and this is where that would be invisible if it were wrong:
    httpx retries nothing by default and nothing here adds any, so one ask is one attempt."""
    attempts = RecordedCalls()

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.requests.append(request)
        raise httpx.ConnectError("nothing is listening", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ProviderError) as raised:
            await BUILDERS[provider](client).complete(SHARED_REQUEST)
    finally:
        await client.aclose()
    assert raised.value.code == "provider_unavailable"
    assert attempts.count == 1, "one deliberate ask is one attempt - nothing retries"


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_a_body_that_is_not_json_is_unavailable_rather_than_a_crash(provider: str) -> None:
    """A proxy's HTML error page is the ordinary way this happens, and a stack trace reaching the
    writer is the one outcome ruling 4 rules out."""
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text="<html>502</html>"))
    )
    try:
        with pytest.raises(ProviderError) as raised:
            await BUILDERS[provider](client).complete(SHARED_REQUEST)
    finally:
        await client.aclose()
    assert raised.value.code == "provider_unavailable"


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_an_injected_client_is_not_closed_by_the_adapter_that_borrowed_it(
    provider: str,
) -> None:
    """The socket's client will outlive one answer, and an adapter that closed it would take the
    next one down with it."""
    client, _ = replay(json_body=WHOLE_ANSWERS[provider])
    adapter = BUILDERS[provider](client)
    try:
        await adapter.complete(SHARED_REQUEST)
        await adapter.aclose()
        assert client.is_closed is False
        await adapter.complete(SHARED_REQUEST)
    finally:
        await client.aclose()


# -- the framing both providers stream over -----------------------------------------------------


def test_an_event_is_dispatched_by_a_blank_line_and_carries_its_name() -> None:
    assert list(iter_events(["event: ping", "data: {}", ""])) == [SSEEvent("ping", "{}")]


def test_repeated_data_fields_are_joined_with_a_newline() -> None:
    """Nothing in this build sends one today. A server that started to would otherwise hand an
    adapter half a JSON document and get reported as a provider refusal."""
    assert list(iter_events(["data: {", 'data: "a": 1', "data: }", ""])) == [
        SSEEvent("", '{\n"a": 1\n}')
    ]


def test_a_comment_line_is_not_an_event() -> None:
    """Several OpenAI-compatible servers hold the connection open with one."""
    assert list(iter_events([": keep-alive", "", "data: 1", ""])) == [SSEEvent("", "1")]


def test_an_event_left_unterminated_is_emitted_rather_than_dropped() -> None:
    """A provider that ends mid-event has produced a stream with no terminator, and that is a
    condition the caller must see rather than one the parser rounds off."""
    assert list(iter_events(["data: half"])) == [SSEEvent("", "half")]


def test_one_leading_space_after_the_colon_is_the_separator_and_is_not_data() -> None:
    assert list(iter_events(["data:  two spaces", ""])) == [SSEEvent("", " two spaces")]
