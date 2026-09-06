"""The chat socket, end to end over the real application (P4-10, D11, D32).

Everything here runs against ``FakeProvider``, which is why it can stage what no real provider
will produce on request: a stream that fails halfway, a stream that simply stops, and a cadence
slow enough for a cancel to land in the middle of. Those are precisely the conditions the panel's
handling exists for, and staging them is the only way to reach that code (P4-3).

Five claims this file is here to hold, each one of the item's own *done when*:

* a full streamed exchange leaves **two** rows - the question and the answer, with its usage;
* a mid-stream failure persists what arrived, carrying the code that stopped it;
* a cancel persists the partial answer marked ``cancelled``, and asks for nothing more;
* an over-budget request is refused **before the provider is called at all**, asserted by the
  fake recording zero calls;
* one deliberate ask is one provider call, and nothing anywhere retries (ruling 6).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from archetype.llm.port import StreamDelta, StreamDone, StreamStart, Usage

from .conftest import build_document
from .fakes.provider import FakeProvider


def start_project(client: TestClient) -> tuple[str, str, str]:
    """A project, a saved chapter, and a conversation to talk in."""
    created = client.post("/api/projects", json={"title": "The Long Road"}).json()
    project_id = created["project"]["id"]
    document_id = created["documents"][0]["id"]
    client.put(
        f"/api/documents/{document_id}/content",
        json={
            "content_json": build_document(
                paragraphs=["The harbour was grey and the gulls had gone inland."]
            ),
            "version": 1,
        },
    )
    conversation_id = client.post(
        f"/api/projects/{project_id}/conversations", json={"title": "About Mira"}
    ).json()["id"]
    return project_id, document_id, conversation_id


def drain(socket) -> list[dict]:
    """Every event up to and including the one that terminates the stream.

    Exactly one of ``done`` or ``error`` ends a well-formed stream (providers.md section 4), so a
    reader that assumed a terminator would hang here rather than quietly losing the answer - which
    is the point: ``stage_stream_truncated`` proves the server supplies one when a provider does
    not.
    """
    events: list[dict] = []
    while True:
        event = socket.receive_json()
        events.append(event)
        if event["type"] in {"done", "error"}:
            return events


def turns(client: TestClient, conversation_id: str) -> list[dict]:
    return client.get(f"/api/conversations/{conversation_id}").json()["messages"]


# -- the ordinary exchange -----------------------------------------------------------------------


def test_a_full_streamed_exchange(chat_client: TestClient, provider: FakeProvider) -> None:
    _, document_id, conversation_id = start_project(chat_client)
    provider.stage_stream_text(
        ["The harbour ", "is grey."],
        model="fake-model",
        usage=Usage(input_tokens=120, output_tokens=8),
    )

    with chat_client.websocket_connect(f"/api/conversations/{conversation_id}/stream") as socket:
        socket.send_json(
            {
                "type": "ask",
                "prompt": "what colour is the harbour?",
                "context": {"document_id": document_id},
            }
        )
        events = drain(socket)

    assert [event["type"] for event in events] == ["start", "delta", "delta", "usage", "done"]
    assert "".join(e["text"] for e in events if e["type"] == "delta") == "The harbour is grey."
    assert events[-1]["stop_reason"] == "end_turn"

    question, answer = turns(chat_client, conversation_id)
    assert question["role"] == "user"
    assert question["content"] == "what colour is the harbour?"
    assert answer["role"] == "assistant"
    assert answer["content"] == "The harbour is grey."
    assert answer["usage"] == {"input_tokens": 120, "output_tokens": 8}
    assert answer["stop_reason"] == "end_turn"
    assert answer["error_code"] == ""
    assert answer["provider"] == "fake"
    assert provider.call_count == 1, "one deliberate ask is one provider call (ruling 6)"


def test_the_composed_context_is_recorded_on_the_answer(
    chat_client: TestClient, provider: FakeProvider
) -> None:
    """Ruling 5: without it a wrong answer cannot be diagnosed without guessing."""
    _, document_id, conversation_id = start_project(chat_client)
    provider.stage_stream_text(["grey."])

    with chat_client.websocket_connect(f"/api/conversations/{conversation_id}/stream") as socket:
        socket.send_json({"type": "ask", "prompt": "why?", "context": {"document_id": document_id}})
        drain(socket)

    context = turns(chat_client, conversation_id)[1]["context"]
    assert [part["kind"] for part in context["parts"]] == [
        "instructions",
        "chapter",
        "question",
    ]
    assert context["selector"]["document_id"] == document_id
    assert context["estimated_tokens"] > 0


def test_the_answer_is_persisted_before_the_terminator_is_sent(
    chat_client: TestClient, provider: FakeProvider
) -> None:
    """A client that refetches on ``done`` must not beat the row it is looking for."""
    _, _, conversation_id = start_project(chat_client)
    provider.stage_stream_text(["done and dusted"])

    with chat_client.websocket_connect(f"/api/conversations/{conversation_id}/stream") as socket:
        socket.send_json({"type": "ask", "prompt": "anything?"})
        drain(socket)
        # Read *while the socket is still open*, exactly as the panel does.
        assert turns(chat_client, conversation_id)[1]["content"] == "done and dusted"


def test_a_second_ask_on_one_socket_carries_the_first_as_history(
    chat_client: TestClient, provider: FakeProvider
) -> None:
    _, _, conversation_id = start_project(chat_client)
    provider.stage_stream_text(["A harbour pilot."])
    provider.stage_stream_text(["Her brother."])

    with chat_client.websocket_connect(f"/api/conversations/{conversation_id}/stream") as socket:
        socket.send_json({"type": "ask", "prompt": "who is Mira?"})
        drain(socket)
        socket.send_json({"type": "ask", "prompt": "and Tomas?"})
        drain(socket)

    assert len(turns(chat_client, conversation_id)) == 4
    assert provider.call_count == 2
    second = provider.calls[1]
    assert [message.role for message in second.messages] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert "who is Mira?" in second.messages[1].content


# -- failure, which is persisted rather than dropped ----------------------------------------------


def test_a_mid_stream_failure_keeps_the_partial_answer_and_says_why(
    chat_client: TestClient, provider: FakeProvider
) -> None:
    _, _, conversation_id = start_project(chat_client)
    provider.stage_stream_failure(
        ["The harbour "], code="provider_rate_limited", message="slow down"
    )

    with chat_client.websocket_connect(f"/api/conversations/{conversation_id}/stream") as socket:
        socket.send_json({"type": "ask", "prompt": "what colour?"})
        events = drain(socket)

    assert events[-1] == {
        "type": "error",
        "code": "provider_rate_limited",
        "message": "slow down",
    }
    answer = turns(chat_client, conversation_id)[1]
    assert answer["content"] == "The harbour "
    assert answer["error_code"] == "provider_rate_limited"
    assert answer["stop_reason"] == ""


def test_a_stream_that_ends_without_saying_so_is_a_failure_the_socket_supplies(
    chat_client: TestClient, provider: FakeProvider
) -> None:
    """What a dropped connection looks like from the inside (providers.md section 4)."""
    _, _, conversation_id = start_project(chat_client)
    provider.stage_stream_truncated(["The harbour "])

    with chat_client.websocket_connect(f"/api/conversations/{conversation_id}/stream") as socket:
        socket.send_json({"type": "ask", "prompt": "what colour?"})
        events = drain(socket)

    assert events[-1]["type"] == "error"
    assert events[-1]["code"] == "provider_unavailable"
    answer = turns(chat_client, conversation_id)[1]
    assert answer["content"] == "The harbour "
    assert answer["error_code"] == "provider_unavailable"


def test_a_failure_before_anything_arrives_is_still_a_visible_turn(
    chat_client: TestClient, provider: FakeProvider
) -> None:
    _, _, conversation_id = start_project(chat_client)
    provider.stage_error("provider_auth_failed", "that key was rejected")

    with chat_client.websocket_connect(f"/api/conversations/{conversation_id}/stream") as socket:
        socket.send_json({"type": "ask", "prompt": "what colour?"})
        events = drain(socket)

    assert events == [
        {"type": "error", "code": "provider_auth_failed", "message": "that key was rejected"}
    ]
    question, answer = turns(chat_client, conversation_id)
    assert question["content"] == "what colour?"
    assert answer["content"] == ""
    assert answer["error_code"] == "provider_auth_failed"


def test_an_unconfigured_provider_says_which_key_is_missing(
    chat_client: TestClient,
) -> None:
    """Exit criterion 6, at the surface the writer actually meets it on."""
    from archetype.llm.registry import build_provider

    _, _, conversation_id = start_project(chat_client)
    # The real registry, with no key anywhere - which is the suite's normal environment.
    chat_client.app.state.provider_factory = build_provider

    with chat_client.websocket_connect(f"/api/conversations/{conversation_id}/stream") as socket:
        socket.send_json({"type": "ask", "prompt": "what colour?"})
        events = drain(socket)

    assert events[-1]["code"] == "provider_unconfigured"
    assert "ARCHETYPE_ANTHROPIC_API_KEY" in events[-1]["message"]
    assert turns(chat_client, conversation_id)[1]["error_code"] == "provider_unconfigured"


def test_an_over_budget_request_is_refused_before_the_provider_is_called_at_all(
    chat_client: TestClient, provider: FakeProvider
) -> None:
    """Ruling 7. The assertion that matters is ``call_count == 0``: nothing was billed."""
    _, document_id, conversation_id = start_project(chat_client)
    chat_client.app.state.settings = chat_client.app.state.settings.model_copy(
        update={"llm_context_budget": 30}
    )

    with chat_client.websocket_connect(f"/api/conversations/{conversation_id}/stream") as socket:
        socket.send_json(
            {"type": "ask", "prompt": "what colour?", "context": {"document_id": document_id}}
        )
        events = drain(socket)

    assert events[-1]["code"] == "context_too_large"
    assert "select less" in events[-1]["message"]
    assert provider.call_count == 0
    answer = turns(chat_client, conversation_id)[1]
    assert answer["error_code"] == "context_too_large"
    assert answer["context"]["estimated_tokens"] > 30, "the record says what was too big"


# -- cancel (D11's stated reason for a socket) ----------------------------------------------------


def test_cancel_stops_the_stream_and_keeps_what_arrived(
    chat_client: TestClient, provider: FakeProvider
) -> None:
    _, _, conversation_id = start_project(chat_client)
    provider.stage_stream(
        [
            StreamStart(model="fake-model"),
            StreamDelta(text="The harbour "),
            StreamDelta(text="is grey and the gulls "),
            StreamDelta(text="had gone inland."),
            StreamDone(stop_reason="end_turn"),
        ]
    )
    # Slow enough that a cancel sent after the first delta lands before the rest.
    provider.set_cadence(between_events=0.05)

    with chat_client.websocket_connect(f"/api/conversations/{conversation_id}/stream") as socket:
        socket.send_json({"type": "ask", "prompt": "describe the harbour"})
        assert socket.receive_json()["type"] == "start"
        first = socket.receive_json()
        assert first["type"] == "delta"
        socket.send_json({"type": "cancel"})
        events = drain(socket)

    assert events[-1] == {"type": "done", "stop_reason": "cancelled", "raw_stop_reason": ""}
    answer = turns(chat_client, conversation_id)[1]
    assert answer["stop_reason"] == "cancelled"
    assert answer["error_code"] == "", "a deliberate stop is not a failure"
    assert answer["content"].startswith("The harbour ")
    assert "had gone inland." not in answer["content"]
    assert provider.call_count == 1, "cancelling asks for nothing more"


def test_a_cancel_with_nothing_in_flight_is_late_rather_than_wrong(
    chat_client: TestClient, provider: FakeProvider
) -> None:
    """The answer had already finished. Punishing that race would break a legitimate client."""
    _, _, conversation_id = start_project(chat_client)
    provider.stage_stream_text(["quick."])
    provider.stage_stream_text(["second answer."])

    with chat_client.websocket_connect(f"/api/conversations/{conversation_id}/stream") as socket:
        socket.send_json({"type": "ask", "prompt": "one"})
        drain(socket)
        socket.send_json({"type": "cancel"})
        socket.send_json({"type": "ask", "prompt": "two"})
        events = drain(socket)

    assert events[-1]["stop_reason"] == "end_turn"
    assert len(turns(chat_client, conversation_id)) == 4


# -- what closes the socket rather than borrowing a provider's code -------------------------------


def test_a_frame_this_build_does_not_understand_closes_the_socket(
    chat_client: TestClient, provider: FakeProvider
) -> None:
    """The server half of D32's asymmetry, on the frames coming the other way.

    Guessing what an unknown frame meant is how tokens get spent on something nobody asked for.
    """
    _, _, conversation_id = start_project(chat_client)

    with (
        pytest.raises(WebSocketDisconnect),
        chat_client.websocket_connect(f"/api/conversations/{conversation_id}/stream") as socket,
    ):
        socket.send_json({"type": "regenerate"})
        socket.receive_json()

    assert provider.call_count == 0
    assert turns(chat_client, conversation_id) == []


def test_an_ask_with_no_prompt_closes_the_socket(chat_client: TestClient) -> None:
    _, _, conversation_id = start_project(chat_client)

    with (
        pytest.raises(WebSocketDisconnect),
        chat_client.websocket_connect(f"/api/conversations/{conversation_id}/stream") as socket,
    ):
        socket.send_json({"type": "ask", "prompt": ""})
        socket.receive_json()


def test_a_socket_for_a_conversation_that_is_not_there_closes_with_a_reason(
    chat_client: TestClient,
) -> None:
    with (
        pytest.raises(WebSocketDisconnect) as raised,
        chat_client.websocket_connect("/api/conversations/cnv_000000000000/stream") as socket,
    ):
        socket.receive_json()

    assert raised.value.code == 1008
    assert "no such conversation" in raised.value.reason


def test_a_socket_for_a_deleted_conversation_closes_too(chat_client: TestClient) -> None:
    project_id, _, conversation_id = start_project(chat_client)
    chat_client.delete(f"/api/conversations/{conversation_id}")

    with (
        pytest.raises(WebSocketDisconnect),
        chat_client.websocket_connect(f"/api/conversations/{conversation_id}/stream") as socket,
    ):
        socket.receive_json()


def test_a_selection_in_a_chapter_that_is_gone_closes_rather_than_faking_a_provider_failure(
    chat_client: TestClient, provider: FakeProvider
) -> None:
    """Ruling 4's six codes are all about a provider, and this is not one of them."""
    _, document_id, conversation_id = start_project(chat_client)
    chat_client.delete(f"/api/documents/{document_id}")

    with (
        pytest.raises(WebSocketDisconnect) as raised,
        chat_client.websocket_connect(f"/api/conversations/{conversation_id}/stream") as socket,
    ):
        socket.send_json(
            {"type": "ask", "prompt": "what colour?", "context": {"document_id": document_id}}
        )
        socket.receive_json()

    assert raised.value.code == 1008
    assert provider.call_count == 0
    assert turns(chat_client, conversation_id) == [], "a refused ask writes nothing"
