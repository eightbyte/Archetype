"""P3-9 - the entry routes, over the real application.

The rules live in ``EntryStore`` and are tested there (``test_entries.py``,
``test_entry_revisions.py``); what these assert is that each route reaches them, that the envelope
comes back when it should, that the filters compose over the wire, and that a bare entry id finds
its way to whichever project file holds it.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from archetype.api.bible_schemas import EntryStatusFilter
from archetype.bible.entries import SEARCH_LIMIT, EntryStatus
from archetype.bible.schema import EntryKind

from .conftest import required_attributes


def make_project(client: TestClient, title: str = "The Long Road") -> str:
    return client.post("/api/projects", json={"title": title}).json()["project"]["id"]


def make_entry(
    client: TestClient,
    project_id: str,
    name: str = "Marlow",
    *,
    kind: str = EntryKind.CHARACTER,
    **fields: Any,
) -> dict[str, Any]:
    response = client.post(
        f"/api/projects/{project_id}/entries",
        json={"kind": kind, "name": name, **fields},
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def project_id(client: TestClient) -> str:
    return make_project(client)


@pytest.fixture
def entry(client: TestClient, project_id: str) -> dict[str, Any]:
    return make_entry(client, project_id)


# -- the vocabulary the wire restates ----------------------------------------------------------


def test_the_status_filter_spells_out_exactly_what_the_store_holds() -> None:
    """The ``AnchorStatusFilter`` rule (P2-7): a second spelling is held to the first.

    ``kind`` and ``relation`` are deliberately **not** spelled out on the wire - those live in
    D26's served definition, and a ``Literal`` for them here would be the second copy that
    decision exists to prevent. A status is a module constant, so it is restated and held.
    """
    assert set(EntryStatusFilter.__args__) == EntryStatus.ALL


# -- creating ----------------------------------------------------------------------------------


def test_creating_an_entry_returns_it_at_revision_one(entry: dict[str, Any]) -> None:
    assert entry["kind"] == EntryKind.CHARACTER
    assert entry["name"] == "Marlow"
    assert entry["revision"] == 1
    assert entry["status"] == EntryStatus.ACCEPTED
    assert entry["origin"] == "user"
    assert entry["needs_review"] is False
    assert entry["deleted_at"] is None


def test_every_kind_is_created_through_the_one_route(client: TestClient, project_id: str) -> None:
    """D26 over HTTP: seven kinds, one route, one shape."""
    for kind in ("character", "place", "item", "faction", "event", "thread", "fact"):
        made = make_entry(
            client, project_id, f"A {kind}", kind=kind, attributes=required_attributes(kind)
        )
        assert made["kind"] == kind


def test_an_unknown_kind_is_a_422_naming_the_field(client: TestClient, project_id: str) -> None:
    response = client.post(
        f"/api/projects/{project_id}/entries", json={"kind": "dragon", "name": "Smaug"}
    )

    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "invalid_attributes"
    assert body["detail"] == {"field": "kind"}
    assert client.get(f"/api/projects/{project_id}/entries").json()["entries"] == []


def test_an_undeclared_attribute_is_a_422_that_writes_nothing(
    client: TestClient, project_id: str
) -> None:
    response = client.post(
        f"/api/projects/{project_id}/entries",
        json={"kind": "character", "name": "Marlow", "attributes": {"eye_colour": "grey"}},
    )

    assert response.status_code == 422
    assert response.json()["error"]["detail"] == {"field": "eye_colour"}
    assert client.get(f"/api/projects/{project_id}/entries").json()["entries"] == []


def test_a_blank_name_is_refused_by_the_wire_model(client: TestClient, project_id: str) -> None:
    """Caught before the store, so the answer is the ordinary validation envelope."""
    response = client.post(
        f"/api/projects/{project_id}/entries", json={"kind": "character", "name": "   "}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_a_status_may_not_be_asked_for_on_creation(client: TestClient, project_id: str) -> None:
    """``proposed`` and ``agent`` are registered with **no writer in this phase** (plan section 3).

    The same rule the ``pre-*`` snapshot reasons follow: a client that could ask for one would be
    that writer, and Phase 7's proposal queue would arrive to find its vocabulary already used.
    """
    response = client.post(
        f"/api/projects/{project_id}/entries",
        json={"kind": "character", "name": "Marlow", "status": "proposed", "origin": "agent"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_creating_in_a_missing_project_is_a_404(client: TestClient) -> None:
    response = client.post(
        "/api/projects/prj_nothing/entries", json={"kind": "character", "name": "Marlow"}
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "project_not_found"


# -- reading -----------------------------------------------------------------------------------


def test_the_list_carries_counts_for_every_kind_including_the_empty_ones(
    client: TestClient, project_id: str, entry: dict[str, Any]
) -> None:
    body = client.get(f"/api/projects/{project_id}/entries").json()

    assert [item["id"] for item in body["entries"]] == [entry["id"]]
    assert body["counts"]["character"] == 1
    assert body["counts"]["place"] == 0
    assert set(body["counts"]) == {
        "character",
        "place",
        "item",
        "faction",
        "event",
        "thread",
        "fact",
    }
    assert body["truncated"] is False


def test_the_counts_are_unfiltered_so_a_filtered_list_still_says_how_many_there_are(
    client: TestClient, project_id: str
) -> None:
    make_entry(client, project_id, "Marlow")
    make_entry(client, project_id, "The Quay", kind=EntryKind.PLACE)

    body = client.get(f"/api/projects/{project_id}/entries", params={"kind": "place"}).json()

    assert [item["name"] for item in body["entries"]] == ["The Quay"]
    assert body["counts"]["character"] == 1


def test_the_filters_compose_over_the_wire(client: TestClient, project_id: str) -> None:
    kestrel = make_entry(client, project_id, "The Kestrel", kind=EntryKind.ITEM)
    make_entry(client, project_id, "Marlow", summary="watches the Kestrel from the quay")

    found = client.get(
        f"/api/projects/{project_id}/entries",
        params={"kind": "item", "q": "kestrel", "status": "accepted"},
    ).json()

    assert [item["id"] for item in found["entries"]] == [kestrel["id"]]


def test_an_unknown_status_filter_is_refused_by_the_route(
    client: TestClient, project_id: str
) -> None:
    response = client.get(f"/api/projects/{project_id}/entries", params={"status": "considered"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_an_unknown_kind_filter_is_a_422_rather_than_an_empty_list(
    client: TestClient, project_id: str
) -> None:
    """An empty list for a value the server does not understand is debugged as missing data."""
    response = client.get(f"/api/projects/{project_id}/entries", params={"kind": "dragon"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_attributes"


def test_the_search_cap_is_reported_rather_than_merely_applied(
    client: TestClient, project_id: str
) -> None:
    """A filter that cannot say "there are more" is lying about what it found.

    Written at the cap rather than well past it, because the interesting case is the boundary:
    exactly ``SEARCH_LIMIT`` matches must **not** claim to be truncated, and one more must.
    """
    for index in range(SEARCH_LIMIT):
        make_entry(client, project_id, f"Marlow {index:03d}")

    at_the_cap = client.get(f"/api/projects/{project_id}/entries", params={"q": "Marlow"}).json()
    assert len(at_the_cap["entries"]) == SEARCH_LIMIT
    assert at_the_cap["truncated"] is False

    make_entry(client, project_id, "Marlow the last")
    over_it = client.get(f"/api/projects/{project_id}/entries", params={"q": "Marlow"}).json()
    assert len(over_it["entries"]) == SEARCH_LIMIT
    assert over_it["truncated"] is True


def test_one_entry_carries_its_citations_and_its_link_count(
    client: TestClient, project_id: str, entry: dict[str, Any]
) -> None:
    body = client.get(f"/api/entries/{entry['id']}").json()

    assert body["entry"]["id"] == entry["id"]
    assert body["citations"] == []
    assert body["link_count"] == 0
    assert body["narrative_position"] is None


def test_a_missing_entry_is_a_404_carrying_the_envelope(client: TestClient) -> None:
    response = client.get("/api/entries/ent_nothing")

    assert response.status_code == 404
    body = response.json()["error"]
    assert body["code"] == "entry_not_found"
    assert "ent_nothing" in body["message"]


def test_a_bare_entry_id_finds_the_project_that_holds_it(client: TestClient) -> None:
    """The locator, one more prefix over one mechanism (P3-9)."""
    first = make_project(client, "The Long Road")
    second = make_project(client, "The Other Book")
    here = make_entry(client, second, "Marlow")

    assert client.get(f"/api/entries/{here['id']}").json()["entry"]["project_id"] == second
    assert client.get(f"/api/projects/{first}/entries").json()["entries"] == []


# -- updating ------------------------------------------------------------------------------------


def test_an_update_keeps_what_it_was_not_told_about(client: TestClient, project_id: str) -> None:
    """An absent field is absent, not blank. A ``PUT`` that omits ``summary`` must not clear it."""
    entry = make_entry(client, project_id, "Marlow", summary="a pilot")

    response = client.put(
        f"/api/entries/{entry['id']}", json={"revision": 1, "name": "Charlie Marlow"}
    )

    assert response.status_code == 200, response.text
    written = response.json()["entry"]
    assert written["name"] == "Charlie Marlow"
    assert written["summary"] == "a pilot"
    assert written["revision"] == 2


def test_attributes_sent_as_an_empty_map_clear_them(client: TestClient, project_id: str) -> None:
    entry = make_entry(client, project_id, "Marlow", attributes={"aliases": ["the pilot"]})

    body = client.put(f"/api/entries/{entry['id']}", json={"revision": 1, "attributes": {}}).json()

    assert body["entry"]["attributes"] == {}


def test_an_update_that_changes_nothing_is_refused_rather_than_writing_a_revision(
    client: TestClient, entry: dict[str, Any]
) -> None:
    response = client.put(f"/api/entries/{entry['id']}", json={"revision": 1})

    assert response.status_code == 422
    assert client.get(f"/api/entries/{entry['id']}/revisions").json()["revisions"] == [
        {
            "entry_id": entry["id"],
            "revision": 1,
            "revised_at": entry["created_at"],
            "reason": "",
            "retcon": False,
            "origin": "user",
        }
    ]


def test_a_stale_revision_is_a_409_carrying_what_the_form_needs(
    client: TestClient, entry: dict[str, Any]
) -> None:
    """D19 applied to entries (ruling 3). The client stops and offers the server's copy."""
    client.put(f"/api/entries/{entry['id']}", json={"revision": 1, "name": "Charlie"})

    response = client.put(f"/api/entries/{entry['id']}", json={"revision": 1, "name": "Kurtz"})

    assert response.status_code == 409
    body = response.json()["error"]
    assert body["code"] == "entry_version_conflict"
    assert body["detail"]["entry_id"] == entry["id"]
    assert body["detail"]["presented_revision"] == 1
    assert body["detail"]["current_revision"] == 2
    assert client.get(f"/api/entries/{entry['id']}").json()["entry"]["name"] == "Charlie"


