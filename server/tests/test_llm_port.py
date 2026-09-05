"""P4-2 and P4-3 - the provider port, its closed vocabularies, and the fake behind the suite.

Written against ``specs/providers.md``, which was written first (P4-1). Three things here are
structural rather than incidental, and each is the kind of rule that stops being true silently:

* **an unknown stream event type is refused on the server** and ignored on the client (D32), so
  the server half is asserted here and the client half in ``web/src/__tests__/stream.test.ts``;
* **no provider SDK is imported outside ``llm/adapters/``** (ruling 2), asserted by walking the
  import graph rather than by review;
* **every constant providers.md names exists in the code under that name** (P4-1's *done when*),
  asserted by reading the document's own table.

Nothing here touches the network, and nothing needs a key.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

import archetype
from archetype.ids import IdPrefix
from archetype.llm import port as port_module
from archetype.llm.port import (
    PROVIDER_ERROR_CODES,
    ROLES,
    STOP_REASONS,
    STREAM_EVENT_TYPES,
    TOOL_CHOICES,
    Capabilities,
    CompletionRequest,
    CompletionResult,
    LLMProvider,
    Message,
    ProviderError,
    StreamDelta,
    StreamDone,
    StreamError,
    StreamStart,
    StreamUsage,
    ToolCall,
    ToolDeclaration,
    Usage,
    parse_stream_event,
)

from .fakes.provider import FakeProvider, NothingStagedError

PACKAGE_ROOT = Path(archetype.__file__).parent
ADAPTERS_DIR = PACKAGE_ROOT / "llm" / "adapters"
PROVIDERS_SPEC = Path(__file__).resolve().parents[2] / "specs" / "providers.md"


def ask(text: str = "What happens in this chapter?") -> CompletionRequest:
    """The smallest legal request - one user message, a model, a ceiling."""
    return CompletionRequest(
        messages=(Message(role="user", content=text),),
        model="fake-model",
        max_tokens=256,
    )


# -- the closed vocabularies --------------------------------------------------------------


def test_the_vocabularies_are_exactly_what_the_specification_says() -> None:
    """providers.md sections 2, 3, 4, and 6, member for member."""
    assert ROLES == ("system", "user", "assistant", "tool")
    assert STOP_REASONS == (
        "end_turn",
        "max_tokens",
        "stop_sequence",
        "tool_use",
        "refusal",
        "other",
        "cancelled",
    )
    assert STREAM_EVENT_TYPES == ("start", "delta", "usage", "done", "error")
    assert TOOL_CHOICES == ("auto", "none", "required")
    assert PROVIDER_ERROR_CODES == (
        "provider_unconfigured",
        "provider_auth_failed",
        "provider_rate_limited",
        "provider_unavailable",
        "provider_refused",
        "context_too_large",
    )


def test_cancelled_is_a_stop_reason_no_adapter_can_produce() -> None:
    """providers.md section 3: the caller that closed the stream writes it, and nobody else.

    There is nothing to assert against an adapter yet - Group B writes the first one - so what is
    pinned here is that the member exists and is documented as the caller's. The adapter half
    lands with P4-5.
    """
    assert "cancelled" in STOP_REASONS
    assert "the caller" in PROVIDERS_SPEC.read_text(encoding="utf-8")


def test_every_constant_the_specification_names_exists_under_that_name() -> None:
    """P4-1's *done when*, enforced against providers.md section 9's own table."""
    rows = re.findall(
        r"^\| `([A-Za-z_.]+)` \| `(llm/port\.py|archetype/ids\.py)` \|",
        PROVIDERS_SPEC.read_text(encoding="utf-8"),
        flags=re.MULTILINE,
    )
    assert len(rows) >= 7, "section 9's constants table did not parse; has it been reshaped?"
    for name, home in rows:
        if home == "llm/port.py":
            assert hasattr(port_module, name), f"providers.md names {name}; llm/port.py has no such"
        else:
            attribute = name.split(".", 1)[1]
            assert hasattr(IdPrefix, attribute), f"providers.md names {name}; ids.py has no such"


# -- the normalised shapes ----------------------------------------------------------------


def test_the_shapes_round_trip_through_pydantic() -> None:
    request = CompletionRequest(
        messages=(
            Message(role="system", content="You are a careful reader."),
            Message(role="user", content="Who is Mira?"),
        ),
        model="fake-model",
        max_tokens=512,
        temperature=0.2,
        stop=("\n\n",),
        tools=(
            ToolDeclaration(name="search", description="find text", parameters={"type": "obj"}),
        ),
        tool_choice="auto",
    )
    assert CompletionRequest.model_validate(request.model_dump()) == request

    result = CompletionResult(
        text="She counts the boats.",
        tool_calls=(ToolCall(id="call_1", name="search", arguments={"q": "Mira"}),),
        stop_reason="tool_use",
        raw_stop_reason="tool_use",
        usage=Usage(input_tokens=120, output_tokens=8),
    )
    assert CompletionResult.model_validate(result.model_dump()) == result


def test_a_shape_is_frozen_and_refuses_a_field_this_build_does_not_know() -> None:
    message = Message(role="user", content="hello")
    with pytest.raises(ValidationError):
        message.content = "goodbye"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        Message(role="user", content="hello", speaker="Mira")  # type: ignore[call-arg]


def test_a_request_must_carry_a_conversation_a_model_and_a_ceiling() -> None:
    with pytest.raises(ValidationError):
        CompletionRequest(messages=(), model="fake-model", max_tokens=10)
    with pytest.raises(ValidationError):
        CompletionRequest(messages=(Message(role="user"),), model="", max_tokens=10)
    with pytest.raises(ValidationError):
        CompletionRequest(messages=(Message(role="user"),), model="m", max_tokens=0)


def test_temperature_defaults_to_the_providers_own_and_not_to_zero() -> None:
    """providers.md section 2: ``None`` means "the provider's default", which is not ``0.0``."""
    assert ask().temperature is None


def test_usage_of_zero_means_not_reported() -> None:
    assert Usage().reported is False
    assert Usage(input_tokens=1).reported is True


def test_tool_arguments_are_parsed_never_a_json_string() -> None:
    """providers.md section 8, rule 1. A string here would push the parse onto every caller."""
    with pytest.raises(ValidationError):
        ToolCall(id="call_1", name="search", arguments='{"q": "Mira"}')  # type: ignore[arg-type]


# -- the stream union (D32) ---------------------------------------------------------------


def test_each_member_of_the_stream_union_deserialises() -> None:
    assert parse_stream_event({"type": "start", "model": "fake-model"}) == StreamStart(
        model="fake-model"
    )
    assert parse_stream_event({"type": "delta", "text": "She "}) == StreamDelta(text="She ")
    assert parse_stream_event(
        {"type": "usage", "usage": {"input_tokens": 12, "output_tokens": 3}}
    ) == StreamUsage(usage=Usage(input_tokens=12, output_tokens=3))
    assert parse_stream_event(
        {"type": "done", "stop_reason": "end_turn", "raw_stop_reason": "end_turn"}
    ) == StreamDone(stop_reason="end_turn", raw_stop_reason="end_turn")
    assert parse_stream_event(
        {"type": "error", "code": "provider_rate_limited", "message": "slow down"}
    ) == StreamError(code="provider_rate_limited", message="slow down")


def test_the_server_refuses_a_stream_event_type_it_does_not_know() -> None:
    """D32's asymmetry, server half: strict here, tolerant in the browser.

    ``step`` is a real Phase 6 event. Refusing it *here* is not a bug to fix when Phase 6 lands -
    it is the guarantee that an adapter and the port cannot part company quietly. The client half
    of this rule is asserted in ``web/src/__tests__/stream.test.ts``.
    """
    for unknown in ({"type": "step", "index": 1}, {"type": "", "text": "x"}, {"text": "x"}):
        with pytest.raises(ValidationError):
            parse_stream_event(unknown)


def test_a_stream_event_is_refused_when_its_own_shape_is_wrong() -> None:
    with pytest.raises(ValidationError):
        parse_stream_event({"type": "done", "stop_reason": "finished"})
    with pytest.raises(ValidationError):
        parse_stream_event({"type": "error", "code": "provider_exploded", "message": "x"})


# -- failure ------------------------------------------------------------------------------


def test_a_provider_error_carries_its_code_its_provider_and_what_was_said() -> None:
    error = ProviderError(
        "provider_rate_limited",
        "the provider is rate limiting this key",
        provider="anthropic",
        detail={"retry_after": 30},
    )
    assert error.code == "provider_rate_limited"
    assert error.provider == "anthropic"
    assert error.detail == {"retry_after": 30}
    assert "provider_rate_limited" in str(error)
    assert isinstance(error, RuntimeError)


# -- ruling 2: no SDK above the adapters --------------------------------------------------


def imported_modules(source: str) -> set[str]:
    """Every top-level module name imported by one file, from its AST rather than a regex."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".", 1)[0])
    return names


