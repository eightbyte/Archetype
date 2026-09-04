"""P3-10 - the link routes and the story-time route, over the real application.

``LinkStore``'s rules are tested in ``test_links.py`` and the ordering module's in
``test_storytime.py``; what these assert is that each route reaches them, that a refusal arrives
in the envelope, and that the story-time route's answer is **the pure module's** for the same data
rather than a second implementation of it.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from archetype.bible.schema import RELATIONS, EntryKind
from archetype.bible.storytime import ContradictionKind, order_events, story_event

from .test_entry_routes import make_entry, make_project


@pytest.fixture
def project_id(client: TestClient) -> str:
    return make_project(client)


@pytest.fixture
def cast(client: TestClient, project_id: str) -> dict[str, str]:
    """One entry of each kind the relations below join."""
    return {
        "marlow": make_entry(client, project_id, "Marlow")["id"],
        "kurtz": make_entry(client, project_id, "Kurtz")["id"],
        "company": make_entry(client, project_id, "The Company", kind=EntryKind.FACTION)["id"],
        "quay": make_entry(client, project_id, "The Quay", kind=EntryKind.PLACE)["id"],
    }


def create_link(
    client: TestClient, project_id: str, from_entry: str, relation: str, to_entry: str, **rest: Any
):
    return client.post(
        f"/api/projects/{project_id}/links",
        json={
            "from_entry": from_entry,
            "relation": relation,
            "to_entry": to_entry,
            **rest,
        },
    )


# -- creating ------------------------------------------------------------------------------------


def test_creating_a_link_returns_one_row(
    client: TestClient, project_id: str, cast: dict[str, str]
) -> None:
    response = create_link(
        client, project_id, cast["marlow"], "member_of", cast["company"], since="the first voyage"
    )

    assert response.status_code == 201, response.text
    link = response.json()
    assert link["from_entry"] == cast["marlow"]
    assert link["to_entry"] == cast["company"]
    assert link["relation"] == "member_of"
    assert link["since"] == "the first voyage"
    assert link["until"] is None
    assert link["deleted_at"] is None


def test_a_relation_is_refused_on_the_side_it_is_offered_from(
    client: TestClient, project_id: str, cast: dict[str, str]
) -> None:
    """Faction to character is a different statement, and is never silently reversed."""
    response = create_link(client, project_id, cast["company"], "member_of", cast["marlow"])

    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "invalid_attributes"
    assert client.get(f"/api/projects/{project_id}/links").json()["links"] == []


def test_a_relation_the_vocabulary_does_not_allow_for_those_kinds_is_refused(
    client: TestClient, project_id: str, cast: dict[str, str]
) -> None:
    response = create_link(client, project_id, cast["quay"], "knows", cast["marlow"])

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_attributes"


def test_an_unknown_relation_is_refused(
    client: TestClient, project_id: str, cast: dict[str, str]
) -> None:
    response = create_link(client, project_id, cast["marlow"], "haunts", cast["quay"])

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_attributes"


def test_an_endpoint_that_does_not_exist_is_a_404(
    client: TestClient, project_id: str, cast: dict[str, str]
) -> None:
    response = create_link(client, project_id, cast["marlow"], "knows", "ent_nothing")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "entry_not_found"


def test_a_duplicate_link_is_a_409_that_names_the_one_that_already_says_it(
    client: TestClient, project_id: str, cast: dict[str, str]
) -> None:
    first = create_link(client, project_id, cast["marlow"], "knows", cast["kurtz"]).json()

    response = create_link(client, project_id, cast["marlow"], "knows", cast["kurtz"])

    assert response.status_code == 409
    body = response.json()["error"]
    assert body["code"] == "duplicate_link"
    assert body["detail"] == {"link_id": first["id"]}


# -- reading -------------------------------------------------------------------------------------


def test_both_directions_come_back_in_one_answer_each_labelled_from_its_end(
    client: TestClient, project_id: str, cast: dict[str, str]
) -> None:
    create_link(client, project_id, cast["marlow"], "member_of", cast["company"])

    from_character = client.get(f"/api/entries/{cast['marlow']}/links").json()["links"]
    from_faction = client.get(f"/api/entries/{cast['company']}/links").json()["links"]

    assert [view["end"] for view in from_character] == ["from"]
    assert from_character[0]["other_id"] == cast["company"]
    assert [view["end"] for view in from_faction] == ["to"]
    assert from_faction[0]["other_id"] == cast["marlow"]
    assert from_character[0]["label"] != from_faction[0]["label"]


def test_a_symmetric_link_appears_once_from_each_side_and_never_twice_from_either(
    client: TestClient, project_id: str, cast: dict[str, str]
) -> None:
    """One row, always (ruling 7). Two would be two rows that can disagree."""
    create_link(client, project_id, cast["marlow"], "knows", cast["kurtz"])

    assert len(client.get(f"/api/entries/{cast['marlow']}/links").json()["links"]) == 1
    assert len(client.get(f"/api/entries/{cast['kurtz']}/links").json()["links"]) == 1
    assert len(client.get(f"/api/projects/{project_id}/links").json()["links"]) == 1


def test_the_project_list_filters_by_relation_and_refuses_an_unknown_one(
    client: TestClient, project_id: str, cast: dict[str, str]
) -> None:
    create_link(client, project_id, cast["marlow"], "knows", cast["kurtz"])
    create_link(client, project_id, cast["marlow"], "member_of", cast["company"])

    filtered = client.get(f"/api/projects/{project_id}/links", params={"relation": "knows"}).json()
    assert [link["relation"] for link in filtered["links"]] == ["knows"]

    refused = client.get(f"/api/projects/{project_id}/links", params={"relation": "haunts"})
    assert refused.status_code == 422


def test_a_deleted_endpoint_hides_the_link_from_every_read_path(
    client: TestClient, project_id: str, cast: dict[str, str]
) -> None:
    """The three-way predicate, over the wire (ruling 9). Nothing was written to the link."""
    link = create_link(client, project_id, cast["marlow"], "knows", cast["kurtz"]).json()
    client.delete(f"/api/entries/{cast['kurtz']}")

    assert client.get(f"/api/projects/{project_id}/links").json()["links"] == []
    assert client.get(f"/api/entries/{cast['marlow']}/links").json()["links"] == []
    assert client.get(f"/api/entries/{cast['marlow']}").json()["link_count"] == 0

    client.post(f"/api/entries/{cast['kurtz']}/restore")
    back = client.get(f"/api/projects/{project_id}/links").json()["links"]
    assert [item["id"] for item in back] == [link["id"]]


def test_an_entrys_links_are_an_empty_list_rather_than_a_404_when_it_has_none(
    client: TestClient, cast: dict[str, str]
) -> None:
    assert client.get(f"/api/entries/{cast['marlow']}/links").json()["links"] == []


# -- editing, deleting, restoring ------------------------------------------------------------------


def test_bounds_and_attributes_are_editable_and_the_endpoints_are_not(
    client: TestClient, project_id: str, cast: dict[str, str]
) -> None:
    link = create_link(client, project_id, cast["marlow"], "knows", cast["kurtz"]).json()

    patched = client.patch(f"/api/links/{link['id']}", json={"since": "the river", "until": None})
    assert patched.status_code == 200, patched.text
    assert patched.json()["since"] == "the river"

    refused = client.patch(f"/api/links/{link['id']}", json={"to_entry": cast["company"]})
    assert refused.status_code == 422
    assert (
        client.get(f"/api/projects/{project_id}/links").json()["links"][0]["to_entry"]
        == (cast["kurtz"])
    )


def test_a_bound_is_cleared_by_sending_null_and_kept_by_saying_nothing(
    client: TestClient, project_id: str, cast: dict[str, str]
) -> None:
    link = create_link(
        client, project_id, cast["marlow"], "knows", cast["kurtz"], since="the river"
    ).json()

    kept = client.patch(f"/api/links/{link['id']}", json={"until": "the fog"}).json()
    assert kept["since"] == "the river"

    cleared = client.patch(f"/api/links/{link['id']}", json={"since": None}).json()
    assert cleared["since"] is None
    assert cleared["until"] == "the fog"


def test_a_patch_that_resolves_to_no_change_is_refused(
    client: TestClient, project_id: str, cast: dict[str, str]
) -> None:
    """Including one that presents only ``attributes: null``, which is not "clear them"."""
    link = create_link(client, project_id, cast["marlow"], "knows", cast["kurtz"]).json()

    assert client.patch(f"/api/links/{link['id']}", json={}).status_code == 422
    assert client.patch(f"/api/links/{link['id']}", json={"attributes": None}).status_code == 422


def test_deleting_and_restoring_a_link_leaves_both_entries_alone(
    client: TestClient, project_id: str, cast: dict[str, str]
) -> None:
    link = create_link(client, project_id, cast["marlow"], "knows", cast["kurtz"]).json()

    deleted = client.delete(f"/api/links/{link['id']}")
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted_at"] is not None
    assert client.get(f"/api/projects/{project_id}/links").json()["links"] == []
    assert client.get(f"/api/entries/{cast['marlow']}").json()["entry"]["deleted_at"] is None

    restored = client.post(f"/api/links/{link['id']}/restore")
    assert restored.status_code == 200
    assert restored.json()["deleted_at"] is None


def test_restoring_a_link_that_would_duplicate_a_live_one_is_a_409(
    client: TestClient, project_id: str, cast: dict[str, str]
) -> None:
    """Delete it, type it again, undo the delete: two identical rows would double-count."""
    first = create_link(client, project_id, cast["marlow"], "knows", cast["kurtz"]).json()
    client.delete(f"/api/links/{first['id']}")
    create_link(client, project_id, cast["marlow"], "knows", cast["kurtz"])

    response = client.post(f"/api/links/{first['id']}/restore")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "duplicate_link"


def test_a_missing_link_is_a_404_carrying_the_envelope(client: TestClient) -> None:
    response = client.delete("/api/links/lnk_nothing")

    assert response.status_code == 404
    body = response.json()["error"]
    assert body["code"] == "link_not_found"
    assert "lnk_nothing" in body["message"]


# -- story-time (D28) ------------------------------------------------------------------------------


def make_event(client: TestClient, project_id: str, name: str, **story_time: Any) -> str:
    attributes = {"story_time": story_time} if story_time else {}
    return make_entry(client, project_id, name, kind=EntryKind.EVENT, attributes=attributes)["id"]


def test_the_route_answers_what_the_pure_module_answers_for_the_same_data(
    client: TestClient, project_id: str
) -> None:
    """Not a second implementation: the route composes two reads and calls the module."""
    first = make_event(client, project_id, "The departure", label="spring", sort_key=1)
    second = make_event(client, project_id, "The river", label="summer", sort_key=2)
    create_link(client, project_id, first, "precedes", second)

    body = client.get(f"/api/projects/{project_id}/storytime").json()

    events = [
        story_event(first, "The departure", {"story_time": {"label": "spring", "sort_key": 1}}),
        story_event(second, "The river", {"story_time": {"label": "summer", "sort_key": 2}}),
    ]
    expected = order_events(events, [(first, second)])
    assert [item["entry_id"] for item in body["order"]] == list(expected.order)
    assert [item["entry_id"] for item in body["unplaced"]] == list(expected.unplaced)
    assert body["contradictions"] == []


def test_an_event_with_neither_a_key_nor_a_constraint_is_unplaced(
    client: TestClient, project_id: str
) -> None:
    """D9's tray, arriving from the data. Not appended, not dropped, and never guessed at."""
    placed = make_event(client, project_id, "The departure", sort_key=1)
    adrift = make_event(client, project_id, "Someone shouted", label="one evening")

    body = client.get(f"/api/projects/{project_id}/storytime").json()

    assert [item["entry_id"] for item in body["order"]] == [placed]
    assert [item["entry_id"] for item in body["unplaced"]] == [adrift]
    assert body["unplaced"][0]["label"] == "one evening"