def test_a_body_only_edit_is_not_a_retcon_and_flags_nobody(
    client: TestClient, project_id: str
) -> None:
    """The half of D27 that keeps the queue worth reading."""
    marlow = make_entry(client, project_id, "Marlow")
    kurtz = make_entry(client, project_id, "Kurtz")
    client.post(
        f"/api/projects/{project_id}/links",
        json={"from_entry": marlow["id"], "relation": "knows", "to_entry": kurtz["id"]},
    )

    body = client.put(
        f"/api/entries/{marlow['id']}", json={"revision": 1, "body_md": "He told the story."}
    ).json()

    assert body["retcon"] is False
    assert body["changed_fields"] == []
    assert body["flagged"] == []
    assert client.get(f"/api/entries/{kurtz['id']}").json()["entry"]["needs_review"] is False


def test_a_retcon_flags_the_entries_a_live_link_joins(client: TestClient, project_id: str) -> None:
    """D27's dependent rule, end to end: the only relationship the data actually knows."""
    marlow = make_entry(client, project_id, "Marlow")
    kurtz = make_entry(client, project_id, "Kurtz")
    stranger = make_entry(client, project_id, "A Stranger")
    client.post(
        f"/api/projects/{project_id}/links",
        json={"from_entry": marlow["id"], "relation": "knows", "to_entry": kurtz["id"]},
    )

    body = client.put(
        f"/api/entries/{marlow['id']}",
        json={"revision": 1, "name": "Charlie Marlow", "reason": "he was never called Marlow"},
    ).json()

    assert body["retcon"] is True
    assert body["changed_fields"] == ["name"]
    assert body["flagged"] == [kurtz["id"]]
    flagged = client.get(f"/api/entries/{kurtz['id']}").json()["entry"]
    assert flagged["needs_review"] is True
    assert "Charlie Marlow" in flagged["review_reason"]
    assert client.get(f"/api/entries/{stranger['id']}").json()["entry"]["needs_review"] is False


