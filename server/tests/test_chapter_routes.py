"""P2-11 - the chapter-management routes, over the real application.

Reorder, soft delete, restore, and the list of what has been deleted. The rules themselves are
:class:`~archetype.manuscript.documents.DocumentStore`'s and are tested in ``test_chapters.py``;
what these assert is that each route reaches them, that a refusal comes back in the envelope
rather than as a ``500``, and that the four read paths still agree about what is live once HTTP
is in the way.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from .conftest import build_document


@pytest.fixture
def manuscript(client: TestClient) -> dict[str, Any]:
    """A project with three chapters, each holding a sentence."""
    created = client.post("/api/projects", json={"title": "The Long Road"}).json()
    project_id = created["project"]["id"]
    ids = [created["documents"][0]["id"]]
    for title in ("Departure", "The Crossing"):
        ids.append(
            client.post(f"/api/projects/{project_id}/documents", json={"title": title}).json()["id"]
        )
    for index, document_id in enumerate(ids):
        client.put(
            f"/api/documents/{document_id}/content",
            json={
                "content_json": build_document(paragraphs=[f"Chapter {index} was written."]),
                "version": 1,
            },
        )
    return {"project_id": project_id, "ids": ids}


def order_of(client: TestClient, project_id: str) -> list[str]:
    return [
        meta["id"]
        for meta in client.get(f"/api/projects/{project_id}/documents").json()["documents"]
    ]


def anchor_over(client: TestClient, document_id: str, passage: str) -> dict[str, Any]:
    """Anchor ``passage`` through the real route, the way the editor's selection would."""
    from archetype.manuscript.projection import project, text_offset_to_pm_position

    document = client.get(f"/api/documents/{document_id}").json()
    projection = project(document["content_json"])
    text_from = projection.text_plain.index(passage)
    from_pos = text_offset_to_pm_position(projection, text_from)
    to_pos = text_offset_to_pm_position(projection, text_from + len(passage))
    assert from_pos is not None and to_pos is not None
    response = client.post(
        f"/api/documents/{document_id}/anchors",
        json={"from_pos": from_pos, "to_pos": to_pos, "version": document["version"]},
    )
    assert response.status_code == 201, response.text
    return response.json()


# -- reorder --------------------------------------------------------------------------------


def test_reorder_rewrites_the_order(client: TestClient, manuscript: dict[str, Any]) -> None:
    project_id, ids = manuscript["project_id"], manuscript["ids"]
    reversed_ids = list(reversed(ids))

    response = client.put(
        f"/api/projects/{project_id}/documents/order", json={"document_ids": reversed_ids}
    )

    assert response.status_code == 200
    body = response.json()
    assert [meta["id"] for meta in body["documents"]] == reversed_ids
    assert [meta["order_index"] for meta in body["documents"]] == [0, 1, 2]
    assert order_of(client, project_id) == reversed_ids


def test_reorder_does_not_move_any_version(client: TestClient, manuscript: dict[str, Any]) -> None:
    """An order is a property of the project. Bumping a version would refuse an autosave."""
    project_id, ids = manuscript["project_id"], manuscript["ids"]
    before = {
        meta["id"]: meta["version"]
        for meta in client.get(f"/api/projects/{project_id}/documents").json()["documents"]
    }

    client.put(
        f"/api/projects/{project_id}/documents/order", json={"document_ids": list(reversed(ids))}
    )

    after = {
        meta["id"]: meta["version"]
        for meta in client.get(f"/api/projects/{project_id}/documents").json()["documents"]
    }
    assert after == before


@pytest.mark.parametrize(
    "make_body, expected_detail",
    [
        (lambda ids: ids[:2], "missing"),
        (lambda ids: [*ids, "doc_nothing"], "unexpected"),
        (lambda ids: [ids[0], ids[0], ids[1], ids[2]], "duplicated"),
    ],
    ids=["one-missing", "one-extra", "one-duplicated"],
)
def test_an_incomplete_order_is_refused_in_the_envelope(
    client: TestClient,
    manuscript: dict[str, Any],
    make_body,
    expected_detail: str,
) -> None:
    """The completeness check is the concurrency guard, so its refusal has to be legible."""
    project_id, ids = manuscript["project_id"], manuscript["ids"]

    response = client.put(
        f"/api/projects/{project_id}/documents/order", json={"document_ids": make_body(ids)}
    )

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "reorder_mismatch"
    assert error["detail"][expected_detail]
    assert order_of(client, project_id) == ids


