"""P4-7 - the prompted-JSON tool fallback, and the corpus of replies it must read.

The corpus is a list in this file rather than a JSON fixture, deliberately. Every other corpus in
this project (`anchors/`, `markdown/`, `schema/`, `bible/storytime/`) is shared - two
implementations, or two suites, held to one statement. This one has exactly one reader, and what
it states is *the shapes a model writes when asked for JSON*, which is a property of prose rather
than of a contract. Keeping it beside the assertions is what makes each case legible as the thing
it is the only cover for.

The bar D31 was ruled on is at the bottom of the file: **a native path and a fallback path produce
identical normalised calls for the same declaration**, asserted over both adapters at once.
"""

from __future__ import annotations

from typing import Any

import pytest

from archetype.llm.adapters.anthropic import DEFAULT_CAPABILITIES as ANTHROPIC_CAPABILITIES
from archetype.llm.adapters.anthropic import AnthropicAdapter
from archetype.llm.adapters.openai_compat import DEFAULT_CAPABILITIES as OPENAI_CAPABILITIES
from archetype.llm.adapters.openai_compat import OpenAICompatibleAdapter
from archetype.llm.adapters.prompted_tools import (
    apply_fallback,
    extract_tool_calls,
    system_instructions,
)
from archetype.llm.port import CompletionRequest, ProviderError, ToolDeclaration

from .conftest import replay