def test_the_retcon_answer_can_be_overridden_in_either_direction(
    client: TestClient, project_id: str
) -> None:
    """And the computed answer still comes back, so an override is legible as an override."""
    marlow = make_entry(client, project_id, "Marlow")
    kurtz = make_entry(client, project_id, "Kurtz")
    client.post(
        f"/api/projects/{project_id}/links",
        json={"from_entry": marlow["id"], "relation": "knows", "to_entry": kurtz["id"]},
    )

    suppressed = client.put(
        f"/api/entries/{marlow['id']}",
        json={"revision": 1, "name": "Marlowe", "retcon": False},
    ).json()
    assert suppressed["retcon"] is False
    assert suppressed["changed_fields"] == ["name"]
    assert suppressed["flagged"] == []

    forced = client.put(
        f"/api/entries/{marlow['id']}",
        json={"revision": 2, "body_md": "a spelling nobody agreed", "retcon": True},
    ).json()
    assert forced["retcon"] is True
    assert forced["changed_fields"] == []
    assert forced["flagged"] == [kurtz["id"]]


def test_the_review_queue_is_a_filter_and_it_empties(client: TestClient, project_id: str) -> None:
    """Half of the phase's exit criterion, over the wire: clearing one flags nothing further."""
    marlow = make_entry(client, project_id, "Marlow")
    kurtz = make_entry(client, project_id, "Kurtz")
    client.post(
        f"/api/projects/{project_id}/links",
        json={"from_entry": marlow["id"], "relation": "knows", "to_entry": kurtz["id"]},
    )
    client.put(f"/api/entries/{marlow['id']}", json={"revision": 1, "name": "Charlie"})

    queue = client.get(f"/api/projects/{project_id}/entries", params={"needs_review": True}).json()
    assert [item["id"] for item in queue["entries"]] == [kurtz["id"]]

    revision = queue["entries"][0]["revision"]
    cleared = client.post(f"/api/entries/{kurtz['id']}/review/clear", json={"revision": revision})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["retcon"] is False
    assert cleared.json()["flagged"] == []

    emptied = client.get(
        f"/api/projects/{project_id}/entries", params={"needs_review": True}
    ).json()
    assert emptied["entries"] == []
    assert client.get(f"/api/entries/{marlow['id']}").json()["entry"]["needs_review"] is False


