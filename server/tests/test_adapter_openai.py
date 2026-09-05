"""P4-6 - the OpenAI-compatible adapter, against recorded payloads and never the network.

Same discipline as ``test_adapter_anthropic.py`` and the same corpus shape, over a different wire
format. What is extra here is the reason this adapter exists at all: the servers that are only
**nearly** compatible. Their variances are what the `local_server_streamed` case and half the
tests below are about - a file path where a model id goes, no usage on a stream, a keep-alive
comment in the middle of one, a server with no tool-calling API at all.

The cross-adapter test that proves the two are interchangeable - one normalised request through
both, one comparison of the normalised results - is in ``test_llm_adapters.py``, because it
belongs to neither.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from archetype.llm.adapters.openai_compat import DEFAULT_CAPABILITIES, OpenAICompatibleAdapter
from archetype.llm.port import (
    Capabilities,
    CompletionRequest,
    CompletionResult,
    ProviderError,
    StreamEvent,
    parse_stream_event,
)

from .conftest import load_provider_cases, replay, replay_case

CASES = load_provider_cases("openai")

WHOLE_ANSWERS = [case for case in CASES if "port_result" in case]
STREAMS = [case for case in CASES if "port_events" in case]
FAILURES = [case for case in CASES if "port_error" in case]
OUTBOUND = [case for case in CASES if "wire_request" in case]


def build(
    case: dict[str, Any] | None = None,
    *,
    client: httpx.AsyncClient | None = None,
    capabilities: Capabilities | None = None,
    stream_usage: bool | None = None,
) -> OpenAICompatibleAdapter:
    overrides = (case or {}).get("adapter") or {}
    declared = capabilities
    if declared is None and "capabilities" in overrides:
        declared = Capabilities.model_validate(overrides["capabilities"])
    if stream_usage is None:
        stream_usage = bool(overrides.get("stream_usage", True))
    return OpenAICompatibleAdapter(
        api_key="test-key", capabilities=declared, client=client, stream_usage=stream_usage
    )


def request_of(case: dict[str, Any]) -> CompletionRequest:
    return CompletionRequest.model_validate(case["port_request"])


def ask(**overrides: Any) -> CompletionRequest:
    base: dict[str, Any] = {
        "messages": [{"role": "user", "content": "What happens here?"}],
        "model": "gpt-4o-mini",
        "max_tokens": 256,
    }
    base.update(overrides)
    return CompletionRequest.model_validate(base)


def answering(body: dict[str, Any]):
    return replay(json_body=body)


def streaming(lines: list[str]):
    return replay(sse=lines)


def whole_answer(**message: Any) -> dict[str, Any]:
    """A minimal chat-completions body, for a case an inline payload states better than a file."""
    finish = message.pop("finish_reason", "stop")
    return {"choices": [{"index": 0, "message": message, "finish_reason": finish}]}


# -- the corpus, both ways ------------------------------------------------------------------


@pytest.mark.parametrize("case", OUTBOUND, ids=[case["name"] for case in OUTBOUND])
def test_the_outbound_body_is_exactly_what_the_corpus_records(case: dict[str, Any]) -> None:
    body = build(case).build_body(request_of(case), stream=bool(case.get("stream")))
    assert body == case["wire_request"]


@pytest.mark.parametrize("case", WHOLE_ANSWERS, ids=[case["name"] for case in WHOLE_ANSWERS])
async def test_a_recorded_answer_normalises_to_what_the_corpus_expects(
    case: dict[str, Any],
) -> None:
    client, calls = replay_case(case)
    try:
        result = await build(case, client=client).complete(request_of(case))
    finally:
        await client.aclose()
    assert result == CompletionResult.model_validate(case["port_result"])
    assert calls.count == 1, "one deliberate ask is one request (ruling 6)"
    assert calls.last.url.path.endswith("/chat/completions")


@pytest.mark.parametrize("case", STREAMS, ids=[case["name"] for case in STREAMS])
async def test_a_recorded_stream_produces_exactly_the_expected_events(
    case: dict[str, Any],
) -> None:
    client, _ = replay_case(case)
    expected: list[StreamEvent] = [parse_stream_event(raw) for raw in case["port_events"]]
    try:
        produced = [event async for event in build(case, client=client).stream(request_of(case))]
    finally:
        await client.aclose()
    assert produced == expected


@pytest.mark.parametrize("case", FAILURES, ids=[case["name"] for case in FAILURES])
async def test_a_recorded_failure_maps_to_the_code_the_corpus_names(case: dict[str, Any]) -> None:
    client, _ = replay_case(case)
    try:
        with pytest.raises(ProviderError) as raised:
            await build(case, client=client).complete(request_of(case))
    finally:
        await client.aclose()
    assert raised.value.code == case["port_error"]["code"]
    assert case["port_error"]["message_contains"] in raised.value.message


# -- the translations worth stating separately ----------------------------------------------


def test_the_system_prompt_stays_a_message_which_is_the_other_half_of_the_port() -> None:
    body = build().build_body(
        ask(
            messages=[
                {"role": "user", "content": "Well?"},
                {"role": "system", "content": "Be exact."},
            ]
        ),
        stream=False,
    )
    assert body["messages"][0] == {"role": "system", "content": "Be exact."}
    assert "system" not in body


def test_an_assistant_s_tool_calls_go_out_with_their_arguments_as_a_json_string() -> None:
    """This protocol's own shape, and the reason the port insists on an object at its side."""
    body = build().build_body(
        ask(
            messages=[
                {"role": "user", "content": "Who is Mira?"},
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {"id": "call_1", "name": "read_bible_entry", "arguments": {"name": "Mira"}}
                    ],
                },
                {"role": "tool", "tool_call_id": "call_1", "content": "A lighthouse keeper."},
            ]
        ),
        stream=False,
    )
    assert body["messages"][1]["tool_calls"] == [
        {
            "id": "call_1",
            "type": "function",
            "function": {"name": "read_bible_entry", "arguments": '{"name": "Mira"}'},
        }
    ]
    assert body["messages"][2] == {
        "role": "tool",
        "tool_call_id": "call_1",
        "content": "A lighthouse keeper.",
    }