def test_no_provider_sdk_is_imported_outside_the_adapters_package() -> None:
    """ruling 2 and providers.md section 11, enforced rather than asserted.

    An SDK type that escapes into a route is how "nothing above the port knows which provider is
    in play" quietly stops being true - and it does not announce itself, because the app goes on
    working until the second provider is configured.
    """
    forbidden = {"anthropic", "openai"}
    offenders: list[str] = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        if ADAPTERS_DIR in path.parents:
            continue
        found = imported_modules(path.read_text(encoding="utf-8")) & forbidden
        if found:
            offenders.append(f"{path.relative_to(PACKAGE_ROOT)} imports {', '.join(sorted(found))}")
    assert not offenders, "a provider SDK escaped llm/adapters/: " + "; ".join(offenders)


def test_the_port_itself_imports_nothing_but_pydantic_and_the_standard_library() -> None:
    """P4-2: the module Phases 6 and 7 are written against stays importable with nothing running."""
    imported = imported_modules((PACKAGE_ROOT / "llm" / "port.py").read_text(encoding="utf-8"))
    assert imported <= {"__future__", "collections", "typing", "pydantic"}


# -- P4-3: the fake -----------------------------------------------------------------------


def test_the_fake_satisfies_the_protocol_rather_than_being_assumed_to() -> None:
    provider: LLMProvider = FakeProvider()
    assert isinstance(provider, LLMProvider)
    assert provider.name == "fake"
    assert isinstance(provider.capabilities, Capabilities)