def test_clearing_a_review_at_a_stale_revision_is_a_409(
    client: TestClient, entry: dict[str, Any]
) -> None:
    response = client.post(f"/api/entries/{entry['id']}/review/clear", json={"revision": 99})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "entry_version_conflict"


# -- deleting and restoring ----------------------------------------------------------------------


def test_a_deleted_entry_leaves_every_list_and_can_be_found_to_restore(
    client: TestClient, project_id: str, entry: dict[str, Any]
) -> None:
    deleted = client.delete(f"/api/entries/{entry['id']}")

    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted_at"] is not None

    listed = client.get(f"/api/projects/{project_id}/entries").json()
    assert listed["entries"] == []
    assert listed["counts"]["character"] == 0

    restorable = client.get(f"/api/projects/{project_id}/entries/deleted").json()
    assert [item["id"] for item in restorable["entries"]] == [entry["id"]]

    client.post(f"/api/entries/{entry['id']}/restore")
    assert len(client.get(f"/api/projects/{project_id}/entries").json()["entries"]) == 1


def test_a_deleted_entry_is_still_readable_by_id_so_its_history_can_be_seen(
    client: TestClient, entry: dict[str, Any]
) -> None:
    """The rule ``SnapshotStore.list`` follows: what somebody deciding to restore needs to see."""
    client.delete(f"/api/entries/{entry['id']}")

    body = client.get(f"/api/entries/{entry['id']}").json()
    assert body["entry"]["deleted_at"] is not None
    assert len(client.get(f"/api/entries/{entry['id']}/revisions").json()["revisions"]) == 2