def test_supports_system_false_folds_the_system_text_into_the_first_user_message() -> None:
    adapter = build(capabilities=DEFAULT_CAPABILITIES.model_copy(update={"supports_system": False}))
    body = adapter.build_body(
        ask(
            messages=[
                {"role": "system", "content": "Be exact."},
                {"role": "user", "content": "Well?"},
            ]
        ),
        stream=False,
    )
    assert body["messages"] == [{"role": "user", "content": "Be exact.\n\nWell?"}]


def test_stream_options_can_be_turned_off_for_a_server_that_rejects_it() -> None:
    """A real incompatibility rather than a hypothetical one: the field is an extension, and a
    server that has not heard of it refuses the whole request."""
    assert "stream_options" not in build(stream_usage=False).build_body(ask(), stream=True)
    assert build().build_body(ask(), stream=True)["stream_options"] == {"include_usage": True}


# -- what comes back ------------------------------------------------------------------------


async def test_a_null_content_reads_as_empty_text_rather_than_the_word_none() -> None:
    """This protocol sends ``content: null`` on a tool-call turn, and every local server copies
    it. Stringifying it would put the word "None" into a transcript."""
    client, _ = answering(whole_answer(role="assistant", content=None))
    try:
        result = await build(client=client).complete(ask())
    finally:
        await client.aclose()
    assert result.text == ""


async def test_tool_arguments_that_will_not_parse_are_a_refusal_that_keeps_the_raw_text() -> None:
    """Never a silently empty call: that would run a tool with defaults the model never asked
    for (``specs/providers.md`` section 8, rule 1)."""
    client, _ = answering(
        whole_answer(
            role="assistant",
            content=None,
            tool_calls=[
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "read_bible_entry", "arguments": '{"name": '},
                }
            ],
            finish_reason="tool_calls",
        )
    )
    try:
        with pytest.raises(ProviderError) as raised:
            await build(client=client).complete(ask())
    finally:
        await client.aclose()
    assert raised.value.code == "provider_refused"
    assert raised.value.detail == {"raw_arguments": '{"name": '}


async def test_a_finish_reason_this_build_does_not_know_becomes_other() -> None:
    client, _ = answering(whole_answer(role="assistant", content="...", finish_reason="eos"))
    try:
        result = await build(client=client).complete(ask())
    finally:
        await client.aclose()
    assert result.stop_reason == "other"
    assert result.raw_stop_reason == "eos"


