"""The conversation routes over the real application (P4-9), and the context preview (P4-10).

The route tests are thin on purpose - every rule lives in
:mod:`archetype.chat.conversations` and has its own suite - but two things can only be asserted
here: that the **envelope** is what a client sees when a conversation is not there, and that a
deleted conversation is absent from every *route* as well as from every store method.

The preview is here rather than with the socket because it is an ordinary request: it composes,
reports, and **spends nothing**. That is ruling 5 made reachable - what is being sent is shown
before it is sent - and the fake provider is asserted to have been called zero times.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from archetype.chat.conversations import ConversationStore

from .conftest import build_document
from .fakes.provider import FakeProvider


def make_project_with_chapter(client: TestClient) -> tuple[str, str]:
    """A project and one saved chapter, returned as ``(project_id, document_id)``."""
    created = client.post("/api/projects", json={"title": "The Long Road"}).json()
    project_id = created["project"]["id"]
    document_id = created["documents"][0]["id"]
    client.put(
        f"/api/documents/{document_id}/content",
        json={
            "content_json": build_document(paragraphs=["The harbour was grey."]),
            "version": 1,
        },
    )
    return project_id, document_id


def new_conversation(client: TestClient, project_id: str, title: str = "") -> str:
    response = client.post(f"/api/projects/{project_id}/conversations", json={"title": title})
    assert response.status_code == 201, response.text
    return response.json()["id"]


# -- the six, and the seventh -------------------------------------------------------------------


def test_create_list_get_rename_delete_restore(client: TestClient) -> None:
    project_id, _ = make_project_with_chapter(client)

    conversation_id = new_conversation(client, project_id, "About Mira")
    listed = client.get(f"/api/projects/{project_id}/conversations").json()
    assert [row["id"] for row in listed["conversations"]] == [conversation_id]

    detail = client.get(f"/api/conversations/{conversation_id}").json()
    assert detail["conversation"]["title"] == "About Mira"
    assert detail["messages"] == []

    renamed = client.patch(f"/api/conversations/{conversation_id}", json={"title": "The harbour"})
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "The harbour"

    deleted = client.delete(f"/api/conversations/{conversation_id}")
    assert deleted.status_code == 200
    assert deleted.json()["deleted_at"] is not None

    restored = client.post(f"/api/conversations/{conversation_id}/restore")
    assert restored.status_code == 200
    assert restored.json()["deleted_at"] is None


def test_a_deleted_conversation_is_absent_from_every_route_together(
    client: TestClient,
) -> None:
    """The store's standing test, one layer up - because a route can forget a predicate too."""
    project_id, _ = make_project_with_chapter(client)
    conversation_id = new_conversation(client, project_id, "About Mira")
    client.delete(f"/api/conversations/{conversation_id}")

    listed = client.get(f"/api/projects/{project_id}/conversations").json()
    assert listed["conversations"] == []
    assert client.get(f"/api/conversations/{conversation_id}").status_code == 404
    assert (
        client.patch(f"/api/conversations/{conversation_id}", json={"title": "x"}).status_code
        == 404
    )
    assert client.delete(f"/api/conversations/{conversation_id}").status_code == 404
    assert client.post(f"/api/conversations/{conversation_id}/context", json={}).status_code == 404

    deleted = client.get(f"/api/projects/{project_id}/conversations/deleted").json()
    assert [row["id"] for row in deleted["conversations"]] == [conversation_id]


def test_an_unknown_conversation_is_the_envelope_and_names_nothing_else(
    client: TestClient,
) -> None:
    response = client.get("/api/conversations/cnv_000000000000")
    assert response.status_code == 404
    body = response.json()["error"]
    assert body["code"] == "conversation_not_found"
    assert "cnv_000000000000" in body["message"]
    assert "projects" not in body["message"], "the directory layout is no business of a browser"