def test_a_sort_key_inversion_is_reported_and_the_edge_still_orders_the_pair(
    client: TestClient, project_id: str
) -> None:
    late = make_event(client, project_id, "The departure", sort_key=9)
    early = make_event(client, project_id, "The river", sort_key=1)
    create_link(client, project_id, late, "precedes", early)

    body = client.get(f"/api/projects/{project_id}/storytime").json()

    assert [item["kind"] for item in body["contradictions"]] == [
        ContradictionKind.SORT_KEY_INVERSION
    ]
    assert set(body["contradictions"][0]["events"]) == {late, early}
    assert [item["entry_id"] for item in body["order"]] == [late, early]


def test_eras_rank_by_the_least_key_among_their_members(
    client: TestClient, project_id: str
) -> None:
    make_event(client, project_id, "The departure", era="Before", sort_key=5)
    make_event(client, project_id, "The river", era="Before", sort_key=2)
    make_event(client, project_id, "A rumour", era="After")

    body = client.get(f"/api/projects/{project_id}/storytime").json()

    assert body["eras"] == [{"era": "After", "rank": None}, {"era": "Before", "rank": 2.0}]


def test_a_deleted_event_leaves_the_timeline(client: TestClient, project_id: str) -> None:
    first = make_event(client, project_id, "The departure", sort_key=1)
    second = make_event(client, project_id, "The river", sort_key=2)
    client.delete(f"/api/entries/{second}")

    body = client.get(f"/api/projects/{project_id}/storytime").json()

    assert [item["entry_id"] for item in body["order"]] == [first]


def test_story_time_on_a_project_with_no_events_is_three_empty_answers(
    client: TestClient, project_id: str
) -> None:
    body = client.get(f"/api/projects/{project_id}/storytime").json()

    assert body == {"order": [], "unplaced": [], "contradictions": [], "eras": []}


def test_precedes_is_the_relation_the_ordering_reads() -> None:
    """Stated here so that renaming it in the vocabulary fails a test rather than a timeline."""
    assert any(relation.relation == "precedes" for relation in RELATIONS)