async def test_a_content_filter_is_a_model_refusal_and_not_an_error() -> None:
    client, _ = answering(
        whole_answer(
            role="assistant",
            content="I can't help with that.",
            finish_reason="content_filter",
        )
    )
    try:
        result = await build(client=client).complete(ask())
    finally:
        await client.aclose()
    assert result.stop_reason == "refusal"
    assert result.text == "I can't help with that."


async def test_a_server_that_reports_no_usage_reads_as_not_reported() -> None:
    client, _ = answering(whole_answer(role="assistant", content="..."))
    try:
        result = await build(client=client).complete(ask())
    finally:
        await client.aclose()
    assert result.usage.reported is False


# -- the prompted-JSON fallback, from this side (P4-7) ---------------------------------------


def test_a_server_without_native_tools_sends_no_tools_field_and_a_prompt_instead() -> None:
    adapter = build(capabilities=DEFAULT_CAPABILITIES.model_copy(update={"native_tools": False}))
    body = adapter.build_body(
        ask(tools=[{"name": "read_bible_entry", "description": "Read one entry."}]),
        stream=False,
    )
    assert "tools" not in body
    assert "tool_choice" not in body
    system = body["messages"][0]
    assert system["role"] == "system"
    assert "read_bible_entry" in system["content"]
    assert '{"tool_calls":' in system["content"]


async def test_a_prompted_reply_becomes_ordinary_tool_calls_with_a_tool_use_stop_reason() -> None:
    """Nothing above the port can tell the difference - which is the entire requirement."""
    adapter_client, _ = answering(
        whole_answer(
            role="assistant",
            content='Looking her up.\n```json\n{"tool_calls": '
            '[{"name": "read_bible_entry", "arguments": {"name": "Mira"}}]}\n```',
        )
    )
    adapter = build(
        client=adapter_client,
        capabilities=DEFAULT_CAPABILITIES.model_copy(update={"native_tools": False}),
    )
    try:
        result = await adapter.complete(
            ask(tools=[{"name": "read_bible_entry", "description": "Read one entry."}])
        )
    finally:
        await adapter_client.aclose()
    assert [call.name for call in result.tool_calls] == ["read_bible_entry"]
    assert result.tool_calls[0].arguments == {"name": "Mira"}
    assert result.stop_reason == "tool_use"
    assert result.raw_stop_reason == "stop", "the provider's own word is never dropped"
    assert result.text == "Looking her up."


# -- streaming ------------------------------------------------------------------------------


def test_a_provider_configured_without_streaming_refuses_when_asked() -> None:
    adapter = build(capabilities=DEFAULT_CAPABILITIES.model_copy(update={"streaming": False}))
    with pytest.raises(ProviderError) as raised:
        adapter.stream(ask())
    assert raised.value.code == "provider_unavailable"


async def test_a_stream_that_ends_without_done_produces_no_done() -> None:
    client, _ = streaming(
        [
            'data: {"choices":[{"index":0,"delta":{"content":"half a "},"finish_reason":null}]}',
            "",
        ]
    )
    try:
        events = [event async for event in build(client=client).stream(ask())]
    finally:
        await client.aclose()
    assert [event.type for event in events] == ["start", "delta"]


async def test_a_mid_stream_error_object_arrives_as_an_error_event() -> None:
    client, _ = streaming(
        [
            'data: {"choices":[{"index":0,"delta":{"content":"half a "},"finish_reason":null}]}',
            "",
            'data: {"error":{"message":"the engine crashed","type":"server_error"}}',
            "",
        ]
    )
    try:
        events = [event async for event in build(client=client).stream(ask())]
    finally:
        await client.aclose()
    assert events[-1].type == "error"
    assert events[-1].code == "provider_unavailable"


# -- headers ---------------------------------------------------------------------------------


async def test_a_key_is_sent_as_a_bearer_token_and_omitted_entirely_when_there_is_none() -> None:
    """A local server usually wants no key, and ``Bearer `` with nothing after it is how a
    permissive server starts answering 401."""
    with_key, keyed = answering(whole_answer(role="assistant", content="."))
    without_key, unkeyed = answering(whole_answer(role="assistant", content="."))
    try:
        await build(client=with_key).complete(ask())
        await OpenAICompatibleAdapter(api_key="", client=without_key).complete(ask())
    finally:
        await with_key.aclose()
        await without_key.aclose()
    assert keyed.last.headers["authorization"] == "Bearer test-key"
    assert "authorization" not in unkeyed.last.headers