def test_a_title_over_the_limit_is_a_422(client: TestClient) -> None:
    project_id, _ = make_project_with_chapter(client)
    response = client.post(f"/api/projects/{project_id}/conversations", json={"title": "x" * 300})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_a_body_with_a_field_this_build_has_never_heard_of_is_refused(
    client: TestClient,
) -> None:
    """Requests are closed even though responses are extension-only (api-contract section 1)."""
    project_id, _ = make_project_with_chapter(client)
    response = client.post(
        f"/api/projects/{project_id}/conversations", json={"title": "x", "pinned": True}
    )
    assert response.status_code == 422


def test_the_transcript_comes_back_whole_after_a_reload(
    client: TestClient, conversations: ConversationStore
) -> None:
    """D30's whole point, at the route the panel actually re-reads."""
    store = conversations
    conversation = store.create("About Mira")
    store.append(conversation.id, role="user", content="who is she?")
    store.append(
        conversation.id,
        role="assistant",
        content="A harbour pilot.",
        provider="fake",
        model="fake-model",
        usage={"input_tokens": 90, "output_tokens": 12},
        stop_reason="end_turn",
        context={"parts": [], "estimated_tokens": 90},
    )

    body = client.get(f"/api/conversations/{conversation.id}").json()
    assert [message["role"] for message in body["messages"]] == ["user", "assistant"]
    answer = body["messages"][1]
    assert answer["usage"] == {"input_tokens": 90, "output_tokens": 12}
    assert answer["stop_reason"] == "end_turn"
    assert answer["context"]["estimated_tokens"] == 90
    assert body["conversation"]["message_count"] == 2


# -- the preview (ruling 5) ----------------------------------------------------------------------


def test_the_preview_composes_and_spends_nothing(
    chat_client: TestClient, provider: FakeProvider
) -> None:
    project_id, document_id = make_project_with_chapter(chat_client)
    conversation_id = new_conversation(chat_client, project_id)

    response = chat_client.post(
        f"/api/conversations/{conversation_id}/context",
        json={"prompt": "is this grey enough?", "context": {"document_id": document_id}},
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert [part["kind"] for part in body["parts"]] == ["instructions", "chapter", "question"]
    assert body["estimated_tokens"] > 0
    assert body["fits"] is True
    assert provider.call_count == 0, "a preview asks a provider for nothing"


def test_the_preview_reports_an_over_budget_context_rather_than_refusing_it(
    chat_client: TestClient,
) -> None:
    """The refusal belongs to the ask; the preview's job is to show the number first."""
    project_id, document_id = make_project_with_chapter(chat_client)
    conversation_id = new_conversation(chat_client, project_id)
    chat_client.app.state.settings = chat_client.app.state.settings.model_copy(
        update={"llm_context_budget": 20}
    )

    body = chat_client.post(
        f"/api/conversations/{conversation_id}/context",
        json={"prompt": "is this grey enough?", "context": {"document_id": document_id}},
    ).json()

    assert body["budget"] == 20
    assert body["fits"] is False


def test_a_selection_needs_both_ends_and_a_document(chat_client: TestClient) -> None:
    project_id, document_id = make_project_with_chapter(chat_client)
    conversation_id = new_conversation(chat_client, project_id)

    half = chat_client.post(
        f"/api/conversations/{conversation_id}/context",
        json={"context": {"document_id": document_id, "from_pos": 1}},
    )
    assert half.status_code == 422

    orphaned = chat_client.post(
        f"/api/conversations/{conversation_id}/context",
        json={"context": {"from_pos": 1, "to_pos": 5}},
    )
    assert orphaned.status_code == 422


def test_a_preview_naming_an_entry_that_is_gone_is_a_404(
    chat_client: TestClient,
) -> None:
    project_id, _ = make_project_with_chapter(chat_client)
    conversation_id = new_conversation(chat_client, project_id)

    response = chat_client.post(
        f"/api/conversations/{conversation_id}/context",
        json={"prompt": "who?", "context": {"entry_ids": ["ent_000000000000"]}},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "entry_not_found"