READ_ENTRY = ToolDeclaration(
    name="read_bible_entry",
    description="Read one story-bible entry by name.",
    parameters={"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
)

#: What a model writes when it has been asked for the envelope. Each case names what it covers.
CORPUS: list[dict[str, Any]] = [
    {
        "name": "bare_json",
        "note": "The instruction followed exactly: one object and nothing else.",
        "reply": '{"tool_calls": [{"name": "read_bible_entry", "arguments": {"name": "Mira"}}]}',
        "calls": [("read_bible_entry", {"name": "Mira"})],
        "text": "",
    },
    {
        "name": "fenced_json",
        "note": "A fence, because a model that has ever written Markdown writes one here too.",
        "reply": '```json\n{"tool_calls": [{"name": "read_bible_entry", '
        '"arguments": {"name": "Mira"}}]}\n```',
        "calls": [("read_bible_entry", {"name": "Mira"})],
        "text": "",
    },
    {
        "name": "prose_either_side",
        "note": "The common case in practice, and the reason the parser scans for a balanced "
        "object rather than requiring the reply to be JSON.",
        "reply": 'Let me look her up.\n\n{"tool_calls": [{"name": "read_bible_entry", '
        '"arguments": {"name": "Mira"}}]}\n\nI will report back.',
        "calls": [("read_bible_entry", {"name": "Mira"})],
        "text": "Let me look her up.\n\n\n\nI will report back.",
    },
    {
        "name": "two_calls",
        "note": "More than one tool in one turn - the parallel case the port has always allowed.",
        "reply": '{"tool_calls": [{"name": "read_bible_entry", "arguments": {"name": "Mira"}}, '
        '{"name": "read_bible_entry", "arguments": {"name": "Halloran"}}]}',
        "calls": [
            ("read_bible_entry", {"name": "Mira"}),
            ("read_bible_entry", {"name": "Halloran"}),
        ],
        "text": "",
    },
    {
        "name": "no_arguments",
        "note": "A tool with nothing to pass it. Absent arguments are an empty object, not a "
        "refusal: the model did call the tool, and it called it with nothing.",
        "reply": '{"tool_calls": [{"name": "list_chapters"}]}',
        "calls": [("list_chapters", {})],
        "text": "",
    },
    {
        "name": "no_tool_at_all",
        "note": "An ordinary answer. **Not a failure** - the marker is what separates a reply "
        "that meant to call a tool from one that never did.",
        "reply": "She has been waiting since the second morning, though the text never counts it.",
        "calls": [],
        "text": "She has been waiting since the second morning, though the text never counts it.",
    },
]

REFUSALS: list[dict[str, Any]] = [
    {
        "name": "malformed_json",
        "note": "The reply meant to call a tool and produced JSON that will not parse. It has "
        "not called no tools - it has failed, and the raw text must survive.",
        "reply": '{"tool_calls": [{"name": "read_bible_entry", "arguments": {"name": "Mira"}]',
    },
    {
        "name": "tool_calls_not_a_list",
        "note": "Well-formed JSON that does not say what the envelope says.",
        "reply": '{"tool_calls": {"name": "read_bible_entry"}}',
    },
    {
        "name": "call_without_a_name",
        "note": "A call naming no tool. Dropping it silently would report an answer with no "
        "action taken and no explanation of why.",
        "reply": '{"tool_calls": [{"arguments": {"name": "Mira"}}]}',
    },
    {
        "name": "arguments_that_are_not_an_object",
        "note": "Arguments as a bare string. Running the tool with an empty object instead would "
        "use defaults the model never asked for.",
        "reply": '{"tool_calls": [{"name": "read_bible_entry", "arguments": "Mira"}]}',
    },
]


# -- the corpus -----------------------------------------------------------------------------


@pytest.mark.parametrize("case", CORPUS, ids=[case["name"] for case in CORPUS])
def test_the_corpus_reads_as_the_calls_it_records(case: dict[str, Any]) -> None:
    parsed = extract_tool_calls(case["reply"])
    assert [(call.name, call.arguments) for call in parsed.tool_calls] == case["calls"]
    assert parsed.text == case["text"]


@pytest.mark.parametrize("case", REFUSALS, ids=[case["name"] for case in REFUSALS])
def test_every_unreadable_call_is_a_refusal_that_keeps_the_reply(case: dict[str, Any]) -> None:
    with pytest.raises(ProviderError) as raised:
        extract_tool_calls(case["reply"], provider="local")
    assert raised.value.code == "provider_refused"
    assert raised.value.detail == {"raw_text": case["reply"]}


def test_ids_are_minted_positionally_so_a_fallback_reply_is_reproducible() -> None:
    """An id pairs a call with its result inside one turn and means nothing outside it, so a
    position is a complete identity - and a random token would make the same reply parse
    differently twice."""
    parsed = extract_tool_calls(CORPUS[3]["reply"])
    assert [call.id for call in parsed.tool_calls] == ["call_0", "call_1"]
    again = extract_tool_calls(CORPUS[3]["reply"])
    assert [call.id for call in again.tool_calls] == ["call_0", "call_1"]


def test_a_stop_reason_becomes_tool_use_while_the_provider_s_own_word_is_left_alone() -> None:
    text, calls, stop = apply_fallback(CORPUS[0]["reply"], "end_turn")
    assert stop == "tool_use"
    assert calls and text == ""
    unchanged_text, no_calls, unchanged_stop = apply_fallback("Just an answer.", "end_turn")
    assert (unchanged_text, no_calls, unchanged_stop) == ("Just an answer.", (), "end_turn")


# -- the instructions -------------------------------------------------------------------------


def test_the_instructions_name_every_tool_and_state_the_envelope() -> None:
    rendered = system_instructions((READ_ENTRY,))
    assert "read_bible_entry" in rendered
    assert "Read one story-bible entry by name." in rendered
    assert '"tool_calls"' in rendered
    assert '"name"' in rendered, "the argument schema travels with the tool"


def test_no_tools_renders_nothing_at_all() -> None:
    """So a caller may concatenate unconditionally, and a provider with nothing declared sees a
    prompt with nothing added to it."""
    assert system_instructions(()) == ""


# -- D31's bar ---------------------------------------------------------------------------------


def request_with_tools() -> CompletionRequest:
    return CompletionRequest(
        messages=[{"role": "user", "content": "Who is Mira related to?"}],
        model="a-model",
        max_tokens=512,
        tools=(READ_ENTRY,),
    )


async def test_a_native_path_and_a_fallback_path_produce_identical_tool_calls() -> None:
    """P4-7's *done when*, over both adapters at once.

    "Identical" is exact on the two things a caller acts on - the tool's **name** and its parsed
    **arguments** - and cannot include the id: a native provider's id is its own and the fallback
    mints one, which ``specs/providers.md`` section 8 rule 3 says in as many words while forbidding
    anything above the port from assuming an id's shape. So both ids are asserted to exist and
    the calls are compared without them.
    """
    native_client, _ = replay(
        json_body={
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_native_1",
                                "type": "function",
                                "function": {
                                    "name": "read_bible_entry",
                                    "arguments": '{"name": "Mira"}',
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        }
    )
    fallback_client, _ = replay(
        json_body={
            "content": [
                {
                    "type": "text",
                    "text": '{"tool_calls": [{"name": "read_bible_entry", '
                    '"arguments": {"name": "Mira"}}]}',
                }
            ],
            "stop_reason": "end_turn",
        }
    )
    native = OpenAICompatibleAdapter(api_key="k", client=native_client)
    fallback = AnthropicAdapter(
        api_key="k",
        client=fallback_client,
        capabilities=ANTHROPIC_CAPABILITIES.model_copy(update={"native_tools": False}),
    )
    try:
        from_native = await native.complete(request_with_tools())
        from_fallback = await fallback.complete(request_with_tools())
    finally:
        await native_client.aclose()
        await fallback_client.aclose()

    assert [(c.name, c.arguments) for c in from_native.tool_calls] == [
        (c.name, c.arguments) for c in from_fallback.tool_calls
    ]
    assert from_native.stop_reason == from_fallback.stop_reason == "tool_use"
    assert all(call.id for call in (*from_native.tool_calls, *from_fallback.tool_calls))


def test_both_adapters_route_a_declaration_into_the_prompt_when_there_is_no_tools_api() -> None:
    """The fallback is not one adapter's feature: a server with no tool API is the OpenAI-shaped
    case in practice and the configurable one in either."""
    request = request_with_tools()
    anthropic_body = AnthropicAdapter(
        api_key="k",
        capabilities=ANTHROPIC_CAPABILITIES.model_copy(update={"native_tools": False}),
    ).build_body(request, stream=False)
    openai_body = OpenAICompatibleAdapter(
        api_key="k",
        capabilities=OPENAI_CAPABILITIES.model_copy(update={"native_tools": False}),
    ).build_body(request, stream=False)

    assert "tools" not in anthropic_body and "tools" not in openai_body
    assert "read_bible_entry" in anthropic_body["system"]
    assert "read_bible_entry" in openai_body["messages"][0]["content"]