def test_deleting_a_deleted_entry_is_a_404(client: TestClient, entry: dict[str, Any]) -> None:
    client.delete(f"/api/entries/{entry['id']}")

    assert client.delete(f"/api/entries/{entry['id']}").status_code == 404


def test_including_deleted_entries_is_asked_for_explicitly(
    client: TestClient, project_id: str, entry: dict[str, Any]
) -> None:
    client.delete(f"/api/entries/{entry['id']}")

    body = client.get(
        f"/api/projects/{project_id}/entries", params={"include_deleted": True}
    ).json()
    assert [item["id"] for item in body["entries"]] == [entry["id"]]


# -- revisions -------------------------------------------------------------------------------------


def test_history_is_complete_from_creation_and_carries_no_state(
    client: TestClient, entry: dict[str, Any]
) -> None:
    client.put(f"/api/entries/{entry['id']}", json={"revision": 1, "name": "Charlie"})

    body = client.get(f"/api/entries/{entry['id']}/revisions").json()

    assert [item["revision"] for item in body["revisions"]] == [2, 1]
    assert all("state" not in item for item in body["revisions"])


def test_one_revision_carries_the_state_it_recorded(
    client: TestClient, entry: dict[str, Any]
) -> None:
    client.put(f"/api/entries/{entry['id']}", json={"revision": 1, "name": "Charlie"})

    body = client.get(f"/api/entries/{entry['id']}/revisions/1").json()

    assert body["meta"]["revision"] == 1
    assert body["state"]["name"] == "Marlow"
    assert "needs_review" not in body["state"]


def test_a_revision_that_does_not_exist_is_a_404_saying_so(
    client: TestClient, entry: dict[str, Any]
) -> None:
    response = client.get(f"/api/entries/{entry['id']}/revisions/9")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "revision_not_found"


def test_restoring_a_revision_appends_to_history_rather_than_rewriting_it(
    client: TestClient, entry: dict[str, Any]
) -> None:
    client.put(f"/api/entries/{entry['id']}", json={"revision": 1, "name": "Charlie"})

    restored = client.post(f"/api/entries/{entry['id']}/revisions/1/restore", json={"revision": 2})

    assert restored.status_code == 200, restored.text
    assert restored.json()["entry"]["name"] == "Marlow"
    assert restored.json()["entry"]["revision"] == 3
    history = client.get(f"/api/entries/{entry['id']}/revisions").json()["revisions"]
    assert [item["revision"] for item in history] == [3, 2, 1]
    assert history[0]["reason"] == "restored revision 1"


def test_restoring_a_revision_at_a_stale_revision_is_a_409(
    client: TestClient, entry: dict[str, Any]
) -> None:
    response = client.post(f"/api/entries/{entry['id']}/revisions/1/restore", json={"revision": 99})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "entry_version_conflict"


def test_a_field_presented_as_null_is_not_a_change(
    client: TestClient, entry: dict[str, Any]
) -> None:
    """Refused rather than writing a revision that records nothing.

    There is no nullable content field on an entry, so ``name: null`` is a client sending the
    wrong thing. Letting it through would put an empty row in the one history a writer consults.
    """
    response = client.put(f"/api/entries/{entry['id']}", json={"revision": 1, "name": None})

    assert response.status_code == 422
    assert client.get(f"/api/entries/{entry['id']}").json()["entry"]["revision"] == 1
