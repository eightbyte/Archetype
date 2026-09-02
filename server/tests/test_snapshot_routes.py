"""P2-12 - the snapshot routes, over the real application.

Capture, history, preview, and restore. The rules are
:class:`~archetype.manuscript.snapshots.SnapshotStore`'s and are tested in ``test_snapshots.py``;
these assert that each route reaches them, that a bare snapshot id finds its file, and that the
two things a client is *not* allowed to do - ask for a ``pre-*`` reason, restore against a stale
version - come back in the envelope.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from archetype.manuscript.snapshots import SnapshotReason

from .conftest import build_document


@pytest.fixture
def chapter(client: TestClient) -> dict[str, Any]:
    """A project with one chapter that has been written to twice."""
    created = client.post("/api/projects", json={"title": "The Long Road"}).json()
    document_id = created["documents"][0]["id"]
    client.put(
        f"/api/documents/{document_id}/content",
        json={"content_json": build_document(paragraphs=["The harbour was grey."]), "version": 1},
    )
    saved = client.put(
        f"/api/documents/{document_id}/content",
        json={
            "content_json": build_document(paragraphs=["The harbour was grey.", "He waited."]),
            "version": 2,
        },
    ).json()
    return {
        "project_id": created["project"]["id"],
        "document_id": document_id,
        "version": saved["version"],
    }


def history(client: TestClient, document_id: str) -> list[dict[str, Any]]:
    response = client.get(f"/api/documents/{document_id}/snapshots")
    assert response.status_code == 200, response.text
    return response.json()["snapshots"]


# -- capture --------------------------------------------------------------------------------


def test_a_manual_mark_carries_its_label(client: TestClient, chapter: dict[str, Any]) -> None:
    response = client.post(
        f"/api/documents/{chapter['document_id']}/snapshots",
        json={"reason": "manual", "label": "before the rewrite"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["captured"] is True
    assert body["snapshot"]["reason"] == "manual"
    assert body["snapshot"]["label"] == "before the rewrite"
    assert body["snapshot"]["version"] == chapter["version"]
    assert body["snapshot"]["word_count"] > 0
    assert body["snapshot"]["size_bytes"] > 0


def test_a_handover_on_an_unchanged_chapter_writes_nothing_and_says_so(
    client: TestClient, chapter: dict[str, Any]
) -> None:
    """Dedup is the ordinary answer, not a failure (D23)."""
    document_id = chapter["document_id"]
    first = client.post(f"/api/documents/{document_id}/snapshots", json={"reason": "handover"})
    assert first.json()["captured"] is True

    second = client.post(f"/api/documents/{document_id}/snapshots", json={"reason": "handover"})

    assert second.status_code == 200
    assert second.json() == {"captured": False, "snapshot": None}
    assert len(history(client, document_id)) == 1


def test_a_capture_with_no_body_is_a_handover(client: TestClient, chapter: dict[str, Any]) -> None:
    """The client's commonest call is the one it makes on every chapter switch."""
    response = client.post(f"/api/documents/{chapter['document_id']}/snapshots")

    assert response.status_code == 200
    assert response.json()["snapshot"]["reason"] == SnapshotReason.HANDOVER


