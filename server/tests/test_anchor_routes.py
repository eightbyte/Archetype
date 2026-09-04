"""P2-7 - the anchor routes, over the real application.

The rules live in the store and are tested there; what these assert is that each route reaches
them, that the envelope comes back when it should, and that a bare anchor id finds its way to
whichever project file holds it.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from .conftest import build_blocks

HARBOUR = [
    "The harbour was grey and the Kestrel rode low in it.",
    "Marlow watched from the quay, saying nothing at all.",
    "He did not look back.",
]


def make_chapter(client: TestClient, blocks: list[str] = HARBOUR) -> dict[str, Any]:
    """A project with one chapter holding ``blocks``, returned as the saved document."""
    created = client.post("/api/projects", json={"title": "The Long Road"}).json()
    document_id = created["documents"][0]["id"]
    saved = client.put(
        f"/api/documents/{document_id}/content",
        json={"content_json": build_blocks(blocks), "version": 1},
    ).json()
    return {
        "project_id": created["project"]["id"],
        "document_id": document_id,
        "version": saved["version"],
    }


def anchor_range(client: TestClient, document_id: str, passage: str) -> tuple[int, int]:
    """The range a client would send, found the way a client finds one - from the document.

    The editor has a ProseMirror selection; a test has the text. Both end up sending positions,
    so this walks the stored content to the same place a selection would land.
    """
    from archetype.manuscript.projection import project, text_offset_to_pm_position

    content = client.get(f"/api/documents/{document_id}").json()["content_json"]
    projection = project(content)
    text_from = projection.text_plain.index(passage)
    from_pos = text_offset_to_pm_position(projection, text_from)
    to_pos = text_offset_to_pm_position(projection, text_from + len(passage))
    assert from_pos is not None and to_pos is not None
    return from_pos, to_pos


@pytest.fixture
def chapter(client: TestClient) -> dict[str, Any]:
    return make_chapter(client)


@pytest.fixture
def anchor(client: TestClient, chapter: dict[str, Any]) -> dict[str, Any]:
    from_pos, to_pos = anchor_range(client, chapter["document_id"], "the Kestrel rode low")
    response = client.post(
        f"/api/documents/{chapter['document_id']}/anchors",
        json={
            "from_pos": from_pos,
            "to_pos": to_pos,
            "version": chapter["version"],
            "label": "the ship",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


# -- creating ---------------------------------------------------------------------------------


def test_creating_an_anchor_returns_the_quote_the_server_derived(anchor: dict[str, Any]) -> None:
    assert anchor["quote"] == "the Kestrel rode low"
    assert anchor["prefix"] == "The harbour was grey and "
    assert anchor["status"] == "ok"
    assert anchor["label"] == "the ship"
    assert anchor["suggestion"] is None


def test_creating_against_a_stale_version_is_a_409(
    client: TestClient, chapter: dict[str, Any]
) -> None:
    from_pos, to_pos = anchor_range(client, chapter["document_id"], "Marlow watched")
    response = client.post(
        f"/api/documents/{chapter['document_id']}/anchors",
        json={"from_pos": from_pos, "to_pos": to_pos, "version": 1},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "version_conflict"
    assert client.get(f"/api/documents/{chapter['document_id']}/anchors").json()["anchors"] == []


def test_a_refused_range_is_a_422_that_says_why(
    client: TestClient, chapter: dict[str, Any]
) -> None:
    response = client.post(
        f"/api/documents/{chapter['document_id']}/anchors",
        json={"from_pos": 4, "to_pos": 4, "version": chapter["version"]},
    )

    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "invalid_anchor_range"
    assert "cursor position" in body["message"]


def test_creating_on_a_missing_document_is_a_404(client: TestClient) -> None:
    response = client.post(
        "/api/documents/doc_nothing/anchors",
        json={"from_pos": 1, "to_pos": 5, "version": 1},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "document_not_found"


def test_an_undeclared_field_is_refused(client: TestClient, chapter: dict[str, Any]) -> None:
    response = client.post(
        f"/api/documents/{chapter['document_id']}/anchors",
        json={"from_pos": 1, "to_pos": 5, "version": 2, "quote": "mine"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


# -- reading ----------------------------------------------------------------------------------


def test_a_document_s_anchors_come_back_resolved(
    client: TestClient, chapter: dict[str, Any], anchor: dict[str, Any]
) -> None:
    body = client.get(f"/api/documents/{chapter['document_id']}/anchors").json()

    assert [one["id"] for one in body["anchors"]] == [anchor["id"]]
    assert body["anchors"][0]["status"] == "ok"


def test_listing_a_missing_document_s_anchors_is_a_404(client: TestClient) -> None:
    response = client.get("/api/documents/doc_nothing/anchors")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "document_not_found"


def test_the_project_list_finds_what_needs_repair(
    client: TestClient, chapter: dict[str, Any], anchor: dict[str, Any]
) -> None:
    project_id = chapter["project_id"]
    assert len(client.get(f"/api/projects/{project_id}/anchors").json()["anchors"]) == 1
    assert client.get(f"/api/projects/{project_id}/anchors?status=stale").json()["anchors"] == []

    client.put(
        f"/api/documents/{chapter['document_id']}/content",
        json={
            "content_json": build_blocks(["The harbour was grey and empty.", *HARBOUR[1:]]),
            "version": chapter["version"],
        },
    )
    stale = client.get(f"/api/projects/{project_id}/anchors?status=stale").json()["anchors"]

    assert [one["id"] for one in stale] == [anchor["id"]]


def test_an_unknown_status_filter_is_a_422(client: TestClient, chapter: dict[str, Any]) -> None:
    """It is a bad request, not a server fault - so it comes back in the envelope, not as a 500."""
    response = client.get(f"/api/projects/{chapter['project_id']}/anchors?status=whatever")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_the_wire_status_vocabulary_is_the_domain_one() -> None:
    """Two spellings of one vocabulary, held together here so neither can drift alone."""
    from typing import get_args

    from archetype.api.schemas import AnchorStatusFilter
    from archetype.manuscript.anchors.status import ALL_STATUSES

    assert set(get_args(AnchorStatusFilter)) == ALL_STATUSES


def test_listing_a_missing_project_s_anchors_is_a_404(client: TestClient) -> None:
    response = client.get("/api/projects/prj_nothing/anchors")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "project_not_found"


# -- the save response (D21) --------------------------------------------------------------------


def test_a_save_carries_back_the_anchors_it_moved(
    client: TestClient, chapter: dict[str, Any], anchor: dict[str, Any]
) -> None:
    """Which is what saves the client a round trip on the request that happens most often."""
    body = client.put(
        f"/api/documents/{chapter['document_id']}/content",
        json={
            "content_json": build_blocks(["A week earlier, nothing happened.", *HARBOUR]),
            "version": chapter["version"],
        },
    ).json()

    assert [one["id"] for one in body["anchors"]] == [anchor["id"]]
    assert body["anchors"][0]["from_pos"] > anchor["from_pos"]


def test_a_save_that_moves_nothing_carries_an_empty_list(
    client: TestClient, chapter: dict[str, Any], anchor: dict[str, Any]
) -> None:
    body = client.put(
        f"/api/documents/{chapter['document_id']}/content",
        json={
            "content_json": build_blocks([*HARBOUR, "The tide turned."]),
            "version": chapter["version"],
        },
    ).json()

    assert body["anchors"] == []


def test_a_save_that_breaks_an_anchor_reports_it_stale_with_its_suggestion(
    client: TestClient, chapter: dict[str, Any], anchor: dict[str, Any]
) -> None:
    body = client.put(
        f"/api/documents/{chapter['document_id']}/content",
        json={
            "content_json": build_blocks(
                ["The harbour was grey and the Kestrel sat low in it.", *HARBOUR[1:]]
            ),
            "version": chapter["version"],
        },
    ).json()

    (moved,) = body["anchors"]
    assert moved["status"] == "stale"
    assert moved["suggestion"]["text"] == "the Kestrel sat low"


# -- re-linking, labelling, removing -------------------------------------------------------------


def test_relinking_repairs_a_stale_anchor(
    client: TestClient, chapter: dict[str, Any], anchor: dict[str, Any]
) -> None:
    saved = client.put(
        f"/api/documents/{chapter['document_id']}/content",
        json={
            "content_json": build_blocks(
                ["The harbour was grey and the Kestrel sat low in it.", *HARBOUR[1:]]
            ),
            "version": chapter["version"],
        },
    ).json()
    from_pos, to_pos = anchor_range(client, chapter["document_id"], "the Kestrel sat low")

    body = client.patch(
        f"/api/anchors/{anchor['id']}",
        json={"from_pos": from_pos, "to_pos": to_pos, "version": saved["version"]},
    )

    assert body.status_code == 200
    assert body.json()["status"] == "ok"
    assert body.json()["quote"] == "the Kestrel sat low"


def test_a_label_can_be_changed_on_its_own(client: TestClient, anchor: dict[str, Any]) -> None:
    body = client.patch(f"/api/anchors/{anchor['id']}", json={"label": "the ship, again"})

    assert body.status_code == 200
    assert body.json()["label"] == "the ship, again"
    assert body.json()["from_pos"] == anchor["from_pos"]


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"from_pos": 2},
        {"from_pos": 2, "to_pos": 6},
        {"to_pos": 6, "version": 2},
    ],
)
def test_half_a_relink_is_refused(
    client: TestClient, anchor: dict[str, Any], body: dict[str, Any]
) -> None:
    """Two of the three is a client that has lost track of which version it is looking at."""
    response = client.patch(f"/api/anchors/{anchor['id']}", json=body)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_patching_a_missing_anchor_is_a_404(client: TestClient) -> None:
    response = client.patch("/api/anchors/anc_nothing", json={"label": "x"})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "anchor_not_found"


def test_deleting_an_anchor(
    client: TestClient, chapter: dict[str, Any], anchor: dict[str, Any]
) -> None:
    assert client.delete(f"/api/anchors/{anchor['id']}").status_code == 204
    assert client.get(f"/api/documents/{chapter['document_id']}/anchors").json()["anchors"] == []
    assert client.delete(f"/api/anchors/{anchor['id']}").status_code == 404


# -- addressing an anchor without naming its project ----------------------------------------------


def test_an_anchor_is_found_in_whichever_project_holds_it(client: TestClient) -> None:
    """The locator answers "which file" for an anchor exactly as it does for a document."""
    make_chapter(client)
    second = make_chapter(client, ["A different manuscript entirely, with its own words."])
    from_pos, to_pos = anchor_range(client, second["document_id"], "different manuscript")
    anchor = client.post(
        f"/api/documents/{second['document_id']}/anchors",
        json={"from_pos": from_pos, "to_pos": to_pos, "version": second["version"]},
    ).json()

    body = client.patch(f"/api/anchors/{anchor['id']}", json={"label": "found it"})

    assert body.status_code == 200
    assert body.json()["project_id"] == second["project_id"]


def test_an_orphaned_anchor_is_reported_orphaned_and_comes_back(
    client: TestClient, chapter: dict[str, Any], anchor: dict[str, Any]
) -> None:
    """The only anchor repair that is not a re-link: restore the chapter it lives in (D22)."""
    from archetype.manuscript.documents import DocumentStore
    from archetype.projects.store import ProjectStore

    store = ProjectStore(client.app.state.settings.projects_dir)
    documents = DocumentStore(store.open(chapter["project_id"]))
    documents.delete(chapter["document_id"])

    orphaned = client.get(f"/api/projects/{chapter['project_id']}/anchors?status=orphaned").json()[
        "anchors"
    ]
    assert [one["id"] for one in orphaned] == [anchor["id"]]

    documents.restore(chapter["document_id"])
    body = client.get(f"/api/documents/{chapter['document_id']}/anchors").json()

    assert body["anchors"][0]["status"] == "ok"
