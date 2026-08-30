"""P1-5, P1-6 - the REST routes and the error envelope.

Every route gets a happy path and a not-found. The save protocol gets more than that, because a
`409` that silently overwrote would be the phase's worst bug (D19, plan section 5).
"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from archetype.manuscript.documents import MAX_CONTENT_BYTES
from archetype.manuscript.projection import empty_document
from archetype.projects.store import ProjectStore

from .conftest import build_document

PROSE = build_document(
    headings=[(1, "Arrival"), (2, "The Quay")],
    paragraphs=["The harbour was grey.", "He did not look back."],
)

ENVELOPE_KEYS = {"code", "message", "detail"}


def error_of(response) -> dict[str, Any]:
    """The envelope from a failing response, checked for shape as it is read."""
    body = response.json()
    assert set(body) == {"error"}, body
    assert set(body["error"]) == ENVELOPE_KEYS, body
    assert isinstance(body["error"]["code"], str) and body["error"]["code"]
    assert isinstance(body["error"]["message"], str) and body["error"]["message"]
    return body["error"]


def create_project(client: TestClient, title: str = "Test Manuscript") -> dict[str, Any]:
    response = client.post("/api/projects", json={"title": title})
    assert response.status_code == 201, response.text
    return response.json()


# -- meta -----------------------------------------------------------------------------------


def test_health_still_answers(client: TestClient) -> None:
    assert client.get("/api/health").json()["status"] == "ok"


def test_openapi_generates_cleanly(app: FastAPI) -> None:
    schema = app.openapi()

    assert schema["info"]["title"] == "Archetype"
    assert {
        "/api/health",
        "/api/projects",
        "/api/projects/{project_id}",
        "/api/projects/{project_id}/documents",
        "/api/projects/{project_id}/outline",
        "/api/documents/{document_id}",
        "/api/documents/{document_id}/content",
    } <= set(schema["paths"])


def test_the_error_envelope_is_documented_in_the_schema(app: FastAPI) -> None:
    responses = app.openapi()["paths"]["/api/documents/{document_id}/content"]["put"]["responses"]
    assert {"400", "404", "409", "413", "422"} <= set(responses)
    assert "ErrorResponse" in str(responses)


# -- projects -------------------------------------------------------------------------------


def test_listing_an_empty_workspace(client: TestClient) -> None:
    assert client.get("/api/projects").json() == {"projects": [], "skipped": []}


def test_creating_a_project_seeds_one_empty_chapter(client: TestClient) -> None:
    body = create_project(client, "The Long Road")

    assert body["project"]["title"] == "The Long Road"
    assert body["project"]["chapter_count"] == 1
    assert body["project"]["word_count"] == 0
    assert len(body["documents"]) == 1
    assert body["documents"][0]["title"] == "Chapter 1"
    assert body["documents"][0]["version"] == 1


def test_a_created_project_appears_in_the_list(client: TestClient) -> None:
    created = create_project(client, "The Long Road")

    listed = client.get("/api/projects").json()["projects"]
    assert [project["id"] for project in listed] == [created["project"]["id"]]
    assert listed[0]["chapter_count"] == 1


@pytest.mark.parametrize("title", ["", "   ", "x" * 201])
def test_creating_a_project_with_an_unusable_title_is_a_422(client: TestClient, title: str) -> None:
    response = client.post("/api/projects", json={"title": title})

    assert response.status_code == 422
    assert error_of(response)["code"] == "validation_error"


def test_an_undeclared_field_is_refused(client: TestClient) -> None:
    """Wire schemas are extension-only, so a field the server does not know is a client bug."""
    response = client.post("/api/projects", json={"title": "Ok", "colour": "blue"})

    assert response.status_code == 422
    assert error_of(response)["code"] == "validation_error"


def test_getting_one_project_returns_its_documents(client: TestClient) -> None:
    created = create_project(client)
    project_id = created["project"]["id"]

    body = client.get(f"/api/projects/{project_id}").json()

    assert body["project"]["id"] == project_id
    assert [doc["id"] for doc in body["documents"]] == [created["documents"][0]["id"]]


def test_getting_a_missing_project_is_a_404(client: TestClient) -> None:
    response = client.get("/api/projects/prj_doesnotexist")

    assert response.status_code == 404
    error = error_of(response)
    assert error["code"] == "project_not_found"
    assert "prj_doesnotexist" in error["message"]


def test_a_project_copied_in_from_a_backup_is_listed(
    client: TestClient, store: ProjectStore, tmp_path: Path
) -> None:
    """D17: backup is a file copy, so a copied-in file simply appears (P1-12)."""
    created = create_project(client, "Portable")
    source = store.find(created["project"]["id"])
    assert source is not None
    shutil.copyfile(source.path, store.projects_dir / "a-copy.sqlite")

    listed = client.get("/api/projects").json()["projects"]
    assert [project["title"] for project in listed] == ["Portable", "Portable"]


def test_an_unreadable_file_is_reported_not_fatal(client: TestClient, store: ProjectStore) -> None:
    """P1-12: one bad file must not take down the list."""
    create_project(client, "Readable")
    (store.projects_dir / "junk.sqlite").write_bytes(b"this is not a database")
    stranger = store.projects_dir / "stranger.sqlite"
    conn = sqlite3.connect(stranger)
    conn.execute("CREATE TABLE something (id TEXT)")
    conn.commit()
    conn.close()

    body = client.get("/api/projects").json()

    assert [project["title"] for project in body["projects"]] == ["Readable"]
    assert {skipped["name"] for skipped in body["skipped"]} == {"junk.sqlite", "stranger.sqlite"}
    assert all(skipped["reason"] for skipped in body["skipped"])


# -- documents ------------------------------------------------------------------------------


def test_the_document_list_omits_content(client: TestClient) -> None:
    """The outline panel must never pull the manuscript to draw a chapter list (P1-5)."""
    project_id = create_project(client)["project"]["id"]

    body = client.get(f"/api/projects/{project_id}/documents").json()

    assert len(body["documents"]) == 1
    assert "content_json" not in body["documents"][0]


def test_creating_a_chapter_appends_it(client: TestClient) -> None:
    project_id = create_project(client)["project"]["id"]

    created = client.post(f"/api/projects/{project_id}/documents", json={"title": "Departure"})
    assert created.status_code == 201
    assert created.json()["order_index"] == 1
    assert created.json()["content_json"] == empty_document()

    listed = client.get(f"/api/projects/{project_id}/documents").json()["documents"]
    assert [doc["title"] for doc in listed] == ["Chapter 1", "Departure"]


def test_creating_a_chapter_without_a_body_takes_the_next_number(client: TestClient) -> None:
    project_id = create_project(client)["project"]["id"]

    created = client.post(f"/api/projects/{project_id}/documents")

    assert created.status_code == 201
    assert created.json()["title"] == "Chapter 2"


def test_creating_a_chapter_in_a_missing_project_is_a_404(client: TestClient) -> None:
    response = client.post("/api/projects/prj_doesnotexist/documents", json={"title": "Nope"})

    assert response.status_code == 404
    assert error_of(response)["code"] == "project_not_found"


def test_getting_a_document_returns_its_content(client: TestClient) -> None:
    document_id = create_project(client)["documents"][0]["id"]

    body = client.get(f"/api/documents/{document_id}").json()

    assert body["id"] == document_id
    assert body["content_json"] == empty_document()
    assert body["version"] == 1
    assert "text_plain" not in body


def test_getting_a_missing_document_is_a_404(client: TestClient) -> None:
    response = client.get("/api/documents/doc_doesnotexist")

    assert response.status_code == 404
    error = error_of(response)
    assert error["code"] == "document_not_found"
    assert "doc_doesnotexist" in error["message"]


def test_a_document_is_found_in_whichever_project_holds_it(client: TestClient) -> None:
    """The locator answers 'which file' for a route that names no project."""
    first = create_project(client, "First")["documents"][0]["id"]
    second = create_project(client, "Second")["documents"][0]["id"]

    assert client.get(f"/api/documents/{first}").json()["id"] == first
    assert client.get(f"/api/documents/{second}").json()["id"] == second
    assert (
        client.get(f"/api/documents/{first}").json()["project_id"]
        != client.get(f"/api/documents/{second}").json()["project_id"]
    )


def test_renaming_a_document(client: TestClient) -> None:
    document_id = create_project(client)["documents"][0]["id"]

    response = client.patch(f"/api/documents/{document_id}", json={"title": "  Arrival  "})

    assert response.status_code == 200
    assert response.json()["title"] == "Arrival"
    assert response.json()["version"] == 1


def test_renaming_a_missing_document_is_a_404(client: TestClient) -> None:
    response = client.patch("/api/documents/doc_doesnotexist", json={"title": "Arrival"})

    assert response.status_code == 404
    assert error_of(response)["code"] == "document_not_found"


# -- the save protocol (P1-6, D19) ------------------------------------------------------------


def test_a_correct_save_returns_the_new_version_and_the_projection(client: TestClient) -> None:
    document_id = create_project(client)["documents"][0]["id"]

    response = client.put(
        f"/api/documents/{document_id}/content", json={"content_json": PROSE, "version": 1}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["document_id"] == document_id
    assert body["version"] == 2
    assert body["word_count"] == 12
    assert body["headings"] == [
        {"level": 1, "text": "Arrival", "ordinal": 0},
        {"level": 2, "text": "The Quay", "ordinal": 1},
    ]
    assert client.get(f"/api/documents/{document_id}").json()["content_json"] == PROSE


def test_a_stale_save_is_a_409_that_writes_nothing(client: TestClient) -> None:
    document_id = create_project(client)["documents"][0]["id"]
    client.put(f"/api/documents/{document_id}/content", json={"content_json": PROSE, "version": 1})
    saved = client.get(f"/api/documents/{document_id}").json()

    response = client.put(
        f"/api/documents/{document_id}/content",
        json={"content_json": build_document(paragraphs=["Clobbered."]), "version": 1},
    )

    assert response.status_code == 409
    error = error_of(response)
    assert error["code"] == "version_conflict"
    assert error["detail"] == {
        "document_id": document_id,
        "presented_version": 1,
        "current_version": 2,
        "updated_at": saved["updated_at"],
    }
    assert client.get(f"/api/documents/{document_id}").json() == saved


def test_saving_a_missing_document_is_a_404(client: TestClient) -> None:
    response = client.put(
        "/api/documents/doc_doesnotexist/content", json={"content_json": PROSE, "version": 1}
    )

    assert response.status_code == 404
    assert error_of(response)["code"] == "document_not_found"


def test_a_malformed_document_is_refused_before_any_write(client: TestClient) -> None:
    document_id = create_project(client)["documents"][0]["id"]
    before = client.get(f"/api/documents/{document_id}").json()

    response = client.put(
        f"/api/documents/{document_id}/content",
        json={"content_json": {"type": "paragraph"}, "version": 1},
    )

    assert response.status_code == 400
    assert error_of(response)["code"] == "invalid_document"
    assert client.get(f"/api/documents/{document_id}").json() == before


def test_an_oversized_document_is_refused_before_any_write(client: TestClient) -> None:
    document_id = create_project(client)["documents"][0]["id"]
    before = client.get(f"/api/documents/{document_id}").json()
    huge = build_document(paragraphs=["x" * (MAX_CONTENT_BYTES + 1)])

    response = client.put(
        f"/api/documents/{document_id}/content", json={"content_json": huge, "version": 1}
    )

    assert response.status_code == 413
    error = error_of(response)
    assert error["code"] == "payload_too_large"
    assert error["detail"]["limit"] == MAX_CONTENT_BYTES
    assert client.get(f"/api/documents/{document_id}").json() == before


@pytest.mark.parametrize(
    "body",
    [
        {"content_json": PROSE},
        {"version": 1},
        {"content_json": PROSE, "version": 0},
        {"content_json": PROSE, "version": "two"},
        {"content_json": "not an object", "version": 1},
        {"content_json": PROSE, "version": 1, "extra": True},
    ],
)
def test_a_save_body_that_does_not_validate_is_a_422(client: TestClient, body: Any) -> None:
    document_id = create_project(client)["documents"][0]["id"]

    response = client.put(f"/api/documents/{document_id}/content", json=body)

    assert response.status_code == 422
    assert error_of(response)["code"] == "validation_error"


def test_content_survives_a_reload(client: TestClient) -> None:
    """Exit criterion 1, at the API level: write it, fetch it, and it is what was written."""
    document_id = create_project(client)["documents"][0]["id"]
    prose = build_document(paragraphs=["Un café, s’il vous plaît — naïve."])

    client.put(f"/api/documents/{document_id}/content", json={"content_json": prose, "version": 1})

    assert client.get(f"/api/documents/{document_id}").json()["content_json"] == prose


# -- outline --------------------------------------------------------------------------------


def test_the_outline_spans_every_chapter(client: TestClient) -> None:
    project_id = create_project(client)["project"]["id"]
    first = client.get(f"/api/projects/{project_id}/documents").json()["documents"][0]["id"]
    second = client.post(
        f"/api/projects/{project_id}/documents", json={"title": "Departure"}
    ).json()["id"]

    client.put(f"/api/documents/{first}/content", json={"content_json": PROSE, "version": 1})
    client.put(
        f"/api/documents/{second}/content",
        json={"content_json": build_document(headings=[(1, "Away")]), "version": 1},
    )

    body = client.get(f"/api/projects/{project_id}/outline").json()

    assert body["project_id"] == project_id
    assert [chapter["title"] for chapter in body["chapters"]] == ["Chapter 1", "Departure"]
    assert [heading["text"] for heading in body["chapters"][0]["headings"]] == [
        "Arrival",
        "The Quay",
    ]
    assert [heading["text"] for heading in body["chapters"][1]["headings"]] == ["Away"]


def test_the_outline_of_a_missing_project_is_a_404(client: TestClient) -> None:
    response = client.get("/api/projects/prj_doesnotexist/outline")

    assert response.status_code == 404
    assert error_of(response)["code"] == "project_not_found"


# -- the envelope, everywhere -----------------------------------------------------------------


def test_an_unknown_route_uses_the_envelope(client: TestClient) -> None:
    response = client.get("/api/nothing-here")

    assert response.status_code == 404
    assert error_of(response)["code"] == "not_found"


def test_a_wrong_method_uses_the_envelope(client: TestClient) -> None:
    response = client.delete("/api/projects")

    assert response.status_code == 405
    assert error_of(response)["code"] == "method_not_allowed"


def test_an_unhandled_exception_is_an_envelope_without_a_traceback(
    client: TestClient, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(self) -> None:
        raise RuntimeError("the disk caught fire")

    monkeypatch.setattr(ProjectStore, "scan", explode)

    response = client.get("/api/projects")

    assert response.status_code == 500
    error = error_of(response)
    assert error["code"] == "internal_error"
    assert "disk caught fire" not in response.text
    assert "Traceback" not in response.text
