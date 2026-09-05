"""P4-5 - the Anthropic adapter, against recorded payloads and never against the network.

Every case in ``tests/fixtures/providers/anthropic/cases.json`` is asserted **in both
directions**: the body the adapter must POST, and the port shape it must produce from what came
back. A translation that drifted on one side only would otherwise round-trip quietly against
itself and be discovered by a writer rather than by a test.

Nothing here opens a socket. The client under every adapter is an ``httpx.MockTransport`` that
answers with the corpus and records what was sent, so ruling 3 is a property of the suite rather
than a promise about how it is used.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from archetype.llm.adapters.anthropic import DEFAULT_CAPABILITIES, AnthropicAdapter
from archetype.llm.port import (
    Capabilities,
    CompletionRequest,
    CompletionResult,
    ProviderError,
    StreamEvent,
    parse_stream_event,
)

from .conftest import load_provider_cases, replay, replay_case

CASES = load_provider_cases("anthropic")

WHOLE_ANSWERS = [case for case in CASES if "port_result" in case]
STREAMS = [case for case in CASES if "port_events" in case]
FAILURES = [case for case in CASES if "port_error" in case]
OUTBOUND = [case for case in CASES if "wire_request" in case]


def build(
    case: dict[str, Any] | None = None,
    *,
    client: httpx.AsyncClient | None = None,
    capabilities: Capabilities | None = None,
) -> AnthropicAdapter:
    overrides = (case or {}).get("adapter") or {}
    declared = capabilities
    if declared is None and "capabilities" in overrides:
        declared = Capabilities.model_validate(overrides["capabilities"])
    return AnthropicAdapter(api_key="test-key", capabilities=declared, client=client)


def request_of(case: dict[str, Any]) -> CompletionRequest:
    return CompletionRequest.model_validate(case["port_request"])


def ask(**overrides: Any) -> CompletionRequest:
    base: dict[str, Any] = {
        "messages": [{"role": "user", "content": "What happens here?"}],
        "model": "claude-opus-5",
        "max_tokens": 256,
    }
    base.update(overrides)
    return CompletionRequest.model_validate(base)


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
    assert calls.last.url.path == "/v1/messages"


@pytest.mark.parametrize("case", STREAMS, ids=[case["name"] for case in STREAMS])
async def test_a_recorded_stream_produces_exactly_the_expected_events(case: dict[str, Any]) -> None:
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
    assert raised.value.provider == "anthropic"


@pytest.mark.parametrize("case", FAILURES, ids=[case["name"] for case in FAILURES])
async def test_a_failure_reaches_a_streamed_request_the_same_way(case: dict[str, Any]) -> None:
    """An auth failure on a streamed ask is the same error a whole one gets, not a dead stream."""
    client, _ = replay_case(case)
    try:
        with pytest.raises(ProviderError) as raised:
            async for _ in build(case, client=client).stream(request_of(case)):
                pass
    finally:
        await client.aclose()
    assert raised.value.code == case["port_error"]["code"]


# -- the translations worth stating separately ----------------------------------------------


def test_the_system_prompt_leaves_the_message_list_for_a_parameter_of_its_own() -> None:
    """The asymmetry with the OpenAI shape, which is the whole reason the port has one form."""
    body = build().build_body(
        ask(
            messages=[
                {"role": "system", "content": "Be exact."},
                {"role": "system", "content": "Answer only from the passage."},
                {"role": "user", "content": "Well?"},
            ]
        ),
        stream=False,
    )
    assert body["system"] == "Be exact.\n\nAnswer only from the passage."
    assert body["messages"] == [{"role": "user", "content": "Well?"}]


def test_temperature_is_absent_unless_the_caller_chose_one() -> None:
    """Not a nicety: the current Claude models reject the parameter with a 400."""
    assert "temperature" not in build().build_body(ask(), stream=False)
    assert build().build_body(ask(temperature=0.0), stream=False)["temperature"] == 0.0


def test_stop_sequences_are_passed_through_under_the_provider_s_own_name() -> None:
    body = build().build_body(ask(stop=["\n\nCHAPTER"]), stream=False)
    assert body["stop_sequences"] == ["\n\nCHAPTER"]


def test_a_tool_result_becomes_a_user_message_carrying_a_tool_result_block() -> None:
    """Where a tool's answer goes is the provider's business, and the port never learns it."""
    body = build().build_body(
        ask(
            messages=[
                {"role": "user", "content": "Who is Mira?"},
                {
                    "role": "assistant",
                    "content": "Looking.",
                    "tool_calls": [
                        {"id": "toolu_1", "name": "read_bible_entry", "arguments": {"name": "Mira"}}
                    ],
                },
                {"role": "tool", "tool_call_id": "toolu_1", "content": "A lighthouse keeper."},
            ]
        ),
        stream=False,
    )
    assert body["messages"][1] == {
        "role": "assistant",
        "content": [
            {"type": "text", "text": "Looking."},
            {
                "type": "tool_use",
                "id": "toolu_1",
                "name": "read_bible_entry",
                "input": {"name": "Mira"},
            },
        ],
    }
    assert body["messages"][2] == {
        "role": "user",
        "content": [
            {"type": "tool_result", "tool_use_id": "toolu_1", "content": "A lighthouse keeper."}
        ],
    }


def test_supports_system_false_folds_the_system_text_into_the_first_user_message() -> None:
    """Section 5: that is what the flag means, and it means nothing else."""
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
    assert "system" not in body
    assert body["messages"] == [{"role": "user", "content": "Be exact.\n\nWell?"}]


def test_tool_choice_required_is_sent_as_this_provider_s_word_for_it() -> None:
    body = build().build_body(
        ask(
            tools=[{"name": "t", "description": "", "parameters": {"type": "object"}}],
            tool_choice="required",
        ),
        stream=False,
    )
    assert body["tool_choice"] == {"type": "any"}


# -- what comes back ------------------------------------------------------------------------


async def test_an_unknown_stop_reason_becomes_other_and_keeps_its_own_word() -> None:
    """``pause_turn`` is real, is a server-tool condition, and is not ``end_turn``."""
    client, _ = answering(
        {"content": [{"type": "text", "text": "..."}], "stop_reason": "pause_turn", "usage": {}}
    )
    try:
        result = await build(client=client).complete(ask())
    finally:
        await client.aclose()
    assert result.stop_reason == "other"
    assert result.raw_stop_reason == "pause_turn"


async def test_a_model_refusal_is_an_answer_and_not_an_error() -> None:
    """``stop_reason="refusal"`` is the *model*; ``provider_refused`` is the *provider*. A refusal
    is complete, billed, and the writer paid for it - throwing it away would lose both the text
    and the usage."""
    client, _ = answering(
        {
            "content": [{"type": "text", "text": "I can't help with that."}],
            "stop_reason": "refusal",
            "usage": {"input_tokens": 40, "output_tokens": 8},
        }
    )
    try:
        result = await build(client=client).complete(ask())
    finally:
        await client.aclose()
    assert result.stop_reason == "refusal"
    assert result.text == "I can't help with that."
    assert result.usage.output_tokens == 8


async def test_usage_that_was_not_reported_reads_as_not_reported() -> None:
    client, _ = answering({"content": [], "stop_reason": "end_turn"})
    try:
        result = await build(client=client).complete(ask())
    finally:
        await client.aclose()
    assert result.usage.reported is False


# -- streaming ------------------------------------------------------------------------------


def test_a_provider_configured_without_streaming_refuses_when_asked_not_when_read() -> None:
    """The refusal is at the ask, exactly as ``FakeProvider``'s is - one deliberate ask, one
    answer, and no iteration needed to find out it was never going to work."""
    adapter = build(capabilities=DEFAULT_CAPABILITIES.model_copy(update={"streaming": False}))
    with pytest.raises(ProviderError) as raised:
        adapter.stream(ask())
    assert raised.value.code == "provider_unavailable"


async def test_a_stream_that_ends_without_a_terminator_produces_no_done() -> None:
    """What a dropped connection looks like from the inside. Inventing a ``done`` here would hide
    it behind an answer that looks complete (``specs/providers.md`` section 4)."""
    client, _ = streaming(
        [
            "event: message_start",
            'data: {"type":"message_start","message":{"model":"claude-opus-5","usage":{}}}',
            "",
            "event: content_block_delta",
            'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"half a "}}',
            "",
        ]
    )
    try:
        events = [event async for event in build(client=client).stream(ask())]
    finally:
        await client.aclose()
    assert [event.type for event in events] == ["start", "delta"]


async def test_a_mid_stream_error_arrives_as_an_error_event_with_the_taxonomy_s_code() -> None:
    client, _ = streaming(
        [
            "event: message_start",
            'data: {"type":"message_start","message":{"model":"claude-opus-5","usage":{}}}',
            "",
            "event: error",
            'data: {"type":"error","error":{"type":"overloaded_error","message":"Overloaded"}}',
            "",
        ]
    )
    try:
        events = [event async for event in build(client=client).stream(ask())]
    finally:
        await client.aclose()
    assert events[-1].type == "error"
    assert events[-1].code == "provider_unavailable"


async def test_a_streamed_tool_call_has_no_phase_4_event_and_the_done_still_says_tool_use() -> None:
    """The one real hole in D32's Phase 4 vocabulary, pinned so that Phase 6 closing it is a
    change to this test rather than a discovery (phase-4-plan section 7, ``B4``)."""
    client, _ = streaming(
        [
            "event: message_start",
            'data: {"type":"message_start","message":{"model":"claude-opus-5","usage":{}}}',
            "",
            "event: content_block_start",
            'data: {"type":"content_block_start","index":0,'
            '"content_block":{"type":"tool_use","id":"toolu_1","name":"read_bible_entry"}}',
            "",
            "event: content_block_delta",
            'data: {"type":"content_block_delta","index":0,'
            '"delta":{"type":"input_json_delta","partial_json":"{\\"name\\":\\"Mira\\"}"}}',
            "",
            "event: message_delta",
            'data: {"type":"message_delta","delta":{"stop_reason":"tool_use"},'
            '"usage":{"output_tokens":12}}',
            "",
            "event: message_stop",
            'data: {"type":"message_stop"}',
            "",
        ]
    )
    try:
        events = [event async for event in build(client=client).stream(ask())]
    finally:
        await client.aclose()
    assert [event.type for event in events] == ["start", "usage", "done"]
    assert events[-1].stop_reason == "tool_use"


# -- headers ---------------------------------------------------------------------------------


async def test_every_request_carries_the_key_and_the_pinned_api_version() -> None:
    client, calls = answering({"content": [], "stop_reason": "end_turn"})
    try:
        await build(client=client).complete(ask())
    finally:
        await client.aclose()
    assert calls.last.headers["x-api-key"] == "test-key"
    assert calls.last.headers["anthropic-version"] == "2023-06-01"


# -- helpers ----------------------------------------------------------------------------------


def answering(body: dict[str, Any]):
    """A replay client for a payload written inline, where a corpus case would be overkill."""
    return replay(json_body=body)


def streaming(lines: list[str]):
    """The same, for a stream."""
    return replay(sse=lines)
