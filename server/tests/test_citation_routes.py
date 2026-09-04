"""P3-10 - the citation routes and *Add to bible*, over the real application.

This is where the bible meets the manuscript, so these tests drive the **whole** path: a real
chapter, a real save, a real anchor minted by ``AnchorStore``, and the entry that cites it. The
rules are ``CitationStore``'s and are tested in ``test_citations.py``; what these assert is that
the routes reach them, that a refusal writes nothing at all, and that a citation reports the
anchor's status rather than deriving a second one.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from archetype.bible.schema import EntryKind

from .conftest import build_blocks, required_attributes
from .test_anchor_routes import anchor_range, make_chapter
from .test_entry_routes import make_entry

HARBOUR = [
    "The harbour was grey and the Kestrel rode low in it.",
    "Marlow watched from the quay, saying nothing at all.",
    "He did not look back.",
]


@pytest.fixture
def chapter(client: TestClient) -> dict[str, Any]:
    return make_chapter(client, HARBOUR)


def add_to_bible(
    client: TestClient,
    chapter: dict[str, Any],
    passage: str,
    *,
    name: str = "Marlow",
    kind: str = EntryKind.CHARACTER,
    version: int | None = None,
    **rest: Any,
):
    from_pos, to_pos = anchor_range(client, chapter["document_id"], passage)
    return client.post(
        f"/api/documents/{chapter['document_id']}/entries",
        json={
            "from_pos": from_pos,
            "to_pos": to_pos,
            "version": chapter["version"] if version is None else version,
            "kind": kind,
            "name": name,
            **rest,
        },
    )


# -- Add to bible (P3-7, ruling 8) ----------------------------------------------------------------


def test_creating_from_a_selection_makes_all_three_in_one_call(
    client: TestClient, chapter: dict[str, Any]
) -> None:
    """The interaction the whole product is arranged around, in its manual form."""
    response = add_to_bible(client, chapter, "Marlow watched from the quay", label="on the quay")

    assert response.status_code == 201, response.text
    made = response.json()
    assert made["entry"]["name"] == "Marlow"
    assert made["role"] == "source"
    # The client sent a range and a version, never a quote; the server read the words.
    assert made["anchor"]["quote"] == "Marlow watched from the quay"
    assert made["anchor"]["status"] == "ok"
    assert made["anchor"]["label"] == "on the quay"

    detail = client.get(f"/api/entries/{made['entry']['id']}").json()
    assert [item["anchor"]["id"] for item in detail["citations"]] == [made["anchor"]["id"]]
    assert detail["citations"][0]["document_id"] == chapter["document_id"]


def test_a_stale_document_version_leaves_no_anchor_no_entry_and_no_citation(
    client: TestClient, chapter: dict[str, Any]
) -> None:
    """One transaction over three tables (``B1``). A refusal writes nothing at all."""
    response = add_to_bible(client, chapter, "Marlow watched", version=1)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "version_conflict"
    assert client.get(f"/api/projects/{chapter['project_id']}/entries").json()["entries"] == []
    assert client.get(f"/api/projects/{chapter['project_id']}/anchors").json()["anchors"] == []


def test_an_unknown_kind_leaves_no_anchor_behind(
    client: TestClient, chapter: dict[str, Any]
) -> None:
    """The half that would be easy to get wrong: the anchor is minted *first*."""
    response = add_to_bible(client, chapter, "Marlow watched", kind="dragon")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_attributes"
    assert client.get(f"/api/projects/{chapter['project_id']}/anchors").json()["anchors"] == []


def test_a_range_the_resolver_refuses_writes_nothing(
    client: TestClient, chapter: dict[str, Any]
) -> None:
    response = client.post(
        f"/api/documents/{chapter['document_id']}/entries",
        json={
            "from_pos": 4,
            "to_pos": 4,
            "version": chapter["version"],
            "kind": "character",
            "name": "Marlow",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_anchor_range"
    assert client.get(f"/api/projects/{chapter['project_id']}/entries").json()["entries"] == []


def test_adding_to_the_bible_from_a_missing_document_is_a_404(client: TestClient) -> None:
    response = client.post(
        "/api/documents/doc_nothing/entries",
        json={"from_pos": 1, "to_pos": 5, "version": 1, "kind": "character", "name": "Marlow"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "document_not_found"


# -- citing an anchor that already exists ------------------------------------------------------


def test_an_existing_anchor_can_be_cited_in_a_role_and_uncited(
    client: TestClient, chapter: dict[str, Any]
) -> None:
    from_pos, to_pos = anchor_range(client, chapter["document_id"], "the Kestrel rode low")
    anchor = client.post(
        f"/api/documents/{chapter['document_id']}/anchors",
        json={"from_pos": from_pos, "to_pos": to_pos, "version": chapter["version"]},
    ).json()
    entry = make_entry(client, chapter["project_id"], "The Kestrel", kind=EntryKind.ITEM)

    cited = client.post(
        f"/api/entries/{entry['id']}/citations",
        json={"anchor_id": anchor["id"], "role": "mention"},
    )
    assert cited.status_code == 201, cited.text
    assert cited.json()["role"] == "mention"
    assert cited.json()["anchor"]["quote"] == "the Kestrel rode low"

    removed = client.delete(f"/api/entries/{entry['id']}/citations/{anchor['id']}")
    assert removed.status_code == 200
    assert removed.json() == {"removed": 1}
    assert client.get(f"/api/entries/{entry['id']}").json()["citations"] == []
    # The anchor stays: it is a fact about the manuscript, and Marks is where one is removed.
    assert len(client.get(f"/api/projects/{chapter['project_id']}/anchors").json()["anchors"]) == 1


def test_citing_twice_in_one_role_is_a_no_op_rather_than_an_error(
    client: TestClient, chapter: dict[str, Any]
) -> None:
    made = add_to_bible(client, chapter, "Marlow watched").json()

    again = client.post(
        f"/api/entries/{made['entry']['id']}/citations",
        json={"anchor_id": made["anchor"]["id"], "role": "source"},
    )

    assert again.status_code == 201
    assert len(client.get(f"/api/entries/{made['entry']['id']}").json()["citations"]) == 1


def test_removing_a_citation_that_is_not_there_returns_zero(
    client: TestClient, chapter: dict[str, Any]
) -> None:
    made = add_to_bible(client, chapter, "Marlow watched").json()

    removed = client.delete(
        f"/api/entries/{made['entry']['id']}/citations/{made['anchor']['id']}",
        params={"role": "payoff"},
    )

    assert removed.json() == {"removed": 0}


def test_an_unknown_role_is_refused_by_the_route(
    client: TestClient, chapter: dict[str, Any]
) -> None:
    made = add_to_bible(client, chapter, "Marlow watched").json()

    response = client.post(
        f"/api/entries/{made['entry']['id']}/citations",
        json={"anchor_id": made["anchor"]["id"], "role": "epigraph"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_citing_an_anchor_from_another_project_is_a_404(client: TestClient) -> None:
    here = make_chapter(client, HARBOUR)
    there = make_chapter(client, ["A different book entirely."])
    from_pos, to_pos = anchor_range(client, there["document_id"], "A different book")
    elsewhere = client.post(
        f"/api/documents/{there['document_id']}/anchors",
        json={"from_pos": from_pos, "to_pos": to_pos, "version": there["version"]},
    ).json()
    entry = make_entry(client, here["project_id"], "Marlow")

    response = client.post(
        f"/api/entries/{entry['id']}/citations", json={"anchor_id": elsewhere["id"]}
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "anchor_not_found"


# -- the reverse view, and the status a citation reports ----------------------------------------


def test_marks_can_ask_which_entries_speak_for_an_anchor(
    client: TestClient, chapter: dict[str, Any]
) -> None:
    made = add_to_bible(client, chapter, "Marlow watched").json()

    body = client.get(f"/api/anchors/{made['anchor']['id']}/entries").json()

    assert [item["entry_id"] for item in body["entries"]] == [made["entry"]["id"]]
    assert body["entries"][0]["name"] == "Marlow"
    assert body["entries"][0]["role"] == "source"


def test_a_deleted_entry_stops_speaking_for_its_anchor(
    client: TestClient, chapter: dict[str, Any]
) -> None:
    made = add_to_bible(client, chapter, "Marlow watched").json()
    client.delete(f"/api/entries/{made['entry']['id']}")

    body = client.get(f"/api/anchors/{made['anchor']['id']}/entries").json()

    assert body["entries"] == []


def test_rewriting_the_passage_makes_the_citation_read_stale(
    client: TestClient, chapter: dict[str, Any]
) -> None:
    """Where ``stale`` stops being an abstraction (exit criterion 5)."""
    made = add_to_bible(client, chapter, "Marlow watched from the quay").json()
    rewritten = list(HARBOUR)
    rewritten[1] = "Nobody was on the quay at all, and the rain had started."
    client.put(
        f"/api/documents/{chapter['document_id']}/content",
        json={"content_json": build_blocks(rewritten), "version": chapter["version"]},
    )

    citations = client.get(f"/api/entries/{made['entry']['id']}").json()["citations"]

    assert [item["anchor"]["status"] for item in citations] == ["stale"]
    # And the entry itself is untouched: a citation is a reason to believe, not the belief.
    assert client.get(f"/api/entries/{made['entry']['id']}").json()["entry"]["revision"] == 1


def test_deleting_the_chapter_makes_the_citation_read_orphaned(
    client: TestClient, chapter: dict[str, Any]
) -> None:
    """Derived from ``deleted_at`` in the one place D22 put it - never a second derivation here."""
    made = add_to_bible(client, chapter, "Marlow watched").json()
    client.post(f"/api/projects/{chapter['project_id']}/documents", json={"title": "Two"})
    client.delete(f"/api/documents/{chapter['document_id']}")

    orphaned = client.get(f"/api/entries/{made['entry']['id']}").json()["citations"]
    assert [item["anchor"]["status"] for item in orphaned] == ["orphaned"]

    client.post(f"/api/documents/{chapter['document_id']}/restore")
    back = client.get(f"/api/entries/{made['entry']['id']}").json()["citations"]
    assert [item["anchor"]["status"] for item in back] == ["ok"]


def test_deleting_an_anchor_removes_the_citation_and_leaves_the_entry(
    client: TestClient, chapter: dict[str, Any]
) -> None:
    made = add_to_bible(client, chapter, "Marlow watched").json()

    assert client.delete(f"/api/anchors/{made['anchor']['id']}").status_code == 204

    detail = client.get(f"/api/entries/{made['entry']['id']}").json()
    assert detail["entry"]["name"] == "Marlow"
    assert detail["citations"] == []


# -- narrative position (derived, never stored) -------------------------------------------------


def test_narrative_position_follows_a_chapter_reorder(
    client: TestClient, chapter: dict[str, Any]
) -> None:
    made = add_to_bible(client, chapter, "Marlow watched").json()
    second = client.post(
        f"/api/projects/{chapter['project_id']}/documents", json={"title": "Two"}
    ).json()

    before = client.get(f"/api/entries/{made['entry']['id']}").json()["narrative_position"]
    assert before["order_index"] == 0
    assert before["document_id"] == chapter["document_id"]

    client.put(
        f"/api/projects/{chapter['project_id']}/documents/order",
        json={"document_ids": [second["id"], chapter["document_id"]]},
    )

    after = client.get(f"/api/entries/{made['entry']['id']}").json()["narrative_position"]
    assert after["order_index"] == 1


def test_an_entry_with_no_source_anchor_has_no_position(
    client: TestClient, chapter: dict[str, Any]
) -> None:
    entry = make_entry(
        client,
        chapter["project_id"],
        "A rumour",
        kind=EntryKind.FACT,
        attributes=required_attributes(EntryKind.FACT),
    )

    assert client.get(f"/api/entries/{entry['id']}").json()["narrative_position"] is None