@pytest.mark.parametrize("reason", sorted(SnapshotReason.ALL - {"handover", "manual"}))
def test_a_client_may_not_ask_for_a_reason_the_server_owns(
    client: TestClient, chapter: dict[str, Any], reason: str
) -> None:
    """A ``pre-*`` snapshot is written beside the operation it protects, or it is a lie."""
    response = client.post(
        f"/api/documents/{chapter['document_id']}/snapshots", json={"reason": reason}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert history(client, chapter["document_id"]) == []


def test_the_wire_vocabulary_is_a_subset_of_the_stores() -> None:
    """Two spellings of one list drift; a test is what keeps them the same list (B10)."""
    from typing import get_args

    from archetype.api.schemas import SnapshotReasonIn

    assert set(get_args(SnapshotReasonIn)) < SnapshotReason.ALL


def test_capturing_for_an_unknown_document_is_a_404(client: TestClient) -> None:
    assert client.post("/api/documents/doc_nothing/snapshots").status_code == 404


def test_capturing_for_a_deleted_chapter_is_a_404(
    client: TestClient, chapter: dict[str, Any]
) -> None:
    """Nothing writes to a chapter that is out of every list, snapshots included."""
    client.delete(f"/api/documents/{chapter['document_id']}")

    response = client.post(f"/api/documents/{chapter['document_id']}/snapshots")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "document_not_found"


# -- history and preview --------------------------------------------------------------------


def test_the_history_is_newest_first_and_carries_no_content(
    client: TestClient, chapter: dict[str, Any]
) -> None:
    document_id = chapter["document_id"]
    client.post(
        f"/api/documents/{document_id}/snapshots", json={"reason": "manual", "label": "one"}
    )
    client.put(
        f"/api/documents/{document_id}/content",
        json={"content_json": build_document(paragraphs=["Rewritten."]), "version": 3},
    )
    client.post(
        f"/api/documents/{document_id}/snapshots", json={"reason": "manual", "label": "two"}
    )

    entries = history(client, document_id)

    assert [entry["label"] for entry in entries] == ["two", "one"]
    assert all("content_json" not in entry for entry in entries)


def test_the_history_of_a_deleted_chapter_is_readable(
    client: TestClient, chapter: dict[str, Any]
) -> None:
    """It is exactly what somebody deciding whether to restore the chapter wants."""
    document_id = chapter["document_id"]
    client.delete(f"/api/documents/{document_id}")

    entries = history(client, document_id)

    assert [entry["reason"] for entry in entries] == [SnapshotReason.PRE_DELETE]


def test_one_snapshot_comes_back_with_its_content(
    client: TestClient, chapter: dict[str, Any]
) -> None:
    marked = client.post(
        f"/api/documents/{chapter['document_id']}/snapshots", json={"reason": "manual"}
    ).json()["snapshot"]

    response = client.get(f"/api/snapshots/{marked['id']}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == marked["id"]
    assert (
        body["content_json"]
        == client.get(f"/api/documents/{chapter['document_id']}").json()["content_json"]
    )


def test_an_unknown_snapshot_is_a_404_in_the_envelope(client: TestClient) -> None:
    response = client.get("/api/snapshots/snp_nothing")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "snapshot_not_found"


def test_a_snapshot_id_finds_its_project_among_several(client: TestClient) -> None:
    """The locator answers "which file" for a snapshot the way it does for a document."""
    other = client.post("/api/projects", json={"title": "Another Manuscript"}).json()
    client.put(
        f"/api/documents/{other['documents'][0]['id']}/content",
        json={"content_json": build_document(paragraphs=["Elsewhere."]), "version": 1},
    )
    marked = client.post(
        f"/api/documents/{other['documents'][0]['id']}/snapshots", json={"reason": "manual"}
    ).json()["snapshot"]

    body = client.get(f"/api/snapshots/{marked['id']}").json()

    assert body["project_id"] == other["project"]["id"]


# -- restore --------------------------------------------------------------------------------


def test_restore_writes_the_snapshot_back_as_an_ordinary_save(
    client: TestClient, chapter: dict[str, Any]
) -> None:
    document_id, version = chapter["document_id"], chapter["version"]
    marked = client.post(
        f"/api/documents/{document_id}/snapshots", json={"reason": "manual", "label": "keep"}
    ).json()["snapshot"]
    before = client.get(f"/api/documents/{document_id}").json()["content_json"]
    client.put(
        f"/api/documents/{document_id}/content",
        json={"content_json": build_document(paragraphs=["All of it, gone."]), "version": version},
    )

    response = client.post(f"/api/snapshots/{marked['id']}/restore", json={"version": version + 1})

    assert response.status_code == 200
    result = response.json()
    assert result["version"] == version + 2
    assert result["document_id"] == document_id
    assert result["anchors"] == []
    document = client.get(f"/api/documents/{document_id}").json()
    assert document["content_json"] == before
    assert document["word_count"] == result["word_count"]


def test_restore_leaves_the_pre_restore_snapshot_in_the_history(
    client: TestClient, chapter: dict[str, Any]
) -> None:
    document_id, version = chapter["document_id"], chapter["version"]
    marked = client.post(
        f"/api/documents/{document_id}/snapshots", json={"reason": "manual"}
    ).json()["snapshot"]

    client.post(f"/api/snapshots/{marked['id']}/restore", json={"version": version})

    assert history(client, document_id)[0]["reason"] == SnapshotReason.PRE_RESTORE


def test_a_stale_restore_is_a_409_and_writes_nothing(
    client: TestClient, chapter: dict[str, Any]
) -> None:
    """Including the snapshot that was about to protect it (A2)."""
    document_id, version = chapter["document_id"], chapter["version"]
    marked = client.post(
        f"/api/documents/{document_id}/snapshots", json={"reason": "manual"}
    ).json()["snapshot"]
    before = client.get(f"/api/documents/{document_id}").json()["content_json"]

    response = client.post(f"/api/snapshots/{marked['id']}/restore", json={"version": version - 1})

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "version_conflict"
    assert error["detail"]["current_version"] == version
    assert [entry["reason"] for entry in history(client, document_id)] == ["manual"]
    assert client.get(f"/api/documents/{document_id}").json()["content_json"] == before


def test_restoring_an_unknown_snapshot_is_a_404(client: TestClient) -> None:
    response = client.post("/api/snapshots/snp_nothing/restore", json={"version": 1})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "snapshot_not_found"


def test_a_restore_re_resolves_the_anchors_the_write_moved(
    client: TestClient, chapter: dict[str, Any]
) -> None:
    """A restore is a write, so D21 applies to it exactly as it does to a keystroke."""
    from archetype.manuscript.projection import project, text_offset_to_pm_position

    document_id, version = chapter["document_id"], chapter["version"]
    document = client.get(f"/api/documents/{document_id}").json()
    projection = project(document["content_json"])
    text_from = projection.text_plain.index("harbour was grey")
    from_pos = text_offset_to_pm_position(projection, text_from)
    to_pos = text_offset_to_pm_position(projection, text_from + len("harbour was grey"))
    client.post(
        f"/api/documents/{document_id}/anchors",
        json={"from_pos": from_pos, "to_pos": to_pos, "version": version},
    )
    marked = client.post(
        f"/api/documents/{document_id}/snapshots", json={"reason": "manual"}
    ).json()["snapshot"]

    # Write the anchored passage away, then restore the mark that still has it.
    broken = client.put(
        f"/api/documents/{document_id}/content",
        json={
            "content_json": build_document(paragraphs=["Nothing of it left."]),
            "version": version,
        },
    ).json()
    assert [anchor["status"] for anchor in broken["anchors"]] == ["stale"]

    restored = client.post(
        f"/api/snapshots/{marked['id']}/restore", json={"version": version + 1}
    ).json()

    assert [anchor["status"] for anchor in restored["anchors"]] == ["ok"]