async def test_a_staged_completion_is_what_comes_back() -> None:
    fake = FakeProvider()
    staged = fake.stage_completion("She counts the boats.", usage=Usage(input_tokens=90))
    assert await fake.complete(ask()) == staged
    assert fake.call_count == 1
    assert fake.last_request.messages[0].content == "What happens in this chapter?"


async def test_the_fake_invents_nothing_when_a_test_staged_nothing() -> None:
    fake = FakeProvider()
    with pytest.raises(NothingStagedError):
        await fake.complete(ask())


async def test_a_staged_error_is_raised_and_spends_one_staging() -> None:
    fake = FakeProvider()
    fake.stage_error("provider_auth_failed", "the key was refused")
    with pytest.raises(ProviderError) as caught:
        await fake.complete(ask())
    assert caught.value.code == "provider_auth_failed"
    # The same staging must not also arm the stream: one staged failure is one failure.
    with pytest.raises(NothingStagedError):
        fake.stream(ask())


async def test_a_staged_error_arms_whichever_method_the_caller_reaches_for() -> None:
    fake = FakeProvider()
    fake.stage_error("provider_unavailable", "connection refused")
    stream = fake.stream(ask())
    with pytest.raises(ProviderError) as caught:
        await anext(stream)
    assert caught.value.code == "provider_unavailable"
    with pytest.raises(NothingStagedError):
        await fake.complete(ask())


async def collect(provider: FakeProvider, request: CompletionRequest | None = None) -> list:
    return [event async for event in provider.stream(request or ask())]


async def test_a_streamed_answer_arrives_in_order() -> None:
    fake = FakeProvider()
    fake.stage_stream_text(["She ", "counts ", "the boats."], usage=Usage(output_tokens=4))
    events = await collect(fake)
    assert [event.type for event in events] == ["start", "delta", "delta", "delta", "usage", "done"]
    assert "".join(e.text for e in events if isinstance(e, StreamDelta)) == "She counts the boats."
    assert events[-1].stop_reason == "end_turn"


async def test_every_stream_failure_mode_the_panel_handles_has_a_staging_method() -> None:
    """P4-3's *done when*, one assertion per mode."""
    mid_stream = FakeProvider()
    mid_stream.stage_stream_failure(["She "], code="provider_rate_limited", message="slow down")
    events = await collect(mid_stream)
    assert [event.type for event in events] == ["start", "delta", "error"]
    assert events[-1].code == "provider_rate_limited"

    truncated = FakeProvider()
    truncated.stage_stream_truncated(["She ", "counts "])
    events = await collect(truncated)
    assert [event.type for event in events] == ["start", "delta", "delta"]
    assert not any(event.type in {"done", "error"} for event in events), (
        "a stream that ends without a terminator is what a dropped socket looks like"
    )

    slow = FakeProvider()
    slow.set_cadence(first_event=0.01, between_events=0.001)
    slow.stage_stream_text(["one", "two"])
    assert len(await collect(slow)) == 4


async def test_a_pathological_sequence_can_be_staged_exactly_as_written() -> None:
    """The fake reorders nothing: the reducer's out-of-order tests need the real thing."""
    fake = FakeProvider()
    staged = fake.stage_stream(
        [
            StreamDelta(text="before the start"),
            StreamStart(model="fake-model"),
            StreamDone(stop_reason="end_turn"),
            StreamDone(stop_reason="end_turn"),
        ]
    )
    assert tuple(await collect(fake)) == staged


def test_a_stream_that_is_opened_and_never_read_still_counts_as_a_call() -> None:
    """The "money" risk: one deliberate ask is one call, and an unread one was still asked."""
    fake = FakeProvider()
    fake.stage_stream_text(["one"])
    fake.stream(ask())
    assert fake.call_count == 1
    assert fake.stream_calls == 1


def test_a_provider_that_cannot_stream_refuses_rather_than_faking_a_cadence() -> None:
    """providers.md section 5. Chunking a whole answer to look like typing is the lie."""
    fake = FakeProvider(capabilities=Capabilities(streaming=False, max_context=8_000))
    fake.stage_stream_text(["one"])
    with pytest.raises(ProviderError) as caught:
        fake.stream(ask())
    assert caught.value.code == "provider_unavailable"
