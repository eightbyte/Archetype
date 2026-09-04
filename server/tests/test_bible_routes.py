"""P3-11 - ``GET /api/bible/schema``, the definition served (D26).

The definition itself is tested in ``test_bible_schema.py``. What these assert is that the route
serves it whole, that it carries no project scope, and the property the whole of D26 rests on:
**adding a field to a kind is a change to one file**, and it appears on the wire without anything
else being edited.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from archetype.bible.schema import ENTRY_KINDS, RELATIONS, FieldType, schema_json


@pytest.fixture
def served(client: TestClient) -> dict[str, Any]:
    response = client.get("/api/bible/schema")
    assert response.status_code == 200, response.text
    return response.json()


def test_the_route_serves_the_definition_whole(served: dict[str, Any]) -> None:
    assert served == schema_json()
    assert len(served["kinds"]) == len(ENTRY_KINDS) == 7
    assert len(served["relations"]) == len(RELATIONS) == 12
    assert set(served["field_types"]) == FieldType.ALL


def test_it_carries_no_project_scope(client: TestClient) -> None:
    """The one route in the API that answers the same bytes for every caller.

    The vocabulary is the product's, not a manuscript's - so it does not take a project, and
    asking for it before any project exists is an ordinary success.
    """
    first = client.get("/api/bible/schema").json()
    client.post("/api/projects", json={"title": "The Long Road"})

    assert client.get("/api/bible/schema").json() == first


def test_every_field_carries_every_key_whatever_its_type(served: dict[str, Any]) -> None:
    """One generic form renders this, so a key that appears only sometimes is a branch.

    ``members`` is filled for an ``enum`` and empty otherwise; ``kinds`` for an ``entry_ref``.
    Both are always present.
    """
    seen: set[str] = set()
    for kind in served["kinds"]:
        assert set(kind) == {"kind", "label", "plural", "fields"}
        for field in kind["fields"]:
            assert set(field) == {
                "name",
                "type",
                "label",
                "required",
                "help",
                "members",
                "kinds",
            }
            assert field["type"] in FieldType.ALL
            seen.add(field["type"])
            assert bool(field["members"]) == (field["type"] == FieldType.ENUM)
            assert bool(field["kinds"]) == (field["type"] == FieldType.ENTRY_REF)

    # Every one of the six is reachable from the wire, so the client's renderer has a case for
    # each and P3-13's "a type without a renderer fails loudly" has something to fail on.
    assert seen == FieldType.ALL


def test_every_relation_says_which_kinds_it_joins_and_whether_it_is_symmetric(
    served: dict[str, Any],
) -> None:
    """A client filters its relation picker from this, so an illegal link cannot be built."""
    for relation in served["relations"]:
        assert set(relation) == {
            "relation",
            "label",
            "inverse_label",
            "from_kinds",
            "to_kinds",
            "symmetric",
        }
        assert relation["from_kinds"] and relation["to_kinds"]
        assert isinstance(relation["symmetric"], bool)


def test_a_field_added_to_a_kind_reaches_the_wire_with_no_other_change(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D26's whole claim, asserted rather than asserted about.

    The definition is patched in the one place it lives; nothing in the route, the wire model, or
    this test's expectations mentions the new field, and it arrives fully formed.
    """
    import archetype.api.bible_routes as bible_routes
    from archetype.bible.schema import FieldDefinition, KindDefinition, definition_for

    character = definition_for("character")
    widened = KindDefinition(
        kind=character.kind,
        label=character.label,
        plural=character.plural,
        fields=(
            *character.fields,
            FieldDefinition(
                name="handedness",
                type=FieldType.ENUM,
                label="Handedness",
                members=("left", "right"),
            ),
        ),
    )
    patched = tuple(
        widened if definition.kind == "character" else definition for definition in ENTRY_KINDS
    )
    monkeypatch.setattr(bible_routes, "ENTRY_KINDS", patched)

    served = client.get("/api/bible/schema").json()

    field = next(
        item
        for kind in served["kinds"]
        if kind["kind"] == "character"
        for item in kind["fields"]
        if item["name"] == "handedness"
    )
    assert field["type"] == "enum"
    assert field["members"] == ["left", "right"]
    assert field["kinds"] == []