def test_reorder_of_an_unknown_project_is_a_404(client: TestClient) -> None:
    response = client.put(
        "/api/projects/prj_nothing/documents/order", json={"document_ids": ["doc_a"]}
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "project_not_found"


def test_an_empty_order_does_not_reach_the_store(
    client: TestClient, manuscript: dict[str, Any]
) -> None:
    """A project always has at least one chapter, so an empty list is a client bug, not a race."""
    response = client.put(
        f"/api/projects/{manuscript['project_id']}/documents/order", json={"document_ids": []}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


# -- delete and restore ---------------------------------------------------------------------


def test_delete_removes_the_chapter_from_every_list(
    client: TestClient, manuscript: dict[str, Any]
) -> None:
    project_id, ids = manuscript["project_id"], manuscript["ids"]

    response = client.delete(f"/api/documents/{ids[1]}")

    assert response.status_code == 200
    assert response.json()["deleted_at"] is not None
    assert order_of(client, project_id) == [ids[0], ids[2]]

    outline = client.get(f"/api/projects/{project_id}/outline").json()
    assert [chapter["document_id"] for chapter in outline["chapters"]] == [ids[0], ids[2]]

    summary = client.get(f"/api/projects/{project_id}").json()["project"]
    assert summary["chapter_count"] == 2

    listed = client.get("/api/projects").json()["projects"]
    assert [project["chapter_count"] for project in listed if project["id"] == project_id] == [2]


def test_a_deleted_chapter_cannot_be_opened_but_its_text_survives(
    client: TestClient, manuscript: dict[str, Any]
) -> None:
    """Soft, not gone - and out of the editor's reach while it is away.

    The document route refuses a deleted chapter, so nothing in the app can open a ghost and
    write to it. What "soft" means is proved by the restore: the text comes back byte for byte.
    """
    document_id = manuscript["ids"][1]
    before = client.get(f"/api/documents/{document_id}").json()

    client.delete(f"/api/documents/{document_id}")
    assert client.get(f"/api/documents/{document_id}").status_code == 404
    assert (
        client.put(
            f"/api/documents/{document_id}/content",
            json={
                "content_json": build_document(paragraphs=["Written to a ghost."]),
                "version": before["version"],
            },
        ).status_code
        == 404
    )

    client.post(f"/api/documents/{document_id}/restore")
    after = client.get(f"/api/documents/{document_id}").json()
    assert after["content_json"] == before["content_json"]
    assert after["version"] == before["version"]


def test_deleted_chapters_are_listed_for_restoring(
    client: TestClient, manuscript: dict[str, Any]
) -> None:
    project_id, ids = manuscript["project_id"], manuscript["ids"]
    assert client.get(f"/api/projects/{project_id}/documents/deleted").json()["documents"] == []

    client.delete(f"/api/documents/{ids[1]}")

    deleted = client.get(f"/api/projects/{project_id}/documents/deleted").json()["documents"]
    assert [meta["id"] for meta in deleted] == [ids[1]]
    assert deleted[0]["deleted_at"] is not None
    assert deleted[0]["word_count"] > 0


def test_restore_brings_the_chapter_back_at_the_end(
    client: TestClient, manuscript: dict[str, Any]
) -> None:
    project_id, ids = manuscript["project_id"], manuscript["ids"]
    client.delete(f"/api/documents/{ids[0]}")

    response = client.post(f"/api/documents/{ids[0]}/restore")

    assert response.status_code == 200
    assert response.json()["deleted_at"] is None
    assert order_of(client, project_id) == [ids[1], ids[2], ids[0]]
    assert client.get(f"/api/projects/{project_id}/documents/deleted").json()["documents"] == []


def test_deleting_a_chapter_orphans_its_anchors_and_restoring_returns_them(
    client: TestClient, manuscript: dict[str, Any]
) -> None:
    """The round trip the *Marks* tab offers: restore the chapter, not the anchor (D22)."""
    project_id, ids = manuscript["project_id"], manuscript["ids"]
    anchor_over(client, ids[1], "was written")

    client.delete(f"/api/documents/{ids[1]}")
    orphaned = client.get(f"/api/projects/{project_id}/anchors?status=orphaned").json()["anchors"]
    assert [anchor["document_id"] for anchor in orphaned] == [ids[1]]

    client.post(f"/api/documents/{ids[1]}/restore")
    after = client.get(f"/api/projects/{project_id}/anchors").json()["anchors"]
    assert [anchor["status"] for anchor in after] == ["ok"]


def test_deleting_the_same_chapter_twice_is_a_404(
    client: TestClient, manuscript: dict[str, Any]
) -> None:
    """The second delete has no live chapter to take a pre-delete snapshot of."""
    document_id = manuscript["ids"][1]
    client.delete(f"/api/documents/{document_id}")

    response = client.delete(f"/api/documents/{document_id}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "document_not_found"


def test_restoring_a_live_chapter_is_a_no_op(
    client: TestClient, manuscript: dict[str, Any]
) -> None:
    project_id, ids = manuscript["project_id"], manuscript["ids"]

    response = client.post(f"/api/documents/{ids[0]}/restore")

    assert response.status_code == 200
    assert order_of(client, project_id) == ids


def test_delete_and_restore_of_an_unknown_document_are_404s(client: TestClient) -> None:
    assert client.delete("/api/documents/doc_nothing").status_code == 404
    assert client.post("/api/documents/doc_nothing/restore").status_code == 404
